mod alt_cache;
mod bot_detector;
mod circuit_breaker;
mod config;
mod metrics;
mod orca_builder;
mod safety_worker;
mod sandwich_types;
mod sandwich_executor;
mod sandwich_listener;
mod jupiter;
mod logger;
mod jito;
mod pool_state;
mod pool_watcher;

// G57: mimalloc como global allocator — reduce tail latency p99 en build_bundle
use mimalloc::MiMalloc;
#[global_allocator]
static GLOBAL: MiMalloc = MiMalloc;

use anyhow::Result;
use circuit_breaker::CircuitBreaker;
use config::{EnvCfg, MIN_PROFIT_BPS, MIN_PROFIT_USDC, POLL_INTERVAL_MS,
             MAX_SESSION_LOSS_USDC, FASE1_PROBE_USDC,
             scan_pairs, tier_slippage_bps};
use core_affinity;
use crossbeam_queue::ArrayQueue;
use sandwich_executor::{SANDWICH_MIN_VICTIM_USDC, run_sandwich_executor};
use sandwich_listener::{new_pool_state_map, run_sandwich_listener, SandwichOpportunity};
use jito::{build_bundle, poll_bundle_status, send_bundle, VoteAccountBlacklist};
use jupiter::{find_cyclic_arb, get_swap_transaction, ArbResult};
use logger::Logger;
use pool_watcher::{new_shared_prices, run_pool_watcher};
use solana_client::rpc_client::RpcClient;
use solana_sdk::signature::{Keypair, Signer};
use rand::Rng;
use std::sync::Arc;
use std::time::Duration;

// SOL/USDC: umbral de gap local para considerar oportunidad (en fracción, 0.0010 = 10 bps)
const LOCAL_GAP_MIN: f64 = 0.0010; // 10 bps — igual que el sandwich
// Datos de pool locales válidos hasta este número de ms antes de caer a Jupiter
const POOL_MAX_AGE_MS: u64 = 1_000;
// Cuánto de la detección local confiamos antes de confirmar con Jupiter quote
// Para el LIVE, siempre confirmamos con Jupiter para obtener la TX de swap

const JUPITER_RATE_PER_SEC: f64 = 0.3;

fn load_keypair(b58_secret: &Option<String>) -> Option<Keypair> {
    let s = b58_secret.as_ref()?;
    let bytes = bs58::decode(s).into_vec().ok()?;
    Keypair::try_from(&bytes[..]).ok()
}

#[tokio::main]
async fn main() -> Result<()> {
    let cfg = EnvCfg::load();
    let keypair = load_keypair(&cfg.wallet_private_key);
    let _has_key = !cfg.helius_api_key.is_empty();

    let rpc_url = if !cfg.helius_rpc.contains("api.mainnet-beta") {
        cfg.helius_rpc.clone()
    } else {
        "https://api.mainnet-beta.solana.com".to_string()
    };

    let rpc = Arc::new(RpcClient::new(rpc_url.clone()));
    // Keep-alive explícito: mantiene conexiones TCP abiertas a Jupiter (-30ms por bundle)
    let http = reqwest::Client::builder()
        .timeout(Duration::from_secs(8))
        .tcp_keepalive(Duration::from_secs(60))
        .pool_idle_timeout(Duration::from_secs(90))
        .build()?;

    // Warmup: ping a Jupiter cada 5s para evitar cold-start TLS en el hot path
    {
        let http_wm = http.clone();
        tokio::spawn(async move {
            loop {
                tokio::time::sleep(Duration::from_secs(5)).await;
                let _ = http_wm.get("https://lite-api.jup.ag/swap/v1/quote")
                    .timeout(Duration::from_secs(2))
                    .send().await;
            }
        });
    }

    // G49: inicializar métricas Prometheus y arrancar servidor /metrics
    metrics::init();
    {
        let port = std::env::var("METRICS_PORT")
            .ok().and_then(|s| s.parse().ok()).unwrap_or(9090u16);
        tokio::spawn(async move { metrics::serve(port).await });
    }

    // Startup: verificar offsets Whirlpool — resuelve discrepancia G33 vs IDL (ver orca_builder.rs)
    // Imprime precios calculados con ambos sets; el set que dé ~$150-200 es el correcto.
    if cfg.paper_mode {
        let pool_pk = orca_builder::ORCA_SOL_USDC_POOL
            .parse::<solana_sdk::pubkey::Pubkey>()
            .expect("valid pool pubkey");
        match rpc.get_account(&pool_pk) {
            Ok(acc) => orca_builder::OrcaPoolInfo::verify_offsets(&acc.data),
            Err(e)  => eprintln!("[startup] verify_offsets: RPC no disponible — {e}"),
        }
    }

    let logger = Logger::new(cfg.paper_mode);

    let jito_tip_usdc   = (cfg.jito_tip_lamports as f64 / 1e9) * cfg.sol_price_usd;
    let base_fees_usdc  = (5_000.0 * 2.0 / 1e9) * cfg.sol_price_usd;
    let total_cost_usdc = jito_tip_usdc + base_fees_usdc;

    println!("{}", "=".repeat(64));
    println!(" SOLANA EXECUTOR · RUST · {}",
        if cfg.paper_mode { "PAPER MODE" } else { "LIVE MODE — DINERO REAL" });
    println!(" pares: {} | sol_price: ${} | tip: ${:.4} | base_fees: ${:.4} | total_cost: ${:.4}",
        scan_pairs().len(), cfg.sol_price_usd, jito_tip_usdc, base_fees_usdc, total_cost_usdc);
    println!(" detección SOL/USDC: LOCAL (pool_watcher Orca+Raydium @50ms)");
    if let Some(kp) = keypair.as_ref() { println!(" wallet: {}", kp.pubkey()); }
    else { println!(" sin keypair — solo detección"); }
    println!("{}", "=".repeat(64));

    let blacklist = VoteAccountBlacklist::new();

    // Kill-switch: rastrear pérdida USDC acumulada en sesión (en microcents, ×1e6)
    let session_profit_usdc = Arc::new(std::sync::atomic::AtomicI64::new(0));

    // Circuit Breaker (G35): compartido entre cyclic arb y sandwich executor
    let cb = CircuitBreaker::new();

    // ── Sandwich bot: listener gRPC + executor ────────────────────────────────
    // G53: ArrayQueue lock-free — listener push(), executor pop() cada 50μs (sin wake-up del runtime)
    // G54: hilos pineados a Core 0 (listener) y Core 1 (executor) del mismo CCX del EPYC 7543P
    {
        let opp_queue: Arc<ArrayQueue<SandwichOpportunity>> = Arc::new(ArrayQueue::new(64));
        let cfg_sw   = Arc::new(cfg.clone());
        let cb_sw    = cb.clone();
        let pool_map = new_pool_state_map();

        // G75 — BotDetector compartido: listener llama observe(), executor consulta blacklist.
        // Background prune cada 1h elimina signers >24h sin TX.
        let bot_detector = Arc::new(bot_detector::BotDetector::new());
        bot_detector::spawn_periodic_prune((*bot_detector).clone());

        // Listener: Core 0 — single-thread Tokio runtime pineado para latencia determinista
        {
            let cfg_lst      = cfg_sw.clone();
            let pool_map_lst = pool_map.clone();
            let queue_lst    = opp_queue.clone();
            let bd_lst       = bot_detector.clone();
            std::thread::spawn(move || {
                if let Some(cores) = core_affinity::get_core_ids() {
                    if let Some(core) = cores.get(0) {
                        core_affinity::set_for_current(*core);
                    }
                }
                let rt = tokio::runtime::Builder::new_current_thread()
                    .enable_all()
                    .build()
                    .expect("sandwich listener runtime");
                rt.block_on(run_sandwich_listener(
                    cfg_lst, pool_map_lst, queue_lst, bd_lst, SANDWICH_MIN_VICTIM_USDC,
                ));
            });
        }

        // Executor: Core 1 — single-thread Tokio runtime pineado para latencia determinista
        {
            let cfg_exec  = cfg_sw.clone();
            let cb_exec   = cb_sw.clone();
            let queue_exec = opp_queue.clone();
            std::thread::spawn(move || {
                if let Some(cores) = core_affinity::get_core_ids() {
                    if let Some(core) = cores.get(1) {
                        core_affinity::set_for_current(*core);
                    }
                }
                let rt = tokio::runtime::Builder::new_current_thread()
                    .enable_all()
                    .build()
                    .expect("sandwich executor runtime");
                rt.block_on(run_sandwich_executor(cfg_exec, cb_exec, queue_exec));
            });
        }

        println!("[main] sandwich bot arrancado (Core 0: listener gRPC, Core 1: executor, queue lock-free)");
    }

    // Blockhash cache: refresh cada 400ms en background (evita RPC síncrono en el hot path)
    // Solana válida blockhashes hasta ~150 slots (~60s). 400ms es seguro para Jito.
    let cached_blockhash: Arc<tokio::sync::RwLock<Option<solana_sdk::hash::Hash>>> =
        Arc::new(tokio::sync::RwLock::new(None));
    {
        let rpc_bh  = rpc.clone();
        let cache   = cached_blockhash.clone();
        tokio::spawn(async move {
            loop {
                if let Ok(bh) = rpc_bh.get_latest_blockhash() {
                    *cache.write().await = Some(bh);
                }
                tokio::time::sleep(Duration::from_millis(400)).await;
            }
        });
    }

    // Arrancar pool watcher en background — actualiza precios cada 50ms
    let pool_prices = new_shared_prices();
    {
        let http_pw = reqwest::Client::builder()
            .timeout(Duration::from_secs(3))
            .build()?;
        let prices_clone = pool_prices.clone();
        let url_clone = rpc_url.clone();
        tokio::spawn(async move {
            run_pool_watcher(http_pw, url_clone, prices_clone).await;
        });
    }

    // Heartbeat stats cada 30s
    {
        let logger = logger.clone();
        tokio::spawn(async move {
            loop {
                tokio::time::sleep(Duration::from_secs(30)).await;
                println!("[stats] {}", logger.summary_line());
                logger.flush();
            }
        });
    }

    // Rate limit Jupiter para pares no-SOL
    let interval_ms = (1000.0 / JUPITER_RATE_PER_SEC) as u64;
    let last_call = Arc::new(tokio::sync::Mutex::new(
        std::time::Instant::now() - Duration::from_secs(10)
    ));

    // Separar pares SOL (detección local) del resto (Jupiter HTTP)
    let sol_mint = config::SOL;

    loop {
        // ── VENTANA HORARIA: solo ejecutar en horas activas (1 o 2 ventanas) ──
        let hour_utc = {
            let now = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH).unwrap_or_default();
            (now.as_secs() % 86400) as f64 / 3600.0
        };
        let in_window1 = cfg.live_hours_start.map_or(true, |s|
            hour_utc >= s && cfg.live_hours_end.map_or(true, |e| hour_utc < e));
        let in_window2 = cfg.live_hours_start2.map_or(false, |s|
            hour_utc >= s && cfg.live_hours_end2.map_or(false, |e| hour_utc < e));
        if !in_window1 && !in_window2 {
            tokio::time::sleep(Duration::from_millis(POLL_INTERVAL_MS)).await;
            continue;
        }

        // ── TIP DINÁMICO POR HORA (G25): ajustar tip según competencia esperada ──
        let tip_multiplier = if hour_utc >= 17.0 && hour_utc < 20.0 {
            cfg.tip_multiplier_peak  // alta competencia americana
        } else if hour_utc >= 3.0 && hour_utc < 5.0 {
            cfg.tip_multiplier_asia  // apertura mercado asiático
        } else {
            1.0
        };
        let effective_tip_lamports = (cfg.jito_tip_lamports as f64 * tip_multiplier) as u64;

        // ── KILL-SWITCH: verificar pérdida de sesión ──────────────────────
        if !cfg.paper_mode {
            let net_microcents = session_profit_usdc.load(std::sync::atomic::Ordering::Relaxed);
            let net_usdc = net_microcents as f64 / 1_000_000.0;
            if net_usdc < -MAX_SESSION_LOSS_USDC {
                eprintln!(
                    "[KILL-SWITCH] pérdida de sesión ${:.2} supera límite ${:.2} — pausa 1h",
                    -net_usdc, MAX_SESSION_LOSS_USDC
                );
                tokio::time::sleep(Duration::from_secs(3600)).await;
            }
        }

        // ── CIRCUIT BREAKER (G35): pausar ejecución si mercado anómalo ───
        if cb.is_tripped() {
            if !cb.check_recovery() {
                tokio::time::sleep(Duration::from_secs(5)).await;
                continue;
            }
            // check_recovery devolvió true → ya reseteado, continuar
        }

        // ── LOOP 1: SOL/USDC vía detección local ─────────────────────────
        {
            let prices_guard = pool_prices.read().await;
            if let Some(pp) = prices_guard.as_ref() {
                if pp.is_fresh(POOL_MAX_AGE_MS) {
                    let gap = pp.gap_pct();
                    let (cheap_dex, expensive_dex, _cheap_p, _expensive_p) = pp.direction();

                    // Log estado del pool cada ciclo (para diagnóstico)
                    if gap > 0.0001 {
                        println!(
                            "[pool] gap={:.4}% orca={:.5} raydium={:.5} cheap={}",
                            gap * 100.0, pp.orca, pp.raydium, cheap_dex
                        );
                    }

                    // Circuit breaker: evaluar gap en ventana rolling 60s
                    if let Some(reason) = cb.observe_gap(gap) {
                        eprintln!("[circuit_breaker] activado: {} — gap_avg={:.4}%", reason, gap * 100.0);
                        // TODO: enviar alerta Telegram aquí
                    }

                    if gap >= LOCAL_GAP_MIN && !cb.is_tripped() {
                        let gap_detected_at = std::time::Instant::now();
                        // Oportunidad detectada localmente — confirmar y ejecutar con Jupiter
                        // En LIVE Fase 1 usamos probe conservador $100; en paper, probes completos
                        let probes: Vec<f64> = if cfg.paper_mode {
                            vec![500.0, 900.0]
                        } else {
                            vec![FASE1_PROBE_USDC]
                        };
                        for probe_usdc in &probes {
                            let gross_usdc = probe_usdc * gap;
                            let net_usdc   = gross_usdc - total_cost_usdc;

                            if net_usdc < MIN_PROFIT_USDC { continue; }
                            if gross_usdc / probe_usdc * 10_000.0 < MIN_PROFIT_BPS { continue; }

                            let slippage = tier_slippage_bps(sol_mint);
                            println!(
                                "[+] LOCAL GAP SOL/USDC {:.4}% probe=${} gross=${:.4} net=${:.4} ({} → {})",
                                gap * 100.0, probe_usdc, gross_usdc, net_usdc,
                                cheap_dex, expensive_dex
                            );

                            let result = find_cyclic_arb(
                                &http, sol_mint, *probe_usdc, total_cost_usdc, slippage
                            ).await;

                            match result {
                                ArbResult::Ok(arb) => {
                                    logger.record_opportunity(&arb, true);
                                    println!(
                                        "    [jupiter confirm] net=${:.4} ({:.2} bps) | {:?}→{:?}",
                                        arb.net_profit, arb.profit_bps,
                                        arb.leg1_dexes, arb.leg2_dexes
                                    );

                                    if cfg.paper_mode {
                                        logger.record_probe(sol_mint, *probe_usdc, "ok");
                                        continue;
                                    }

                                    let kp = match keypair.as_ref() {
                                        Some(k) => k,
                                        None => continue,
                                    };
                                    let user = kp.pubkey().to_string();
                                    let (tx1_res, tx2_res) = tokio::join!(
                                        get_swap_transaction(&http, &arb.leg1_quote, &user),
                                        get_swap_transaction(&http, &arb.leg2_quote, &user)
                                    );
                                    let (tx1, tx2) = match (tx1_res, tx2_res) {
                                        (Ok(a), Ok(b)) => (a, b),
                                        _ => { println!("    [live] no se pudo obtener swap tx"); continue; }
                                    };
                                    // A/B tip: A = tip dinámico base, B = base × 1.5
                                    let ab_tip = if rand::thread_rng().gen_bool(0.5) {
                                        effective_tip_lamports
                                    } else {
                                        (effective_tip_lamports as f64 * 1.5) as u64
                                    };
                                    let ab_group = if ab_tip == effective_tip_lamports { "A" } else { "B" };
                                    let gap_to_send_ms = gap_detected_at.elapsed().as_millis() as u64;
                                    execute_bundle(&rpc, &http, tx1, tx2, kp, &cfg,
                                                   &blacklist, &logger, &arb, &session_profit_usdc,
                                                   ab_tip, ab_group, &cached_blockhash, gap_to_send_ms, &cb).await;
                                }
                                ArbResult::NoProfit(arb) => {
                                    logger.record_probe(sol_mint, *probe_usdc, "no_profit");
                                    logger.record_opportunity(&arb, false);
                                    println!("    [jupiter] gap local sí, Jupiter dice no_profit net=${:.4}", arb.net_profit);
                                }
                                ArbResult::NoRoute  => logger.record_probe(sol_mint, *probe_usdc, "no_route"),
                                ArbResult::ApiError => logger.record_probe(sol_mint, *probe_usdc, "api_error"),
                            }
                        }
                    }
                }
            }
            // guard se suelta aquí
        }

        // ── LOOP 2: pares no-SOL vía Jupiter HTTP (JUP, etc.) ────────────
        let pairs = scan_pairs();
        for (mint, amounts) in pairs.iter().filter(|(m, _)| *m != sol_mint) {
            for amount in amounts {
                // Throttle Jupiter
                {
                    let mut last = last_call.lock().await;
                    let elapsed = last.elapsed();
                    if elapsed < Duration::from_millis(interval_ms) {
                        tokio::time::sleep(Duration::from_millis(interval_ms) - elapsed).await;
                    }
                    *last = std::time::Instant::now();
                }

                let slippage = tier_slippage_bps(mint);
                let result = find_cyclic_arb(&http, mint, *amount, total_cost_usdc, slippage).await;

                match result {
                    ArbResult::Ok(arb) | ArbResult::NoProfit(arb) => {
                        let profitable = arb.net_profit >= MIN_PROFIT_USDC && arb.profit_bps >= MIN_PROFIT_BPS;
                        logger.record_probe(mint, *amount, if profitable { "ok" } else { "no_profit" });
                        logger.record_opportunity(&arb, profitable);
                        if !profitable { continue; }

                        println!(
                            "[+] ARB {} USDC → {} → USDC | net=${:.4} ({:.2} bps) | {:?}→{:?}",
                            arb.input_usdc, config::name_for(mint),
                            arb.net_profit, arb.profit_bps,
                            arb.leg1_dexes, arb.leg2_dexes
                        );

                        if cfg.paper_mode {
                            println!("    [paper] quote OK — net=${:.4}", arb.net_profit);
                            continue;
                        }
                        let kp = match keypair.as_ref() { Some(k) => k, None => continue };
                        let user = kp.pubkey().to_string();
                        let (tx1_res, tx2_res) = tokio::join!(
                            get_swap_transaction(&http, &arb.leg1_quote, &user),
                            get_swap_transaction(&http, &arb.leg2_quote, &user)
                        );
                        let (tx1, tx2) = match (tx1_res, tx2_res) {
                            (Ok(a), Ok(b)) => (a, b),
                            _ => { println!("    [live] no se pudo obtener swap tx"); continue; }
                        };
                        execute_bundle(&rpc, &http, tx1, tx2, kp, &cfg,
                                       &blacklist, &logger, &arb, &session_profit_usdc,
                                       effective_tip_lamports, "A", &cached_blockhash, 0, &cb).await;
                    }
                    ArbResult::NoRoute  => logger.record_probe(mint, *amount, "no_route"),
                    ArbResult::ApiError => logger.record_probe(mint, *amount, "api_error"),
                }
            }
        }

        tokio::time::sleep(Duration::from_millis(POLL_INTERVAL_MS)).await;
    }
}

async fn execute_bundle(
    rpc: &Arc<RpcClient>,
    http: &reqwest::Client,
    tx1: String,
    tx2: String,
    keypair: &Keypair,
    _cfg: &EnvCfg,
    blacklist: &VoteAccountBlacklist,
    logger: &Logger,
    arb: &jupiter::CyclicArb,
    session_profit: &Arc<std::sync::atomic::AtomicI64>,
    tip_lamports: u64,
    ab_group: &str,
    blockhash_cache: &Arc<tokio::sync::RwLock<Option<solana_sdk::hash::Hash>>>,
    gap_to_send_ms: u64,
    cb: &Arc<CircuitBreaker>,
) {
    let built = build_bundle(rpc, &tx1, &tx2, keypair, tip_lamports, blacklist, blockhash_cache).await;
    let built = match built {
        Ok(Some(b)) => b,
        Ok(None)    => { println!("    [live] bundle: descartado (blacklist)"); return; }
        Err(e)      => { println!("    [live] buildBundle error — {e}"); return; }
    };

    let sent = send_bundle(http, &built.bundle, &built.swap_txs, blacklist).await;
    let (bundle_id, endpoint) = match sent {
        Some(x) => x,
        None    => { println!("    [live] bundle: todos los endpoints fallaron"); return; }
    };
    let host = url::Url::parse(&endpoint).ok()
        .and_then(|u| u.host_str().map(|s| s.split('.').next().unwrap_or("?").to_string()))
        .unwrap_or_default();
    println!("    [live] bundle enviado: {bundle_id} ({host})");
    println!("    [live] gap_to_send={gap_to_send_ms}ms tip={tip_lamports} ab={ab_group}");
    logger.record_bundle_sent(&bundle_id, &endpoint, arb.net_profit, &arb.intermediate, arb.input_usdc, tip_lamports, ab_group, gap_to_send_ms);

    let logger_p  = logger.clone();
    let http_p    = http.clone();
    let profit_p  = session_profit.clone();
    let cb_p      = cb.clone();
    let net_usdc  = arb.net_profit;
    tokio::spawn(async move {
        let status = poll_bundle_status(&http_p, &bundle_id, &endpoint, 20_000).await;
        let sym = match status { "landed" => "✅", "failed" => "❌", _ => "⏱" };
        println!("    [jito] {sym} bundle {}… → {status}", &bundle_id[..8.min(bundle_id.len())]);
        logger_p.record_bundle_status(&bundle_id, status);

        // Circuit Breaker: registrar éxito o fallo consecutivo
        if status == "landed" {
            cb_p.record_success();
        } else if status == "failed" {
            if let Some(reason) = cb_p.record_failure() {
                eprintln!("[circuit_breaker] activado: {} — demasiados fallos consecutivos", reason);
                // TODO: enviar alerta Telegram aquí
            }
        }

        let delta_microcents = if status == "landed" {
            (net_usdc * 1_000_000.0) as i64
        } else {
            -100_i64
        };
        profit_p.fetch_add(delta_microcents, std::sync::atomic::Ordering::Relaxed);
    });
}
