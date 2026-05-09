# Conteo de outliers rejected por source (audit collusion BS-3)
# Firma Gemma r110 §4
[
  inputs
  | select(.audit_type == "btc_consensus_fetch")
  | .outliers_rejected[]?
] | group_by(.) | map({source: .[0], rejection_count: length}) | sort_by(.rejection_count) | reverse
