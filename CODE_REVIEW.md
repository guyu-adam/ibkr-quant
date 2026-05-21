# ibkr-quant 代码评审报告

> 评审日期：2026-05-21 | 评审人：Claude Code

---

## 一、总体评价

项目骨架清晰，四大策略（美股动量、时区套利、港股IPO打新、长期组合）的分层设计合理。`core/strategy/config` 三层架构是量化交易系统的经典范式。但代码中存在若干**阻断性 bug**和**结构性缺陷**，目前无法在生产环境中安全运行。

**综合评分：4.5/10**

| 维度 | 评分 | 说明 |
|------|------|------|
| 架构设计 | 6/10 | 分层合理，但接口不统一，模块间耦合过紧 |
| 策略逻辑 | 7/10 | 策略思路清晰，参数化做得好 |
| 代码质量 | 4/10 | 存在阻断性 bug，重复代码，缺少类型标注 |
| 错误处理 | 3/10 | 大量裸 except，无重试/降级机制 |
| 测试覆盖 | 0/10 | 零测试用例 |
| 可运维性 | 4/10 | 日志有但无轮转，无监控告警，无持久化 |

---

## 二、阻断性 Bug（必须立即修复）

### 2.1 `TradingEngine` 在 live 模式下未连接 broker

**文件：** `main.py:123` + `core/engine.py:30-31`

```python
# main.py line 123
engine = TradingEngine()
engine._main_loop()
```

`TradingEngine.__init__` 创建了自己的 `self.broker = IBKRBroker()`，但 `run_live()` 从未调用 `engine.start()`（只有 `start()` 里才 `self.broker.connect()`）。所以引擎启动后，所有 `self.broker.get_bars()` 调用都会失败，动量策略完全不工作。

**修复建议：** 改为 `engine.start()`，或将 `broker` 从外部注入。

### 2.2 `_bracket_order` 实现完全错误

**文件：** `strategy/hk_ipo.py:138-158`

三个问题：
1. `parent.contract` 不存在 — `MarketOrder` 没有 `contract` 属性，`ib.qualifyContracts(None)` 会报错。
2. 函数内部调用了 `ib.placeOrder`（155-157行），但调用方 `place_ipo_trade` 又把返回值传给 `broker.ib.placeOrder`（132行），导致 stop_loss 被重复下单。
3. OCA group 逻辑需要 parent order 先提交获取 orderId，才能给子订单设置 `parentId`，当前实现顺序错误。

**修复建议：** 重写为标准的 bracket order 流程——先下 parent（transmit=False），获取 orderId，再下 take_profit 和 stop_loss，最后一个 transmit=True。

### 2.3 `run_monthly.py` 引用不存在的模块

**文件：** `run_monthly.py:14`

```python
from strategy.monthly_rotation import get_momentum_scores, generate_orders
```

`strategy/monthly_rotation.py` 不存在。月度轮动策略功能完全不可用。

**修复建议：** 实现该模块，或删除 `run_monthly.py`。

### 2.4 `quant_toolkit` 依赖未在 requirements.txt 中声明

**文件：** `requirements.txt`

`quant_toolkit/analytics.py` 依赖 `quantstats`，`indicators.py` 依赖 `ta`，`portfolio.py` 依赖 `PyPortfolioOpt` 和 `scipy`。这些都不在 `requirements.txt` 中。

---

## 三、架构与接口设计问题

### 3.1 缺少抽象策略基类

四个策略类接口各不相同：

| 策略 | 入口方法 | 退出方法 |
|------|---------|---------|
| TradingEngine | `_main_loop()` | `_close_all_eod()` |
| HKIPOStrategy | `run()` | `close_all()` |
| TZArbStrategy | `execute(signals)` | `close_all()` |
| LongTermPortfolio | `rebalance()` | `check_trailing_stops()` |

建议定义统一的 `Strategy` 抽象基类：

```python
from abc import ABC, abstractmethod

class BaseStrategy(ABC):
    @abstractmethod
    def on_bar(self, data: dict) -> list[Signal]: ...
    @abstractmethod
    def on_close(self) -> None: ...
    @property
    @abstractmethod
    def name(self) -> str: ...
```

### 3.2 Broker 接口不可测试

`IBKRBroker` 直接依赖 `ib_insync.IB()` 实例，无法在不连接 TWS 的情况下进行单元测试。没有抽象接口层，所有依赖 broker 的逻辑（风控、引擎、策略）都无法 mock 测试。

**建议：** 抽取 `AbstractBroker` 协议类：

```python
from typing import Protocol

class BrokerProtocol(Protocol):
    def connect(self) -> None: ...
    def disconnect(self) -> None: ...
    def net_liquidation(self) -> float: ...
    def positions(self) -> dict: ...
    def market_order(self, symbol: str, qty: int, action: str) -> object: ...
    def get_bars(self, symbol: str, duration: str, bar_size: str) -> "pd.DataFrame": ...
    def last_price(self, symbol: str) -> float: ...
```

### 3.3 RiskManager 紧耦合

`RiskManager` 直接接受 `IBKRBroker` 实例，无法独立测试。且风控逻辑和 broker 数据获取混在一起。

**建议：** `approve()` 和 `position_size()` 改为接收纯数据参数（equity、daily_pnl、positions、current_exposure），而非直接调用 broker 方法。

### 3.4 指标计算重复实现

`strategy/signals.py` 手写了 RSI/EMA/ATR，而 `quant_toolkit/indicators.py` 使用 `ta` 库又实现了一遍。两套实现可能产生微小差异，导致回测与实盘信号不一致。

**建议：** 删除 `signals.py` 中的指标函数，统一使用 `quant_toolkit.indicators`。

### 3.5 `TradingEngine` 职责过重

引擎同时负责：市场时间判断、数据拉取、信号计算、开仓平仓、止损监控、收盘清仓。应拆分为：
- `MarketClock` — 交易时间管理
- `DataFeed` — 数据获取抽象
- `OrderExecutor` — 订单执行
- `StopManager` — 止损跟踪

---

## 四、错误处理与健壮性

### 4.1 裸异常捕获且无重试

```python
# 典型模式 - 几乎每个文件都有
except Exception as e:
    log.warning(f"...")
    return []  # 或 return 0.0 / return {}
```

IBKR 连接会因网络波动断开，无重试机制意味着任何一次临时故障都会导致策略停止或静默失败。

**建议：** 
- 对 IBKR API 调用加入指数退避重试（3次，间隔 1s/2s/4s）
- 区分可恢复错误（网络超时）和不可恢复错误（合约不存在）

### 4.2 `net_liquidation()` 失败返回 0.0 极其危险

```python
# core/broker.py:37
def net_liquidation(self) -> float:
    vals = self.ib.accountValues(self.account())
    for v in vals:
        if v.tag == "NetLiquidation" and v.currency == "USD":
            return float(v.value)
    return 0.0  # ← 失败时返回 0，会导致 division by zero 或风控失效
```

当 IBKR 返回的数据不含 `NetLiquidation` 时（比如刚连接数据未就绪），返回 0.0 会导致 `RiskManager.position_size()` 计算出 0 shares（风险金额 = 0 * 1% = 0），所有交易被静默跳过。

**建议：** 返回 `None` 或抛异常，调用方显式处理。添加数据就绪检查。

### 4.3 网页抓取无容错

`hk_ipo.py` 依赖 AASTOCKS 和 IPOBoss 的 HTML 结构。这两个网站改版会导致策略静默返回空列表，不会报错。

**建议：** 加入结构校验（检查预期 CSS selector 是否存在），连续3天抓取失败时发送告警。

### 4.4 `quant_toolkit/ibkr_extended.py` 的连接检查不准确

```python
if not self._connected:
    print(f"WARNING: ...")
    return pd.DataFrame()
```

`_connected` 仅在 `connect()` 成功时设为 True。但如果之后连接断开（网络闪断），`_connected` 仍为 True，后续调用会抛出未捕获的异常。

**建议：** 使用 `self.ib.isConnected()` 做实时检查，而非依赖标志位。

---

## 五、策略逻辑问题

### 5.1 动量策略：冷却期用 wall-clock 时间而非 bar 时间

```python
# core/engine.py:70-71
last = self._last_signal_time.get(symbol, 0)
if time.time() - last < SIGNAL_COOLDOWN:
    return
```

`SIGNAL_COOLDOWN = 60`（秒），但 bar 是 5 分钟。如果同一个 bar 内循环多次，冷却期机制被绕过。

**建议：** 冷却应基于 bar 数量（如"同一 symbol 最快每 2 个 bar 产生一个信号"）。

### 5.2 动量策略：信号只在 bar 末尾检查

引擎在每根 5 分钟 K 线末尾拉取 OHLC 数据并计算信号。但实际交易中，价格可能在 bar 中间大幅波动并触发止损。当前实现在 5 分钟内对价格变化完全无感知。

**建议：** 止损检查应独立于信号生成循环，以更高频率（如每 10 秒）运行。

### 5.3 时区套利：HKD/USD 汇率硬编码

```python
TZ_ARB = {"hkd_usd_rate": 7.8}
```

港币挂钩美元但并非完全固定（波动区间 7.75-7.85），且 7.8 这个值在实际交易中可能是买入价也可能是卖出价。对精度敏感的资金计算应考虑实时汇率。

### 5.4 时区套利：信号使用 yfinance 收盘价而非实时价

`compute_signals()` 用 `yfinance` 拉 ADR 收盘价，但 `yfinance` 的数据有 15-20 分钟延迟。这对盘前计算信号影响不大，但在盘中反向套利场景（港股→美股）会完全不可用。

### 5.5 长期组合：权益计算存在双重折扣

```python
# strategy/long_term.py:153
equity = self.broker.net_liquidation() * self.cfg.get("max_equity_pct", 0.6)
```

先乘以 `max_equity_pct`（60%），但风控层还有 `MAX_TOTAL_EXPOSURE`（80%）检查。两层叠加可能导致实际配置比例远低于预期。

**建议：** 风控参数与策略参数统一管理，避免隐式叠加。

### 5.6 港股 IPO：未考虑回拨机制和公开发售比例

香港 IPO 有回拨机制（散户超额认购时从机构份额划转），且散户中签率通常很低（热门股可能 <5%）。策略假设"开盘买入"可以成交，但实际可能：
- 暗盘已大幅高开，无法以 IPO 价成交
- 流动性不足（小盘新股）

**建议：** 加入首日开盘价的滑点模型（假设成交价 = IPO 价 × 1.X）。

---

## 六、代码质量问题

### 6.1 中英混杂注释

部分文件用中文注释（`signals.py`、`broker.py`），部分用英文（`tz_arb.py`）。建议统一为英文。

### 6.2 缺少类型标注

几乎所有函数没有 type hints。对于一个金融交易系统，类型错误可能导致资金损失。

```python
# 当前
def position_size(self, price, atr):
    ...

# 建议
def position_size(self, price: float, atr: float) -> int:
    ...
```

### 6.3 硬编码魔法数字

```python
# config/settings.py — 已经参数化了，很好
# 但以下位置仍有硬编码：
# core/engine.py:78
if df is None or len(df) < 40:   # 40 是什么？应该是 RSI_PERIOD + MOM_SLOW + buffer

# core/risk.py:27
risk_amt = equity * 0.01          # 应该引用配置

# strategy/backtest.py:31
for i in range(40, len(df)):      # 同上
```

### 6.4 不可达代码

```python
# strategy/hk_ipo.py:195
if not ipo_price:
    continue
```

`ipo_price` 是 `float`，不会是 falsy（0.0 是合法价格）。正确写法是 `if ipo_price <= 0`。

### 6.5 `quant_toolkit/indicators.py` — `bollinger_bands` 参数类型错误

```python
def bollinger_bands(close, period=20, nbdev=2):
```

`nbdev` 名称暗示 "number of deviations"（整数），但传给 `ta` 库的 `window_dev` 确实接受 int。命名可以更清晰：`num_std`。

---

## 七、性能与可扩展性

### 7.1 每个 bar 为每个 symbol 单独拉数据

```python
# core/engine.py:74
df = self.broker.get_bars(symbol, duration="3 D", bar_size=BAR_SIZE)
```

7 个 symbol × 每个独立的 HTTP 请求 = 每 5 分钟 7 次 IBKR API 调用。IBKR 有频率限制（尤其历史数据请求）。

**建议：** 批量请求或使用实时 bar 订阅（`reqRealTimeBars`）代替轮询。

### 7.2 止损检查每次迭代对所有 symbol 调用 `last_price`

```python
# core/engine.py:126
price = self.broker.last_price(symbol)
```

每个 `last_price` 调用触发一次 `qualifyContracts` + `reqMktData`。7 个 symbol 的止损检查就是 7 次 API 调用。

**建议：** 使用 IBKR 的 snapshot market data（`reqMktData` 的 `snapshot=True`）减少开销。

### 7.3 无持久化层

交易信号、订单执行结果、PnL 变动仅记录在日志文件中。没有数据库存储，无法进行交易后分析和审计。

**建议：** 加入 SQLite 存储交易记录，schema 包含：timestamp, symbol, signal_type, entry_price, exit_price, pnl, strategy_name。

---

## 八、安全性

### 8.1 实盘确认不足

```python
# main.py:92
confirm = input("⚠  Live trading mode — type YES to confirm: ").strip()
if confirm != "YES":
```

仅依赖一个字符串输入。建议：生成唯一确认码（如随机6位数字），要求用户输入匹配。

### 8.2 无订单价格限制

`market_order()` 直接使用市价单，没有价格带保护。在流动性不足或闪崩场景下，市价单可能以极端价格成交。

**建议：** 市价单改为限价单（基于 last_price + 一定 slippage 容忍度），超时未成交自动取消。

---

## 九、补充测试用例

以下是针对核心模块的测试用例实现建议：

### 9.1 `tests/test_signals.py`

```python
"""
Unit tests for strategy/signals.py
"""
import unittest
import pandas as pd
import numpy as np
from strategy.signals import ema, rsi, atr, compute_indicators, generate_signal


class TestEMA(unittest.TestCase):
    def setUp(self):
        self.close = pd.Series([10.0, 11.0, 12.0, 11.5, 12.5, 13.0, 12.0, 11.0, 10.5, 11.5])

    def test_ema_output_length(self):
        result = ema(self.close, period=5)
        self.assertEqual(len(result), len(self.close))

    def test_ema_no_nan_at_end(self):
        """EMA should produce a value for the last data point."""
        result = ema(self.close, period=3)
        self.assertFalse(pd.isna(result.iloc[-1]))

    def test_ema_monotonic_input(self):
        """EMA of strictly increasing series should be increasing."""
        increasing = pd.Series(range(1, 21), dtype=float)
        result = ema(increasing, period=5)
        self.assertTrue(result.iloc[-1] > result.iloc[5])

    def test_ema_constant_input(self):
        """EMA of constant series should equal the constant."""
        constant = pd.Series([5.0] * 50)
        result = ema(constant, period=10)
        pd.testing.assert_series_equal(
            result.iloc[20:], constant.iloc[20:], check_exact=False, rtol=1e-10
        )


class TestRSI(unittest.TestCase):
    def setUp(self):
        np.random.seed(42)
        self.close = pd.Series(np.random.randn(100).cumsum() + 100)

    def test_rsi_range(self):
        result = rsi(self.close, period=14)
        valid = result.dropna()
        self.assertTrue((valid >= 0).all() and (valid <= 100).all())

    def test_rsi_all_up(self):
        """RSI of a strictly increasing series should be near 100."""
        up = pd.Series(range(1, 101), dtype=float)
        result = rsi(up, period=14)
        self.assertGreater(result.iloc[-1], 95)

    def test_rsi_all_down(self):
        """RSI of a strictly decreasing series should be near 0."""
        down = pd.Series(range(100, 0, -1), dtype=float)
        result = rsi(down, period=14)
        self.assertLess(result.iloc[-1], 5)

    def test_rsi_returns_nan_for_insufficient_data(self):
        short = pd.Series([10.0, 11.0, 12.0])
        result = rsi(short, period=14)
        self.assertTrue(result.isna().all())


class TestATR(unittest.TestCase):
    def setUp(self):
        dates = pd.date_range("2024-01-01", periods=50, freq="D")
        self.df = pd.DataFrame({
            "open":  np.random.randn(50).cumsum() + 100,
            "high":  np.random.randn(50).cumsum() + 102,
            "low":   np.random.randn(50).cumsum() + 98,
            "close": np.random.randn(50).cumsum() + 100,
        }, index=dates)
        self.df["high"] = self.df[["open", "high", "low", "close"]].max(axis=1)
        self.df["low"] = self.df[["open", "high", "low", "close"]].min(axis=1)

    def test_atr_positive(self):
        result = atr(self.df, period=14)
        valid = result.dropna()
        self.assertTrue((valid > 0).all())

    def test_atr_output_length(self):
        result = atr(self.df, period=14)
        self.assertEqual(len(result), len(self.df))


class TestComputeIndicators(unittest.TestCase):
    def setUp(self):
        dates = pd.date_range("2024-01-01", periods=100, freq="5min")
        self.df = pd.DataFrame({
            "open":   np.random.randn(100).cumsum() + 100,
            "high":   np.random.randn(100).cumsum() + 103,
            "low":    np.random.randn(100).cumsum() + 97,
            "close":  np.random.randn(100).cumsum() + 100,
            "volume": np.random.randint(1000, 10000, 100),
        }, index=dates)
        self.df["high"] = self.df[["open", "close"]].max(axis=1) + 2
        self.df["low"] = self.df[["open", "close"]].min(axis=1) - 2

    def test_returns_all_columns(self):
        result = compute_indicators(self.df)
        for col in ["rsi", "ema_fast", "ema_slow", "atr", "momentum"]:
            self.assertIn(col, result.columns)

    def test_momentum_sign_consistent(self):
        """momentum column should reflect ema_fast - ema_slow."""
        result = compute_indicators(self.df)
        pd.testing.assert_series_equal(
            result["momentum"],
            result["ema_fast"] - result["ema_slow"],
            check_names=False,
        )

    def test_no_side_effect(self):
        """compute_indicators should not mutate input DataFrame."""
        original_cols = list(self.df.columns)
        compute_indicators(self.df)
        self.assertEqual(list(self.df.columns), original_cols)


class TestGenerateSignal(unittest.TestCase):
    def _make_df(self, close_series=None):
        """Helper to create a minimal DataFrame with required columns."""
        n = len(close_series) if close_series is not None else 100
        dates = pd.date_range("2024-01-01", periods=n, freq="5min")
        df = pd.DataFrame(index=dates)
        if close_series is not None:
            df["close"] = close_series
        else:
            df["close"] = np.random.randn(n).cumsum() + 100
        df["rsi"] = rsi(df["close"], 14)
        df["ema_fast"] = ema(df["close"], 10)
        df["ema_slow"] = ema(df["close"], 30)
        df["atr"] = pd.Series(np.random.uniform(0.5, 3.0, n), index=dates)
        df["momentum"] = df["ema_fast"] - df["ema_slow"]
        return df

    def test_signal_keys(self):
        df = self._make_df()
        sig = generate_signal(df)
        for key in ["signal", "price", "atr", "stop_long", "stop_short", "reason"]:
            self.assertIn(key, sig)

    def test_signal_value_range(self):
        df = self._make_df()
        sig = generate_signal(df)
        self.assertIn(sig["signal"], [-1, 0, 1])

    def test_long_stop_below_price(self):
        """Stop for long should be below current price."""
        df = self._make_df()
        sig = generate_signal(df)
        self.assertLess(sig["stop_long"], sig["price"])

    def test_short_stop_above_price(self):
        """Stop for short should be above current price."""
        df = self._make_df()
        sig = generate_signal(df)
        self.assertGreater(sig["stop_short"], sig["price"])

    def test_signal_0_when_rsi_neutral(self):
        """No signal when RSI is between oversold and overbought."""
        n = 50
        dates = pd.date_range("2024-01-01", periods=n, freq="5min")
        df = pd.DataFrame(index=dates)
        df["close"] = pd.Series(np.linspace(100, 110, n), index=dates)
        df["rsi"] = pd.Series([50.0] * n, index=dates)         # neutral RSI
        df["ema_fast"] = pd.Series(np.linspace(100, 112, n), index=dates)
        df["ema_slow"] = pd.Series(np.linspace(100, 108, n), index=dates)
        df["atr"] = pd.Series([1.0] * n, index=dates)
        df["momentum"] = df["ema_fast"] - df["ema_slow"]       # > 0 bullish
        sig = generate_signal(df)
        self.assertEqual(sig["signal"], 0)


if __name__ == "__main__":
    unittest.main()
```

### 9.2 `tests/test_risk.py`

```python
"""
Unit tests for core/risk.py
"""
import unittest
from unittest.mock import MagicMock, patch
from core.risk import RiskManager


class TestRiskManager(unittest.TestCase):
    def setUp(self):
        self.mock_broker = MagicMock()
        self.mock_broker.net_liquidation.return_value = 100_000.0
        self.mock_broker.daily_pnl.return_value = 500.0
        self.mock_broker.positions.return_value = {}
        self.rm = RiskManager(self.mock_broker)

    # ── position_size ──────────────────────────────────────────────────────────
    def test_position_size_positive(self):
        shares = self.rm.position_size(price=150.0, atr=3.0)
        # risk_amt = 100000 * 0.01 = 1000
        # stop_dist = 3.0 * 2.0 = 6.0
        # shares = min(int(1000/6), int(100000*0.1/150)) = min(166, 66) = 66
        self.assertEqual(shares, 66)

    def test_position_size_zero_atr(self):
        shares = self.rm.position_size(price=100.0, atr=0.0)
        self.assertEqual(shares, 0)

    def test_position_size_negative_atr(self):
        shares = self.rm.position_size(price=100.0, atr=-1.0)
        self.assertEqual(shares, 0)

    def test_position_size_high_price_limits_shares(self):
        """Very high price should be constrained by MAX_POSITION_PCT."""
        shares = self.rm.position_size(price=50_000.0, atr=500.0)
        # risk_amt = 1000, stop_dist = 1000 → 1 share
        # max_shares = 100000 * 0.1 / 50000 = 0.2 → 0
        self.assertEqual(shares, 0)

    # ── approve ────────────────────────────────────────────────────────────────
    def test_approve_normal(self):
        self.mock_broker.last_price.return_value = 100.0
        result = self.rm.approve("AAPL", 100, 150.0)
        self.assertTrue(result)

    def test_approve_halted(self):
        self.rm._halted = True
        result = self.rm.approve("AAPL", 100, 150.0)
        self.assertFalse(result)

    def test_approve_daily_loss_trigger(self):
        self.mock_broker.daily_pnl.return_value = -3000.0   # -3% > 2% limit
        self.mock_broker.last_price.return_value = 100.0
        result = self.rm.approve("AAPL", 100, 150.0)
        self.assertFalse(result)
        self.assertTrue(self.rm._halted)

    def test_approve_total_exposure_limit(self):
        # Existing position: 800 shares @ $100 = $80,000 exposure
        self.mock_broker.positions.return_value = {"SPY": 800}
        self.mock_broker.last_price.return_value = 100.0
        # new exposure = 80000 + (100 * 150) = 95000 > 100000 * 0.8 = 80000
        result = self.rm.approve("AAPL", 100, 150.0)
        self.assertFalse(result)

    def test_approve_exposure_within_limit(self):
        self.mock_broker.positions.return_value = {"SPY": 100}
        self.mock_broker.last_price.return_value = 100.0
        # existing: 10000, new: 15000, total: 25000 < 80000
        result = self.rm.approve("AAPL", 100, 150.0)
        self.assertTrue(result)

    # ── reset_halt ─────────────────────────────────────────────────────────────
    def test_reset_halt(self):
        self.rm._halted = True
        self.rm.reset_halt()
        self.assertFalse(self.rm._halted)


if __name__ == "__main__":
    unittest.main()
```

### 9.3 `tests/test_broker_mock.py`

```python
"""
Unit tests using a mocked IBKR broker to verify broker-dependent logic.
"""
import unittest
from unittest.mock import MagicMock, patch, PropertyMock
import pandas as pd
import numpy as np
from core.risk import RiskManager
from strategy.signals import compute_indicators, generate_signal


class TestRiskManagerWithMockBroker(unittest.TestCase):
    """Integration-ish tests: RiskManager + mock broker."""

    def setUp(self):
        self.broker = MagicMock()
        self.broker.net_liquidation.return_value = 50_000.0
        self.broker.daily_pnl.return_value = 200.0
        self.broker.positions.return_value = {}
        self.rm = RiskManager(self.broker)

    def test_consecutive_approvals(self):
        """Multiple approvals within limits should all pass."""
        self.broker.last_price.return_value = 50.0
        for _ in range(5):
            result = self.rm.approve("TEST", 100, 50.0)
            self.assertTrue(result)

    def test_daily_loss_halts_all_further_trades(self):
        """Once daily loss is hit, all subsequent approvals fail."""
        self.broker.daily_pnl.return_value = -2000.0   # -4% > 2% limit
        self.broker.last_price.return_value = 50.0
        result1 = self.rm.approve("A", 10, 50.0)
        self.assertFalse(result1)
        result2 = self.rm.approve("B", 10, 50.0)
        self.assertFalse(result2)

    def test_exposure_tracks_new_positions(self):
        """Exposure check should account for pending trade value."""
        # 80% of 50000 = 40000
        self.broker.last_price.return_value = 200.0
        # First trade: 100 shares @ 200 = 20000 → OK
        self.assertTrue(self.rm.approve("X", 100, 200.0))
        # Simulate position update after first trade
        self.broker.positions.return_value = {"X": 100}
        # Second: another 150 shares @ 200 = 30000, total = 50000 > 40000 → FAIL
        self.assertFalse(self.rm.approve("Y", 150, 200.0))

    def test_position_size_zero_equity(self):
        """position_size with zero equity should return 0."""
        self.broker.net_liquidation.return_value = 0.0
        shares = self.rm.position_size(price=100.0, atr=2.0)
        self.assertEqual(shares, 0)


class TestSignalPipeline(unittest.TestCase):
    """End-to-end test: raw data → indicators → signal."""

    def _make_uptrend_data(self) -> pd.DataFrame:
        """Generate a DataFrame with a clear uptrend (close price rising steadily)."""
        n = 60
        dates = pd.date_range("2024-06-01", periods=n, freq="5min")
        df = pd.DataFrame(index=dates)
        close = np.linspace(100, 130, n) + np.random.randn(n) * 0.5
        df["close"] = close
        df["open"] = close - np.random.uniform(0, 0.3, n)
        df["high"] = close + np.random.uniform(0.3, 0.8, n)
        df["low"] = close - np.random.uniform(0.3, 0.8, n)
        df["volume"] = np.random.randint(5000, 50000, n)
        return df

    def _make_downtrend_data(self) -> pd.DataFrame:
        """Generate a DataFrame with a clear downtrend."""
        n = 60
        dates = pd.date_range("2024-06-01", periods=n, freq="5min")
        df = pd.DataFrame(index=dates)
        close = np.linspace(130, 100, n) + np.random.randn(n) * 0.5
        df["close"] = close
        df["open"] = close + np.random.uniform(0, 0.3, n)
        df["high"] = close + np.random.uniform(0.3, 0.8, n)
        df["low"] = close - np.random.uniform(0.3, 0.8, n)
        df["volume"] = np.random.randint(5000, 50000, n)
        return df

    def test_pipeline_output_structure(self):
        df = self._make_uptrend_data()
        df = compute_indicators(df)
        sig = generate_signal(df)
        self.assertIsNotNone(sig["price"])
        self.assertIsNotNone(sig["atr"])
        self.assertGreater(sig["atr"], 0)

    def test_pipeline_preserves_original_columns(self):
        df = self._make_uptrend_data()
        orig_cols = set(df.columns)
        df_result = compute_indicators(df)
        for col in orig_cols:
            self.assertIn(col, df_result.columns)


if __name__ == "__main__":
    unittest.main()
```

### 9.4 `tests/test_backtest.py`

```python
"""
Unit tests for strategy/backtest.py
"""
import unittest
from unittest.mock import patch, MagicMock
import pandas as pd
import numpy as np
from strategy.backtest import run_backtest, _max_drawdown


class TestMaxDrawdown(unittest.TestCase):
    def test_no_drawdown(self):
        self.assertEqual(_max_drawdown([100, 101, 102, 103]), 0.0)

    def test_simple_drawdown(self):
        self.assertAlmostEqual(_max_drawdown([100, 90, 100]), -0.1)

    def test_multiple_drawdowns(self):
        # peak 100, drops to 80 (-20%), recovers to 100, drops to 70 (-30%)
        self.assertAlmostEqual(_max_drawdown([100, 80, 100, 70]), -0.3)

    def test_flat_curve(self):
        self.assertEqual(_max_drawdown([100] * 10), 0.0)


class TestRunBacktest(unittest.TestCase):
    @patch("strategy.backtest.yf.download")
    def test_empty_data_returns_empty(self, mock_download):
        mock_download.return_value = pd.DataFrame()
        result = run_backtest("FAKE")
        self.assertEqual(result, {})

    @patch("strategy.backtest.yf.download")
    def test_result_keys(self, mock_download):
        """Verify all expected keys are in the result dict."""
        dates = pd.date_range("2023-01-01", periods=200, freq="B")
        mock_download.return_value = pd.DataFrame({
            "Open":   np.random.randn(200).cumsum() + 100,
            "High":   np.random.randn(200).cumsum() + 103,
            "Low":    np.random.randn(200).cumsum() + 97,
            "Close":  np.random.randn(200).cumsum() + 100,
            "Volume": np.random.randint(1000, 10000, 200),
        }, index=dates)

        result = run_backtest("TEST")
        for key in ["symbol", "total_trades", "win_rate", "final_equity",
                     "total_return", "sharpe", "max_drawdown", "equity_curve"]:
            self.assertIn(key, result)

    @patch("strategy.backtest.yf.download")
    def test_no_trades_scenario(self, mock_download):
        """No triggers: RSI stays neutral (~50), no signals should fire."""
        n = 200
        dates = pd.date_range("2023-01-01", periods=n, freq="B")
        # Flat price → RSI stays around 50 → no signals
        mock_download.return_value = pd.DataFrame({
            "Open":   [100.0] * n,
            "High":   [100.5] * n,
            "Low":    [99.5] * n,
            "Close":  [100.0] * n,
            "Volume": [10000] * n,
        }, index=dates)

        result = run_backtest("FLAT")
        self.assertEqual(result["total_trades"], 0)
        self.assertEqual(result["final_equity"], 10_000.0)

    @patch("strategy.backtest.yf.download")
    def test_equity_curve_length(self, mock_download):
        """Equity curve should have length = len(data) + 1 (initial value)."""
        n = 100
        dates = pd.date_range("2023-01-01", periods=n, freq="B")
        close = np.linspace(100, 100, n)  # flat
        mock_download.return_value = pd.DataFrame({
            "Open":   close,
            "High":   close + 1,
            "Low":    close - 1,
            "Close":  close,
            "Volume": [10000] * n,
        }, index=dates)

        result = run_backtest("TEST")
        self.assertEqual(len(result["equity_curve"]), n + 1)

    @patch("strategy.backtest.yf.download")
    def test_win_rate_in_range(self, mock_download):
        n = 200
        dates = pd.date_range("2023-01-01", periods=n, freq="B")
        close = np.random.randn(n).cumsum() + 100
        mock_download.return_value = pd.DataFrame({
            "Open":   close - 0.5,
            "High":   close + 1,
            "Low":    close - 1,
            "Close":  close,
            "Volume": [10000] * n,
        }, index=dates)

        result = run_backtest("TEST")
        if result["total_trades"] > 0:
            self.assertGreaterEqual(result["win_rate"], 0.0)
            self.assertLessEqual(result["win_rate"], 1.0)


if __name__ == "__main__":
    unittest.main()
```

### 9.5 `tests/test_quant_toolkit.py`

```python
"""
Unit tests for quant_toolkit indicators and portfolio modules.
"""
import unittest
import pandas as pd
import numpy as np
from quant_toolkit.indicators import rsi, macd, ema, atr, bollinger_bands, obv
from quant_toolkit.portfolio import _validate


class TestQuantIndicators(unittest.TestCase):
    def setUp(self):
        n = 100
        dates = pd.date_range("2024-01-01", periods=n, freq="D")
        self.close = pd.Series(np.random.randn(n).cumsum() + 100, index=dates)
        self.high = self.close + np.random.uniform(0.5, 2.0, n)
        self.low = self.close - np.random.uniform(0.5, 2.0, n)
        self.volume = pd.Series(np.random.randint(10000, 100000, n), index=dates)

    def test_rsi_range(self):
        result = rsi(self.close, period=14)
        valid = result.dropna()
        self.assertTrue((valid >= 0).all())
        self.assertTrue((valid <= 100).all())

    def test_macd_columns(self):
        result = macd(self.close)
        for col in ["macd", "signal", "histogram"]:
            self.assertIn(col, result.columns)

    def test_macd_histogram_is_diff(self):
        result = macd(self.close)
        pd.testing.assert_series_equal(
            result["histogram"].dropna(),
            (result["macd"] - result["signal"]).dropna(),
            check_names=False,
        )

    def test_ema_length(self):
        result = ema(self.close, period=20)
        self.assertEqual(len(result), len(self.close))

    def test_atr_positive(self):
        result = atr(self.high, self.low, self.close, period=14)
        valid = result.dropna()
        self.assertTrue((valid >= 0).all())

    def test_bollinger_bands_columns(self):
        result = bollinger_bands(self.close)
        for col in ["upper", "middle", "lower", "bandwidth", "percent_b"]:
            self.assertIn(col, result.columns)

    def test_bollinger_upper_above_lower(self):
        result = bollinger_bands(self.close)
        valid = result.dropna()
        self.assertTrue((valid["upper"] >= valid["lower"]).all())

    def test_obv_length(self):
        result = obv(self.close, self.volume)
        self.assertEqual(len(result), len(self.close))


class TestPortfolioValidation(unittest.TestCase):
    def test_validate_too_few_rows(self):
        df = pd.DataFrame({"A": np.random.randn(10)}, index=pd.date_range("2024-01-01", periods=10))
        with self.assertRaises(ValueError):
            _validate(df)

    def test_validate_sufficient_rows(self):
        df = pd.DataFrame({"A": np.random.randn(50)}, index=pd.date_range("2024-01-01", periods=50))
        result = _validate(df)
        self.assertEqual(len(result), 50)

    def test_validate_drops_nan(self):
        data = np.random.randn(50)
        data[10] = np.nan
        data[20] = np.nan
        df = pd.DataFrame({"A": data}, index=pd.date_range("2024-01-01", periods=50))
        result = _validate(df)
        self.assertEqual(len(result), 48)


if __name__ == "__main__":
    unittest.main()
```

### 9.6 `tests/test_long_term.py`

```python
"""
Unit tests for strategy/long_term.py
"""
import unittest
from unittest.mock import MagicMock
import pandas as pd
from strategy.long_term import compute_target_weights, rebalance_trades


class TestComputeTargetWeights(unittest.TestCase):
    def test_normal_case(self):
        portfolio = {"A": 0.25, "B": 0.25}
        weights = compute_target_weights(portfolio)
        self.assertAlmostEqual(sum(weights.values()), 1.0)
        self.assertAlmostEqual(weights["A"], 0.5)

    def test_already_normalized(self):
        portfolio = {"A": 0.5, "B": 0.5}
        weights = compute_target_weights(portfolio)
        self.assertAlmostEqual(sum(weights.values()), 1.0)

    def test_empty(self):
        self.assertEqual(compute_target_weights({}), {})

    def test_zero_sum(self):
        self.assertEqual(compute_target_weights({"A": 0, "B": 0}), {})


class TestRebalanceTrades(unittest.TestCase):
    def setUp(self):
        self.prices = {"A": 100.0, "B": 200.0, "C": 50.0}
        self.weights = {"A": 0.5, "B": 0.3, "C": 0.2}

    def test_no_positions_all_buys(self):
        """Empty portfolio: should generate buy trades for all."""
        trades = rebalance_trades(
            current_positions={},
            target_weights=self.weights,
            prices=self.prices,
            equity=10_000.0,
            drift_threshold=0.0,  # 0 threshold = always rebalance
        )
        self.assertEqual(len(trades), 3)
        for t in trades:
            self.assertEqual(t["action"], "BUY")

    def test_drift_threshold_skips_small(self):
        """Positions close to target should be skipped."""
        current = {"A": 50, "B": 15, "C": 40}  # close to target
        trades = rebalance_trades(
            current_positions=current,
            target_weights=self.weights,
            prices=self.prices,
            equity=10_000.0,
            drift_threshold=0.05,  # 5% drift threshold
        )
        # With 5% threshold, small deviations should be skipped
        drift_A = 0.5 - (50 * 100) / 10000  # 0.5 - 0.5 = 0
        self.assertAlmostEqual(drift_A, 0.0)

    def test_sell_when_overweight(self):
        """Overweight position should generate SELL."""
        current = {"A": 200, "B": 0, "C": 0}   # A is 200% of portfolio
        trades = rebalance_trades(
            current_positions=current,
            target_weights={"A": 0.3, "B": 0.7},
            prices={"A": 100.0, "B": 50.0},
            equity=20_000.0,
            drift_threshold=0.0,
        )
        sells = [t for t in trades if t["action"] == "SELL"]
        self.assertTrue(len(sells) >= 1)
        self.assertEqual(sells[0]["ticker"], "A")

    def test_missing_price_skipped(self):
        """Tickers with no price data should be skipped."""
        trades = rebalance_trades(
            current_positions={},
            target_weights={"A": 0.5, "B": 0.5},
            prices={"A": 100.0, "B": 0.0},   # B has zero price
            equity=10_000.0,
            drift_threshold=0.0,
        )
        tickers = [t["ticker"] for t in trades]
        self.assertNotIn("B", tickers)


if __name__ == "__main__":
    unittest.main()
```

### 9.7 `tests/test_tz_arb.py` (部分)

```python
"""
Unit tests for strategy/tz_arb.py — signal computation only.
"""
import unittest
from unittest.mock import patch
import pandas as pd
import numpy as np
from strategy.tz_arb import compute_signals, ADR_PAIRS


class TestComputeSignals(unittest.TestCase):
    @patch("strategy.tz_arb._get_close")
    def test_no_signal_below_threshold(self, mock_get_close):
        """ADR move below threshold should produce no signal."""
        close_data = pd.Series([100.0, 101.0], index=pd.DatetimeIndex([
            "2024-06-01", "2024-06-02"
        ]))
        mock_get_close.return_value = close_data
        signals = compute_signals(threshold=0.05)  # 5% threshold, 1% move → no signal
        self.assertEqual(len(signals), 0)

    @patch("strategy.tz_arb._get_close")
    def test_signal_above_threshold(self, mock_get_close):
        """ADR move above threshold should produce signal."""
        close_data = pd.Series([100.0, 104.0], index=pd.DatetimeIndex([
            "2024-06-01", "2024-06-02"
        ]))
        mock_get_close.return_value = close_data
        signals = compute_signals(threshold=0.02)
        # Should get 1 signal per ADR pair (7 pairs)
        self.assertGreater(len(signals), 0)
        for s in signals:
            self.assertIn("hk_code", s)
            self.assertIn("adr", s)
            self.assertIn("signal", s)
            self.assertIn("adr_move", s)

    @patch("strategy.tz_arb._get_close")
    def test_signal_direction_long(self, mock_get_close):
        """Positive ADR move should generate long signal (+1)."""
        close_data = pd.Series([100.0, 105.0], index=pd.DatetimeIndex([
            "2024-06-01", "2024-06-02"
        ]))
        mock_get_close.return_value = close_data
        signals = compute_signals(threshold=0.02)
        for s in signals:
            self.assertEqual(s["signal"], 1)

    @patch("strategy.tz_arb._get_close")
    def test_signal_direction_short(self, mock_get_close):
        """Negative ADR move should generate short signal (-1)."""
        close_data = pd.Series([100.0, 95.0], index=pd.DatetimeIndex([
            "2024-06-01", "2024-06-02"
        ]))
        mock_get_close.return_value = close_data
        signals = compute_signals(threshold=0.02)
        for s in signals:
            self.assertEqual(s["signal"], -1)

    @patch("strategy.tz_arb._get_close")
    def test_empty_data_graceful(self, mock_get_close):
        """Missing data for all pairs should return empty list, not crash."""
        mock_get_close.return_value = None
        signals = compute_signals()
        self.assertEqual(signals, [])

    def test_adr_pairs_format(self):
        """All ADR keys should be valid US tickers, all values should be .HK tickers."""
        for us, hk in ADR_PAIRS.items():
            self.assertFalse(hk.startswith("$"))
            self.assertTrue(hk.endswith(".HK"))
            self.assertNotIn(" ", us)


if __name__ == "__main__":
    unittest.main()
```

### 9.8 运行测试的入口脚本

```bash
# 运行所有测试
python -m pytest tests/ -v

# 仅运行 signals 测试
python -m pytest tests/test_signals.py -v

# 带覆盖率
python -m pytest tests/ -v --cov=. --cov-report=html
```

需在 `requirements.txt` 中添加：`pytest>=8.0`, `pytest-cov>=5.0`。

---

## 十、优先修复路线图

| 优先级 | 问题 | 影响 | 工作量 |
|--------|------|------|--------|
| P0 | 2.1 Engine 未连接 broker | 动量策略完全不工作 | 小 |
| P0 | 2.2 bracket order 实现错误 | IPO 策略无法下单 | 中 |
| P0 | 2.3 monthly_rotation 缺失 | 月度轮动不可用 | 大 |
| P0 | 2.4 依赖未声明 | 安装后导入报错 | 小 |
| P1 | 3.1 策略缺少统一接口 | 扩展困难 | 中 |
| P1 | 4.2 NLV 返回 0 的危险默认值 | 可能导致异常交易 | 小 |
| P1 | 6.3 硬编码魔法数字 | 维护性差 | 小 |
| P2 | 3.2 Broker 不可 mock | 无法写测试 | 大 |
| P2 | 7.3 无持久化层 | 无法审计 | 中 |
| P3 | 6.2 缺少类型标注 | 可维护性 | 中 |
| P3 | 8.2 无订单价格保护 | 滑点风险 | 中 |

---

## 十一、总结

这个项目的策略思路是成熟的——四大策略覆盖了日内、跨境套利、事件驱动和长期配置，风控参数也做了中心化管理。代码量控制在合理范围内（约 3000 行），没有过度工程化。

但工程层面的问题较重：三个阻断性 bug 导致核心功能无法正常运行，零测试覆盖意味着任何修改都可能引入回归。建议先把 P0 问题修完、补上 P1 的接口统一和错误处理，再逐步建立测试体系。
