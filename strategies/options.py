"""
期权策略 v3 — VIX 择时 + IBKR 期权链 + Delta/DTE 筛选。

Strategies:
  - Covered Call: 持正股 + 卖虚值 Call，delta≈0.30，DTE≈30
  - Protective Put: 持正股 + 买虚值 Put，delta≈-0.20，DTE≈60
  - Iron Condor: 卖宽跨式 + 买保护，short delta≈0.16，DTE≈45

VIX regime gates:
  VIX < 15  → sell premium (CC, IC)
  VIX 15-25 → neutral
  VIX 25-35 → buy protection (PP)
  VIX > 35  → halt all option selling
"""

import logging
from typing import Optional
from core.strategy_base import BaseStrategy
from config.settings import OPTION_VIX_SELL, OPTION_VIX_HEDGE, OPTION_VIX_HALT

log = logging.getLogger(__name__)


def get_vix_regime(vix: float) -> str:
    """sell | hedge | halt | neutral"""
    if vix > OPTION_VIX_HALT:
        return "halt"
    if vix > OPTION_VIX_HEDGE:
        return "hedge"
    if vix < OPTION_VIX_SELL:
        return "sell"
    return "neutral"


def filter_options_by_delta(chain: list[dict], target_delta: float,
                            call_or_put: str, tolerance: float = 0.05) -> Optional[dict]:
    """Filter options chain to nearest delta match."""
    candidates = []
    for opt in chain:
        delta = abs(opt.get("delta", 0))
        if abs(delta - abs(target_delta)) <= tolerance:
            candidates.append((abs(delta - abs(target_delta)), opt))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    return candidates[0][1]


def filter_options_by_dte(chain: list[dict], target_dte: int,
                          tolerance: int = 5) -> list[dict]:
    """Filter options chain to nearest DTE."""
    result = []
    for opt in chain:
        dte = opt.get("dte", 0)
        if abs(dte - target_dte) <= tolerance:
            result.append(opt)
    return sorted(result, key=lambda o: o.get("dte", 0))


class CoveredCallStrategy(BaseStrategy):
    """Covered Call — 持正股 + 卖虚值 Call，收时间价值。

    Only sells in low-VIX (sell premium regime).
    """

    def __init__(self, config: dict | None = None):
        cfg = config or {}
        self.delta = cfg.get("delta", 0.30)
        self.dte = cfg.get("dte", 30)
        self.roll_dte = cfg.get("roll_dte", 7)
        self.min_premium = cfg.get("min_premium", 0.01)
        self._vix = 20.0

    @property
    def name(self) -> str:
        return "covered_call"

    def set_vix(self, vix: float):
        self._vix = vix

    def on_bar(self, data: dict) -> list:
        return []

    def on_close(self) -> None:
        pass

    def generate_signals(self, broker, positions: dict,
                         option_chain: list[dict]) -> list[dict]:
        """Generate covered call signals from IBKR options chain.

        Args:
            broker: IBKRBroker instance
            positions: {symbol: quantity} dict
            option_chain: list of option dicts with {symbol, strike, delta, dte,
                          last, bid, ask, option_type}

        Returns:
            list of signal dicts
        """
        regime = get_vix_regime(self._vix)
        if regime in ("halt", "hedge"):
            log.info(f"CC: VIX={self._vix:.1f} regime={regime} — skipping")
            return []

        signals = []
        for symbol, qty in positions.items():
            if qty <= 0:
                continue

            # 100 shares per contract
            contracts = qty // 100
            if contracts <= 0:
                continue

            stock_opts = [o for o in option_chain
                          if o.get("underlying") == symbol
                          and o.get("option_type") == "CALL"]
            if not stock_opts:
                continue

            # Filter by DTE and delta
            dte_filtered = filter_options_by_dte(stock_opts, self.dte)
            best = filter_options_by_delta(dte_filtered, self.delta, "CALL")
            if not best:
                continue

            premium = best.get("bid", 0)
            if premium < self.min_premium:
                continue

            signals.append({
                "signal": "sell_call",
                "underlying": symbol,
                "option_symbol": best["symbol"],
                "strike": best["strike"],
                "contracts": contracts,
                "premium": premium,
                "dte": best.get("dte"),
                "delta": best.get("delta"),
                "reason": f"CC: VIX={self._vix:.1f} delta={best.get('delta',0):.2f} DTE={best.get('dte',0)}",
            })

        return signals


class ProtectivePutStrategy(BaseStrategy):
    """Protective Put — 买虚值 Put 对冲尾部风险。

    Increases hedge ratio in high-VIX.
    """

    def __init__(self, config: dict | None = None):
        cfg = config or {}
        self.put_delta = cfg.get("put_delta", -0.20)
        self.dte = cfg.get("dte", 60)
        self.cost_pct = cfg.get("cost_pct", 0.02)
        self._vix = 20.0

    @property
    def name(self) -> str:
        return "protective_put"

    def set_vix(self, vix: float):
        self._vix = vix

    def on_bar(self, data: dict) -> list:
        return []

    def on_close(self) -> None:
        pass

    def generate_signals(self, broker, positions: dict,
                         option_chain: list[dict]) -> list[dict]:
        """Generate protective put signals."""
        regime = get_vix_regime(self._vix)

        # Dynamic hedge ratio
        if regime == "hedge":
            hedge_pct = 1.0  # full hedge in high VIX
        elif regime == "neutral":
            hedge_pct = 0.5  # partial hedge
        else:
            hedge_pct = 0.0  # no hedge in low VIX

        if hedge_pct <= 0:
            return []

        signals = []
        for symbol, qty in positions.items():
            if qty <= 0:
                continue

            contracts = int(qty // 100 * hedge_pct)
            if contracts <= 0:
                continue

            stock_opts = [o for o in option_chain
                          if o.get("underlying") == symbol
                          and o.get("option_type") == "PUT"]
            if not stock_opts:
                continue

            dte_filtered = filter_options_by_dte(stock_opts, self.dte)
            best = filter_options_by_delta(dte_filtered, self.put_delta, "PUT")
            if not best:
                continue

            signals.append({
                "signal": "buy_put",
                "underlying": symbol,
                "option_symbol": best["symbol"],
                "strike": best["strike"],
                "contracts": contracts,
                "cost": best.get("ask", 0) * contracts * 100,
                "dte": best.get("dte"),
                "delta": best.get("delta"),
                "reason": f"PP: VIX={self._vix:.1f} hedge={hedge_pct:.0%}",
            })

        return signals


class IronCondorStrategy(BaseStrategy):
    """Iron Condor — 卖宽跨式 + 买保护翼。

    Only sells in low-VIX regime.
    """

    def __init__(self, config: dict | None = None):
        cfg = config or {}
        self.short_delta = cfg.get("short_delta", 0.16)
        self.long_delta = cfg.get("long_delta", 0.05)
        self.dte = cfg.get("dte", 45)
        self.profit_pct = cfg.get("profit_pct", 0.50)
        self.stop_pct = cfg.get("stop_pct", 2.0)
        self._vix = 20.0

    @property
    def name(self) -> str:
        return "iron_condor"

    def set_vix(self, vix: float):
        self._vix = vix

    def on_bar(self, data: dict) -> list:
        return []

    def on_close(self) -> None:
        pass

    def generate_signals(self, broker, option_chain: list[dict],
                         underlyings: list[str] = None) -> list[dict]:
        """Generate Iron Condor signals.

        Sells OTM call spread + OTM put spread on index ETFs.
        """
        regime = get_vix_regime(self._vix)
        if regime in ("halt", "hedge"):
            log.info(f"IC: VIX={self._vix:.1f} regime={regime} — skipping")
            return []

        underlyings = underlyings or ["SPY", "QQQ"]
        signals = []

        for symbol in underlyings:
            price = broker.last_price(symbol)
            if price <= 0:
                continue

            calls = [o for o in option_chain
                     if o.get("underlying") == symbol
                     and o.get("option_type") == "CALL"]
            puts = [o for o in option_chain
                    if o.get("underlying") == symbol
                    and o.get("option_type") == "PUT"]

            if not calls or not puts:
                continue

            # Short legs: ~0.16 delta
            short_call = filter_options_by_delta(
                filter_options_by_dte(calls, self.dte), self.short_delta, "CALL")
            short_put = filter_options_by_delta(
                filter_options_by_dte(puts, self.dte), self.short_delta, "PUT")

            # Long legs: ~0.05 delta (wider wings)
            long_call = filter_options_by_delta(calls, self.long_delta, "CALL")
            long_put = filter_options_by_delta(puts, self.long_delta, "PUT")

            if not all([short_call, short_put, long_call, long_put]):
                continue

            credit = (short_call.get("bid", 0) + short_put.get("bid", 0)
                      - long_call.get("ask", 0) - long_put.get("ask", 0))
            max_loss = (short_call["strike"] - long_call["strike"]
                        + short_put["strike"] - long_put["strike"]) - credit

            if credit <= 0 or max_loss <= 0:
                continue

            signals.append({
                "signal": "iron_condor",
                "underlying": symbol,
                "short_call_strike": short_call["strike"],
                "long_call_strike": long_call["strike"],
                "short_put_strike": short_put["strike"],
                "long_put_strike": long_put["strike"],
                "dte": self.dte,
                "credit": round(credit, 2),
                "max_loss": round(max_loss, 2),
                "profit_target": round(credit * self.profit_pct, 2),
                "reason": f"IC: VIX={self._vix:.1f} credit={credit:.2f} max_loss={max_loss:.2f}",
            })

        return signals
