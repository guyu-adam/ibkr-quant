# ibkr-quant 代码评审报告（复审）

> 初评：2026-05-21 | 复审：2026-05-21（commit `538a9ba`）| 评审人：Claude Code

---

## 一、总体评价

初评中的 4 个 P0 问题已全部修复，新增了 7 个测试模块和完整的月度轮动策略，还独立实现了一套 A 股纸上交易系统。代码质量有明显提升。

**综合评分：4.5/10 → 6.5/10**

| 维度 | 初评 | 复审 | 变化说明 |
|------|------|------|----------|
| 架构设计 | 6 | 6 | 新增 paper_trading 独立系统，两套并存 |
| 策略逻辑 | 7 | 8 | 新增月度轮动 + A股策略，逻辑清晰 |
| 代码质量 | 4 | 6 | P0 bug 全部修复，魔法数字消除 |
| 错误处理 | 3 | 5 | 新增 retry 机制，NLV 安全处理 |
| 测试覆盖 | 0 | 6 | 7 个测试模块，覆盖核心逻辑 |
| 可运维性 | 4 | 5 | 新增 Flask 仪表盘 |

---

## 二、初评 P0 问题修复确认

| 问题 | 状态 | 修复方式 |
|------|------|----------|
| Engine 未连接 broker | ✅ 已修复 | `main.py:125` — `engine._main_loop()` → `engine.start()` |
| bracket order 实现错误 | ✅ 已修复 | `hk_ipo.py:138-177` — 标准化 OCA transmit 流程 |
| monthly_rotation 缺失 | ✅ 已修复 | 新增 `strategy/monthly_rotation.py`，29 只标的动量轮动 |
| 依赖未声明 | ✅ 已修复 | `requirements.txt` 补全 ta/quantstats/PyPortfolioOpt/scipy/pytest |

---

## 三、新增内容评价

### 3.1 `paper_trading/` — A 股纸上交易系统

独立实现了完整的纸上交易系统，含 Flask Web 仪表盘、RSI+EMA 日内策略、腾讯财经实时行情。

**优点：**
- 完整闭环：行情获取 → 策略评估 → 交易执行 → 前端展示
- 一手 100 股（board lot）处理正确
- ATR 移动止损逻辑
- WebSocket + REST 双通道，30 秒自动刷新
- 交易日历判断（上午/下午时段）

**问题：**

1. **指标计算第三套实现** — `paper_trading/strategy.py` 手写了 `_rsi`/`_ema`/`_atr`，与 `signals.py` 和 `quant_toolkit/indicators.py` 形成三套实现。且 `_rsi` 使用 `alpha=1/period`（Wilder's smoothing），`signals.py` 使用 `span=period`（标准 EMA），**两者数值不同**。

2. **`allow_unsafe_werkzeug=True`**（`app.py:202`）— 允许任意网络访问 Werkzeug 开发服务器，仅适合本地调试，不应对外暴露。

3. **代理硬编码** — `proxies={'http': None, 'https': None}` 写死跳过代理，应改为可配置。

4. **无持仓限制检查** — `evaluate()` 只检查 `MAX_POSITIONS`，不检查单票仓位上限或总仓位上限。

5. **paper_trading 与主系统零代码共享** — 策略逻辑、风控、数据获取都是独立实现的。如果未来要对接 IBKR 实盘，需要大量重构。

### 3.2 `strategy/monthly_rotation.py` — 月度动量轮动

29 只美股大盘+蓝筹的 3 个月动量排名，TOP_N=5 等权配置。实现干净，`get_momentum_scores()` + `generate_orders()` 职责分离好，sell/buy/hold 三类订单逻辑正确。`run_monthly.py` 可直接调用。

**小问题：** `get_momentum_scores()` 逐个 symbol 调 `yf.Ticker().history()`，29 只会发 29 次网络请求，建议改用 `yf.download(universe)` 批量拉取。

### 3.3 测试模块

7 个测试文件共约 40 个用例，覆盖了 signals、risk、backtest、long_term、quant_toolkit、tz_arb。用 Mock 替代了 IBKR 实例，不依赖真实 TWS 连接。结构规范，Docstring 清晰。

**但当前环境未安装依赖**（pandas/numpy 等），测试无法运行。同时 `ib_insync` 在 Windows pip 上不可用，影响开发体验。

---

## 四、复审新发现问题

### 4.1 `main.py` — NLV 可能为 None 但未处理

```python
# main.py:71-72 — nlv 现在是 float | None
nlv = broker.net_liquidation()
pnl = broker.daily_pnl()
print(f"  Net Liquidation:  ${nlv:,.2f}")        # ← None 会报错
print(f"  Daily P&L:        ${pnl:,.2f}  ({pnl/nlv*100:.2f}%)")  # ← 除零/None
```

### 4.2 `_retry` 装饰器捕获范围过窄

```python
# core/broker.py:17-33
def _retry(func):
    def wrapper(*args, **kwargs):
        for attempt in range(RETRY_ATTEMPTS):
            try:
                return func(*args, **kwargs)
            except ConnectionError as e:      # ← 只捕获 ConnectionError
                ...
            except Exception as e:
                raise                          # ← 其余异常直接抛出，不重试
```

IBKR 网络问题可能表现为 `TimeoutError`、`OSError`、`socket.timeout` 等，这些不会被 `ConnectionError` 捕获，也不会重试。且 `_retry` 装饰器定义了但**未在任何方法上使用**。

### 4.3 `risk.py` — TRADE_RISK_PCT 硬编码

```python
TRADE_RISK_PCT = 0.01   # 应该放进 config/settings.py
```

### 4.4 `signals.py` — `rsi()` 修复引入边界问题

```python
# 当 avg_l == 0 且 avg_g == 0 时（价格完全不变），avg_g/0 → inf → RSI=0
# rsi_vals[avg_l == 0] = 100.0 会覆盖所有 avg_l==0 的情况
# 但如果价格在前 period 根 bar 完全不变，avg_g 和 avg_l 都是 0
# 实际中罕见，但逻辑上不够精确
```

### 4.5 跨模块常量不一致

| 常量 | `signals.py` | `quant_toolkit/indicators.py` | `paper_trading/strategy.py` |
|------|-------------|-------------------------------|----------------------------|
| RSI_PERIOD | 14 (from config) | 14 (default arg) | 14 (hardcoded) |
| RSI_OVERSOLD | 30 (from config) | N/A | 30 (hardcoded) |
| ATR period | 14 (from config) | 14 (default arg) | 14 (hardcoded) |
| RSI 算法 | EMA (span) | ta library (Wilder's) | Wilder's (alpha) |

`paper_trading/strategy.py` 的参数应引用 `config/settings.py` 避免魔术数字。

---

## 五、综合评审对比

### 初评 P0-P3 路线图复查

| 优先级 | 问题 | 状态 |
|--------|------|------|
| P0 | Engine 未连接 broker | ✅ 已修复 |
| P0 | bracket order 错误 | ✅ 已修复 |
| P0 | monthly_rotation 缺失 | ✅ 已修复 |
| P0 | 依赖未声明 | ✅ 已修复 |
| P1 | 策略缺少统一接口 | ❌ 未改（paper_trading 加剧了分散） |
| P1 | NLV 返回 0 的危险默认值 | ✅ 改为返回 None + fallback |
| P1 | 硬编码魔法数字 | ✅ 大部分消除 |
| P2 | Broker 不可 mock | ❌ 未改（测试用 MagicMock 绕过） |
| P2 | 无持久化层 | ❌ 未改 |
| P3 | 缺少类型标注 | ❌ 未改 |
| P3 | 无订单价格保护 | ❌ 未改 |

### 新建议优先修复

| 优先级 | 问题 | 影响 |
|--------|------|------|
| P1 | paper_trading 第三套指标实现 | 三套实现维护成本高，行为不一致 |
| P1 | main.py NLV=None 未处理 | show_status 会崩溃 |
| P1 | `_retry` 装饰器未使用 + 捕获范围窄 | 重试机制形同虚设 |
| P2 | paper_trading 参数硬编码 | 可维护性 |
| P2 | `allow_unsafe_werkzeug=True` | 部署安全性 |
| P3 | 跨模块常量不统一 | 长期一致性 |

---

## 六、总结

第二次审查结果正面：P0 问题全部清零，新增的月度轮动和测试套件是高质量的补充。`paper_trading/` 作为独立的 A 股纸上交易系统功能完整，但与主系统存在明显的代码重复（尤其是指标计算）。

当前最大风险不是功能正确性，而是**三套指标实现的行为一致性**——回测用一套、实盘用另一套、纸上交易用第三套，可能产生策略漂移。建议下一步把 `quant_toolkit.indicators` 作为唯一指标源，其余模块全部引用它。
