"""
统一数据源抽象层 — 屏蔽 yfinance / IBKR / Tencent / 本地缓存 的差异

所有策略通过此接口获取数据，不直接依赖具体数据源。
"""

from abc import ABC, abstractmethod
import pandas as pd


class DataFeed(ABC):
    """数据源抽象基类"""

    @abstractmethod
    def name(self) -> str:
        """数据源标识"""
        ...

    @abstractmethod
    def fetch_history(self, symbol: str, period: str = "6mo",
                      interval: str = "1d") -> pd.DataFrame | None:
        """
        拉取历史K线数据。

        Returns:
            DataFrame with columns: open, high, low, close, volume
            或 None 表示数据不可用
        """
        ...

    @abstractmethod
    def fetch_realtime(self, symbols: list[str]) -> dict[str, float]:
        """
        拉取实时价格。

        Returns:
            {symbol: price} 映射
        """
        ...

    @abstractmethod
    def is_connected(self) -> bool:
        """数据源是否可达"""
        ...


class YFinanceFeed(DataFeed):
    """基于 yfinance 的免费数据源（支持美股 + A股）"""

    def __init__(self):
        self._connected = True

    def name(self) -> str:
        return "yfinance"

    def is_connected(self) -> bool:
        return self._connected

    def fetch_history(self, symbol: str, period: str = "6mo",
                      interval: str = "1d") -> pd.DataFrame | None:
        import yfinance as yf
        try:
            df = yf.download(symbol, period=period, interval=interval,
                             progress=False, auto_adjust=True)
            if df is None or df.empty or len(df) < 20:
                return None
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.droplevel(1)
            # Normalize column names to lowercase
            df = df.rename(columns={
                'Open': 'open', 'High': 'high', 'Low': 'low',
                'Close': 'close', 'Volume': 'volume',
            })
            return df[['open', 'high', 'low', 'close', 'volume']]
        except Exception:
            return None

    def fetch_realtime(self, symbols: list[str]) -> dict[str, float]:
        """yfinance 实时价格有15分钟延迟"""
        import yfinance as yf
        result = {}
        for sym in symbols:
            try:
                info = yf.Ticker(sym).fast_info
                px = info.last_price or info.previous_close
                if px:
                    result[sym] = float(px)
            except Exception:
                continue
        return result


class TencentFeed(DataFeed):
    """基于腾讯财经的 A 股实时行情（无延迟，仅限 A 股）"""

    BASE_URL = "https://qt.gtimg.cn/q="

    def __init__(self, disable_proxy: bool = False):
        import requests as _r
        self._requests = _r
        self._connected = True
        self._proxies = {'http': None, 'https': None} if disable_proxy else None
        self._prefix_cache: dict[str, str] = {}

    def name(self) -> str:
        return "tencent"

    def is_connected(self) -> bool:
        return self._connected

    def _to_tencent_code(self, symbol: str) -> str:
        """000001 → sz000001, 600519 → sh600519"""
        if symbol in self._prefix_cache:
            return self._prefix_cache[symbol]
        prefix = 'sh' if symbol.startswith('6') else 'sz'
        code = f"{prefix}{symbol}"
        self._prefix_cache[symbol] = code
        return code

    def fetch_realtime(self, symbols: list[str]) -> dict[str, float]:
        codes = ','.join(self._to_tencent_code(s) for s in symbols)
        try:
            r = self._requests.get(
                self.BASE_URL + codes,
                headers={'Referer': 'https://gu.qq.com'},
                timeout=8, proxies=self._proxies,
            )
            r.encoding = 'gbk'
            result = {}
            for line in r.text.splitlines():
                if '~' not in line:
                    continue
                parts = line.split('"')[1].split('~') if '"' in line else []
                if len(parts) < 5:
                    continue
                code = parts[2]
                price = float(parts[3]) if parts[3] else 0.0
                if price > 0 and code in symbols:
                    result[code] = price
            return result
        except Exception:
            return {}

    def fetch_history(self, symbol: str, period: str = "6mo",
                      interval: str = "1d") -> pd.DataFrame | None:
        """腾讯不提供历史数据，委托给 yfinance"""
        return YFinanceFeed().fetch_history(symbol, period, interval)


class CachedFeed(DataFeed):
    """
    带缓存的数据源装饰器 — 减少重复网络请求
    """

    def __init__(self, backend: DataFeed, ttl_seconds: int = 300):
        import time as _time
        self._backend = backend
        self._ttl = ttl_seconds
        self._time = _time
        self._cache: dict[str, tuple[float, pd.DataFrame | None]] = {}

    def name(self) -> str:
        return f"cached({self._backend.name()})"

    def is_connected(self) -> bool:
        return self._backend.is_connected()

    def fetch_history(self, symbol: str, period: str = "6mo",
                      interval: str = "1d") -> pd.DataFrame | None:
        key = f"{symbol}:{period}:{interval}"
        now = self._time.time()
        entry = self._cache.get(key)
        if entry and (now - entry[0]) < self._ttl:
            return entry[1]
        df = self._backend.fetch_history(symbol, period, interval)
        self._cache[key] = (now, df)
        return df

    def fetch_realtime(self, symbols: list[str]) -> dict[str, float]:
        return self._backend.fetch_realtime(symbols)

    def invalidate(self, symbol: str | None = None):
        """清除缓存"""
        if symbol:
            keys = [k for k in self._cache if k.startswith(symbol + ':')]
            for k in keys:
                del self._cache[k]
        else:
            self._cache.clear()
