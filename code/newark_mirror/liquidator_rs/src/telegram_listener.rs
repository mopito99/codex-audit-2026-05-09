//! R42 Q3 — Telegram inbound listener for safe ops commands.
//!
//! Triple-lock whitelist: from.id ∈ admin_user_ids
//!                        AND chat.id == expected_chat_id
//!                        AND message_thread_id == admin_topic_id
//! Plus `/cb_reset <SECRET_TOKEN>` to gate against replay/social engineering.
//!
//! ⚠ TODOs (R43 follow-ups):
//!   1. `from.id` and `chat.id` real values — Gemma R43 #4 explains how to find them programmatically.
//!   2. CircuitBreaker API mapping:
//!      Gemma uses `cb.reset()` and `cb.get_status()` — our actual API is
//!      `cb.safe_reset() -> Result<(), String>` and `cb.last_trip_reason()` / `cb.is_tripped()`.
//!      Adapted in this file to use the real API.
//!   3. Concurrent access — main.rs needs Arc<CircuitBreaker> not Arc<Mutex<CB>>
//!      because our CB uses interior mutability (atomics). The `&mut CircuitBreaker`
//!      that Gemma's snippet expects is replaced here with `&Arc<CircuitBreaker>`.

use crate::circuit_breaker::CircuitBreaker;
use crate::stats::DaemonStats;
use reqwest::Client;
use serde::Deserialize;
use std::collections::HashSet;
use std::sync::Arc;
use tokio::time::Duration;
use tracing::{error, info, warn};

#[derive(Deserialize)]
struct Update {
    update_id: u64,
    message: Option<Message>,
}

#[derive(Deserialize)]
struct Message {
    #[serde(default)]
    #[allow(dead_code)]
    message_id: u64,
    from: User,
    chat: Chat,
    text: Option<String>,
    #[serde(default)]
    message_thread_id: Option<i64>,
}

#[derive(Deserialize)]
struct User {
    id: u64,
}

#[derive(Deserialize)]
struct Chat {
    id: i64,
}

#[derive(Clone)]
pub struct TelegramConfig {
    pub bot_token: String,
    pub admin_user_ids: HashSet<u64>,
    pub expected_chat_id: i64,
    pub admin_topic_id: i64,
    pub secret_token: String,
}

pub struct TelegramListener {
    config: TelegramConfig,
    client: Client,
    last_update_id: u64,
}

impl TelegramListener {
    pub fn new(config: TelegramConfig) -> Self {
        Self {
            config,
            client: Client::builder()
                .timeout(Duration::from_secs(35))
                .build()
                .expect("reqwest client"),
            last_update_id: 0,
        }
    }

    pub async fn listen(
        mut self,
        circuit_breaker: Arc<CircuitBreaker>,
        stats: Arc<DaemonStats>,
    ) {
        info!(
            chat = self.config.expected_chat_id,
            topic = self.config.admin_topic_id,
            "telegram listener started"
        );

        loop {
            let url = format!(
                "https://api.telegram.org/bot{}/getUpdates?offset={}&timeout=30",
                self.config.bot_token,
                self.last_update_id + 1
            );

            match self.client.get(&url).send().await {
                Ok(resp) => match resp.json::<serde_json::Value>().await {
                    Ok(body) => {
                        if let Some(result) = body.get("result").and_then(|r| r.as_array()) {
                            for update_val in result {
                                if let Ok(update) =
                                    serde_json::from_value::<Update>(update_val.clone())
                                {
                                    self.last_update_id = update.update_id;
                                    if let Some(msg) = update.message {
                                        self.handle_message(msg, &circuit_breaker, &stats).await;
                                    }
                                }
                            }
                        }
                    }
                    Err(e) => warn!(error=?e, "telegram getUpdates parse"),
                },
                Err(e) => {
                    error!(error=?e, "telegram getUpdates");
                    tokio::time::sleep(Duration::from_secs(5)).await;
                }
            }
        }
    }

    async fn handle_message(
        &self,
        msg: Message,
        cb: &Arc<CircuitBreaker>,
        stats: &Arc<DaemonStats>,
    ) {
        // STRICT WHITELIST VALIDATION (R42 Q3)
        let is_admin = self.config.admin_user_ids.contains(&msg.from.id);
        let is_correct_chat = msg.chat.id == self.config.expected_chat_id;
        let is_correct_topic = msg.message_thread_id == Some(self.config.admin_topic_id);

        if !is_admin || !is_correct_chat || !is_correct_topic {
            warn!(
                from_id = msg.from.id,
                chat_id = msg.chat.id,
                thread = ?msg.message_thread_id,
                "telegram unauthorized attempt — silent drop"
            );
            return;
        }

        let text = match msg.text {
            Some(t) => t,
            None => return,
        };
        let trimmed = text.trim();

        if trimmed == "/cb_status" {
            let tripped = cb.is_tripped();
            let reason = cb
                .last_trip_reason()
                .map(|r| format!("{r:?}"))
                .unwrap_or_else(|| "OK".to_string());
            let consec = cb.consecutive_failures();
            self.send(format!(
                "CB status — tripped={tripped} reason={reason} consecutive_failures={consec}"
            ))
            .await;
        } else if trimmed.starts_with("/cb_reset") {
            let parts: Vec<&str> = trimmed.split_whitespace().collect();
            if parts.len() == 2 && parts[1] == self.config.secret_token {
                match cb.safe_reset() {
                    Ok(()) => self.send("CB safe_reset OK".into()).await,
                    Err(e) => self.send(format!("CB safe_reset rejected: {e}")).await,
                }
            } else {
                self.send("Error: invalid /cb_reset secret token".into()).await;
            }
        } else if trimmed == "/bot_stats" {
            self.send(stats.snapshot_text()).await;
        } else if trimmed.starts_with("/stop") {
            // R55 — kill switch: trip CB with WalletDrain so safe_reset rejects auto-recovery.
            // Requires /manual_reset or service restart to clear.
            let parts: Vec<&str> = trimmed.split_whitespace().collect();
            if parts.len() == 2 && parts[1] == self.config.secret_token {
                cb.trip(crate::circuit_breaker::TripReason::WalletDrain);
                self.send(
                    "🛑 STOP — daemon paused. CB tripped with WalletDrain. \
                     would_send=false until /manual_reset or service restart."
                        .into(),
                )
                .await;
            } else {
                self.send("Error: invalid /stop secret token".into()).await;
            }
        } else if trimmed.starts_with("/manual_reset") {
            let parts: Vec<&str> = trimmed.split_whitespace().collect();
            if parts.len() == 2 && parts[1] == self.config.secret_token {
                cb.manual_reset();
                self.send("✅ CB manual_reset OK — daemon resumed".into()).await;
            } else {
                self.send("Error: invalid /manual_reset secret token".into()).await;
            }
        } else if trimmed == "/help" {
            self.send(
                "Commands:\n\
                 /cb_status              — show CB state\n\
                 /cb_reset <secret>      — safe reset (rejects SlotLag/WalletDrain)\n\
                 /stop <secret>          — 🛑 KILL SWITCH (CB trip WalletDrain)\n\
                 /manual_reset <secret>  — force clear any trip\n\
                 /bot_stats              — telemetry snapshot\n\
                 /help                   — this"
                    .into(),
            )
            .await;
        }
    }

    async fn send(&self, text: String) {
        let url = format!(
            "https://api.telegram.org/bot{}/sendMessage",
            self.config.bot_token
        );
        let payload = serde_json::json!({
            "chat_id": self.config.expected_chat_id,
            "message_thread_id": self.config.admin_topic_id,
            "text": text,
        });
        if let Err(e) = self.client.post(&url).json(&payload).send().await {
            error!(error=?e, "telegram sendMessage failed");
        }
    }
}

/// R47 C2 — load TelegramConfig from .env (TG_BOT_TOKEN, TG_ADMIN_USER_IDS,
/// TG_EXPECTED_CHAT_ID, TG_ADMIN_TOPIC_ID, TG_SECRET_TOKEN). CSV format for IDs.
pub fn parse_telegram_config_from_env() -> anyhow::Result<TelegramConfig> {
    let token = std::env::var("TG_BOT_TOKEN")
        .map_err(|_| anyhow::anyhow!("TG_BOT_TOKEN missing"))?;
    let admin_user_ids: HashSet<u64> = std::env::var("TG_ADMIN_USER_IDS")
        .unwrap_or_default()
        .split(",")
        .map(|s| s.trim())
        .filter_map(|s| s.parse::<u64>().ok())
        .collect();
    if admin_user_ids.is_empty() {
        anyhow::bail!("TG_ADMIN_USER_IDS missing or empty");
    }
    let expected_chat_id: i64 = std::env::var("TG_EXPECTED_CHAT_ID")?.parse()?;
    let admin_topic_id: i64 = std::env::var("TG_ADMIN_TOPIC_ID")?.parse()?;
    let secret_token = std::env::var("TG_SECRET_TOKEN")
        .map_err(|_| anyhow::anyhow!("TG_SECRET_TOKEN missing"))?;
    Ok(TelegramConfig {
        bot_token: token,
        admin_user_ids,
        expected_chat_id,
        admin_topic_id,
        secret_token,
    })
}
