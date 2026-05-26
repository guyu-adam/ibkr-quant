# quant

**多市场量化交易系统 — 覆盖美股、港股、加密货币、A 股**

Multi-market quantitative trading system: US stocks, HK stocks, crypto, A-shares.

---

## 项目结构

```
quant/
├── README.md
├── main.py                     # 统一入口
├── requirements.txt
├── config/
│   └── settings.py             # 全局配置
├── strategies/                 # 量化算法
│   ├── contracts.py            # 合约策略（永续合约网格震荡）
│   ├── options.py              # 期权策略（备兑/保护性看跌/铁鹰）
│   ├── leverage.py             # 杠杆策略（杠杆ETF/保证金多空配对）
│   ├── fast_trading.py         # 快速交易（美股日内动量/RSI均值回归）
│   ├── slow_trading.py         # 慢速交易（港股IPO打新/ADR时区套利）
│   └── long_term.py            # 长期策略（组合管理/再平衡/定投）
├── interfaces/                 # 对外接口
│   ├── ibkr.py                 # Interactive Brokers
│   ├── okx.py                  # OKX 欧易
│   ├── schwab.py               # Charles Schwab 嘉信
│   ├── ths.py                  # 同花顺（A股行情+交易）
│   └── binance.py              # Binance 币安
├── paper_trading/              # 模拟盘
│   ├── engine.py
│   └── app.py                  # Flask Web 仪表盘
├── core/                       # 共用核心
│   ├── strategy_base.py        # 策略抽象基类
│   ├── risk.py                 # 风控模块
│   ├── data_feed.py            # 数据源抽象（yfinance/腾讯/缓存）
│   ├── engine.py               # 交易引擎
│   ├── ml_model.py             # ML 模型（LightGBM收益预测）
│   ├── alpha_factors.py        # Alpha 因子库
│   ├── portfolio_optimizer.py  # 组合优化器
│   └── analytics.py            # 量化分析工具
└── tests/                      # 测试
```

---

## 策略矩阵

| 策略 | 类型 | 市场 | 频率 | 接口 |
|------|------|------|------|------|
| 美股日内动量 | 快速交易 | US | 5分钟 | IBKR |
| 合约网格震荡 | 合约 | Crypto | 实时 | OKX / Binance |
| 保证金多空配对 | 杠杆 | US | 日频 | IBKR |
| 杠杆ETF趋势 | 杠杆 | US | 日频 | IBKR / Schwab |
| 期权备兑/铁鹰 | 期权 | US | 周频 | IBKR |
| 港股IPO打新 | 慢速交易 | HK | 事件驱动 | IBKR |
| ADR时区套利 | 慢速交易 | US→HK | 每日 | IBKR |
| 长期组合管理 | 长期 | US | 月度 | IBKR / Schwab |

---

## 快速开始

```bash
git clone git@github.com:guyu-adam/quant.git
cd quant
pip install -r requirements.txt

# 回测
python main.py --backtest

# 账户状态 + 信号扫描
python main.py --status

# 长期组合再平衡
python main.py --rebalance

# 模拟盘 Web 仪表盘
python main.py --paper
```

---

## 风控

- 单仓上限：权益的 10%
- 总敞口上限：权益的 80%
- 日亏损熔断：-2% 自动停止交易
- 波动率自适应仓位（ATR-based sizing）
- 所有策略共享 `RiskManager` 统一管控

---

## 免责声明

本项目仅供学习和研究目的。不构成投资建议。实盘交易有损失本金的风险。

For educational and research purposes only. Not financial advice.

---

## License

MIT
