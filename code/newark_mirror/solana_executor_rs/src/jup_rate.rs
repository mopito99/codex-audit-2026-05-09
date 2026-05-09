// Rate limiter global para Jupiter API.
// Una sola instancia global controla TODAS las llamadas a Jupiter
// desde cualquier modulo (cyclic arb, fat_finger, etc).

use std::sync::{Mutex, OnceLock};
use std::time::{Duration, Instant};

const JUP_MIN_INTERVAL_MS: u64 = 1000; // 1.67 calls/sec max — seguro bajo Jupiter free tier

static JUP_LAST_CALL: OnceLock<Mutex<Instant>> = OnceLock::new();

pub async fn throttle() {
    let mutex = JUP_LAST_CALL.get_or_init(|| Mutex::new(Instant::now() - Duration::from_secs(10)));
    let sleep_ms = {
        let mut last = mutex.lock().unwrap();
        let elapsed = last.elapsed();
        let interval = Duration::from_millis(JUP_MIN_INTERVAL_MS);
        if elapsed < interval {
            let sleep = interval - elapsed;
            *last = Instant::now() + sleep;
            sleep.as_millis() as u64
        } else {
            *last = Instant::now();
            0
        }
    };
    if sleep_ms > 0 {
        tokio::time::sleep(Duration::from_millis(sleep_ms)).await;
    }
}
