"""
强化学习交易智能体 — PPO (Proximal Policy Optimization) + 离散动作空间。

参考: FinRL (AI4Finance) + OpenAI SpinningUp PPO

动作空间: {0: SELL, 1: HOLD, 2: BUY} 共 3 个离散动作
状态空间: [returns_5d, returns_21d, rsi, macd_hist, bb_position, vol_ratio, vix, position_flag]
奖励: 每日收益率 - 交易成本 - 回撤惩罚

Usage:
    from core.rl_agent import PPOTradingAgent
    agent = PPOTradingAgent(state_dim=8, action_dim=3)
    agent.train(env_data, episodes=200)
    action = agent.predict(state_vector)  # 0/1/2
"""

import logging
import numpy as np
from collections import deque

log = logging.getLogger(__name__)

try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    from torch.distributions import Categorical
    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False


# ═══════════════════ PPO 神经网络 ═══════════════════════════════════════════

class _ActorCritic(nn.Module):
    """Shared backbone + separate actor/critic heads."""

    def __init__(self, state_dim: int, action_dim: int, hidden_dim: int = 128):
        if not HAS_TORCH:
            raise ImportError("torch required for PPO agent")
        super().__init__()
        self.shared = nn.Sequential(
            nn.Linear(state_dim, hidden_dim),
            nn.LayerNorm(hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.LayerNorm(hidden_dim),
            nn.ReLU(),
        )
        self.actor = nn.Linear(hidden_dim, action_dim)
        self.critic = nn.Linear(hidden_dim, 1)

        # Orthogonal init (stable RL baseline)
        for m in self.modules():
            if isinstance(m, nn.Linear):
                nn.init.orthogonal_(m.weight, gain=np.sqrt(2))
                nn.init.constant_(m.bias, 0.0)

    def forward(self, x):
        features = self.shared(x)
        logits = self.actor(features)
        value = self.critic(features)
        return logits, value

    def get_action(self, x, deterministic: bool = False):
        logits, value = self.forward(x)
        probs = F.softmax(logits, dim=-1)
        dist = Categorical(probs)
        if deterministic:
            action = torch.argmax(probs, dim=-1)
        else:
            action = dist.sample()
        return action, dist.log_prob(action), dist.entropy(), value


# ═══════════════════ PPO Memory Buffer ════════════════════════════════════════

class _RolloutBuffer:
    """Store (s, a, log_prob, reward, done, value) for PPO update."""

    def __init__(self, capacity: int = 2048):
        self.states: list = []
        self.actions: list = []
        self.log_probs: list = []
        self.rewards: list = []
        self.dones: list = []
        self.values: list = []
        self._capacity = capacity

    def add(self, state, action, log_prob, reward, done, value):
        self.states.append(state)
        self.actions.append(action)
        self.log_probs.append(log_prob)
        self.rewards.append(reward)
        self.dones.append(done)
        self.values.append(value)

    def clear(self):
        self.states.clear()
        self.actions.clear()
        self.log_probs.clear()
        self.rewards.clear()
        self.dones.clear()
        self.values.clear()

    def __len__(self):
        return len(self.states)


# ═══════════════════ PPO Agent ════════════════════════════════════════════════

class PPOTradingAgent:
    """
    PPO agent for discrete action trading.

    Args:
        state_dim: 状态维度
        action_dim: 动作数量 (default=3: SELL/HOLD/BUY)
        lr: 学习率
        gamma: 折扣因子
        clip_eps: PPO clip 范围
        ent_coef: 熵正则系数（鼓励探索）
        vf_coef: 价值函数损失权重
        max_grad_norm: 梯度裁剪
    """

    def __init__(self, state_dim: int = 8, action_dim: int = 3,
                 lr: float = 3e-4, gamma: float = 0.99,
                 clip_eps: float = 0.2, ent_coef: float = 0.01,
                 vf_coef: float = 0.5, max_grad_norm: float = 0.5,
                 hidden_dim: int = 128):
        if not HAS_TORCH:
            log.warning("torch not installed — PPO agent disabled")
            self._model = None
            return

        self.state_dim = state_dim
        self.action_dim = action_dim
        self.gamma = gamma
        self.clip_eps = clip_eps
        self.ent_coef = ent_coef
        self.vf_coef = vf_coef
        self.max_grad_norm = max_grad_norm

        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model = _ActorCritic(state_dim, action_dim, hidden_dim).to(self.device)
        self.optimizer = torch.optim.Adam(self.model.parameters(), lr=lr)
        self.buffer = _RolloutBuffer()

    def _to_tensor(self, x) -> torch.Tensor:
        if isinstance(x, np.ndarray):
            return torch.FloatTensor(x).to(self.device)
        return torch.FloatTensor([x]).to(self.device)

    def predict(self, state: np.ndarray, deterministic: bool = True) -> int:
        """Return action 0/1/2 given state vector."""
        if self._model is None:
            return 1  # HOLD

        with torch.inference_mode():
            s = self._to_tensor(state).unsqueeze(0)
            action, _, _, _ = self.model.get_action(s, deterministic=deterministic)
            return int(action.item())

    def predict_proba(self, state: np.ndarray) -> np.ndarray:
        """Return action probability distribution [p_sell, p_hold, p_buy]."""
        if self._model is None:
            return np.array([0.0, 1.0, 0.0])

        with torch.inference_mode():
            logits, _ = self.model(self._to_tensor(state).unsqueeze(0))
            probs = F.softmax(logits, dim=-1).cpu().numpy()[0]
            return probs

    def record_step(self, state, action, log_prob, reward, done, value):
        self.buffer.add(state, action, log_prob, reward, done, value)

    def update(self, epochs: int = 10, batch_size: int = 64) -> dict:
        """PPO policy update using collected rollouts. Returns metrics dict."""
        if self._model is None or len(self.buffer) == 0:
            return {"policy_loss": 0, "value_loss": 0, "entropy": 0}

        # Compute advantages via GAE (simplified: Monte Carlo returns)
        rewards = np.array(self.buffer.rewards)
        values = np.array([v.item() if isinstance(v, torch.Tensor) else v
                          for v in self.buffer.values])
        dones = np.array(self.buffer.dones)

        # Compute discounted returns and advantages
        returns = np.zeros_like(rewards)
        advantages = np.zeros_like(rewards)
        running_return = 0.0
        running_adv = 0.0
        for t in reversed(range(len(rewards))):
            running_return = rewards[t] + self.gamma * running_return * (1 - dones[t])
            returns[t] = running_return
            td_error = rewards[t] + self.gamma * values[t + 1] * (1 - dones[t]) - values[t] if t + 1 < len(rewards) else rewards[t] - values[t]
            # GAE
            running_adv = td_error + self.gamma * 0.95 * running_adv * (1 - dones[t])
            advantages[t] = running_adv

        # Normalize advantages
        advantages = (advantages - advantages.mean()) / (advantages.std() + 1e-8)

        states = np.array(self.buffer.states)
        actions = np.array(self.buffer.actions)
        old_log_probs = np.array([lp.item() if isinstance(lp, torch.Tensor) else lp
                                   for lp in self.buffer.log_probs])

        total_policy_loss = 0.0
        total_value_loss = 0.0
        total_entropy = 0.0
        n_updates = 0

        for _ in range(epochs):
            # Shuffle
            indices = np.random.permutation(len(states))
            for start in range(0, len(indices), batch_size):
                batch_idx = indices[start:start + batch_size]
                s_batch = self._to_tensor(states[batch_idx])
                a_batch = torch.LongTensor(actions[batch_idx]).to(self.device)
                old_lp_batch = self._to_tensor(old_log_probs[batch_idx])
                adv_batch = self._to_tensor(advantages[batch_idx])
                ret_batch = self._to_tensor(returns[batch_idx])

                logits, values_pred = self.model(s_batch)
                probs = F.softmax(logits, dim=-1)
                dist = Categorical(probs)
                new_log_probs = dist.log_prob(a_batch)
                entropy = dist.entropy().mean()

                # PPO clipped objective
                ratio = torch.exp(new_log_probs - old_lp_batch)
                surr1 = ratio * adv_batch
                surr2 = torch.clamp(ratio, 1 - self.clip_eps, 1 + self.clip_eps) * adv_batch
                policy_loss = -torch.min(surr1, surr2).mean()

                value_loss = F.mse_loss(values_pred.squeeze(-1), ret_batch)

                loss = policy_loss + self.vf_coef * value_loss - self.ent_coef * entropy

                self.optimizer.zero_grad()
                loss.backward()
                nn.utils.clip_grad_norm_(self.model.parameters(), self.max_grad_norm)
                self.optimizer.step()

                total_policy_loss += policy_loss.item()
                total_value_loss += value_loss.item()
                total_entropy += entropy.item()
                n_updates += 1

        self.buffer.clear()

        return {
            "policy_loss": total_policy_loss / max(n_updates, 1),
            "value_loss": total_value_loss / max(n_updates, 1),
            "entropy": total_entropy / max(n_updates, 1),
        }

    def save(self, path: str):
        if self._model:
            torch.save({
                "model_state": self.model.state_dict(),
                "optimizer_state": self.optimizer.state_dict(),
                "state_dim": self.state_dim,
                "action_dim": self.action_dim,
            }, path)

    def load(self, path: str):
        if not HAS_TORCH:
            return
        ckpt = torch.load(path, map_location=self.device, weights_only=True)
        self.state_dim = ckpt["state_dim"]
        self.action_dim = ckpt["action_dim"]
        self.model = _ActorCritic(self.state_dim, self.action_dim).to(self.device)
        self.model.load_state_dict(ckpt["model_state"])
        self.optimizer.load_state_dict(ckpt["optimizer_state"])


# ═══════════════════ 交易环境 (Gym-style) ═════════════════════════════════════

class TradingEnv:
    """Minimal RL environment wrapping OHLCV data.

    State (8-dim):
      [ret_5d, ret_21d, rsi_norm, macd_hist_norm, bb_position, vol_ratio, vix_norm, position_flag]

    Reward: daily_return - cost * |trade| - drawdown_penalty
    Done: end of data or stop-loss hit
    """

    def __init__(self, prices: np.ndarray, features: np.ndarray | None = None,
                 initial_cash: float = 100_000, commission: float = 0.001,
                 max_position: float = 1.0, stop_loss_pct: float = 0.05):
        """
        Args:
            prices: 1D array of close prices [T]
            features: T×F array of pre-computed features (optional)
        """
        self.prices = prices
        self.features = features
        self.initial_cash = initial_cash
        self.commission = commission
        self.max_position = max_position
        self.stop_loss_pct = stop_loss_pct
        self._reset()

    def _reset(self):
        self._step = 0
        self._cash = self.initial_cash
        self._position = 0      # 0 = no position, 1 = long
        self._entry_price = 0.0
        self._equity = [self.initial_cash]
        self._done = False

    def reset(self) -> np.ndarray:
        self._reset()
        return self._get_state()

    def _get_state(self) -> np.ndarray:
        if self.features is not None and self._step < len(self.features):
            state = list(self.features[self._step][:6])
        else:
            state = [0.0] * 6

        # Add VIX proxy (normalized vol)
        if self._step >= 20:
            rets = np.diff(self.prices[max(0, self._step - 20):self._step + 1])
            rets = rets / self.prices[max(0, self._step - 20):self._step]
            vix_proxy = np.clip(np.std(rets) * np.sqrt(252), 0, 1)
        else:
            vix_proxy = 0.2
        state.append(vix_proxy)

        # Position flag
        state.append(float(self._position))

        return np.array(state, dtype=np.float32)

    def step(self, action: int) -> tuple[np.ndarray, float, bool, dict]:
        """
        Execute one step.

        action: 0=SELL (close long), 1=HOLD, 2=BUY (open/add long)
        """
        if self._done:
            return self._get_state(), 0.0, True, {}

        price = self.prices[self._step]
        prev_equity = self._equity[-1]

        # Execute action
        trade_cost = 0.0
        if action == 2 and self._position == 0:  # BUY
            self._position = 1
            self._entry_price = price
            invest = self._cash * self.max_position
            shares = invest / (price * (1 + self.commission))
            self._cash -= shares * price * (1 + self.commission)
            trade_cost = shares * price * self.commission
            self._shares = shares
        elif action == 0 and self._position == 1:  # SELL
            self._cash += self._shares * price * (1 - self.commission)
            pnl = (price - self._entry_price) / self._entry_price
            trade_cost = self._shares * price * self.commission
            self._position = 0
            self._shares = 0

        # Compute equity
        if self._position == 1:
            unrealized = self._shares * price
            equity = self._cash + unrealized
        else:
            equity = self._cash

        self._equity.append(equity)

        # Reward: return - cost - drawdown penalty
        ret = (equity - prev_equity) / (prev_equity + 1e-8)
        peak = max(self._equity)
        drawdown = (peak - equity) / (peak + 1e-8)

        reward = ret - trade_cost / (equity + 1e-8)
        if drawdown > 0.1:
            reward -= drawdown * 0.1  # drawdown penalty

        # Done?
        self._step += 1
        if self._step >= len(self.prices) - 1:
            self._done = True
        if self._position == 1 and self._entry_price > 0:
            stop_price = self._entry_price * (1 - self.stop_loss_pct)
            if price <= stop_price:
                self._done = True
                reward -= 0.5

        info = {
            "step": self._step, "equity": equity,
            "position": self._position, "price": price,
        }

        return self._get_state(), reward, self._done, info

    @property
    def equity_curve(self) -> list:
        return self._equity
