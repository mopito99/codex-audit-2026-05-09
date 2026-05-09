"""Export minimal on-disk artifacts for audit/homologation.

This script creates the expected PPO/DT artifact files so an auditor can verify:
- model architectures are present
- weights files exist and can be loaded by the runtime

It does NOT claim the models are trained; it exports current initialized weights.
If you want trained artifacts, run the training scripts in tools/.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Allow running as a script from repo root
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _ensure_parent(path: str) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def export_ppo() -> str:
    # Ensure config reads PPO agent selection.
    os.environ.setdefault("AGENT_TYPE", "ppo_transformer")

    from app.config import PPO_WEIGHTS_PATH, PPO_PER_SYMBOL, PPO_WEIGHTS_DIR
    from app.engine import QuantumEngine

    export_symbol = os.getenv("PPO_EXPORT_SYMBOL", "BTC-USDT").strip() or "BTC-USDT"

    engine = QuantumEngine(initial_capital=10000.0, symbol=export_symbol)

    if bool(PPO_PER_SYMBOL):
        # Mirror runtime layout: <PPO_WEIGHTS_DIR>/<SYMBOL>/ppo.pt
        safe = "".join([c if (c.isalnum() or c in ("-", "_", ".")) else "_" for c in export_symbol.upper()])
        out_path = Path(str(PPO_WEIGHTS_DIR)) / (safe or "UNKNOWN") / "ppo.pt"
        p = _ensure_parent(str(out_path))
    else:
        p = _ensure_parent(str(PPO_WEIGHTS_PATH))

    engine.agent.save(str(p))
    return str(p)


def export_dt() -> tuple[str, str]:
    # Ensure config reads DT-related defaults.
    os.environ.setdefault("AGENT_TYPE", "decision_transformer")

    from app.config import DT_CONTEXT_LEN, DT_META_PATH, DT_WEIGHTS_PATH
    from app.engine import QuantumEngine

    # Creating the engine will build DTConfig (and meta if present) consistently.
    # Then we export weights + a minimal meta file.
    _ = QuantumEngine(initial_capital=10000.0)

    w = _ensure_parent(str(DT_WEIGHTS_PATH))
    m = _ensure_parent(str(DT_META_PATH))

    # Export initialized DT model weights
    # (We re-import through engine so that architecture stays aligned with runtime.)
    from app.models.decision_transformer import DTConfig, DecisionTransformer

    state_dim = 21
    cfg = DTConfig(state_dim=state_dim, act_dim=3, context_len=int(DT_CONTEXT_LEN))
    model = DecisionTransformer(cfg)

    import torch

    torch.save(model.state_dict(), str(w))

    meta = {
        "state_dim": int(state_dim),
        "act_dim": 3,
        "context_len": int(cfg.context_len),
        "d_model": int(cfg.d_model),
        "nhead": int(cfg.nhead),
        "nlayer": int(cfg.nlayer),
        "trained": False,
        "exported_by": "tools/export_audit_artifacts.py",
    }
    m.write_text(json.dumps(meta, indent=2, sort_keys=True))

    return str(w), str(m)


def main() -> int:
    ppo_path = export_ppo()
    dt_w, dt_m = export_dt()
    print("OK PPO", ppo_path)
    print("OK DT", dt_w)
    print("OK DT_META", dt_m)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
