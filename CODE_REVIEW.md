# ibkr-quant 代码评审报告（三审）

> 初评：2026-05-21 | 复审：2026-05-21（`538a9ba`）| 三审：2026-05-21（`f2cd2fa`）| 评审人：Claude Code

---

## 一、总体评价

三审针对复审指出的 6 个 P1/P2 问题全部精准修复。`paper_trading` 的指标实现已统一到 `strategy.signals`，`_retry` 装饰器已激活并覆盖 7 个关键方法，所有硬编码参数迁移到 `config/settings.py`。代码库从"功能正确但有债务"进入"可维护"阶段。

**评分变化：4.5 → 6.5 → 7.5/10**

| 维度 | 初评 | 复审 | 三审 | 说明 |
|------|------|------|------|------|
| 架构设计 | 6 | 6 | 6 | 两套系统并存，待统一策略接口 |
| 策略逻辑 | 7 | 8 | 8 | 四策略 + 月度轮动 + A股纸上 |
| 代码质量 | 4 | 6 | 7 | 复审判定问题全部清零 |
| 错误处理 | 3 | 5 | 7 | retry 已激活 + NLV 安全处理 |
| 测试覆盖 | 0 | 6 | 6 | 未变（环境限制无法运行） |
| 可运维性 | 4 | 5 | 6 | 安全配置 + 批量数据拉取 |

---

## 二、三审修复确认（commit `f2cd2fa`）

| 复审判定问题 | 状态 | 修复详情 |
|-------------|------|----------|
| paper_trading 第三套指标 | ✅ | `strategy.py` 改为 `from strategy.signals import rsi, ema, atr` |
| paper_trading 参数硬编码 | ✅ | 全部常量从 `config.settings` 导入 |
| `_retry` 未使用 + 捕获窄 | ✅ | 捕获 `(ConnectionError, TimeoutError, OSError)`，应用到 7 个方法 |
| `main.py` NLV=None 崩溃 | ✅ | `show_status` 加 `if nlv is None` 分支 |
| `allow_unsafe_werkzeug` | ✅ | 改为 `debug` 由 `PAPER_TRADING_DEBUG` 环境变量控制，host=127.0.0.1 |
| proxy 硬编码 | ✅ | `engine.py` 通过 `DISABLE_PROXY` 环境变量控制 |
| monthly_rotation 逐个请求 | ✅ | 改为 `yf.download(" ".join(symbols))` 批量拉取，带 fallback |
| NaN 保护 | ✅ | `strategy.py` 加 `if pd.isna(latest_rsi) or pd.isna(latest_atr): return 'hold'` |

---

## 三、当前代码库结构（一览）

```
ibkr-quant/
├── config/settings.py          ← 所有参数集中管理（新增 TRADE_RISK_PCT）
├── core/
│   ├── broker.py               ← @_retry 覆盖 7 个关键方法
│   ├── engine.py               ← 美股动量引擎
│   └── risk.py                 ← 风控（引用 TRADE_RISK_PCT）
├── strategy/
│   ├── signals.py              ← 唯一指标实现源（RSI/EMA/ATR）
│   ├── hk_ipo.py               ← 港股 IPO（OCA bracket 已修复）
│   ├── tz_arb.py               ← 时区套利
│   ├── long_term.py            ← 长期组合
│   ├── backtest.py             ← 回测引擎
│   └── monthly_rotation.py     ← 月度动量轮动（批量数据拉取）
├── quant_toolkit/               ← 独立分析工具箱（ta 库实现，不复用 signals.py）
│   ├── indicators.py
│   ├── analytics.py
│   ├── portfolio.py
│   └── ibkr_extended.py
├── paper_trading/               ← A股纸上交易系统（已统一引用 signals.py）
│   ├── app.py                  ← Flask 仪表盘（安全配置）
│   ├── engine.py               ← 模拟撮合引擎（可配置代理）
│   └── strategy.py             ← RSI+EMA 策略（复用 signals.py 指标）
├── tests/                       ← 7 个测试模块，~40 用例
│   ├── test_signals.py
│   ├── test_risk.py
│   ├── test_backtest.py
│   ├── test_broker_mock.py
│   ├── test_long_term.py
│   ├── test_quant_toolkit.py
│   └── test_tz_arb.py
├── main.py                      ← 入口（NLV=None 已处理）
└── run_monthly.py               ← 月度再平衡脚本
```

---

## 四、剩余待改善项（非阻断）

| 优先级 | 问题 | 说明 |
|--------|------|------|
| P2 | `quant_toolkit/indicators.py` 仍独立 | 分析工具用 `ta` 库，与 `signals.py` 不同。可接受（工具性质不同），但长期建议统一 |
| P2 | 策略缺少统一抽象接口 | 五个策略入口方法名不一致 |
| P2 | 无持久化层 | 交易记录仅日志，无数据库 |
| P3 | 缺少类型标注 | `broker.py` 有部分，其余模块无 |
| P3 | 无订单价格保护 | 市价单无滑点上限 |
| P3 | `quant_toolkit` 依赖 `quantstats`/`ta`/`PyPortfolioOpt` | 这些库在 Windows pip 上可能安装失败，建议加 try/except 导入 |

---

## 五、总结

三轮迭代（初评 → 修复 → 复审 → 再修复）后，代码库已达到可投入纸面和模拟交易的状态。P0 阻断性 bug 全部清零，P1 工程债务大幅削减，测试框架就位。`paper_trading` 与主系统的指标实现已统一，消除了策略漂移风险。

下一个里程碑建议：在模拟环境连续运行一周，验证 scheduler 调度、止损触发、OCA bracket 的实际行为，然后决定何时切到实盘。
