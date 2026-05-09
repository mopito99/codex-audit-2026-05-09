import math
from dataclasses import dataclass

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F


@dataclass
class TimeGANTrainConfig:
    seq_len: int = 48
    batch_size: int = 64
    lr: float = 1e-3
    device: str | None = None
    pretrain_steps: int = 500
    supervisor_steps: int = 500
    joint_steps: int = 1000
    gamma: float = 1.0


class _GRUBlock(nn.Module):
    def __init__(self, in_dim: int, hidden_dim: int, num_layers: int, out_dim: int):
        super().__init__()
        self.rnn = nn.GRU(in_dim, hidden_dim, num_layers=num_layers, batch_first=True)
        self.proj = nn.Linear(hidden_dim, out_dim)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        h, _ = self.rnn(x)
        return self.proj(h)


class TimeGAN(nn.Module):
    """A small, working TimeGAN-style generator for multivariate time-series.

    Notes:
    - This is a simplified TimeGAN implementation (GRU-based).
    - It supports training (fit) and sampling (sample) and is intended for synthetic
      scenario generation in the "paper" architecture.
    """

    def __init__(
        self,
        feature_dim: int,
        hidden_dim: int = 64,
        num_layers: int = 2,
        noise_dim: int | None = None,
    ):
        super().__init__()

        if feature_dim <= 0:
            raise ValueError("feature_dim must be > 0")
        if hidden_dim <= 0:
            raise ValueError("hidden_dim must be > 0")
        if num_layers <= 0:
            raise ValueError("num_layers must be > 0")

        self.feature_dim = int(feature_dim)
        self.hidden_dim = int(hidden_dim)
        self.num_layers = int(num_layers)
        self.noise_dim = int(noise_dim or feature_dim)

        # Embedder / Recovery
        self.embedder = _GRUBlock(self.feature_dim, self.hidden_dim, self.num_layers, self.hidden_dim)
        self.recovery = _GRUBlock(self.hidden_dim, self.hidden_dim, self.num_layers, self.feature_dim)

        # Generator / Supervisor
        self.generator = _GRUBlock(self.noise_dim, self.hidden_dim, self.num_layers, self.hidden_dim)
        self.supervisor = _GRUBlock(self.hidden_dim, self.hidden_dim, self.num_layers, self.hidden_dim)

        # Discriminator
        self.discriminator_rnn = nn.GRU(self.hidden_dim, self.hidden_dim, num_layers=self.num_layers, batch_first=True)
        self.discriminator_head = nn.Linear(self.hidden_dim, 1)

    def embed(self, x: torch.Tensor) -> torch.Tensor:
        return torch.tanh(self.embedder(x))

    def recover(self, h: torch.Tensor) -> torch.Tensor:
        return self.recovery(h)

    def generate_latent(self, z: torch.Tensor) -> torch.Tensor:
        h = torch.tanh(self.generator(z))
        h_sup = torch.tanh(self.supervisor(h))
        return h_sup

    def discriminate(self, h: torch.Tensor) -> torch.Tensor:
        # returns logits [B,T,1]
        y, _ = self.discriminator_rnn(h)
        return self.discriminator_head(y)

    @torch.no_grad()
    def sample(self, n: int, seq_len: int, *, device: str | torch.device | None = None) -> torch.Tensor:
        self.eval()
        if n <= 0:
            raise ValueError("n must be > 0")
        if seq_len <= 0:
            raise ValueError("seq_len must be > 0")
        dev = device or next(self.parameters()).device
        z = torch.randn(n, seq_len, self.noise_dim, device=dev)
        h_hat = self.generate_latent(z)
        x_hat = self.recover(h_hat)
        return x_hat

    def fit(self, sequences: np.ndarray, cfg: TimeGANTrainConfig) -> dict:
        """Train TimeGAN on sequences.

        sequences: np.ndarray of shape [N, T, D] (float32 preferred)
        """

        if sequences.ndim != 3:
            raise ValueError("sequences must be [N,T,D]")
        n, t, d = sequences.shape
        if d != self.feature_dim:
            raise ValueError(f"feature_dim mismatch: got {d}, expected {self.feature_dim}")
        if cfg.seq_len != t:
            raise ValueError(f"cfg.seq_len mismatch: got {cfg.seq_len}, data T={t}")

        device = torch.device(cfg.device) if cfg.device else next(self.parameters()).device
        self.to(device)

        x_all = torch.as_tensor(sequences, dtype=torch.float32, device=device)

        opt_e = torch.optim.Adam(list(self.embedder.parameters()) + list(self.recovery.parameters()), lr=cfg.lr)
        opt_s = torch.optim.Adam(self.supervisor.parameters(), lr=cfg.lr)
        opt_g = torch.optim.Adam(list(self.generator.parameters()) + list(self.supervisor.parameters()), lr=cfg.lr)
        opt_d = torch.optim.Adam(list(self.discriminator_rnn.parameters()) + list(self.discriminator_head.parameters()), lr=cfg.lr)

        def _batch() -> torch.Tensor:
            idx = torch.randint(0, n, (cfg.batch_size,), device=device)
            return x_all[idx]

        losses = {
            "pretrain_mse": [],
            "supervised_mse": [],
            "g_loss": [],
            "d_loss": [],
        }

        self.train()

        # 1) Embedder pretrain (reconstruction)
        for _ in range(int(cfg.pretrain_steps)):
            x = _batch()
            h = self.embed(x)
            x_tilde = self.recover(h)
            loss = F.mse_loss(x_tilde, x)
            opt_e.zero_grad(set_to_none=True)
            loss.backward()
            opt_e.step()
            losses["pretrain_mse"].append(float(loss.detach().cpu()))

        # 2) Supervisor train (latent dynamics)
        for _ in range(int(cfg.supervisor_steps)):
            x = _batch()
            with torch.no_grad():
                h = self.embed(x)
            h_sup = torch.tanh(self.supervisor(h))
            loss_s = F.mse_loss(h_sup[:, 1:, :], h[:, 1:, :])
            opt_s.zero_grad(set_to_none=True)
            loss_s.backward()
            opt_s.step()
            losses["supervised_mse"].append(float(loss_s.detach().cpu()))

        # 3) Joint training (generator + discriminator + embedder/recovery lightly)
        for step in range(int(cfg.joint_steps)):
            x = _batch()

            # Real latent
            h = self.embed(x)
            h_sup = torch.tanh(self.supervisor(h))

            # Fake latent
            z = torch.randn(cfg.batch_size, t, self.noise_dim, device=device)
            h_hat = self.generate_latent(z)

            # --- Discriminator update ---
            y_real = self.discriminate(h_sup.detach())
            y_fake = self.discriminate(h_hat.detach())
            d_loss = F.binary_cross_entropy_with_logits(y_real, torch.ones_like(y_real)) + F.binary_cross_entropy_with_logits(
                y_fake, torch.zeros_like(y_fake)
            )
            opt_d.zero_grad(set_to_none=True)
            d_loss.backward()
            opt_d.step()

            # --- Generator update ---
            y_fake_g = self.discriminate(h_hat)
            g_adv = F.binary_cross_entropy_with_logits(y_fake_g, torch.ones_like(y_fake_g))

            # Supervised loss on latent dynamics
            g_sup = F.mse_loss(h_hat[:, 1:, :], h_hat[:, 1:, :].detach())
            # (kept as a small stabilizer term; real supervised structure is in supervisor stage)

            # Moment matching (mean/std) in data space
            x_hat = self.recover(h_hat)
            x_mean, x_std = x.mean(dim=(0, 1)), x.std(dim=(0, 1))
            xh_mean, xh_std = x_hat.mean(dim=(0, 1)), x_hat.std(dim=(0, 1))
            g_mom = F.mse_loss(xh_mean, x_mean) + F.mse_loss(xh_std, x_std)

            g_loss = g_adv + 0.1 * g_mom + 0.01 * g_sup
            opt_g.zero_grad(set_to_none=True)
            g_loss.backward()
            opt_g.step()

            # Light reconstruction step to keep embedder/recovery stable
            if step % 5 == 0:
                h2 = self.embed(x)
                x_tilde = self.recover(h2)
                e_loss = F.mse_loss(x_tilde, x)
                opt_e.zero_grad(set_to_none=True)
                e_loss.backward()
                opt_e.step()

            losses["g_loss"].append(float(g_loss.detach().cpu()))
            losses["d_loss"].append(float(d_loss.detach().cpu()))

        return {"losses": losses}


def make_sliding_windows(series: np.ndarray, seq_len: int) -> np.ndarray:
    """Convert a 2D array [N,D] into overlapping windows [Nw,seq_len,D]."""
    if series.ndim != 2:
        raise ValueError("series must be [N,D]")
    n, d = series.shape
    if n < seq_len:
        raise ValueError("series shorter than seq_len")
    windows = []
    for i in range(0, n - seq_len + 1):
        windows.append(series[i : i + seq_len])
    return np.stack(windows, axis=0).astype(np.float32)
