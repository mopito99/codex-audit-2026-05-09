#!/bin/bash
set -u
LOG_PATH="/home/ubuntu/liquidator_rs/data/cyclic_shadow.jsonl"
T0_FILE="/home/ubuntu/liquidator_rs/data/shadow_run.t0"
ANALYZER="/home/ubuntu/liquidator_rs/analyze_shadow.py"
TG_TOKEN="<REDACTED-TG-BOT-TOKEN>"
TG_CHAT="-1003801924175"
TG_TOPIC="3"  # arb topic

OUT_FILE="/home/ubuntu/liquidator_rs/data/shadow_verdict_$(date -u +%Y%m%dT%H%M%SZ).txt"
T0=$(cat "$T0_FILE" 2>/dev/null || echo "T0=unknown")
LINES=$(wc -l < "$LOG_PATH")

{
  echo "===== CYCLIC SHADOW 24H VERDICT ====="
  echo "$T0"
  echo "TF=$(date -u +%FT%TZ)"
  echo "records=$LINES"
  echo "----- analyze_shadow.py output -----"
  python3 "$ANALYZER" "$LOG_PATH" 2>&1
  echo "----- end -----"
} > "$OUT_FILE"

# Telegram (truncate to ~3500 chars to fit)
BODY=$(head -c 3500 "$OUT_FILE")
curl -s -X POST "https://api.telegram.org/bot${TG_TOKEN}/sendMessage" \
  -d chat_id="${TG_CHAT}" \
  -d message_thread_id="${TG_TOPIC}" \
  -d parse_mode=Markdown \
  --data-urlencode text="\`\`\`
${BODY}
\`\`\`" > /dev/null

echo "verdict written to $OUT_FILE and posted to Telegram"
