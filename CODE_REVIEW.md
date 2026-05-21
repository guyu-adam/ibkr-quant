# ibkr-quant 代码评审报告（五审）

> 初评：2026-05-21 | 四审（`26c6860`，8.0）| 五审：2026-05-21（`a4fe9ed`）| 评审人：Claude Code

---

## 一、总体评价

本提交是一次小型重构——引入 `DataFeed` 抽象层、构建了继承 `BaseStrategy` 的 `MeanReversionStrategy`、将 A 股标的池从 5 只扩展到 150 只全覆盖。架构清晰度大幅提升。但经实际运行模拟盘后，发现了多个导致亏损的实质性 bug。

**评分变化：4.5 → 6.5 → 7.5 → 8.0 → 8.5 → 8.0/10**（因模拟盘亏损 bug 下调）

| 维度 | 四审 | 五审 | 关键变化 |
|------|------|------|----------|
| 架构设计 | 7 | 8 | DataFeed 抽象层 + 策略策略分离 |
| 策略逻辑 | 8 | 9 | 多因子评分买入 + 四条件卖出 |
| 代码质量 | 8 | 8 | 策略逻辑集中，但出现两个回归 |
| 错误处理 | 8 | 8 | 未变 |
| 测试覆盖 | 8 | 8 | 旧测试适配，未新增 |
| 可运维性 | 6 | 7 | 标的池 5→150，A 股全行业覆盖 |

---

## 二、新增内容

### 2.1 `core/data_feed.py` — 统一数据源层 ✅ 关键架构改进

```
DataFeed (ABC)
├── YFinanceFeed   — 美股 + A 股历史数据（yfinance）
├── TencentFeed    — A 股实时行情（腾讯财经，GBK 解码）
└── CachedFeed     — 装饰器模式，TTL 缓存减少网络请求
```

**设计亮点：**
- `DataFeed` ABC 定义 `fetch_history` / `fetch_realtime` / `is_connected` / `name`
- `CachedFeed` 用组合模式包装任意 backend，支持 `invalidate()` 按 symbol 或全部清缓存
- `TencentFeed.fetch_history()` 委托给 `YFinanceFeed`——「腾讯只给实时价，历史走 yfinance」
- `TencentFeed` 的 `_to_tencent_code` 带 `_prefix_cache` 避免重复计算

**与 `BaseStrategy` + `DataFeed` 组合：** 任何策略只依赖这两个抽象，数据源可热切换（回测用 CSV、实盘用 IBKR、纸上交易用腾讯），无需改动策略代码。

### 2.2 `strategy/mean_reversion.py` — 首个完整 `BaseStrategy` 实现 ✅

266 行，实现了 RSI 超卖反弹 + MACD 底背离 + 成交量验证的多因子评分策略。

**买入评分体系（满分 ~90）：**
| 条件 | 分数 |
|------|------|
| RSI < oversold（线性，最高 50 分） | `min(50, (oversold - RSI) × 3)` |
| MACD histogram 连续三根收窄 | +15 |
| MACD histogram > 0 | +10 |
| MACD line > signal line | +5 |
| 成交量 > 1.5x 均量 | +10 |
| 成交量 > 1.2x 均量 | +5 |
| **总评分** ≥ `min_score`(30) → 买入 | |

**卖出条件（四个维度）：**
1. RSI > overbought（70）
2. 触发止损（hard stop 3% 或 ATR trailing stop）
3. MACD 死叉 + RSI < 50 + histogram 下降
4. 获利 > 5% 且 RSI 回落 < 55

**继承认证：** 首个实际继承 `BaseStrategy` 的策略类（`name`/`on_bar`/`on_close`/`start`/`stop`），`on_close` 清除止损状态。

> **注意：** `on_bar()` 抛出 `NotImplementedError`，实际入口是 `evaluate()`。这是一种务实的部分实现——保持接口兼容，但允许更灵活的调用方式。

### 2.3 `paper_trading/` 重构

**删除：** `paper_trading/strategy.py`（旧的独立 RSI+EMA 策略）

**新增：**
- `pt_strategy.py` — 策略适配层，100% 委托给 `MeanReversionStrategy`
- `universe.py` — 150 只 A 股（12 个 GICS 行业）

**关键变化：** `run_strategy()` 现在采用**评分排名制**——对所有标的打分后按 score 降序买入，优先买最高分的，直到仓位槽满。

### 2.4 `paper_trading/universe.py` — A 股 12 行业覆盖 ✅

| 行业 | 数量 | 代表 |
|------|------|------|
| 银行 | 12 | 招行、工行、建行 |
| 保险/券商 | 10 | 中国平安、中信证券 |
| 白酒/食品 | 12 | 茅台、五粮液、伊利 |
| 科技/电子/半导体 | 18 | 宁德时代、中芯国际 |
| 医药/医疗 | 16 | 恒瑞、迈瑞、药明康德 |
| 新能源 | 12 | 隆基、阳光电源、通威 |
| 汽车 | 10 | 比亚迪、长城、上汽 |
| 房地产/建材 | 10 | 万科、海螺水泥、三一 |
| 能源/化工 | 10 | 中石油、万华化学 |
| 家电 | 8 | 格力、美的、海尔 |
| 交通运输 | 8 | 国航、顺丰 |
| 电信/传媒 | 8 | 中国移动、分众传媒 |
| 金属/矿业 | 8 | 紫金矿业、赣锋锂业 |
| 公用事业 | 6 | 长江电力、中国核电 |
| 军工 | 6 | 中航沈飞、中国船舶 |

---

## 三、本轮发现的问题

### 3.1 `paper_trading/pt_strategy.py:128` — `pd` 未导入且是死代码

```python
# 第 128 行
atr_df = pd.DataFrame({'high': high, 'low': low, 'close': close})
```

`import pandas as pd` 不存在，这一行会触发 `NameError`。而且 `atr_df` 创建后从未被使用（真正用的是下一行的 `_strategy._atr(high, low, close, ...)` 直接传 Series）。**修复：删除该行。**

### 3.2 `paper_trading/app.py:207` — `allow_unsafe_werkzeug=True` 回归

```python
socketio.run(app, host='127.0.0.1', port=8888, debug=debug_mode, allow_unsafe_werkzeug=True)
```

三审中已修复的问题又回来了。**应删除该参数**（`debug` 环境变量已足以控制开发模式）。

### 3.3 `main.py` 放弃多策略调度

旧版 `main.py` 有完整的 scheduler 支持四大策略并行（HK IPO / TZ Arb / LT Portfolio 的定时任务 + 动量引擎）。新版只跑 `MeanReversionStrategy`。

四个策略模块仍在 `strategy/` 中，但 `main.py` 不再调用它们。**需确认这是有意为之还是遗漏。** 如果是有意简化（先验证单一策略），建议在 commit 中说明。

### 3.4 `paper_trading/engine.py` 与 `TencentFeed` 功能重复

`engine.update_quotes()` 自己调用腾讯 API 解析行情，而 `TencentFeed.fetch_realtime()` 有完全相同的逻辑。engine 没有使用 `TencentFeed`。建议 engine 改为持有 `TencentFeed` 实例，通过 `feed.fetch_realtime(SYMBOLS)` 获取行情。

### 3.5 `MeanReversionStrategy` 内部指标是第四套实现

策略自带 `_rsi`/`_atr`/`_macd` 静态方法，加上 `signals.py`、`quant_toolkit/indicators.py`、旧 `paper_trading/strategy.py`（已删），共三套存活。但这次的动机合理——策略需要完全自包含（zero-dependency），可以直接放到任何项目中运行。

---

## 四、模拟盘亏损根因分析（运行时发现）

模拟盘运行后出现亏损，经逐链路排查，锁定以下 5 个 bug。其中 #4.1 和 #4.2 是亏损主因。

### 4.1 致命：策略缺失趋势过滤 — 在下跌趋势中持续"接飞刀"

**对比旧版 `strategy/signals.py`（有保护）：**

```python
# 旧版 — RSI 超卖 AND EMA 趋势向上，两个条件同时满足才做多
bullish_trend = row["momentum"] > 0    # EMA_fast > EMA_slow
if row["rsi"] < RSI_OVERSOLD and bullish_trend:
    signal = 1
```

**新版 `strategy/mean_reversion.py`（无保护）：**

```python
# 新版 — 只看 RSI，不管趋势方向
if cur_rsi < self.rsi_oversold:
    score += min(50, (self.rsi_oversold - cur_rsi) * 3)
    # RSI 越低分越高，哪怕股票在一路暴跌
```

**亏损机制：** 在一路下跌的股票上，RSI 会持续低于 30，策略反复买入 → 3% 止损 → 再买入 → 再止损。这是经典的"散户抄底"亏损模式。旧版 `signals.py` 的 EMA 趋势过滤器在重写为 `mean_reversion.py` 时被丢弃。

**修复建议：** 在 `evaluate()` 的买入评分中加入趋势确认条件（如 `close > EMA(close, 30)` 才允许买入）。

### 4.2 致命：信号价格和成交价格来自两个不同的数据源

```
策略评估 → 信号价格:
  TencentFeed.fetch_history() → YFinanceFeed (日线, 15分钟延迟)
  → cur_close = 昨日收盘价 或 延迟的日内价

执行买入 → 成交价格:
  engine.buy() → engine.latest_prices (腾讯财经实时行情, 无延迟)
  → 实际成交价
```

**典型亏损场景（茅台）：**

| 步骤 | 数据源 | 价格 | 
|------|--------|------|
| 策略评估 RSI | yfinance 日线 | 1700（昨收，RSI=28 超卖）|
| 策略输出 | 基于 1700 | `signal='buy'` |
| 引擎执行 | 腾讯实时 | 1730（今天已经反弹了）|

策略基于 1700 判断"超卖该抄底"，但市场已经在 1730 消化了这个信息。你买在反弹顶部，均值回归的利润已经被别人吃完了。**解决：** `evaluate()` 应同时接收实时价格，用实时价做信号判断和止损计算，历史数据只用于指标计算。

### 4.3 `engine.buy()` 金额计算链条断裂

`pt_strategy.py` 按策略价算投入金额，`engine.buy()` 按自己的实时价重新算手数：

```python
# pt_strategy.py — 用策略价格
shares = _sizer.size(portfolio_val, price, cur_atr)  # 基于 1700 算股数
amount = shares * price * 1.01                        # 基于 1700 算金额

# engine.py — 用自己的实时价格
def buy(self, symbol, amount):
    price = self.latest_prices.get(symbol)             # 1730
    lots = int(amount / (price * 100))                 # amount/1730 vs amount/1700
    shares = lots * 100                                # 买到的股数不一样
```

金额按 1700 计算，执行按 1730。如果实时价更高，买到的股数比预期少。如果实时价更低，买到更多但成本基准是乱的。两个价格源各自为政，形成了隐性的"滑点放大器"。

### 4.4 崩溃：`pt_strategy.py:128` — `pd` 未导入

```python
atr_df = pd.DataFrame({'high': high, 'low': low, 'close': close})
#         ^^ NameError: name 'pd' is not defined
```

`import pandas as pd` 缺失，买入路径触发 `NameError` 崩溃。而且 `atr_df` 创建后从未使用（真正用 ATR 的是下一行 `_strategy._atr(high, low, close, ...)` 直接传 Series）。**这行是死代码 — 直接删除即可。**

### 4.5 CachedFeed TTL=300 秒 + 循环 60 秒 = 信号滞后 5 分钟

```python
_data_feed = CachedFeed(TencentFeed(...), ttl_seconds=300)  # 数据缓存 5 分钟

while engine.running:
    run_strategy(engine)      # 每 60 秒跑一次
    time.sleep(60)
```

5 分钟内跑 5 次策略，全部使用同一份缓存数据。叠加 yfinance 日线 15 分钟延迟，策略做决策时看见的信息实际是 15-20 分钟前的。在 A 股这种高波动市场，20 分钟的滞后足够让一个信号从盈利变亏损。

**修复建议：** 策略评估不使用 CachedFeed，或把 TTL 降到 30 秒。实时价格应直接走 `TencentFeed.fetch_realtime()`。

---

## 五、变化亮点总结

| 新增 | 状态 |
|------|------|
| `core/data_feed.py` | ✅ 三个实现，缓存装饰器 |
| `strategy/mean_reversion.py` | ✅ 首例 BaseStrategy 实现，多因子评分 |
| `paper_trading/universe.py` | ✅ 150 只 A 股，12 行业 |
| `paper_trading/pt_strategy.py` | ✅ 100% 委托给 MeanReversionStrategy |
| `paper_trading/strategy.py` | 🗑️ 已删除（旧实现） |

| 问题 | 严重度 | 修复成本 | 亏损影响 |
|------|--------|---------|---------|
| 策略缺失趋势过滤 | **P0** | 加 3 行条件 | 反复抄底→止损→亏损 |
| 信号/成交价格来自两个数据源 | **P0** | 策略接收实时价 | 永远买在滞后点 |
| engine.buy 金额计算链断裂 | P1 | 统一价格源 | 买入成本漂移 |
| `pd` 未导入 | P1 | 删一行 | 买路径崩溃 |
| `allow_unsafe_werkzeug` 回归 | P2 | 删一个参数 | 无 |
| main.py 多策略调度丢失 | P2 | 中等 | 无 |
| engine 与 TencentFeed 重复 | P3 | 小重构 | 无 |
| CachedFeed TTL=300s | P1 | 改30s或去掉 | 信号滞后5分钟 |

---

## 六、迭代总览

| 轮次 | 评分的核心提升 | 分数 |
|------|---------------|------|
| 初评 | 发现 4 个阻断性 P0 bug | 4.5 |
| 复审 | P0 清零 + 测试 + 月度轮动 | 6.5 |
| 三审 | 指标统一、retry 激活、硬编码消除 | 7.5 |
| 四审 | 策略 ABC + safe imports + 测试翻倍 | 8.0 |
| 五审（初） | DataFeed 抽象 + BaseStrategy 实现 + 150 标的 | 8.5 |
| **五审（终）** | **模拟盘运行发现 2 个 P0 亏损 bug** | **8.0** |

五审初期架构评分上调至 8.5，但实际运行模拟盘后发现策略层面的两个致命缺陷（趋势过滤缺失、双价格源错配）导致持续亏损，最终评分回调至 8.0。架构方向正确，策略实现需回补旧版的 EMA 趋势过滤器并统一数据源。
