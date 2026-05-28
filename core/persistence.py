"""
数据持久化模块 — SQLite 交易日志 + 信号记录 + 权益快照。

Usage:
    from core.persistence import TradeJournal
    journal = TradeJournal("trades.db")
    journal.log_signal(symbol="AAPL", strategy="mean_reversion", signal="buy", price=150.0)
    journal.log_trade(symbol="AAPL", action="BUY", shares=100, price=150.0, reason="RSI=25")
"""

import sqlite3
import os
import json
import logging
from datetime import datetime

log = logging.getLogger(__name__)

DB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")


class TradeJournal:
    """Persistent trade and signal journal backed by SQLite."""

    def __init__(self, db_name: str = "trades.db"):
        os.makedirs(DB_DIR, exist_ok=True)
        self._path = os.path.join(DB_DIR, db_name)
        self._conn = sqlite3.connect(self._path)
        self._create_tables()
        log.info(f"TradeJournal: {self._path}")

    def _create_tables(self):
        cur = self._conn.cursor()
        cur.executescript("""
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL DEFAULT (datetime('now')),
                symbol TEXT NOT NULL,
                strategy TEXT NOT NULL,
                signal TEXT NOT NULL,
                price REAL,
                score REAL,
                regime INTEGER,
                reason TEXT
            );
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL DEFAULT (datetime('now')),
                symbol TEXT NOT NULL,
                action TEXT NOT NULL,
                shares REAL NOT NULL,
                price REAL NOT NULL,
                strategy TEXT,
                reason TEXT,
                commission REAL DEFAULT 0.0
            );
            CREATE TABLE IF NOT EXISTS equity_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL DEFAULT (datetime('now')),
                equity REAL NOT NULL,
                positions_json TEXT
            );
            CREATE TABLE IF NOT EXISTS risk_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL DEFAULT (datetime('now')),
                event_type TEXT NOT NULL,
                reason TEXT,
                equity REAL
            );
            CREATE INDEX IF NOT EXISTS idx_signals_ts ON signals(ts);
            CREATE INDEX IF NOT EXISTS idx_signals_symbol ON signals(symbol);
            CREATE INDEX IF NOT EXISTS idx_trades_ts ON trades(ts);
            CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol);
            CREATE INDEX IF NOT EXISTS idx_equity_ts ON equity_snapshots(ts);
            CREATE INDEX IF NOT EXISTS idx_risk_ts ON risk_events(ts);
        """)
        self._conn.commit()

    # ── Signals ──────────────────────────────────────────────────────────
    def log_signal(self, symbol: str, strategy: str, signal: str,
                   price: float = 0.0, score: float = 0.0,
                   regime: int = 0, reason: str = ""):
        cur = self._conn.cursor()
        cur.execute(
            "INSERT INTO signals (symbol, strategy, signal, price, score, regime, reason) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (symbol, strategy, signal, price, score, regime, reason),
        )
        self._conn.commit()

    # ── Trades ────────────────────────────────────────────────────────────
    def log_trade(self, symbol: str, action: str, shares: float,
                  price: float, strategy: str = "", reason: str = "",
                  commission: float = 0.0):
        cur = self._conn.cursor()
        cur.execute(
            "INSERT INTO trades (symbol, action, shares, price, strategy, reason, commission) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (symbol, action, shares, price, strategy, reason, commission),
        )
        self._conn.commit()

    # ── Equity ────────────────────────────────────────────────────────────
    def log_equity(self, equity: float, positions: dict | None = None):
        cur = self._conn.cursor()
        pos_json = json.dumps(positions or {})
        cur.execute(
            "INSERT INTO equity_snapshots (equity, positions_json) VALUES (?, ?)",
            (equity, pos_json),
        )
        self._conn.commit()

    # ── Risk Events ───────────────────────────────────────────────────────
    def log_risk_event(self, event_type: str, reason: str = "", equity: float = 0.0):
        cur = self._conn.cursor()
        cur.execute(
            "INSERT INTO risk_events (event_type, reason, equity) VALUES (?, ?, ?)",
            (event_type, reason, equity),
        )
        self._conn.commit()

    # ── Queries ───────────────────────────────────────────────────────────
    def recent_signals(self, limit: int = 50) -> list[dict]:
        cur = self._conn.cursor()
        cur.execute(
            "SELECT ts, symbol, strategy, signal, price, score, reason "
            "FROM signals ORDER BY id DESC LIMIT ?", (limit,)
        )
        cols = ["ts", "symbol", "strategy", "signal", "price", "score", "reason"]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def recent_trades(self, limit: int = 50) -> list[dict]:
        cur = self._conn.cursor()
        cur.execute(
            "SELECT ts, symbol, action, shares, price, strategy, reason "
            "FROM trades ORDER BY id DESC LIMIT ?", (limit,)
        )
        cols = ["ts", "symbol", "action", "shares", "price", "strategy", "reason"]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def equity_curve(self, limit: int = 500) -> list[dict]:
        cur = self._conn.cursor()
        cur.execute(
            "SELECT ts, equity FROM equity_snapshots ORDER BY id DESC LIMIT ?", (limit,)
        )
        return [{"ts": row[0], "equity": row[1]} for row in cur.fetchall()]

    def risk_events(self, limit: int = 50) -> list[dict]:
        cur = self._conn.cursor()
        cur.execute(
            "SELECT ts, event_type, reason, equity FROM risk_events "
            "ORDER BY id DESC LIMIT ?", (limit,)
        )
        cols = ["ts", "event_type", "reason", "equity"]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def trade_summary(self) -> dict:
        """Aggregated trade statistics."""
        cur = self._conn.cursor()
        cur.execute("SELECT COUNT(*) FROM trades")
        total = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM trades WHERE action='SELL'")
        sells = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM trades WHERE action='BUY'")
        buys = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM risk_events")
        risk_count = cur.fetchone()[0]
        return {
            "total_trades": total, "buys": buys, "sells": sells,
            "risk_events": risk_count,
        }

    def close(self):
        self._conn.close()
