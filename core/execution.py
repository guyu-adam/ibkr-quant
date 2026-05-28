"""
订单执行算法 — TWAP / VWAP / POV / Iceberg 智能拆单。

避免大单冲击市场，降低滑点成本。

Usage:
    from core.execution import TWAPExecutor, VWAPExecutor
    twap = TWAPExecutor(total_shares=1000, duration_minutes=30, slices=10)
    for slice_info in twap.slice():
        broker.market_order(slice_info.symbol, slice_info.shares, slice_info.side)
"""

import time as _time
import logging
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


@dataclass
class SliceOrder:
    symbol: str
    side: str            # BUY / SELL
    shares: int
    slice_num: int
    total_slices: int
    price_limit: float = 0.0  # 0 = no limit


@dataclass
class ExecReport:
    symbol: str
    total_shares: int
    filled_shares: int = 0
    avg_price: float = 0.0
    slippage_bps: float = 0.0
    slices_executed: int = 0
    start_time: float = 0.0
    end_time: float = 0.0
    status: str = "pending"  # pending / executing / completed / cancelled


# ═══════════════════════════ TWAP ══════════════════════════════════════════════

class TWAPExecutor:
    """Time-Weighted Average Price — 等时间间隔等量拆单。

    Args:
        total_shares: 总股数
        duration_minutes: 执行时长（分钟）
        slices: 拆单数量
    """

    def __init__(self, total_shares: int, duration_minutes: int = 30,
                 slices: int = 10):
        if slices <= 0 or total_shares <= 0:
            raise ValueError("slices and total_shares must be positive")
        self.total_shares = total_shares
        self.duration_minutes = duration_minutes
        self.slices = slices
        self._interval = (duration_minutes * 60) / slices
        self._slice_size = total_shares // slices
        self._remainder = total_shares % slices
        self._current = 0

    def slice(self, symbol: str, side: str = "BUY") -> list[SliceOrder]:
        """Generator yielding one slice at a time."""
        orders = []
        for i in range(self.slices):
            qty = self._slice_size + (1 if i < self._remainder else 0)
            if qty <= 0:
                continue
            orders.append(SliceOrder(
                symbol=symbol, side=side, shares=qty,
                slice_num=i + 1, total_slices=self.slices,
            ))
        return orders

    @property
    def interval_seconds(self) -> float:
        return self._interval

    @property
    def avg_size_per_slice(self) -> int:
        return max(1, self.total_shares // self.slices)


# ═══════════════════════════ VWAP ══════════════════════════════════════════════

class VWAPExecutor:
    """Volume-Weighted Average Price — 按历史成交量分布分配订单。

    使用历史日内成交量曲线预测当前执行窗口的成交量分布。

    Args:
        total_shares: 总股数
        duration_minutes: 执行时长
        slices: 拆单数量
        volume_profile: 历史各时段成交量占比 (list of 390 floats for minute bars)
    """

    def __init__(self, total_shares: int, duration_minutes: int = 30,
                 slices: int = 10, volume_profile: list[float] | None = None):
        self.total_shares = total_shares
        self.duration_minutes = duration_minutes
        self.slices = slices
        self._volume_profile = volume_profile
        self._interval = (duration_minutes * 60) / slices

    def slice(self, symbol: str, side: str = "BUY",
              current_minute: int = 0) -> list[SliceOrder]:
        """
        Generate VWAP slices.

        Args:
            current_minute: 当前市场时间的分钟数 (0=9:30, 390=16:00)
        """
        orders = []

        if self._volume_profile and len(self._volume_profile) > current_minute:
            # Use historical volume profile to weight slices
            window_end = min(current_minute + self.duration_minutes,
                             len(self._volume_profile))
            profile_window = self._volume_profile[current_minute:window_end]
            total_vol = sum(profile_window)

            if total_vol <= 0 or len(profile_window) < self.slices:
                # Fall back to equal slices
                qty = self.total_shares // self.slices
                rem = self.total_shares % self.slices
                for i in range(self.slices):
                    sz = qty + (1 if i < rem else 0)
                    if sz > 0:
                        orders.append(SliceOrder(
                            symbol=symbol, side=side, shares=sz,
                            slice_num=i + 1, total_slices=self.slices,
                        ))
                return orders

            # Distribute by volume proportion
            # Resample profile_window to self.slices buckets
            bucket_size = max(1, len(profile_window) // self.slices)
            bucket_vols = []
            for i in range(self.slices):
                start = i * bucket_size
                end = min(start + bucket_size, len(profile_window))
                bucket_vols.append(sum(profile_window[start:end]))

            total_bucket = sum(bucket_vols)
            allocated = 0
            for i, bv in enumerate(bucket_vols[:-1]):
                qty = int(self.total_shares * bv / total_bucket)
                allocated += qty
                if qty > 0:
                    orders.append(SliceOrder(
                        symbol=symbol, side=side, shares=qty,
                        slice_num=i + 1, total_slices=self.slices,
                    ))
            # Last slice gets remainder
            last_qty = self.total_shares - allocated
            if last_qty > 0:
                orders.append(SliceOrder(
                    symbol=symbol, side=side, shares=last_qty,
                    slice_num=self.slices, total_slices=self.slices,
                ))
        else:
            # Equal slices fallback
            qty = self.total_shares // self.slices
            rem = self.total_shares % self.slices
            for i in range(self.slices):
                sz = qty + (1 if i < rem else 0)
                if sz > 0:
                    orders.append(SliceOrder(
                        symbol=symbol, side=side, shares=sz,
                        slice_num=i + 1, total_slices=self.slices,
                    ))

        return orders

    @property
    def interval_seconds(self) -> float:
        return self._interval


# ═══════════════════════════ POV ═══════════════════════════════════════════════

class POVExecutor:
    """Percentage of Volume — 以市场成交量的固定比例参与交易。

    实时监控市场成交量，以 target_pct 的比例下限价单或市价单。

    Args:
        total_shares: 目标总股数
        target_pct: 目标市场参与率 (0.05 = 5%)
        max_duration_minutes: 最大执行时长
        min_trade_size: 最小单笔数量
    """

    def __init__(self, total_shares: int, target_pct: float = 0.05,
                 max_duration_minutes: int = 60, min_trade_size: int = 100):
        self.total_shares = total_shares
        self.target_pct = target_pct
        self.max_duration_minutes = max_duration_minutes
        self.min_trade_size = min_trade_size
        self._filled = 0
        self._start_time: float | None = None

    def should_execute(self, market_volume: int) -> int:
        """
        Determine how many shares to trade given recent market volume.

        Returns: number of shares to trade this slice.
        """
        if self._filled >= self.total_shares:
            return 0

        if self._start_time is None:
            self._start_time = _time.time()

        # Check max duration
        if self._start_time and _time.time() - self._start_time > self.max_duration_minutes * 60:
            # Force complete remaining
            remaining = self.total_shares - self._filled
            return remaining

        target_qty = max(self.min_trade_size,
                         int(market_volume * self.target_pct))
        target_qty = min(target_qty, self.total_shares - self._filled)
        return target_qty

    def record_fill(self, shares: int):
        self._filled += shares

    @property
    def is_complete(self) -> bool:
        return self._filled >= self.total_shares

    @property
    def progress_pct(self) -> float:
        if self.total_shares <= 0:
            return 1.0
        return self._filled / self.total_shares


# ═══════════════════════════ Iceberg ═══════════════════════════════════════════

class IcebergExecutor:
    """冰山订单 — 只显示订单总量的一小部分，隐藏真实意图。

    Args:
        total_shares: 总股数
        display_shares: 每次显示的股数（冰山尖）
        price_limit: 限价（0=市价）
        refresh_seconds: 显示量刷新间隔
    """

    def __init__(self, total_shares: int, display_shares: int = 100,
                 price_limit: float = 0.0, refresh_seconds: float = 5.0):
        self.total_shares = total_shares
        self.display_shares = min(display_shares, total_shares)
        self.price_limit = price_limit
        self.refresh_seconds = refresh_seconds
        self._remaining = total_shares
        self._last_refresh = 0.0

    def peek(self) -> int:
        """How many shares to display on the book right now."""
        now = _time.time()
        if now - self._last_refresh >= self.refresh_seconds and self._remaining > 0:
            self._last_refresh = now
            return min(self.display_shares, self._remaining)
        return 0

    def consume(self, filled: int):
        """Called when a displayed slice gets filled."""
        self._remaining = max(0, self._remaining - filled)

    @property
    def is_complete(self) -> bool:
        return self._remaining <= 0


# ═══════════════════════════ Execution Manager ═════════════════════════════════

class ExecutionManager:
    """Manage multiple execution algorithms concurrently.

    Usage:
        mgr = ExecutionManager()
        mgr.add(TWAPExecutor(5000, 30, 10), "AAPL", "BUY")
        mgr.run_step(broker)
    """

    def __init__(self):
        self._tasks: dict[str, dict] = {}  # task_id → {executor, symbol, side, ...}

    def add(self, executor, symbol: str, side: str = "BUY",
            task_id: str | None = None) -> str:
        tid = task_id or f"{symbol}_{side}_{_time.time()}"
        self._tasks[tid] = {
            "executor": executor, "symbol": symbol, "side": side,
            "status": "pending", "filled": 0, "avg_price": 0.0,
        }
        return tid

    def run_step(self, broker, task_id: str, price: float = 0.0):
        """Execute one step of the given task."""
        t = self._tasks.get(task_id)
        if not t or t["status"] not in ("pending", "executing"):
            return

        t["status"] = "executing"
        exc = t["executor"]
        symbol = t["symbol"]
        side = t["side"]

        if isinstance(exc, TWAPExecutor):
            orders = exc.slice(symbol, side)
            for o in orders:
                broker.market_order(o.symbol, o.shares, o.side)
                t["filled"] += o.shares
                if price > 0:
                    old_total = t["avg_price"] * (t["filled"] - o.shares)
                    t["avg_price"] = (old_total + price * o.shares) / t["filled"]
        elif isinstance(exc, VWAPExecutor):
            orders = exc.slice(symbol, side)
            for o in orders:
                broker.market_order(o.symbol, o.shares, o.side)
                t["filled"] += o.shares
        elif isinstance(exc, POVExecutor):
            qty = exc.should_execute(0)  # need real market volume
            if qty > 0:
                broker.market_order(symbol, qty, side)
                exc.record_fill(qty)
                t["filled"] += qty

            if exc.is_complete:
                t["status"] = "completed"

    def cancel(self, task_id: str):
        t = self._tasks.get(task_id)
        if t:
            t["status"] = "cancelled"

    def status(self, task_id: str) -> dict:
        t = self._tasks.get(task_id, {})
        return {
            "task_id": task_id, "status": t.get("status"),
            "symbol": t.get("symbol"), "filled": t.get("filled", 0),
            "avg_price": t.get("avg_price", 0.0),
        }
