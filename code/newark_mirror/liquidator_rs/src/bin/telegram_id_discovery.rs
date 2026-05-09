//! R46/R47 C1 — Telegram ID discovery helper.
//! Polls getUpdates, prints from.id, chat.id, message_thread_id for each
//! incoming message. Used once to populate the TG_* env vars for C2.
//!
//! Pre-flight (BotFather):
//!   1. /setprivacy → select bot → Disable
//!   2. Add bot as ADMIN to the EcoArb channel
//!   3. (re-add bot if it was already there)
//! Then: TG_BOT_TOKEN=... cargo run --bin telegram_id_discovery
//! Send "ID_CHECK" in the admin topic → Ctrl+C when captured.

use dotenvy::dotenv;
use serde::Deserialize;
use std::env;
use std::time::Duration;

#[derive(Deserialize, Debug)]
struct Update {
    update_id: u64,
    message: Option<Message>,
}

#[derive(Deserialize, Debug)]
struct Message {
    #[allow(dead_code)]
    message_id: u64,
    from: User,
    chat: Chat,
    text: Option<String>,
    message_thread_id: Option<u64>,
}

#[derive(Deserialize, Debug)]
struct User {
    id: u64,
    username: Option<String>,
    #[allow(dead_code)]
    first_name: Option<String>,
}

#[derive(Deserialize, Debug)]
struct Chat {
    id: i64,
    #[serde(rename = "type")]
    chat_type: String,
}

#[derive(Deserialize, Debug)]
struct TelegramResponse {
    #[allow(dead_code)]
    ok: bool,
    result: Vec<Update>,
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    dotenv().ok();
    let token = env::var("TG_BOT_TOKEN").expect("TG_BOT_TOKEN must be set in .env");
    let mut offset = 0u64;

    println!("[TELEGRAM ID DISCOVERY] active");
    println!("Listening for messages... send 'ID_CHECK' in your admin topic.");
    println!("Ctrl+C to stop.\n");

    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(35))
        .build()?;

    loop {
        let url = format!(
            "https://api.telegram.org/bot{}/getUpdates?offset={}&timeout=30",
            token, offset
        );

        match client.get(&url).send().await {
            Ok(resp) => {
                if let Ok(data) = resp.json::<TelegramResponse>().await {
                    for update in data.result {
                        if let Some(msg) = update.message {
                            println!("--------------------------------------------------");
                            println!("[TELEGRAM ID DISCOVERY]");
                            println!("  update_id            : {}", update.update_id);
                            println!("  from.id              : {}  (= USER ID)", msg.from.id);
                            println!(
                                "  from.username        : {}",
                                msg.from.username.as_deref().unwrap_or("N/A")
                            );
                            println!("  chat.id              : {}  (= CHAT ID)", msg.chat.id);
                            println!("  chat.type            : \"{}\"", msg.chat.chat_type);
                            println!(
                                "  message_thread_id    : {}  (= TOPIC ID)",
                                msg.message_thread_id.unwrap_or(0)
                            );
                            println!(
                                "  text                 : {}",
                                msg.text.as_deref().unwrap_or("Empty")
                            );
                            println!("--------------------------------------------------");
                        }
                        offset = update.update_id + 1;
                    }
                }
            }
            Err(e) => {
                eprintln!("request error: {}. Retrying in 1s...", e);
                tokio::time::sleep(Duration::from_secs(1)).await;
            }
        }
    }
}
