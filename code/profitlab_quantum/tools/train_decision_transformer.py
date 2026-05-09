import argparse
import json
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from sqlalchemy import text

from app.db import get_db
from app.models.decision_transformer import DTConfig, DecisionTransformer


ACTION_MAP = {"HOLD": 0, "LONG": 1, "SHORT": 2}


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _extract_state(features: dict, state_keys: list[str]) -> np.ndarray:
    out = []
    for k in state_keys:
        v = features.get(k, 0.0)
        try:
            fv = float(v)
            if not np.isfinite(fv):
                fv = 0.0
        except Exception:
            fv = 0.0
        out.append(fv)
    return np.asarray(out, dtype=np.float32)


def _parse_rows(rows, state_keys):
    """Parse decision-log rows into (feats, acts, closes) lists."""
    feats, acts, closes = [], [], []
    for row in rows:
        try:
            f = json.loads(row.features)
        except Exception:
            continue
        rec = str(f.get("recommendation", "HOLD")).upper()
        feats.append(_extract_state(f, state_keys))
        acts.append(ACTION_MAP.get(rec, 0))
        closes.append(float(f.get("close_price", 0.0) or 0.0))
    return feats, acts, closes


def _proxy_rewards(acts, closes):
    """Compute proxy rewards from close deltas and actions."""
    rewards = []
    for i in range(len(closes) - 1):
        p0, p1 = closes[i], closes[i + 1]
        if p0 == 0:
            rewards.append(0.0)
        elif acts[i] == 1:
            rewards.append((p1 - p0) / p0)
        elif acts[i] == 2:
            rewards.append(-(p1 - p0) / p0)
        else:
            rewards.append(0.0)
    rewards.append(0.0)
    return rewards


def _returns_to_go(rewards):
    """Compute cumulative future rewards."""
    rtg = []
    running = 0.0
    for rwd in reversed(rewards):
        running = float(rwd) + running
        rtg.append(running)
    return list(reversed(rtg))


def _build_sequences(rows, context_len: int, state_keys: list[str]):
    by_symbol = {}
    for r in rows:
        by_symbol.setdefault(r.symbol, []).append(r)

    samples = []
    for _sym, rs in by_symbol.items():
        rs = sorted(rs, key=lambda x: x.timestamp)
        feats, acts, closes = _parse_rows(rs, state_keys)

        if len(feats) < context_len + 1:
            continue

        rewards = _proxy_rewards(acts, closes)
        rtg = _returns_to_go(rewards)

        for i in range(0, len(feats) - context_len):
            s_seq = np.stack(feats[i : i + context_len], axis=0)
            a_seq = np.asarray(acts[i : i + context_len], dtype=np.int64)
            rtg_seq = np.asarray(rtg[i : i + context_len], dtype=np.float32).reshape(context_len, 1)
            target_a = int(acts[i + context_len - 1])
            samples.append((s_seq, a_seq, rtg_seq, target_a))

    return samples


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--context-len", type=int, default=32)
    ap.add_argument("--out", default="/srv/profitlab_quantum/artifacts/dt")
    ap.add_argument("--steps", type=int, default=2000)
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--d-model", type=int, default=128)
    ap.add_argument("--nhead", type=int, default=4)
    ap.add_argument("--nlayer", type=int, default=3)
    args = ap.parse_args()

    out_dir = Path(args.out)
    _ensure_dir(out_dir)

    # Keep state keys aligned with engine state columns + HTF context
    state_keys = [
        "open",
        "high",
        "low",
        "close",
        "volume",
        "fvg_bull_size",
        "fvg_bear_size",
        "is_fvg_bull",
        "is_fvg_bear",
        "is_sweep_high",
        "is_sweep_low",
        "bull_ob_distance",
        "bear_ob_distance",
        "bull_ob_age",
        "bear_ob_age",
        "bull_ob_tests",
        "bear_ob_tests",
        "bull_ob_mitigated",
        "bear_ob_mitigated",
        "htf_bias",
        "htf_trend",
    ]

    db = get_db()
    try:
        rows = db.execute(
            text(
                """
                SELECT timestamp, symbol, features
                FROM decision_logs
                ORDER BY timestamp ASC
                LIMIT 20000
                """
            )
        ).fetchall()
    finally:
        db.close()

    samples = _build_sequences(rows, context_len=int(args.context_len), state_keys=state_keys)
    if not samples:
        raise SystemExit("Not enough decision_logs to build DT dataset")

    device = "cuda" if torch.cuda.is_available() else "cpu"

    cfg = DTConfig(
        state_dim=len(state_keys),
        act_dim=3,
        context_len=int(args.context_len),
        d_model=int(args.d_model),
        nhead=int(args.nhead),
        nlayer=int(args.nlayer),
    )
    model = DecisionTransformer(cfg).to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=float(args.lr), weight_decay=1e-4)

    rng = np.random.default_rng(seed=42)
    model.train()
    for step in range(int(args.steps)):
        batch = [samples[rng.integers(0, len(samples))] for _ in range(int(args.batch))]
        s = torch.from_numpy(np.stack([b[0] for b in batch], axis=0)).to(device=device)
        a = torch.from_numpy(np.stack([b[1] for b in batch], axis=0)).to(device=device, dtype=torch.long)
        rtg = torch.from_numpy(np.stack([b[2] for b in batch], axis=0)).to(device=device)
        y = torch.tensor([b[3] for b in batch], device=device, dtype=torch.long)

        logits = model(s, a, rtg)
        last_logits = logits[:, -1, :]
        loss = F.cross_entropy(last_logits, y)

        opt.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step()

        if step % 200 == 0:
            print("step", step, "loss", float(loss.detach().cpu()))

    torch.save(model.state_dict(), out_dir / "dt.pt")
    (out_dir / "dt_meta.json").write_text(
        json.dumps(
            {
                "state_keys": state_keys,
                "context_len": cfg.context_len,
                "d_model": cfg.d_model,
                "nhead": cfg.nhead,
                "nlayer": cfg.nlayer,
            },
            indent=2,
        )
    )
    print("OK", str(out_dir / "dt.pt"))


if __name__ == "__main__":
    main()
