# Latency p99 fetch_total_ms del btc_consensus
# Firma Gemma r110 §4
[
  inputs
  | select(.audit_type == "btc_consensus_fetch")
  | .fetch_total_ms
] | sort | {
  count: length,
  p50: .[length/2 | floor],
  p95: .[length*0.95 | floor],
  p99: .[length*0.99 | floor],
  max: .[-1],
  min: .[0],
}
