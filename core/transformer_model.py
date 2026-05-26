"""
Transformer 选股模型 v2 (P3) — Encoder-based price forecasting.

Architecture: TransformerEncoder → Linear head → future returns
Input: [batch, seq_len, n_features] — lagged returns + factors
Output: ranked expected returns → long top_k, short bottom_k

v2 fixes:
  - Replaced decoder-only with encoder (no zero-memory cross-attention)
  - Added gradient clipping, LR scheduler, early stopping
  - Proper train/val split and epoch logging

Usage:
    from core.transformer_model import PriceTransformer
    model = PriceTransformer(n_features=32, seq_len=60)
    model.train(X_train, y_train)
    preds = model.predict(X_test)
"""

import logging
import numpy as np
import pandas as pd
from config.settings import (
    TRANSFORMER_D_MODEL, TRANSFORMER_N_HEADS, TRANSFORMER_N_LAYERS,
    TRANSFORMER_SEQ_LEN, TRANSFORMER_HORIZON,
)

log = logging.getLogger(__name__)


class PriceTransformer:
    """Transformer encoder for multi-stock return prediction."""

    def __init__(self, n_features=32, d_model=TRANSFORMER_D_MODEL,
                 n_heads=TRANSFORMER_N_HEADS, n_layers=TRANSFORMER_N_LAYERS,
                 seq_len=TRANSFORMER_SEQ_LEN, horizon=TRANSFORMER_HORIZON,
                 dropout=0.1):
        self.n_features = n_features
        self.d_model = d_model
        self.n_heads = n_heads
        self.n_layers = n_layers
        self.seq_len = seq_len
        self.horizon = horizon
        self.dropout = dropout
        self._model = None
        self._trained = False

    def train(self, X: np.ndarray, y: np.ndarray,
              epochs=80, batch_size=32, lr=0.001, val_split=0.2,
              patience=10):
        """Train the transformer with early stopping and LR scheduling."""
        try:
            import torch
            import torch.nn as nn
            from torch.utils.data import DataLoader, TensorDataset

            device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

            model = _EncoderTransformer(
                n_features=self.n_features,
                d_model=self.d_model,
                n_heads=self.n_heads,
                n_layers=self.n_layers,
                seq_len=self.seq_len,
                dropout=self.dropout,
            ).to(device)

            # Split
            n_val = max(1, int(len(X) * val_split))
            X_train, y_t = X[:-n_val], y[:-n_val]
            X_val, y_v = X[-n_val:], y[-n_val:]

            train_data = TensorDataset(
                torch.FloatTensor(X_train), torch.FloatTensor(y_t))
            train_loader = DataLoader(train_data, batch_size=batch_size,
                                      shuffle=True)

            optimizer = torch.optim.Adam(model.parameters(), lr=lr)
            scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
                optimizer, mode='min', factor=0.5, patience=5, verbose=False)
            criterion = nn.MSELoss()
            best_val_loss = float('inf')
            best_state = None
            patience_counter = 0

            for epoch in range(epochs):
                model.train()
                total_loss = 0.0
                for batch_X, batch_y in train_loader:
                    batch_X, batch_y = batch_X.to(device), batch_y.to(device)
                    optimizer.zero_grad()
                    pred = model(batch_X).squeeze(-1)
                    loss = criterion(pred, batch_y)
                    loss.backward()
                    torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                    optimizer.step()
                    total_loss += loss.item()

                model.eval()
                with torch.inference_mode():
                    val_pred = model(torch.FloatTensor(X_val).to(device)).squeeze(-1).cpu()
                    val_loss = float(criterion(val_pred, torch.FloatTensor(y_v)))

                scheduler.step(val_loss)

                if val_loss < best_val_loss:
                    best_val_loss = val_loss
                    best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
                    patience_counter = 0
                else:
                    patience_counter += 1

                if (epoch + 1) % 20 == 0:
                    log.info(f"Transformer epoch {epoch+1}/{epochs}: "
                             f"train_loss={total_loss/len(train_loader):.4f} "
                             f"val_loss={val_loss:.4f}")

                if patience_counter >= patience:
                    log.info(f"Early stopping at epoch {epoch+1}")
                    break

            if best_state is not None:
                model.load_state_dict(best_state)
            self._model = model.to("cpu")
            self._trained = True
            log.info(f"Transformer trained: {len(X_train)} samples, "
                     f"best_val_loss={best_val_loss:.6f}")

        except ImportError:
            log.warning("torch not installed — transformer disabled")
        except Exception as e:
            log.warning(f"Transformer training failed: {e}")

    def predict(self, X: np.ndarray) -> np.ndarray:
        """Predict expected returns for each sample."""
        if not self._trained or self._model is None:
            return np.zeros(len(X))

        try:
            import torch
            self._model.eval()
            with torch.inference_mode():
                preds = self._model(torch.FloatTensor(X)).squeeze(-1).numpy()
            return preds
        except Exception:
            return np.zeros(len(X))

    def rank_stocks(self, X: np.ndarray, symbols: list[str],
                    top_k=20, bottom_k=10) -> tuple[list, list]:
        """Return (long_list, short_list) ranked by predicted returns."""
        preds = self.predict(X)
        ranked = sorted(zip(symbols, preds), key=lambda x: x[1], reverse=True)
        longs = [s for s, _ in ranked[:top_k]]
        shorts = [s for s, _ in ranked[-bottom_k:]]
        return longs, shorts


class _EncoderTransformer:
    """Transformer encoder for time series — self-attention, no cross-attention."""

    def __init__(self, n_features, d_model, n_heads, n_layers, seq_len, dropout):
        import torch
        import torch.nn as nn
        super().__init__()
        self.input_proj = nn.Linear(n_features, d_model)
        self.pos_encoding = _PositionalEncoding(d_model, dropout, seq_len)
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d_model, nhead=n_heads, dropout=dropout,
            dim_feedforward=d_model * 4, batch_first=True,
        )
        self.encoder = nn.TransformerEncoder(encoder_layer, num_layers=n_layers)
        self.output_proj = nn.Linear(d_model, 1)

    def forward(self, x):
        x = self.input_proj(x)
        x = self.pos_encoding(x)
        x = self.encoder(x)
        return self.output_proj(x[:, -1, :])


class _PositionalEncoding:
    """Sinusoidal positional encoding."""

    def __init__(self, d_model, dropout, max_len):
        import torch
        import torch.nn as nn
        super().__init__()
        self.dropout = nn.Dropout(p=dropout)
        pe = torch.zeros(max_len, d_model)
        position = torch.arange(0, max_len).unsqueeze(1).float()
        div_term = torch.exp(torch.arange(0, d_model, 2).float() *
                            -(np.log(10000.0) / d_model))
        pe[:, 0::2] = torch.sin(position * div_term)
        pe[:, 1::2] = torch.cos(position * div_term)
        self.register_buffer('pe', pe.unsqueeze(0))

    def forward(self, x):
        import torch
        return self.dropout(x + self.pe[:, :x.size(1), :])
