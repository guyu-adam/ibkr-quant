"""纸上交易核心引擎"""

import os
import threading
import datetime
import time
import logging
import requests as _requests

logger = logging.getLogger(__name__)

SYMBOLS = ['000001', '600519', '300750', '000858', '601318']
SYMBOL_NAMES = {
    '000001': '平安银行', '600519': '贵州茅台', '300750': '宁德时代',
    '000858': '五粮液', '601318': '中国平安',
}


class PaperTradingEngine:
    def __init__(self, initial_cash=10000.0):
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.positions = {}       # {symbol: {shares, avg_cost, stop_loss}}
        self.trades = []          # [{time, symbol, action, shares, price, amount}]
        self.latest_prices = {}   # {symbol: price}
        self.quote_time = None
        self.lock = threading.RLock()
        self.running = False
        self.max_positions = 5

    # ── 行情更新（腾讯财经接口，直连，绕过代理）──────────────
    def update_quotes(self):
        try:
            prefix_map = {
                '000001': 'sz', '600519': 'sh', '300750': 'sz',
                '000858': 'sz', '601318': 'sh',
            }
            codes = ','.join(f"{prefix_map[s]}{s}" for s in SYMBOLS)
            r = _requests.get(
                f'https://qt.gtimg.cn/q={codes}',
                headers={'Referer': 'https://gu.qq.com'},
                timeout=8, proxies={'http': None, 'https': None}
            )
            r.encoding = 'gbk'
            updated = 0
            for line in r.text.splitlines():
                if '~' not in line:
                    continue
                parts = line.split('"')[1].split('~') if '"' in line else []
                if len(parts) < 5:
                    continue
                code = parts[2]
                price = float(parts[3]) if parts[3] else 0.0
                if code in SYMBOLS and price > 0:
                    with self.lock:
                        self.latest_prices[code] = price
                    updated += 1
            if updated:
                self.quote_time = datetime.datetime.now().strftime('%H:%M:%S')
                logger.info(f"行情更新完成 {self.quote_time} ({updated}只)")
            else:
                logger.warning("行情数据为空（非交易时段）")
        except Exception as e:
            logger.error(f"行情更新失败: {e}")

    # ── 资产计算 ──────────────────────────────────────────────
    def total_value(self):
        with self.lock:
            val = self.cash
            for sym, pos in self.positions.items():
                px = self.latest_prices.get(sym, pos['avg_cost'])
                val += pos['shares'] * px
            return round(val, 2)

    def total_pnl(self):
        return round(self.total_value() - self.initial_cash, 2)

    def daily_pnl(self):
        return self.total_pnl()  # simplified: same as total since start

    def daily_return_pct(self):
        if self.initial_cash == 0:
            return 0
        return round((self.total_value() - self.initial_cash) / self.initial_cash * 100, 2)

    def unrealized_pnl(self, symbol):
        with self.lock:
            if symbol not in self.positions:
                return 0.0
            pos = self.positions[symbol]
            px = self.latest_prices.get(symbol, pos['avg_cost'])
            return round((px - pos['avg_cost']) * pos['shares'], 2)

    # ── 交易执行 ──────────────────────────────────────────────
    def buy(self, symbol, amount):
        """用 amount 元买入 symbol，返回 trade 或 None"""
        with self.lock:
            price = self.latest_prices.get(symbol)
            if not price or price <= 0:
                return None
            if amount > self.cash:
                amount = self.cash
            lots = int(amount / (price * 100))
            if lots == 0:
                return None
            shares = lots * 100
            cost = shares * price
            self.cash -= cost

            if symbol in self.positions:
                pos = self.positions[symbol]
                total_s = pos['shares'] + shares
                pos['avg_cost'] = round((pos['avg_cost'] * pos['shares'] + cost) / total_s, 4)
                pos['shares'] = total_s
            else:
                self.positions[symbol] = {
                    'shares': shares,
                    'avg_cost': price,
                    'stop_loss': round(price * 0.95, 2),
                }

            trade = {
                'time': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'symbol': symbol,
                'name': SYMBOL_NAMES.get(symbol, ''),
                'action': 'BUY',
                'shares': shares,
                'price': price,
                'amount': round(cost, 2),
            }
            self.trades.append(trade)
            logger.info(f"BUY  {symbol} {shares}股 @{price}  金额{cost:.2f}")
            return trade

    def sell(self, symbol, shares=None):
        with self.lock:
            if symbol not in self.positions:
                return None
            pos = self.positions[symbol]
            price = self.latest_prices.get(symbol, pos['avg_cost'])
            if shares is None:
                shares = pos['shares']
            shares = min(shares, pos['shares'])
            if shares == 0:
                return None
            revenue = shares * price
            self.cash += revenue
            pos['shares'] -= shares
            if pos['shares'] == 0:
                del self.positions[symbol]

            trade = {
                'time': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'symbol': symbol,
                'name': SYMBOL_NAMES.get(symbol, ''),
                'action': 'SELL',
                'shares': shares,
                'price': price,
                'amount': round(revenue, 2),
            }
            self.trades.append(trade)
            logger.info(f"SELL {symbol} {shares}股 @{price}  金额{revenue:.2f}")
            return trade

    # ── 状态快照 ──────────────────────────────────────────────
    def snapshot(self):
        with self.lock:
            positions = []
            for sym, pos in self.positions.items():
                px = self.latest_prices.get(sym, pos['avg_cost'])
                pnl = round((px - pos['avg_cost']) * pos['shares'], 2)
                pnl_pct = round((px - pos['avg_cost']) / pos['avg_cost'] * 100, 2)
                positions.append({
                    'symbol': sym,
                    'name': SYMBOL_NAMES.get(sym, ''),
                    'shares': pos['shares'],
                    'avg_cost': pos['avg_cost'],
                    'price': px,
                    'pnl': pnl,
                    'pnl_pct': pnl_pct,
                    'stop_loss': pos['stop_loss'],
                })
            return {
                'cash': round(self.cash, 2),
                'total_value': self.total_value(),
                'pnl': self.total_pnl(),
                'pnl_pct': self.daily_return_pct(),
                'positions': positions,
                'quote_time': self.quote_time or '--',
                'trade_count': len(self.trades),
            }
