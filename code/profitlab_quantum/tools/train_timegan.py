import argparse
import json
import os
from pathlib import Path

import numpy as np
import torch

from app.data.bingx import BingXReader
from app.models.timegan import TimeGAN, TimeGANTrainConfig, make_sliding_windows


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _minmax_scale(x: np.ndarray, eps: float = 1e-8):
    x_min = x.min(axis=0, keepdims=True)
    x_max = x.max(axis=0, keepdims=True)
    scale = np.maximum(x_max - x_min, eps)
    return (x - x_min) / scale, x_min, scale


def _minmax_inverse(x: np.ndarray, x_min: np.ndarray, scale: np.ndarray):
    return x * scale + x_min


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--timeframe", default="5m")
    ap.add_argument("--limit", type=int, default=2000)
    ap.add_argument("--seq-len", type=int, default=48)
    ap.add_argument("--features", default="open,high,low,close,volume")
    ap.add_argument("--hidden-dim", type=int, default=64)
    ap.add_argument("--layers", type=int, default=2)
    ap.add_argument("--pretrain", type=int, default=300)
    ap.add_argument("--supervisor", type=int, default=300)
    ap.add_argument("--joint", type=int, default=800)
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--out", default="/srv/profitlab_quantum/artifacts/timegan")
    ap.add_argument("--samples", type=int, default=200)
    args = ap.parse_args()

    out_dir = Path(args.out)
    _ensure_dir(out_dir)

    reader = BingXReader()
    df = reader.get_klines(args.symbol, interval=args.timeframe, limit=args.limit)
    if df is None or df.empty:
        raise SystemExit("No klines returned")

    cols = [c.strip() for c in args.features.split(",") if c.strip()]
    x = df[cols].astype(float).to_numpy()

    x_scaled, x_min, scale = _minmax_scale(x)
    windows = make_sliding_windows(x_scaled, seq_len=int(args.seq_len))

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = TimeGAN(feature_dim=len(cols), hidden_dim=int(args.hidden_dim), num_layers=int(args.layers))
    model.to(device)

    cfg = TimeGANTrainConfig(
        seq_len=int(args.seq_len),
        batch_size=int(args.batch),
        lr=float(args.lr),
        device=device,
        pretrain_steps=int(args.pretrain),
        supervisor_steps=int(args.supervisor),
        joint_steps=int(args.joint),
    )

    report = model.fit(windows, cfg)

    # Save model + scaler
    torch.save(model.state_dict(), out_dir / f"timegan_{args.symbol}_{args.timeframe}.pt")
    meta = {
        "symbol": args.symbol,
        "timeframe": args.timeframe,
        "cols": cols,
        "seq_len": int(args.seq_len),
        "x_min": x_min.squeeze(0).tolist(),
        "scale": scale.squeeze(0).tolist(),
        "train_report": {k: (v[-5:] if isinstance(v, list) else v) for k, v in report.get("losses", {}).items()},
    }
    (out_dir / f"timegan_{args.symbol}_{args.timeframe}.json").write_text(json.dumps(meta, indent=2))

    # Generate samples
    with torch.no_grad():
        x_hat = model.sample(int(args.samples), int(args.seq_len)).detach().cpu().numpy()
    x_hat = _minmax_inverse(x_hat, x_min, scale)

    np.save(out_dir / f"samples_{args.symbol}_{args.timeframe}.npy", x_hat.astype(np.float32))

    print("OK")
    print("model", str(out_dir / f"timegan_{args.symbol}_{args.timeframe}.pt"))
    print("meta", str(out_dir / f"timegan_{args.symbol}_{args.timeframe}.json"))
    print("samples", str(out_dir / f"samples_{args.symbol}_{args.timeframe}.npy"))


if __name__ == "__main__":
    main()
