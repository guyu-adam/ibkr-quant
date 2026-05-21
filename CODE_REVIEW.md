# ibkr-quant 代码评审报告（四审）

> 初评：2026-05-21 | 复审（`538a9ba`）| 三审（`f2cd2fa`）| 四审：2026-05-21（`26c6860`）| 评审人：Claude Code

---

## 一、总体评价

四审提交（`26c6860`）直击两个长期债务：**策略抽象基类**和**safe imports**。新增 4 个测试模块，总用例从 ~40 个翻到 ~90+（commit 声称 117）。`quant_toolkit` 的 Windows 兼容性问题通过 try/except 优雅降级解决。

**评分变化：4.5 → 6.5 → 7.5 → 8.0/10**

| 维度 | 初评 | 复审 | 三审 | 四审 | 说明 |
|------|------|------|------|------|------|
| 架构设计 | 6 | 6 | 6 | 7 | 策略 ABC 已定义，safe imports 解决依赖脆弱性 |
| 策略逻辑 | 7 | 8 | 8 | 8 | 未变 |
| 代码质量 | 4 | 6 | 7 | 8 | 策略接口标准化 + 可选依赖降级 |
| 错误处理 | 3 | 5 | 7 | 8 | quant_toolkit 优雅降级 |
| 测试覆盖 | 0 | 6 | 6 | 8 | 测试模块数 7→11，用例 ~40→~90+ |
| 可运维性 | 4 | 5 | 6 | 6 | 未变 |

---

## 二、新增内容详细评价

### 2.1 `core/strategy_base.py` — 策略抽象基类 ✅✅

```python
class BaseStrategy(ABC):
    @abstractmethod
    def on_bar(self, data: dict) -> list: ...    # 每根 bar 返回 [Signal]
    @abstractmethod
    def on_close(self) -> None: ...              # 收盘清仓
    @property
    @abstractmethod
    def name(self) -> str: ...                   # 策略唯一标识
    def start(self) -> None: pass                # 可选钩子
    def stop(self) -> None: pass                 # 可选钩子
```

设计合理：三个必须实现的抽象方法 + 两个可选的 lifecycle hooks。`on_bar` 返回 `list[Signal]`（而非单个信号），天然支持多信号场景。

**当前局限：** 现有 5 个策略类尚未继承 `BaseStrategy`。这可以理解 — `TradingEngine._main_loop()` 是 while-true 循环模式，`HKIPOStrategy.run()` 是定时触发模式，硬套 `on_bar`/`on_close` 需要大重构。建议新策略从 `BaseStrategy` 继承，老策略逐步迁移。

### 2.2 `quant_toolkit/__init__.py` — Safe imports ✅

```python
try:
    from quant_toolkit.portfolio import max_sharpe, min_volatility, risk_parity
except ImportError as e:
    _log.warning("quant_toolkit.portfolio unavailable: %s", e)
    max_sharpe = None
```

`ibkr_extended`、`portfolio`、`analytics` 三个模块都加了 try/except。在 Windows 上 `ib_insync`/`PyPortfolioOpt` 不可用时不会阻止整个 toolkit 加载。配合 `requirements.txt` 中的声明，文档和代码行为一致。

### 2.3 新增测试模块

| 文件 | 覆盖范围 | 亮点 |
|------|---------|------|
| `test_strategy_base.py` | ABC 接口强制、缺方法报错、lifecycle hooks | 覆盖 3 种缺失组合 |
| `test_hk_ipo.py` | 抓取容错、灰市数据、threshold 判断、风控拒绝、config merge | Mock 网络异常 |
| `test_monthly_rotation.py` | 空数据、sell stale、hold existing、target shares 正数 | 覆盖 6 种订单场景 |
| `test_paper_trading.py` | 引擎初始化、行情解析、买入卖出、snapshot、零现金、零价格 | 24 个用例覆盖引擎全生命周期 |

`test_paper_trading.py` 尤其扎实 — 从腾讯财经 GBK 编码解析到 board lot 计算到持仓清空，覆盖了引擎的完整行为。

---

## 三、遗留问题复查

| 优先级 | 问题 | 初评 | 复审 | 三审 | 四审 |
|--------|------|------|------|------|------|
| P0 | Engine 未连接 broker | ❌ | ✅ | ✅ | ✅ |
| P0 | bracket order 实现错误 | ❌ | ✅ | ✅ | ✅ |
| P0 | monthly_rotation 缺失 | ❌ | ✅ | ✅ | ✅ |
| P0 | 依赖未声明 | ❌ | ✅ | ✅ | ✅ |
| P1 | 策略缺少统一接口 | ❌ | ❌ | ❌ | 🔶 基类已定义，待迁移 |
| P1 | NLV 返回危险默认值 | ❌ | ✅ | ✅ | ✅ |
| P1 | `_retry` 未使用 | ❌ | ❌ | ✅ | ✅ |
| P1 | 指标三套实现 | ❌ | ❌ | ✅ | ✅ |
| P2 | Broker 不可 mock | ❌ | ❌ | ❌ | ❌ |
| P2 | 无持久化层 | ❌ | ❌ | ❌ | ❌ |
| P2 | safe imports | ❌ | ❌ | ❌ | ✅ |
| P3 | 缺少类型标注 | ❌ | ❌ | ❌ | ❌ |
| P3 | 无订单价格保护 | ❌ | ❌ | ❌ | ❌ |

> 🔶 = 部分完成（基类存在但未接入现有策略）

---

## 四、当前项目状态总览

```
ibkr-quant/                       评分: 8.0/10
├── config/settings.py            ✅ 所有参数集中管理
├── core/
│   ├── strategy_base.py          ✅ 新增 — 统一策略 ABC
│   ├── broker.py                 ✅ @_retry × 7，NLV 安全返回
│   ├── engine.py                 ✅ 魔法数字消除
│   └── risk.py                   ✅ TRADE_RISK_PCT 外部化
├── strategy/
│   ├── signals.py                ✅ 唯一指标源（paper_trading 已统一）
│   ├── hk_ipo.py                 ✅ OCA bracket 已修复
│   ├── tz_arb.py                 ✅ 无变化
│   ├── long_term.py              ✅ 无变化
│   ├── backtest.py               ✅ 魔法数字消除
│   └── monthly_rotation.py       ✅ 批量数据拉取
├── quant_toolkit/                 ✅ safe imports 优雅降级
├── paper_trading/                 ✅ 指标统一引用 signals.py
├── tests/  (11 模块, ~90+ 用例)    ✅ 覆盖 core/strategy/paper_trading
├── main.py                        ✅ NLV=None 已处理
└── run_monthly.py                 ✅ 对接 monthly_rotation
```

---

## 五、四轮迭代总结

| 轮次 | 解决的关键问题 | 评分 |
|------|---------------|------|
| 初评 → 复审 | 四个 P0 bug + 7 测试模块 + 月度轮动 | 4.5 → 6.5 |
| 复审 → 三审 | 指标统一、retry 激活、硬编码消除、安全配置 | 6.5 → 7.5 |
| 三审 → 四审 | 策略 ABC、safe imports、测试翻倍 | 7.5 → 8.0 |

四轮迭代将一个"有想法但跑不起来"的原型，变成了"接口清晰、错误可控、测试充分"的准生产系统。剩余 P2/P3 项（持久化、类型标注、mock broker）不再阻碍模拟交易验证。

**下一步建议：** 在 IBKR paper account 上运行 1-2 周，验证 scheduler 调度和 OCA bracket 的实际行为。如稳定，可以开始考虑切到小额实盘。
