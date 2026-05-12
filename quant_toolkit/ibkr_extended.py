"""
Extended IBKR broker — builds on top of core.broker.IBKRBroker.

Adds:
  - Option chain retrieval
  - Historical implied volatility
  - Forex rates
  - Top-mover scanner
  - News headlines
"""

import pandas as pd
from ib_insync import Stock, Option, Forex, util
from datetime import datetime, timedelta

from core.broker import IBKRBroker


class IBKRBrokerExtended(IBKRBroker):
    """Extends IBKRBroker with options, IV, forex, scanner, and news."""

    # ── Option Chain ───────────────────────────────────────────────────────────
    def get_option_chain(self, symbol: str) -> pd.DataFrame:
        """Return option chain as DataFrame.

        Columns: strike, expiry, call_bid, call_ask, put_bid, put_ask, iv
        """
        try:
            if not self._connected:
                print(f"WARNING: Not connected to IBKR. Cannot fetch option chain for {symbol}.")
                return pd.DataFrame()

            contract = Stock(symbol, "SMART", "USD")
            self.ib.qualifyContracts(contract)

            chains = self.ib.reqSecDefOptParams(
                symbol, "", contract.secType, contract.conId
            )
            if not chains:
                print(f"WARNING: No option chain data for {symbol}.")
                return pd.DataFrame()

            chain = chains[0]
            expiry = chain.expirations[0]

            rows = []
            for strike in chain.strikes:
                call_opt = Option(symbol, expiry, strike, "C", "SMART", currency="USD")
                put_opt = Option(symbol, expiry, strike, "P", "SMART", currency="USD")
                self.ib.qualifyContracts(call_opt, put_opt)

                try:
                    call_ticker = self.ib.reqMktData(call_opt, "", True, False)
                    put_ticker = self.ib.reqMktData(put_opt, "", True, False)
                    self.ib.sleep(0.01)

                    iv = None
                    if call_ticker.modelGreeks and call_ticker.modelGreeks.impliedVol is not None:
                        iv = call_ticker.modelGreeks.impliedVol
                    elif put_ticker.modelGreeks and put_ticker.modelGreeks.impliedVol is not None:
                        iv = put_ticker.modelGreeks.impliedVol

                    rows.append({
                        "strike":   strike,
                        "expiry":   expiry,
                        "call_bid": call_ticker.bid if call_ticker.bid != -1 else None,
                        "call_ask": call_ticker.ask if call_ticker.ask != -1 else None,
                        "put_bid":  put_ticker.bid if put_ticker.bid != -1 else None,
                        "put_ask":  put_ticker.ask if put_ticker.ask != -1 else None,
                        "iv":       iv,
                    })
                except Exception:
                    continue

            return pd.DataFrame(rows)

        except Exception as e:
            print(f"WARNING: Failed to get option chain for {symbol}: {e}")
            return pd.DataFrame()

    # ── Historical Implied Volatility ────────────────────────────────────────
    def get_historical_iv(self, symbol: str, days: int = 30) -> pd.Series:
        """Return historical implied volatility series for *symbol* over past *days*.

        Uses IBKR's OPTION_IMPLIED_VOLATILITY bar type (generic tick 24).
        Returns a Series indexed by date.
        """
        try:
            if not self._connected:
                print(f"WARNING: Not connected to IBKR. Cannot fetch historical IV for {symbol}.")
                return pd.Series(dtype=float)

            contract = Stock(symbol, "SMART", "USD")
            self.ib.qualifyContracts(contract)
            bars = self.ib.reqHistoricalData(
                contract,
                endDateTime="",
                durationStr=f"{days} D",
                barSizeSetting="1 day",
                whatToShow="OPTION_IMPLIED_VOLATILITY",
                useRTH=True,
                formatDate=1,
            )
            if not bars:
                print(f"WARNING: No historical IV data for {symbol}.")
                return pd.Series(dtype=float)

            df = util.df(bars)
            iv_series = df.set_index("date")["close"]
            iv_series.name = f"{symbol}_IV"
            return iv_series

        except Exception as e:
            print(f"WARNING: Failed to get historical IV for {symbol}: {e}")
            return pd.Series(dtype=float)

    # ── Forex ────────────────────────────────────────────────────────────────
    def get_forex_rate(self, pair: str = "EURUSD") -> float:
        """Return the current forex rate for *pair*, e.g. 'EURUSD'."""
        try:
            if not self._connected:
                print(f"WARNING: Not connected to IBKR. Cannot fetch forex rate for {pair}.")
                return 0.0

            base = pair[:3]
            quote = pair[3:]
            fx = Forex(pair, base + ".PRO", quote + ".PRO")
            self.ib.qualifyContracts(fx)
            ticker = self.ib.reqMktData(fx, "", True, False)
            self.ib.sleep(0.1)
            return ticker.last or ticker.close or 0.0

        except Exception as e:
            print(f"WARNING: Failed to get forex rate for {pair}: {e}")
            return 0.0

    # ── Scanner — Top Movers ─────────────────────────────────────────────────
    def scanner_top_movers(self, n: int = 20) -> pd.DataFrame:
        """Return top *n* movers by price-change percentage.

        Returns DataFrame with columns: symbol, change_pct, volume, last_price
        """
        try:
            if not self._connected:
                print("WARNING: Not connected to IBKR. Cannot run scanner.")
                return pd.DataFrame()

            scan_sub = self.ib.reqScannerSubscription()
            scan_sub.scanCode = "HOT_BY_PRICE_VOLUME"
            scan_sub.numberOfRows = n

            results = []

            def on_data(_sub, items):
                for item in items:
                    c = item.contractDetails.contract
                    results.append({
                        "symbol":     c.symbol,
                        "change_pct": item.contractDetails.priceChangePercent,
                        "volume":     item.contractDetails.volume,
                        "last_price": item.contractDetails.lastPrice,
                    })

            self.ib.scannerDataEvent += on_data
            self.ib.reqScannerSubscription(scan_sub)
            self.ib.sleep(3)
            self.ib.scannerDataEvent -= on_data
            self.ib.cancelScannerSubscription(scan_sub)

            return pd.DataFrame(results).head(n)

        except Exception as e:
            print(f"WARNING: Failed to run scanner: {e}")
            return pd.DataFrame()

    # ── News ─────────────────────────────────────────────────────────────────
    def get_news(self, symbol: str, max_items: int = 5) -> list:
        """Return latest news headlines for *symbol*.

        Returns list of dicts: [{headline, time, source}, ...]
        """
        try:
            if not self._connected:
                print(f"WARNING: Not connected to IBKR. Cannot fetch news for {symbol}.")
                return []

            contract = Stock(symbol, "SMART", "USD")
            self.ib.qualifyContracts(contract)

            providers = self.ib.reqNewsProviders()
            if not providers:
                print(f"WARNING: No news providers available.")
                return []

            provider_codes = "+".join([p.code for p in providers[:3]])

            end = datetime.now()
            start = end - timedelta(days=7)

            news_items = self.ib.reqHistoricalNews(
                contract.conId,
                provider_codes,
                start.strftime("%Y-%m-%d %H:%M:%S"),
                end.strftime("%Y-%m-%d %H:%M:%S"),
                max_items,
            )

            result = []
            for item in news_items[:max_items]:
                result.append({
                    "headline": item.headline,
                    "time":     item.time,
                    "source":   item.providerCode,
                })
            return result

        except Exception as e:
            print(f"WARNING: Failed to get news for {symbol}: {e}")
            return []
