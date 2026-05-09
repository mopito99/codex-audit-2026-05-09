# Latency descompuesta T0→T1→T2 (firma Gemma r110 §4b + r111 §3)
# T0: tick API recibido
# T1: weighted_median calculated
# T2: mode_decision committed
[
  inputs
  | select(.audit_type == "mode_transition")
  | select(.latency_breakdown != null)
  | {
      ts: .ts_utc,
      event: (.trigger.event // null),
      fetch_ms: .latency_breakdown.fetch_latency_ms,
      compute_ms: .latency_breakdown.compute_latency_ms,
      total_ms: .latency_breakdown.total_decision_latency_ms,
      mode_to: .mode_decision.mode_after,
      runtime_version: .runtime_version,
    }
] | {
  count: length,
  fetch_ms_p50: ([.[] | .fetch_ms] | sort | .[length/2 | floor]),
  fetch_ms_p99: ([.[] | .fetch_ms] | sort | .[length*0.99 | floor]),
  compute_ms_p50: ([.[] | .compute_ms] | sort | .[length/2 | floor]),
  compute_ms_p99: ([.[] | .compute_ms] | sort | .[length*0.99 | floor]),
  total_ms_p50: ([.[] | .total_ms] | sort | .[length/2 | floor]),
  total_ms_p99: ([.[] | .total_ms] | sort | .[length*0.99 | floor]),
  worst_decision: max_by(.total_ms),
}
