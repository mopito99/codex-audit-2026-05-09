# Kill switch BTC triggers en últimas 24h
# Firma Gemma r110 §4
[
  inputs
  | select(.audit_type == "kill_switch_btc_trigger")
  | {
      ts: .ts_utc,
      btc_move_pct: .trigger_result.btc_move_pct,
      threshold_pct: .trigger_result.threshold_pct,
      event: .trigger_result.matched_event.event,
      consensus_price: .trigger_result.consensus_price_at_trigger,
      forensic_sources: .trigger_result.forensic_per_source,
      system_load: .trigger_result.system_load,
    }
] | sort_by(.ts) | reverse
