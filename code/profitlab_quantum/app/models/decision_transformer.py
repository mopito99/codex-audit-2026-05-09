from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F


@dataclass
class DTConfig:
    state_dim: int
    act_dim: int
    context_len: int = 32
    d_model: int = 128
    nhead: int = 4
    nlayer: int = 3
    dropout: float = 0.1


class DecisionTransformer(nn.Module):
    """Decision Transformer (offline) for discrete actions.

    This is a compact implementation: causal TransformerEncoder over (rtg, state, action) tokens.
    """

    def __init__(self, cfg: DTConfig):
        super().__init__()
        if cfg.d_model % cfg.nhead != 0:
            raise ValueError("d_model must be divisible by nhead")

        self.cfg = cfg
        self.state_embed = nn.Linear(cfg.state_dim, cfg.d_model)
        self.rtg_embed = nn.Linear(1, cfg.d_model)
        self.act_embed = nn.Embedding(cfg.act_dim, cfg.d_model)
        self.tok_ln = nn.LayerNorm(cfg.d_model)

        self.pos_embed = nn.Embedding(cfg.context_len * 3, cfg.d_model)

        enc_layer = nn.TransformerEncoderLayer(
            d_model=cfg.d_model,
            nhead=cfg.nhead,
            dim_feedforward=4 * cfg.d_model,
            dropout=cfg.dropout,
            activation="gelu",
            batch_first=True,
            norm_first=True,
        )
        self.encoder = nn.TransformerEncoder(enc_layer, num_layers=cfg.nlayer)

        self.act_head = nn.Linear(cfg.d_model, cfg.act_dim)

    def forward(
        self,
        states: torch.Tensor,  # [B,T,Ds]
        actions: torch.Tensor,  # [B,T] (ints)
        returns_to_go: torch.Tensor,  # [B,T,1]
    ) -> torch.Tensor:
        b, t, _ = states.shape
        if t != self.cfg.context_len:
            raise ValueError("T must equal context_len")

        s = self.state_embed(states)
        r = self.rtg_embed(returns_to_go)
        a = self.act_embed(actions)

        # interleave tokens: (rtg_0, s_0, a_0, rtg_1, s_1, a_1, ...)
        tok = torch.stack([r, s, a], dim=2).reshape(b, t * 3, self.cfg.d_model)
        tok = self.tok_ln(tok)

        pos = torch.arange(t * 3, device=tok.device).unsqueeze(0)
        tok = tok + self.pos_embed(pos)

        # causal mask
        seq = t * 3
        mask = torch.triu(torch.ones(seq, seq, device=tok.device), diagonal=1).bool()

        h = self.encoder(tok, mask=mask)

        # action logits predicted from the STATE token positions (1,4,7,...) per triplet
        state_positions = torch.arange(1, seq, 3, device=tok.device)
        h_state = h.index_select(1, state_positions)  # [B,T,D]
        logits = self.act_head(h_state)
        return logits


class DecisionTransformerAgent:
    """Inference wrapper exposing a get_action(state) API compatible with engine usage."""

    def __init__(self, model: DecisionTransformer, *, device: str | None = None, target_rtg: float = 0.05):
        self.model = model
        self.cfg = model.cfg
        self.device = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
        self.model.to(self.device)
        self.model.eval()

        self.is_on_policy = False
        self.target_rtg = float(target_rtg)

        self._states: list[np.ndarray] = []
        self._actions: list[int] = []
        self._rtg: list[float] = []

    @torch.no_grad()
    def get_action(self, state: np.ndarray):
        s = np.asarray(state, dtype=np.float32).reshape(-1)
        self._states.append(s)

        # bootstrap actions/rtg history
        if len(self._actions) < len(self._states):
            self._actions.append(0)
        if len(self._rtg) < len(self._states):
            self._rtg.append(self.target_rtg)

        # truncate
        self._states = self._states[-self.cfg.context_len :]
        self._actions = self._actions[-self.cfg.context_len :]
        self._rtg = self._rtg[-self.cfg.context_len :]

        # pad left
        pad_n = self.cfg.context_len - len(self._states)
        if pad_n > 0:
            zeros = np.zeros_like(s)
            states = [zeros for _ in range(pad_n)] + list(self._states)
            actions = [0 for _ in range(pad_n)] + list(self._actions)
            rtg = [self.target_rtg for _ in range(pad_n)] + list(self._rtg)
        else:
            states = list(self._states)
            actions = list(self._actions)
            rtg = list(self._rtg)

        states_t = torch.from_numpy(np.stack(states, axis=0)).to(device=self.device).unsqueeze(0)
        actions_t = torch.tensor(actions, device=self.device, dtype=torch.long).unsqueeze(0)
        rtg_t = torch.from_numpy(np.array(rtg, dtype=np.float32).reshape(1, self.cfg.context_len, 1)).to(device=self.device)

        logits = self.model(states_t, actions_t, rtg_t)
        last_logits = logits[:, -1, :]
        probs = F.softmax(last_logits, dim=-1).squeeze(0)

        dist = torch.distributions.Categorical(probs)
        action_t = dist.sample()
        log_prob_t = dist.log_prob(action_t)

        action = int(action_t.item())
        self._actions[-1] = action

        # signature-compatible outputs
        value = torch.tensor(0.0, device=self.device)
        seq_state = states_t.squeeze(0).detach().cpu().numpy()

        return action, log_prob_t.squeeze(0), value, probs.detach(), seq_state
