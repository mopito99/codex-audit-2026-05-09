# V3 vs V4 disagreement counter (V4 hubiera bloqueado pero V3 dejaba pasar)
# Firma Gemma r92
[
  inputs
  | select(.v3_v4_disagreement == true)
] | {
  total: length,
  by_block_reason: ([.[] | .v4_block_reason] | group_by(.) | map({reason: .[0], count: length})),
}
