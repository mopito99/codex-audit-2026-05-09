"""Audit smoke runner.

Goal: produce a reproducible, auditor-friendly snapshot showing:
- health endpoint reachable (if web is running)
- BingX depth endpoint reachable and microstructure derivation works
- DT/PPO weight files detection
- TimeGAN/DT tooling presence

This does not trade; it only probes read-only market endpoints and local artifacts.
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

# Allow running as a script from repo root
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


async def _probe_bingx_depth(symbol: str, limit: int):
    from app.data.bingx import BingXReader
    from main import _compute_microstructure_from_depth

    b = BingXReader()
    depth = await b.get_depth(symbol, limit=limit)
    if not depth:
        return {"ok": False, "reason": "no depth"}

    ms = _compute_microstructure_from_depth(depth, top_n=min(10, limit))
    return {"ok": True, "microstructure": ms}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="BTC-USDT")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--out", default="/srv/profitlab_quantum/artifacts/audit_smoke.json")
    args = ap.parse_args()

    from app.config import PPO_WEIGHTS_PATH, DT_WEIGHTS_PATH, DT_META_PATH

    out = {
        "env": {
            "AGENT_TYPE": os.getenv("AGENT_TYPE", "ppo_transformer"),
            "USE_WS_FEED": os.getenv("USE_WS_FEED", "1"),
            "USE_ORDERBOOK": os.getenv("USE_ORDERBOOK", "1"),
            "BINGX_FEE_TAKER": os.getenv("BINGX_FEE_TAKER", "0.001"),
            "BINGX_SLIPPAGE_BPS": os.getenv("BINGX_SLIPPAGE_BPS", "2.5"),
        },
        "artifacts": {
            "ppo_weights_path": PPO_WEIGHTS_PATH,
            "ppo_weights_exists": Path(PPO_WEIGHTS_PATH).exists(),
            "dt_weights_path": DT_WEIGHTS_PATH,
            "dt_weights_exists": Path(DT_WEIGHTS_PATH).exists(),
            "dt_meta_path": DT_META_PATH,
            "dt_meta_exists": Path(DT_META_PATH).exists(),
        },
        "tools_present": {
            "train_timegan": Path("tools/train_timegan.py").exists(),
            "train_decision_transformer": Path("tools/train_decision_transformer.py").exists(),
        },
    }

    out["bingx_depth"] = asyncio.run(_probe_bingx_depth(args.symbol, int(args.limit)))

    p = Path(args.out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, indent=2, sort_keys=True))
    print("OK", str(p))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
