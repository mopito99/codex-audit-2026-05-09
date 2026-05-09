#![allow(dead_code)] // Constantes/funciones para Phase 2 LIVE (sandwich y cyclic activos)
// G49 — Prometheus metrics: 7 contadores/gauges/histogramas del sandwich bot.
// Exporta en :9090/metrics para Grafana en Dallas.
// Lock-free: prometheus usa AtomicU64 internamente — safe desde listener y executor.

use prometheus::{
    register_counter, register_gauge, register_histogram,
    Counter, Encoder, Gauge, Histogram, TextEncoder,
};
use std::sync::OnceLock;

// ── Métricas globales (inicializadas una vez en main) ─────────────────────────

static VICTIM_DETECTED:      OnceLock<Counter>   = OnceLock::new();
static BUNDLE_SENT:          OnceLock<Counter>   = OnceLock::new();
static BUNDLE_LANDED:        OnceLock<Counter>   = OnceLock::new();
static STALE_RATE:           OnceLock<Gauge>     = OnceLock::new();
static P95_TIP_LAMPORTS:     OnceLock<Gauge>     = OnceLock::new();
static NET_PROFIT_USDC:      OnceLock<Counter>   = OnceLock::new();
static PIPELINE_LATENCY_MS:  OnceLock<Histogram> = OnceLock::new();

/// Registrar todas las métricas en el registry global de prometheus.
/// Llamar una sola vez desde main() antes de arrancar el bot.
pub fn init() {
    VICTIM_DETECTED.get_or_init(|| {
        register_counter!(
            "sandwich_victim_detected_total",
            "Víctimas detectadas por gRPC Yellowstone"
        ).expect("register victim_detected")
    });
    BUNDLE_SENT.get_or_init(|| {
        register_counter!(
            "sandwich_bundle_sent_total",
            "Bundles enviados a Jito NY"
        ).expect("register bundle_sent")
    });
    BUNDLE_LANDED.get_or_init(|| {
        register_counter!(
            "sandwich_bundle_landed_total",
            "Bundles confirmados landed (getSignatureStatuses)"
        ).expect("register bundle_landed")
    });
    STALE_RATE.get_or_init(|| {
        register_gauge!(
            "sandwich_stale_rate",
            "Fracción de víctimas rechazadas por estado stale del pool"
        ).expect("register stale_rate")
    });
    P95_TIP_LAMPORTS.get_or_init(|| {
        register_gauge!(
            "sandwich_p95_tip_lamports",
            "Tip p95 del stream Jito rolling 30s (lamports)"
        ).expect("register p95_tip")
    });
    NET_PROFIT_USDC.get_or_init(|| {
        register_counter!(
            "sandwich_net_profit_usdc_total",
            "Profit neto acumulado real (back_out - front_in - tip) en USDC"
        ).expect("register net_profit")
    });
    PIPELINE_LATENCY_MS.get_or_init(|| {
        register_histogram!(
            "sandwich_pipeline_latency_ms",
            "Latencia victim_detected→bundle_sent en ms",
            vec![5.0, 10.0, 20.0, 30.0, 50.0, 75.0, 100.0, 150.0, 200.0, 300.0]
        ).expect("register pipeline_latency")
    });
}

// ── Helpers de actualización ──────────────────────────────────────────────────

pub fn inc_victim_detected() {
    if let Some(c) = VICTIM_DETECTED.get() { c.inc(); }
}

pub fn inc_bundle_sent() {
    if let Some(c) = BUNDLE_SENT.get() { c.inc(); }
}

pub fn inc_bundle_landed() {
    if let Some(c) = BUNDLE_LANDED.get() { c.inc(); }
}

pub fn set_stale_rate(rate: f64) {
    if let Some(g) = STALE_RATE.get() { g.set(rate); }
}

pub fn set_p95_tip(lamports: u64) {
    if let Some(g) = P95_TIP_LAMPORTS.get() { g.set(lamports as f64); }
}

pub fn add_net_profit(usdc: f64) {
    if usdc > 0.0 {
        if let Some(c) = NET_PROFIT_USDC.get() { c.inc_by(usdc); }
    }
}

pub fn observe_pipeline_latency(ms: u64) {
    if let Some(h) = PIPELINE_LATENCY_MS.get() { h.observe(ms as f64); }
}

// ── Servidor HTTP /metrics (tokio, sin hyper) ─────────────────────────────────

/// Arranca un servidor HTTP mínimo en `0.0.0.0:port` que sirve /metrics.
/// Solo acepta GET /metrics — responde con el formato texto de Prometheus.
pub async fn serve(port: u16) {
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    use tokio::net::TcpListener;

    let addr = format!("0.0.0.0:{port}");
    let listener = match TcpListener::bind(&addr).await {
        Ok(l) => { println!("[metrics] escuchando en http://{addr}/metrics"); l }
        Err(e) => { eprintln!("[metrics] no se pudo bindear {addr}: {e}"); return; }
    };

    loop {
        let Ok((mut socket, _peer)) = listener.accept().await else { continue };
        tokio::spawn(async move {
            // Leer request (ignoramos el contenido, solo servimos métricas)
            let mut buf = [0u8; 256];
            let _ = socket.read(&mut buf).await;

            let encoder = TextEncoder::new();
            let families = prometheus::gather();
            let mut body = Vec::new();
            if encoder.encode(&families, &mut body).is_err() {
                return;
            }

            let header = format!(
                "HTTP/1.1 200 OK\r\nContent-Type: text/plain; version=0.0.4; charset=utf-8\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
                body.len()
            );
            let _ = socket.write_all(header.as_bytes()).await;
            let _ = socket.write_all(&body).await;
        });
    }
}
