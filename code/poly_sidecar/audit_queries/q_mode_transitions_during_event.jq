# Mode transitions durante NFP/CPI/FOMC window
# Firma Gemma r110 §4
[
  inputs
  | select(.audit_type == "mode_transition")
  | {
      ts: .ts_utc,
      mode_from: .mode_decision.mode_before,
      mode_to: .mode_decision.mode_after,
      reason: .mode_decision.decision_reason,
      sf: (.sf_calculation.sf_used_for_decision // null),
      runtime_version: .runtime_version,
    }
] | sort_by(.ts)
