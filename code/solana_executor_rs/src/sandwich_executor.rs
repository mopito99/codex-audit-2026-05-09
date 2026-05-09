// Sandwich executor — recibe víctimas del sandwich_listener, calcula rentabilidad,
// gestiona tip-laddering e inventory, y ejecuta (o simula en paper mode) el bundle.
//
// Bundle sandwich: [FrontRun_TX, Victim_TX, BackRun_TX, Tip_TX]
// Jito garantiza atomicidad: si la víctima no ejecuta, el bundle falla completo.
// Paper mode: simulación completa con logging a JSONL. Live mode: TODO G24 (Orca CLMM builder).

use std::collections::VecDeque;
use std::sync::Arc;
use std::time::{Duration, Instant};

use crossbeam_queue::ArrayQueue;

use reqwest;

use crate::circuit_breaker::CircuitBreaker;
use crate::config::EnvCfg;
use crate::metrics;
use crate::sandwich_listener::SandwichOpportunity;

// Orca Whirlpool SOL/USDC fee (0.05%)
const ORCA_FEE_PCT: f64 = 0.0005;

// Probe size Fase 1 sandwich: $1,000 (G69 — equilibrio visibilidad/gross en pool long-tail $2M).
// $1,500 era agresivo y nos hacía visibles a otros bots; $500 insuficiente en pools $5M.
pub const SANDWICH_PROBE_USDC: f64 = 1_000.0;

// Víctima mínima para intentar sandwich (filtro grueso; executor hace cálculo preciso)
pub const SANDWICH_MIN_VICTIM_USDC: f64 = 200.0;

// Seguridad epsilon Fase 1: gross debe ser ≥ 1.5× costos para ejecutar (G51)
const SAFETY_MARGIN: f64 = 1.5;

// Multiplicadores para tip-laddering (G34/G40): 3 bundles independientes
// Jito solo cobra el que aterriza. Distribuimos riesgo de tip insuficiente.
const LADDER_MULTS: [f64; 3] = [1.5, 2.0, 2.5];

// ── Tip Ladder ────────────────────────────────────────────────────────────────

/// Ventana deslizante de 30s de tips enviados. Calcula mediana → base para laddering (G40).
pub struct TipLadder {
    history: VecDeque<(u64, Instant)>, // (tip_lamports, sent_at)
}

impl TipLadder {
    pub fn new() -> Self {
        Self { history: VecDeque::new() }
    }

    fn prune(&mut self) {
        let cutoff = Instant::now() - Duration::from_secs(30);
        while self.history.front().map_or(false, |(_, t)| *t < cutoff) {
            self.history.pop_front();
        }
    }

    pub fn record(&mut self, tip_lamports: u64) {
        self.prune();
        self.history.push_back((tip_lamports, Instant::now()));
    }

    /// Mediana de tips en la ventana de 30s. fallback si ventana vacía.
    pub fn median(&mut self, fallback: u64) -> u64 {
        self.prune();
        if self.history.is_empty() {
            return fallback;
        }
        let mut tips: Vec<u64> = self.history.iter().map(|(t, _)| *t).collect();
        tips.sort_unstable();
        tips[tips.len() / 2]
    }

    /// [tip_A, tip_B, tip_C] = mediana × [1.5, 2.0, 2.5]
    /// En paper mode usamos tip_A para el log (conservador).
    pub fn ladder(&mut self, fallback: u64) -> [u64; 3] {
        let median = self.median(fallback);
        [
            (median as f64 * LADDER_MULTS[0]) as u64,
            (median as f64 * LADDER_MULTS[1]) as u64,
            (median as f64 * LADDER_MULTS[2]) as u64,
        ]
    }
}

// ── Profit math ───────────────────────────────────────────────────────────────

/// CLMM first-order profit estimate (G51/G26).
/// Retorna (gross_usdc, victim_impact_pct, min_amount_out_back_usdc).
/// min_amount_out_back = probe_usdc × (1 - victim_impact) × (1 - 0.001) — precio límite estricto (G56).
/// Slippage 0.1% cubre solo errores de redondeo; NUNCA usar % genérico en back-run.
fn estimate_profit(
    opp: &SandwichOpportunity,
    probe_usdc: f64,
    sol_price_usd: f64,
) -> (f64, f64, f64) {
    let l = opp.pool_state.liquidity as f64;
    let sqrt_x64 = opp.pool_state.sqrt_price_x64 as f64;
    if l == 0.0 || sqrt_x64 == 0.0 {
        return (0.0, 0.0, 0.0);
    }

    let victim_usdc = if opp.victim_a_to_b {
        opp.victim_amount_in as f64 / 1e9 * sol_price_usd
    } else {
        opp.victim_amount_in as f64 / 1e6
    };

    // victim_impact: linearización CLMM primera orden
    // Δprice/price = 2 × victim_usdc × 1e6 × 2^64 / (L × sqrt_x64)
    let two_64 = (1u128 << 64) as f64;
    let victim_impact = 2.0 * victim_usdc * 1_000_000.0 * two_64 / (l * sqrt_x64);

    let gross = probe_usdc * victim_impact;

    // Precio límite back-run (G56): recuperamos probe invertido al precio post-víctima menos ε=0.1%
    // El back-run invierte la dirección: si front-run fue USDC→SOL, back-run es SOL→USDC
    let min_amount_out_back = probe_usdc * (1.0 - victim_impact) * 0.999;

    (gross, victim_impact * 100.0, min_amount_out_back)
}

/// Epsilon mínimo para que el trade sea rentable (G51).
/// ε = (2×tip_usdc + 2×dex_fees) × safety_margin
fn epsilon_usdc(tip_lamports: u64, sol_price_usd: f64, probe_usdc: f64) -> f64 {
    let tip_usdc = tip_lamports as f64 / 1e9 * sol_price_usd;
    let dex_fees = 2.0 * ORCA_FEE_PCT * probe_usdc;
    (2.0 * tip_usdc + dex_fees) * SAFETY_MARGIN
}

// ── Inventory check ───────────────────────────────────────────────────────────

/// Pausa si SOL < 2.0 O USDC < $500 (G47).
fn inventory_ok(sol: f64, usdc: f64) -> bool {
    sol >= 2.0 && usdc >= 500.0
}

// ── JSONL logging ─────────────────────────────────────────────────────────────

fn log_op(
    path: &str,
    opp: &SandwichOpportunity,
    probe_usdc: f64,
    gross_usdc: f64,
    net_usdc: f64,
    impact_pct: f64,
    min_amount_out_back: f64,
    tip_lamports: u64,
    latency_recv_ms: u64,
    would_execute: bool,
    sol_price_usd: f64,
) {
    use std::io::Write;

    let victim_usdc = if opp.victim_a_to_b {
        opp.victim_amount_in as f64 / 1e9 * sol_price_usd
    } else {
        opp.victim_amount_in as f64 / 1e6
    };

    let price = opp.pool_state.price_usdc_per_sol();
    let slot_delta = opp.detected_slot.saturating_sub(opp.pool_state.slot);

    let entry = format!(
        "{}\n",
        serde_json::json!({
            "ts":                 chrono::Utc::now().to_rfc3339(),
            "victimSig":          opp.victim_sig,
            "victimUSDC":         (victim_usdc * 100.0).round() / 100.0,
            "victimAToB":         opp.victim_a_to_b,
            "probeUSDC":          probe_usdc,
            "grossUSDC":          (gross_usdc * 10000.0).round() / 10000.0,
            "netUSDC":            (net_usdc * 10000.0).round() / 10000.0,
            "impactPct":          (impact_pct * 10000.0).round() / 10000.0,
            "minAmountOutBack":   (min_amount_out_back * 100.0).round() / 100.0, // G56: precio límite back-run
            "tipLamports":        tip_lamports,
            "latencyMs":          latency_recv_ms,
            "wouldExecute":       would_execute,
            "price":              (price * 100.0).round() / 100.0,
            "poolSlot":           opp.pool_state.slot,
            "detectedSlot":       opp.detected_slot,
            "slotDelta":          slot_delta,
            // S3/G77/G75/G68 — fields para análisis paper mode
            "isV0":               opp.is_v0,
            "numAltLookups":      opp.num_alt_lookups,
            "victimSigner":       opp.victim_signer,
            "computeUnitPrice":   opp.compute_unit_price,
            "hasJitoTip":         opp.has_jito_tip,
            "filterReason":       opp.filter_reason,
        })
    );

    if let Ok(mut f) = std::fs::OpenOptions::new()
        .create(true).append(true).open(path)
    {
        let _ = f.write_all(entry.as_bytes());
    }
}

// ── G55: Poll getSignatureStatuses post-bundle ────────────────────────────────

/// Espera 400ms (G55), luego sondea getSignatureStatuses cada 100ms durante ≤800ms (≈2 slots).
/// sig: firma del front-run TX — si aterriza, el bundle Jito completo aterrizó (atomicidad garantizada).
/// Retorna "landed" | "failed" | "timeout".
#[allow(dead_code)] // G55 — usado en Phase 2 LIVE post-bundle-send
async fn poll_landing(http: &reqwest::Client, rpc_url: &str, sig: &str) -> &'static str {
    tokio::time::sleep(Duration::from_millis(400)).await;
    for _ in 0..8 {
        let body = serde_json::json!({
            "jsonrpc": "2.0", "id": 1,
            "method": "getSignatureStatuses",
            "params": [[sig], {"searchTransactionHistory": false}]
        });
        if let Ok(resp) = http.post(rpc_url).json(&body)
            .timeout(Duration::from_millis(500)).send().await
        {
            if let Ok(v) = resp.json::<serde_json::Value>().await {
                let entry = &v["result"]["value"][0];
                if !entry.is_null() {
                    if entry["err"].is_null() {
                        let s = entry["confirmationStatus"].as_str().unwrap_or("");
                        if s == "confirmed" || s == "finalized" { return "landed"; }
                    } else {
                        return "failed";
                    }
                }
            }
        }
        tokio::time::sleep(Duration::from_millis(100)).await;
    }
    "timeout"
}

// ── Main executor loop ────────────────────────────────────────────────────────

/// Executor de sandwich. Sondea la ArrayQueue lock-free cada 50μs (G53).
/// Hilo separado con afinidad a Core 1 (G54). Actualiza JSONL con min_amount_out_back (G56).
pub async fn run_sandwich_executor(
    cfg: Arc<EnvCfg>,
    cb: Arc<CircuitBreaker>,
    queue: Arc<ArrayQueue<SandwichOpportunity>>,
) {
    let log_path = format!("{}/sandwich_paper_ops.jsonl", crate::config::log_dir());
    let mut tip_ladder = TipLadder::new();
    let _http = reqwest::Client::builder()
        .timeout(Duration::from_secs(5))
        .tcp_keepalive(Duration::from_secs(60))
        .build()
        .unwrap_or_else(|_| reqwest::Client::new());

    // Inventory en memoria — en producción leer desde balance.json (actualizado por el bot)
    let sol_balance: f64 = 5.0;
    let usdc_balance: f64 = SANDWICH_PROBE_USDC;

    // Stats sesión
    let mut victims_seen:     u64 = 0;
    let mut victims_skipped:  u64 = 0;
    let mut would_execute:    u64 = 0;
    let mut session_gross:    f64 = 0.0;

    println!(
        "[sandwich_executor] arrancado — probe=${} min_victim=${} mode={} poll=50μs",
        SANDWICH_PROBE_USDC, SANDWICH_MIN_VICTIM_USDC,
        if cfg.paper_mode { "PAPER" } else { "LIVE" }
    );

    loop {
        // Sondeo lock-free (G53): si no hay víctima, dormir 50μs y reintentar
        let opp = match queue.pop() {
            Some(o) => o,
            None => {
                tokio::time::sleep(Duration::from_micros(50)).await;
                continue;
            }
        };

        victims_seen += 1;
        let recv_latency_ms = opp.detected_at.elapsed().as_millis() as u64;

        // ── Circuit breaker ──────────────────────────────────────────────────
        if cb.is_tripped() && !cb.check_recovery() {
            victims_skipped += 1;
            println!("[sandwich_executor] ⏸ CB activo — descartando víctima {}", victims_skipped);
            continue;
        }

        // ── Inventory check (G47) ────────────────────────────────────────────
        if !inventory_ok(sol_balance, usdc_balance) {
            victims_skipped += 1;
            println!(
                "[sandwich_executor] ⛔ inventario bajo SOL={:.2} USDC={:.0} — pausa",
                sol_balance, usdc_balance
            );
            // Pausa 60s antes de reintentar (no spamear logs)
            tokio::time::sleep(Duration::from_secs(60)).await;
            continue;
        }

        // G49: latencia de pipeline para cada víctima procesada
        metrics::observe_pipeline_latency(recv_latency_ms);

        // ── Profit estimate ──────────────────────────────────────────────────
        let (gross, impact_pct, min_amount_out_back) = estimate_profit(&opp, SANDWICH_PROBE_USDC, cfg.sol_price_usd);

        // Tip: usar ladder de la ventana 30s, conservador = ladder[0]
        let tips = tip_ladder.ladder(cfg.jito_tip_lamports);
        let tip_for_calc = tips[0]; // tier A (más bajo de los 3)
        metrics::set_p95_tip(tips[0]);

        let epsilon = epsilon_usdc(tip_for_calc, cfg.sol_price_usd, SANDWICH_PROBE_USDC);
        let net = gross - epsilon;

        if net < 0.0 {
            victims_skipped += 1;
            // Paper mode: log SIEMPRE para data gathering (G50). El stdout solo
            // se imprime si el gap era prometedor (>50% del epsilon) para no spamear.
            if gross > epsilon * 0.5 {
                let victim_usdc = if opp.victim_a_to_b {
                    opp.victim_amount_in as f64 / 1e9 * cfg.sol_price_usd
                } else {
                    opp.victim_amount_in as f64 / 1e6
                };
                println!(
                    "[sandwich] ✗ no_profit victim=${:.0} gross=${:.4} ε=${:.4} impact={:.5}% lat={}ms",
                    victim_usdc, gross, epsilon, impact_pct, recv_latency_ms
                );
            }
            log_op(
                &log_path, &opp, SANDWICH_PROBE_USDC,
                gross, net, impact_pct, min_amount_out_back,
                tip_for_calc, recv_latency_ms, false, cfg.sol_price_usd,
            );
            continue;
        }

        // ── Víctima rentable ─────────────────────────────────────────────────
        would_execute += 1;
        session_gross += gross;

        let victim_usdc = if opp.victim_a_to_b {
            opp.victim_amount_in as f64 / 1e9 * cfg.sol_price_usd
        } else {
            opp.victim_amount_in as f64 / 1e6
        };

        println!(
            "[sandwich] 🥪 EJECUTAR victim=${:.0} ({}) gross=${:.4} net=${:.4} impact={:.5}% \
             lat={}ms sig={}... tips=[{},{},{}] slot_delta={}",
            victim_usdc,
            if opp.victim_a_to_b { "SOL→USDC" } else { "USDC→SOL" },
            gross, net, impact_pct,
            recv_latency_ms,
            &opp.victim_sig[..8.min(opp.victim_sig.len())],
            tips[0], tips[1], tips[2],
            opp.detected_slot.saturating_sub(opp.pool_state.slot),
        );

        // Registrar tip en ladder para calibrar futuros bundles
        tip_ladder.record(tips[0]);

        if cfg.paper_mode {
            log_op(
                &log_path, &opp, SANDWICH_PROBE_USDC,
                gross, net, impact_pct, min_amount_out_back,
                tips[0], recv_latency_ms, true, cfg.sol_price_usd,
            );
            if would_execute % 10 == 0 {
                println!(
                    "[sandwich_executor] stats paper — seen={} skipped={} would_exec={} gross_total=${:.2}",
                    victims_seen, victims_skipped, would_execute, session_gross
                );
            }
            continue;
        }

        // ── LIVE MODE ────────────────────────────────────────────────────────
        // Para ejecutar el sandwich real necesitamos (G24):
        //   1. build_orca_swap_ix(USDC→SOL, probe, pool, keypair)  → FrontRun TX
        //   2. victim_tx_b58 — raw bytes del victim desde gRPC proto (pendiente sandwich_listener)
        //   3. build_orca_swap_ix(SOL→USDC, sol_out, pool, keypair) → BackRun TX
        //      → other_amount_threshold = min_amount_out_back (G56: precio límite estricto, no %)
        //   4. build_tip_tx(keypair, blockhash, tip_lamports)       → Tip TX
        //   5. send_sandwich_bundle([front, victim, back, tip], tips)
        //      → 3 bundles independientes con tips[0,1,2] via Jito NY
        //   6. poll getSignatureStatuses 400ms después, cada 100ms durante 2 slots (G55)
        //
        // Estado: local CLMM instruction builder pendiente (G24/G29).
        println!(
            "[sandwich_executor] LIVE pendiente: Orca CLMM builder (G24) + victim_tx relay | min_out=${:.2}",
            min_amount_out_back
        );
        log_op(
            &log_path, &opp, SANDWICH_PROBE_USDC,
            gross, net, impact_pct, min_amount_out_back,
            tips[0], recv_latency_ms, true, cfg.sol_price_usd,
        );
        tip_ladder.record(tips[0]);
        metrics::inc_bundle_sent();
        // G55: cuando G24 complete, reemplazar con sig real del front-run TX:
        //   let http_p = http.clone(); let rpc_url = cfg.helius_rpc.clone(); let net_cp = net;
        //   tokio::spawn(async move {
        //       let status = poll_landing(&http_p, &rpc_url, &front_run_sig).await;
        //       if status == "landed" { metrics::inc_bundle_landed(); metrics::add_net_profit(net_cp); }
        //       println!("[sandwich] G55 landing: {status}");
        //   });
    }
}
