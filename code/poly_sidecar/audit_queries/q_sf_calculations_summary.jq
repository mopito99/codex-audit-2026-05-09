# Resumen SF calculations (todos, no solo transitions)
# Firma Gemma r92 §2 (log everything)
[
  inputs
  | select(.audit_type == "sf_calculation" or .audit_type == "mode_transition")
  | {
      ts: .ts_utc,
      event: (.event // .trigger.event // null),
      sf_naive: (.sf_naive // .sf_calculation.sf_naive // null),
      sf_adjusted: (.sf_adjusted // .sf_calculation.sf_adjusted // null),
      threshold_crossed: (.threshold_crossed // null),
      mode_transition: (.mode_transition // .mode_decision.mode_unchanged | not),
    }
] | sort_by(.ts) | reverse
