"""
同花顺 / 东方财富 — A 股行情与交易接口 v2。

数据源：
  1. 腾讯财经免费行情（无延迟）
  2. 东方财富 HTTP API（免费，实时，推荐）
  3. 同花顺客户端交易协议（需客户端运行 + API 端口开放）

Usage:
    from interfaces.ths import THSBroker
    broker = THSBroker()
    broker.connect()
    quotes = broker.get_realtime_quote(["000001", "600519"])
"""

import logging
import requests

from core.broker_interface import BrokerInterface
from config.settings import THS_HOST, THS_PORT

log = logging.getLogger(__name__)

TENCENT_QUOTE_URL = "https://qt.gtimg.cn/q="
EASTMONEY_URL = "https://push2.eastmoney.com/api/qt/stock/get"


def _to_tencent_code(symbol: str) -> str:
    prefix = 'sh' if symbol.startswith('6') else 'sz'
    return f"{prefix}{symbol}"


def _to_eastmoney_code(symbol: str) -> str:
    """000001 → 1.000001, 600519 → 1.600519"""
    market = 1 if symbol.startswith('6') else 0
    return f"{market}.{symbol}"


class THSBroker(BrokerInterface):
    """A 股券商适配器 — 行情 (腾讯/东方财富) + 交易 (同花顺客户端)."""

    def __init__(self, host=THS_HOST, port=THS_PORT, account=""):
        self.host = host
        self.port = port
        self.account = account
        self._connected = False
        self._prefix_cache: dict[str, str] = {}

    def connect(self):
        self._connected = True
        log.info(f"THS connected (tencent + eastmoney quote, ths trade @ {self.host}:{self.port})")

    def disconnect(self):
        self._connected = False

    def get_realtime_quote(self, symbols: list[str], source: str = "eastmoney") -> dict:
        """Get real-time quotes. source: 'tencent' | 'eastmoney'."""
        if source == "eastmoney":
            return self._eastmoney_quote(symbols)
        return self._tencent_quote(symbols)

    def _tencent_quote(self, symbols: list[str]) -> dict:
        """腾讯财经免费行情."""
        codes = ','.join(_to_tencent_code(s) for s in symbols)
        try:
            r = requests.get(
                TENCENT_QUOTE_URL + codes,
                headers={'Referer': 'https://gu.qq.com'},
                timeout=8,
            )
            r.encoding = 'gbk'
            result = {}
            for line in r.text.splitlines():
                if '~' not in line or '"' not in line:
                    continue
                parts = line.split('"')[1].split('~')
                if len(parts) < 40:
                    continue
                result[parts[2]] = {
                    "name": parts[1],
                    "price": float(parts[3] or 0),
                    "prev_close": float(parts[4] or 0),
                    "open": float(parts[5] or 0),
                    "volume": int(parts[6] or 0),
                    "high": float(parts[33] or 0),
                    "low": float(parts[34] or 0),
                }
            return result
        except Exception as e:
            log.error(f"Tencent quote failed: {e}")
            return {}

    def _eastmoney_quote(self, symbols: list[str]) -> dict:
        """东方财富免费实时行情."""
        result = {}
        for sym in symbols:
            try:
                secid = _to_eastmoney_code(sym)
                resp = requests.get(
                    EASTMONEY_URL,
                    params={
                        "secid": secid,
                        "fields": "f43,f44,f45,f46,f47,f48,f57,f58,f170",
                        "ut": "fa5fd1943c7b386f172d6893dbbd4b1a",
                    },
                    headers={"Referer": "https://quote.eastmoney.com/"},
                    timeout=5,
                )
                data = resp.json().get("data", {})
                if data:
                    result[sym] = {
                        "price": data.get("f43", 0) / 100 if data.get("f43") else 0,
                        "high": data.get("f44", 0) / 100 if data.get("f44") else 0,
                        "low": data.get("f45", 0) / 100 if data.get("f45") else 0,
                        "open": data.get("f46", 0) / 100 if data.get("f46") else 0,
                        "volume": data.get("f47", 0),
                        "amount": data.get("f48", 0),
                        "prev_close": data.get("f170", 0) / 100 if data.get("f170") else 0,
                        "name": data.get("f58", ""),
                    }
            except Exception as e:
                log.error(f"EastMoney quote {sym}: {e}")
        return result

    def last_price(self, symbol: str) -> float:
        q = self.get_realtime_quote([symbol])
        return q.get(symbol, {}).get("price", 0.0)

    def net_liquidation(self) -> float:
        return 0.0

    def daily_pnl(self) -> float:
        return 0.0

    def positions(self) -> dict[str, float]:
        return {}

    def market_order(self, symbol: str, shares: int, action: str):
        """同花顺客户端交易 — 需要客户端运行并开放 API 端口."""
        try:
            # Protocol: simple socket-based, depends on THS client version
            import socket
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(5)
            s.connect((self.host, self.port))
            # THS order format (simplified)
            msg = f"{self.account}|{action}|{symbol}|{shares}|0"
            s.send(msg.encode("gbk"))
            resp = s.recv(1024)
            s.close()
            log.info(f"THS {action} {shares} {symbol}: {resp.decode('gbk', errors='ignore')}")
        except Exception as e:
            log.warning(f"THS order failed (is THS client running?): {e}")
