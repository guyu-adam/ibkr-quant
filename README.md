# quant

**多市场、多策略量化交易系统 — 覆盖美股、港股、加密货币、A 股，统一架构，热插拔接口。**

Multi-market, multi-strategy quantitative trading system. US stocks, HK stocks, crypto, A-shares — unified architecture, hot-swappable broker interfaces.

[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://python.org)
[![Tests](https://img.shields.io/badge/tests-86%2F86%20passed-brightgreen.svg)](tests/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

---

## 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                         main.py                              │
│                   统一入口 / CLI / 调度                        │
├─────────────────────────────────────────────────────────────┤
│  strategies/                   interfaces/                  │
│  ┌─────────────┐              ┌──────────────┐              │
│  │ contracts   │              │    ibkr      │              │
│  │ options     │              │    okx       │              │
│  │ leverage    │──────────────│   schwab     │──────────────│
│  │ fast_trading│  策略-接口    │    ths       │  券商/交易所   │
│  │ slow_trading│   解耦       │  binance     │              │
│  │ long_term   │              └──────────────┘              │
│  └─────────────┘                                            │
├─────────────────────────────────────────────────────────────┤
│  core/                                                      │
│  strategy_base  risk  data_feed  engine  ml_model           │
│  alpha_factors  portfolio_optimizer  indicators  backtest   │
│  regime_detector  ensemble  meta_labeling  walkforward      │
│  transformer_model  llm_alpha  broker_interface             │
├─────────────────────────────────────────────────────────────┤
│  paper_trading/              tests/                         │
│  模拟盘 Web 仪表盘            38 tests · 100% pass            │
└─────────────────────────────────────────────────────────────┘
```

---

## 策略矩阵

### 快速交易 `strategies/fast_trading.py`
| 策略 | 逻辑 | 频率 | 标的 |
|------|------|------|------|
| RSI 均值回归 | RSI(14) 超卖≤30 买入 + EMA30 趋势过滤 + MACD 背离确认 + 成交量验证 | 5 分钟 K 线 | SPY, QQQ, NVDA, AAPL, MSFT, TSLA, AMZN |

### 合约 `strategies/contracts.py`
| 策略 | 逻辑 | 频率 | 标的 |
|------|------|------|------|
| 网格震荡 | 在中间价上下各布 N 层网格，回调买入/反弹卖出，震荡市收割波动 | 实时 | OKX 永续合约 |

### 期权 `strategies/options.py`
| 策略 | 逻辑 | 频率 | 标的 |
|------|------|------|------|
| 备兑看涨 (Covered Call) | 持正股 + 卖虚值 Call，delta≈0.30，DTE≈30，收时间价值 | 月频 | 美股正股 |
| 保护性看跌 (Protective Put) | 持正股 + 买虚值 Put，delta≈-0.20，DTE≈60，对冲尾部风险 | 月频 | 美股正股 |
| 铁鹰 (Iron Condor) | 卖宽跨式 + 买保护，short delta≈0.16，DTE≈45，50%止盈 | 月频 | 美股指数 |

### 杠杆 `strategies/leverage.py`
| 策略 | 逻辑 | 频率 | 标的 |
|------|------|------|------|
| 杠杆 ETF 趋势 | EMA(20/50) 双均线趋势追踪 + ATR 波动率止损 | 日频 | TQQQ, SOXL, UPRO |
| 保证金多空配对 | 同行业内做多强势+做空弱势，z-score 进出场，市场中性 | 日频 | 配对股票 |

### 慢速交易 `strategies/slow_trading.py`
| 策略 | 逻辑 | 频率 | 标的 |
|------|------|------|------|
| 港股 IPO 打新 | 灰市溢价≥15% → 首日开盘买入 → 目标捕获 60% 溢价 → 止损 5% | 事件驱动 | 港股新股 |
| ADR→港股时区套利 | 美股 ADR 隔夜涨跌≥1.5% → 港股开盘顺势套利 → 1:2 盈亏比 | 每日 | ADR+港股正股 |

### 长期策略 `strategies/long_term.py`
| 策略 | 逻辑 | 频率 | 标的 |
|------|------|------|------|
| 组合再平衡 | 目标权重偏离>5% → 触发调仓 | 月度 | QQQ, SPY, NVDA 等 |
| 定投加仓 (DCA) | 价格低于52周高点>15% → 额外加仓半份 | 每日检查 | 组合内标的 |
| 移动止损 | 从峰值回撤>25% → 清仓该标的 | 每日检查 | 组合内标的 |

---

## 接口适配

| 接口 | 文件 | 市场 | 状态 | 前置条件 |
|------|------|------|------|----------|
| **IBKR** | `interfaces/ibkr.py` | 美股/港股 | 可用 | TWS/Gateway 运行，API 端口开放 |
| **OKX** | `interfaces/okx.py` | 永续合约 | 可用 | API Key + Secret + Passphrase |
| **Binance** | `interfaces/binance.py` | 现货/合约 | 行情可用 | API Key + Secret（可选） |
| **同花顺** | `interfaces/ths.py` | A 股 | 行情可用 | 腾讯财经免费行情 |
| **嘉信** | `interfaces/schwab.py` | 美股/ETF | 骨架 | OAuth 2.0 注册 |

### 连接示例

```python
# IBKR
from interfaces.ibkr import IBKRBroker
broker = IBKRBroker(host="127.0.0.1", port=7497)
broker.connect()

# OKX
from interfaces.okx import OKXBroker
broker = OKXBroker(api_key="...", secret_key="...", passphrase="...")
broker.connect()

# Binance
from interfaces.binance import BinanceBroker
broker = BinanceBroker(api_key="...", secret="...")
broker.connect()

# 同花顺（A股行情）
from interfaces.ths import THSBroker
broker = THSBroker()
quotes = broker.get_realtime_quote(["000001", "600519"])
```

---

## 快速开始

```bash
git clone git@github.com:guyu-adam/quant.git
cd quant
pip install -r requirements.txt
```

### CLI 命令

```bash
python main.py --backtest      # 离线回测（信号扫描，无需连接券商）
python main.py --status        # IBKR 账户状态 + 实时信号扫描
python main.py --rebalance     # 强制长期组合再平衡
python main.py --paper         # 启动模拟盘 Web 仪表盘 (http://127.0.0.1:5000)
```

---

## 配置

编辑 `config/settings.py`：

```python
# ── 券商 ──
IBKR_HOST = "127.0.0.1"
IBKR_PORT = 7497          # 7497=实盘 | 7496=模拟

# ── 风控 ──
ACCOUNT_EQUITY      = 10_000    # 账户本金
MAX_POSITION_PCT    = 0.10      # 单仓上限 10%
MAX_TOTAL_EXPOSURE  = 0.80      # 总敞口上限 80%
MAX_DAILY_LOSS_PCT  = 0.02      # 日亏损熔断 2%
STOP_LOSS_ATR_MULT  = 2.0       # ATR 止损倍数
TRADE_RISK_PCT      = 0.01      # 每笔风险 1%

# ── 策略参数 ──
US_WATCHLIST  = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "AMZN"]
RSI_OVERSOLD  = 30
RSI_OVERBOUGHT = 70
LONG_TERM_PORTFOLIO = {"positions": {"QQQ": 0.25, "SPY": 0.20, ...}}
```

---

## 风控体系

所有策略共享统一的 `RiskManager` 风控模块：

```
订单请求
  ├── 检查日亏损熔断 (≥-2% → 停止交易)
  ├── 检查单仓上限 (≤10% 权益)
  ├── 检查总敞口上限 (≤80% 权益)
  ├── 波动率自适应仓位 (ATR-based sizing)
  └── 通过 → 下单
```

---

## 测试

```bash
pytest tests/ -v          # 运行全部 38 个测试
pytest tests/ --cov=core  # 含覆盖率报告
```

```
tests/
├── test_strategy_base.py        # 策略基类接口验证 (8)
├── test_risk.py                 # 风控模块 (19)
├── test_alpha_factors.py        # 因子计算 (5)
├── test_ml_model.py             # ML 模型 (5)
├── test_paper_trading.py        # 模拟盘 (5)
├── test_portfolio_optimizer.py  # 组合优化 (6)
├── test_hrp.py                  # HRP 层级风险平价 (8)
├── test_ensemble.py             # 策略融合引擎 (7)
├── test_regime_detector.py      # 市场状态检测 (4)
├── test_meta_labeling.py        # Meta-Labeling (5)
├── test_contracts.py            # 合约网格策略 (7)
└── test_fast_trading.py         # 快速交易策略 (7)
```

---

## 开发路线

- [x] 统一架构重组（策略/接口/核心解耦）
- [x] 6 大策略模块骨架搭建
- [x] 5 个券商接口适配
- [x] RSI 均值回归策略（完整实现）
- [x] 长期组合管理（再平衡/DCA/移动止损）
- [x] 合约网格震荡（完整实现）
- [x] BrokerInterface ABC 统一接口
- [x] 风控全面测试覆盖 (kelly/ATR/熔断)
- [x] .env 配置外部化
- [x] CI/CD + pre-commit hooks
- [x] pyproject.toml 项目打包
- [x] 期权链分析 + 自动下单 (Covered Call / Protective Put / Iron Condor)
- [x] 嘉信 OAuth 2.0 完整接入
- [x] 同花顺 + 东方财富 API 接入
- [x] Transformer 模型 v2 修复 (causal mask, early stopping, gradient clipping)
- [x] 回测引擎 (交易成本 + 滑点建模)
- [x] 测试从 38 → 86 (12 个测试文件)
- [ ] 实盘回测对比报告

---

## 免责声明

本项目仅供学习和研究目的，不构成投资建议。实盘交易存在本金损失风险。请先在模拟盘中充分验证策略。

For educational and research purposes only. Not financial advice. Always validate on paper first.

---

## License

MIT
