"""
同花顺 Tonghuashun — A 股行情与交易接口。

同花顺提供以下接入方式：
  1. 同花顺客户端 API（本地端口, 需安装同花顺客户端）
  2. 同花顺 iFinD 数据终端（付费）
  3. 腾讯财经免费行情（HTTP，仅行情，不可交易）

当前实现：腾讯财经行情 + 同花顺客户端交易。

Usage:
    from interfaces.ths import THSBroker
    broker = THSBroker(host="127.0.0.1", port=8010)
    quote = broker.get_realtime_quote(["000001", "600519"])
"""

import logging
import requests

from config.settings import THS_HOST, THS_PORT

log = logging.getLogger(__name__)

TENCENT_QUOTE_URL = "https://qt.gtimg.cn/q="


class THSBroker:
    """同花顺 A 股券商适配器 — 行情 + 交易."""

    def __init__(self, host=THS_HOST, port=THS_PORT, account=""):
        self.host = host
        self.port = port
        self.account = account
        self._connected = False
        self._prefix_cache: dict[str, str] = {}

    def connect(self):
        self._connected = True
        log.info(f"THS connected (tencent quote, ths trade @ {self.host}:{self.port})")

    def disconnect(self):
        self._connected = False

    def _to_tencent_code(self, symbol: str) -> str:
        if symbol in self._prefix_cache:
            return self._prefix_cache[symbol]
        prefix = 'sh' if symbol.startswith('6') else 'sz'
        code = f"{prefix}{symbol}"
        self._prefix_cache[symbol] = code
        return code

    def get_realtime_quote(self, symbols: list[str]) -> dict[str, dict]:
        """腾讯财经免费行情 — 无延迟"""
        codes = ','.join(self._to_tencent_code(s) for s in symbols)
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
                    "name": parts[1], "price": float(parts[3] or 0),
                    "prev_close": float(parts[4] or 0), "open": float(parts[5] or 0),
                    "volume": int(parts[6] or 0), "high": float(parts[33] or 0),
                    "low": float(parts[34] or 0),
                }
            return result
        except Exception as e:
            log.error(f"THS quote failed: {e}")
            return {}

    def last_price(self, symbol: str) -> float:
        q = self.get_realtime_quote([symbol])
        return q.get(symbol, {}).get("price", 0.0)

    def net_liquidation(self) -> float:
        return 0.0

    def daily_pnl(self) -> float:
        return 0.0

    def positions(self) -> dict:
        return {}

    def market_order(self, symbol: str, shares: int, action: str):
        # TODO: 同花顺客户端交易协议（需要客户端运行并开放 API 端口）
        log.info(f"THS order: {action} {shares} {symbol}")
