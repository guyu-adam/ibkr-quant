# ibkr-quant

**多策略 Interactive Brokers 量化交易系统 — 同时跑美股动量、时区套利、港股 IPO、长期组合四套策略。**

**Multi-strategy quantitative trading system for Interactive Brokers — runs US momentum, timezone arbitrage, HK IPO pop, and long-term portfolio strategies concurrently.**

---

[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://python.org)
[![IBKR](https://img.shields.io/badge/broker-Interactive%20Brokers-red.svg)](https://interactivebrokers.com)
[![Paper Trading](https://img.shields.io/badge/default-paper%20trading-green.svg)](config/settings.py)
[![Markets](https://img.shields.io/badge/markets-US%20%2B%20HK-blue.svg)](strategy/)

---

## 四大策略 / Four Strategies

### 1. 美股动量（日内）/ US Momentum (Intraday)
RSI 均值回归 + EMA 趋势过滤，对 SPY/QQQ/NVDA 等大盘股进行 5 分钟 K 线交易。

RSI mean-reversion + EMA trend filter on SPY, QQQ, AAPL, MSFT, NVDA, TSLA, AMZN. Trades 5-min bars.

```
RSI(14) 超卖 ≤ 30  →  做多信号
RSI(14) 超买 ≥ 70  →  做空信号（叠加 EMA 方向过滤）
止损：entry ± 2×ATR(14)
```

### 2. 时区套利（ADR→港股）/ Timezone Arbitrage (ADR → HK)
美股 ADR 隔夜涨跌幅 ≥ 1.5%，港股开盘时顺势套利港股对应正股，通常领先大陆市场反应。

US ADR overnight move ≥ 1.5% triggers a HK open trade on the underlying. Exploits the price discovery lag between US ADR and HK ordinary shares.

```
触发条件：ADR 隔夜涨跌 > 1.5%
风险：每笔 1% 权益
止盈：1:2 风险/收益比
```

### 3. 港股 IPO 打新溢价 / HK IPO Pop
灰市溢价 ≥ 15% 时，在 IPO 首日开盘买入，目标捕捉灰市溢价的 60%。

Buy on IPO day open when grey-market premium ≥ 15%. Target: capture 60% of the grey-market premium.

```
最低灰市溢价：15%
止损：IPO 发行价 -5%
最大同时持仓：2 只
```

### 4. 长期组合 / Long-Term Portfolio
每月再平衡一次，配置 QQQ(25%)、SPY(20%)、NVDA(15%)、BRK.B(10%)、新兴市场 ETF(10%) 等。

Monthly rebalancing of a diversified long-term portfolio: QQQ 25%, SPY 20%, NVDA 15%, BRK.B 10%, EM ETF 10%, etc.

---

## 回测结果 / Backtest Results

### US Momentum — 5分钟 K 线实测（最近30个交易日，yfinance数据）

> 在 RTX 5060 Ti Linux 机器上运行，$10,000 起始资金，RSI(14) + EMA(10/30) 过滤

| 标的 | 30日收益 | 同期Buy&Hold | 交易次数 | 胜率 | 最终权益 |
|---|---|---|---|---|---|
| SPY | **+3.22%** | +15.71% | 13 | 92% | $10,322 |
| QQQ | **+3.66%** | +25.98% | 14 | 79% | $10,366 |
| NVDA | **+5.11%** | +30.43% | 16 | 75% | $10,511 |

*注：策略做均值回归，非追涨，buy&hold 跑赢是正常的（大牛市）。实盘跑美股开盘时段5分钟K线。*

### 其他策略（需连接 IBKR TWS 实盘验证）

| 策略 / Strategy | 预期年化 | 风险 |
|---|---|---|
| Timezone Arbitrage | ~11% | ADR 流动性风险 |
| HK IPO Pop | ~23% | 灰市数据获取 |
| Long-term Portfolio | ~14% | 市场系统性风险 |

*历史回测不代表未来收益。默认启用模拟交易（PAPER_TRADE=True）。*  
*Past performance does not guarantee future results. Paper trading enabled by default.*

---

## 快速开始 / Quick Start

```bash
git clone https://github.com/guyu-adam/ibkr-quant.git
cd ibkr-quant
pip install -r requirements.txt

# 1. 先跑回测验证策略 / Run backtest first
python main.py backtest

# 2. 开启 TWS 或 IB Gateway 后运行模拟 / Start TWS/Gateway then paper trade
python main.py live

# 3. 每月再平衡 / Monthly rebalance
python run_monthly.py
```

### IBKR 连接配置 / IBKR Connection

打开 TWS → 全局配置 → API → 设置 → 勾选"启用 ActiveX 和 Socket"

Open TWS → Global Config → API → Settings → Enable ActiveX and Socket Clients

| 模式 / Mode | 端口 / Port |
|---|---|
| TWS 模拟 / TWS Paper | 7496 |
| TWS 实盘 / TWS Live | 7497 |
| Gateway 模拟 / GW Paper | 4002 |
| Gateway 实盘 / GW Live | 4001 |

---

## 风控 / Risk Management

- 单仓上限：权益的 10%
- 总敞口上限：权益的 80%
- 日亏损熔断：-2% 自动停止交易
- 所有策略共享 `RiskManager` 模块统一管控

---

## 项目结构 / Structure

```
ibkr-quant/
├── config/settings.py      # 所有参数配置 / All parameters
├── core/
│   ├── broker.py           # IBKR 连接封装 / IBKR connection wrapper
│   ├── engine.py           # 策略调度引擎 / Strategy scheduler
│   └── risk.py             # 风控模块 / Risk manager
├── strategy/
│   ├── signals.py          # 信号生成 / Signal generation
│   ├── hk_ipo.py           # 港股 IPO 策略 / HK IPO strategy
│   ├── tz_arb.py           # 时区套利 / Timezone arbitrage
│   ├── long_term.py        # 长期组合 / Long-term portfolio
│   └── backtest.py         # 回测引擎 / Backtest engine
├── main.py                 # 入口 / Entry point
└── run_monthly.py          # 月度任务 / Monthly task
```

---

## 免责声明 / Disclaimer

本项目仅供学习和研究目的。不构成投资建议。实盘交易有损失本金的风险。

For educational and research purposes only. Not financial advice. Live trading involves risk of loss.

---

## License

MIT
