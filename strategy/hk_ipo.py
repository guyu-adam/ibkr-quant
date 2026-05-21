"""
HK IPO First-Day Pop Strategy
─────────────────────────────
Logic:
  1. Scrape HKEX listing calendar for stocks debuting today
  2. Fetch grey-market premium from AASTOCKS (or fallback to IPOboss)
  3. If grey premium >= threshold → buy at market open, set target + stop
  4. Exit at EOD regardless (HK IPOs are often volatile after first hour)

IBKR contract: Stock(code, "SEHK", "HKD")  e.g. "9988" for BabaHK
"""

import re
import logging
from datetime import date, datetime
from typing import Optional

import requests
from bs4 import BeautifulSoup
from ib_insync import Stock

log = logging.getLogger(__name__)

HKEX_CALENDAR_URL = "https://www.hkex.com.hk/eng/market/sec_tradinfo/stockcode/eisdeqty_mem.htm"
AASTOCKS_IPO_URL  = "https://www.aastocks.com/en/stocks/market/ipo/mainboard.aspx"
IPOBOSS_URL       = "https://www.ipoboss.hk/en/greymarket"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 Chrome/124 Safari/537.36"
    )
}

# ── data fetch ────────────────────────────────────────────────────────────────

def fetch_listing_today() -> list[dict]:
    """
    Returns list of stocks listing on HKEX today.
    Format: [{"code": "9988", "name": "...", "ipo_price": 68.0}]
    Scrapes HKEX 'New Listing' page; falls back to empty list on failure.
    """
    try:
        r = requests.get(AASTOCKS_IPO_URL, headers=HEADERS, timeout=10)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")
        today = date.today().strftime("%d/%m/%Y")
        listings = []
        for row in soup.select("table.data-table tr"):
            cells = [c.get_text(strip=True) for c in row.find_all("td")]
            if len(cells) >= 5 and today in cells[3]:  # listing date column
                try:
                    code      = re.sub(r"\D", "", cells[0]).zfill(4)
                    name      = cells[1]
                    ipo_price = float(re.sub(r"[^\d.]", "", cells[2]) or 0)
                    listings.append({"code": code, "name": name, "ipo_price": ipo_price})
                except (ValueError, IndexError):
                    continue
        return listings
    except Exception as e:
        log.warning(f"AASTOCKS IPO fetch failed: {e}")
        return []


def fetch_grey_premium(code: str) -> Optional[float]:
    """
    Returns grey-market implied premium (e.g. 0.25 = 25% above IPO price).
    Scrapes ipoboss.hk; returns None on failure.
    """
    try:
        r = requests.get(IPOBOSS_URL, headers=HEADERS, timeout=10)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")
        for row in soup.select("tr"):
            cells = [c.get_text(strip=True) for c in row.find_all("td")]
            if len(cells) >= 4:
                row_code = re.sub(r"\D", "", cells[0]).zfill(4)
                if row_code == code:
                    premium_text = re.sub(r"[^\d.\-]", "", cells[3])
                    if premium_text:
                        pct = float(premium_text)
                        return pct / 100.0
        return None
    except Exception as e:
        log.debug(f"Grey market fetch failed for {code}: {e}")
        return None


# ── IBKR helpers ──────────────────────────────────────────────────────────────

def hk_contract(broker, code: str):
    """Qualify and return a SEHK Stock contract."""
    c = Stock(code, "SEHK", "HKD")
    broker.ib.qualifyContracts(c)
    return c


def place_ipo_trade(broker, risk_mgr, code: str, ipo_price: float,
                    grey_premium: float, cfg: dict) -> Optional[object]:
    """
    Buy at market open, set OCA bracket (profit target + stop loss).
    Returns trade object or None if risk check fails.
    """
    if grey_premium < cfg["min_grey_premium"]:
        log.info(f"[IPO] {code}: grey premium {grey_premium:.1%} < threshold, skip")
        return None

    contract = hk_contract(broker, code)
    equity   = broker.net_liquidation()
    # position size: risk_pct of equity, stop at IPO price
    stop_px   = ipo_price * (1 - cfg["stop_pct"])
    target_px = ipo_price * (1 + grey_premium * cfg["target_pct_of_premium"])
    risk_per_share = ipo_price - stop_px
    if risk_per_share <= 0:
        return None

    max_risk = equity * cfg["max_risk_per_trade"]
    # HKD → USD rough conversion (10 USD ≈ 78 HKD as rough factor)
    hkd_risk  = max_risk * 7.8
    shares    = int(hkd_risk / risk_per_share / 100) * 100  # round to board lot

    if shares <= 0:
        log.info(f"[IPO] {code}: calculated 0 shares, skip")
        return None

    if not risk_mgr.approve(code, shares, ipo_price):
        return None

    log.info(f"[IPO] BUY {code}  shares={shares}  ipo={ipo_price:.2f}  "
             f"target={target_px:.2f}  stop={stop_px:.2f}  grey={grey_premium:.1%}")

    trade = _bracket_order(
        broker.ib, contract, "BUY", shares, ipo_price, target_px, stop_px
    )
    return trade


def _bracket_order(ib, contract, action, qty, entry, target, stop):
    """
    Standard bracket order: parent → take_profit + stop_loss (OCA group).

    Uses transmit flags so all three orders are submitted atomically:
      1. Parent (transmit=False) — held at IBKR
      2. Take-profit child (transmit=False) — held
      3. Stop-loss child (transmit=True)  — activates the bracket
    """
    from ib_insync import MarketOrder, LimitOrder, StopOrder

    oca_group = f"IPO_{qty}_{int(entry * 100)}"

    # Parent entry order
    parent = MarketOrder(action, qty)
    parent.transmit = False
    parent.ocaGroup = oca_group
    parent.ocaType = 1

    trade_parent = ib.placeOrder(contract, parent)

    # Take-profit (opposite action to exit)
    exit_action = "SELL" if action == "BUY" else "BUY"
    take_profit = LimitOrder(exit_action, qty, round(target, 3))
    take_profit.parentId = trade_parent.order.orderId
    take_profit.transmit = False
    take_profit.ocaGroup = oca_group
    take_profit.ocaType = 1

    trade_tp = ib.placeOrder(contract, take_profit)

    # Stop-loss (last child with transmit=True activates the whole bracket)
    stop_loss = StopOrder(exit_action, qty, round(stop, 3))
    stop_loss.parentId = trade_parent.order.orderId
    stop_loss.transmit = True
    stop_loss.ocaGroup = oca_group
    stop_loss.ocaType = 1

    trade_sl = ib.placeOrder(contract, stop_loss)
    return trade_parent


# ── strategy runner ───────────────────────────────────────────────────────────

class HKIPOStrategy:
    """
    Called once at HK market open (09:30 HKT).
    Scans today's listings and trades those with strong grey-market premiums.
    """

    DEFAULT_CFG = {
        "min_grey_premium":          0.15,   # minimum 15% grey premium to trade
        "stop_pct":                  0.05,   # stop 5% below IPO price
        "target_pct_of_premium":     0.60,   # target = 60% of grey premium
        "max_risk_per_trade":        0.015,  # risk 1.5% of USD equity per trade
        "max_concurrent_positions":  2,
    }

    def __init__(self, broker, risk_mgr, cfg: dict = None):
        self.broker   = broker
        self.risk_mgr = risk_mgr
        self.cfg      = {**self.DEFAULT_CFG, **(cfg or {})}
        self._active  = {}  # code → trade

    def run(self):
        listings = fetch_listing_today()
        if not listings:
            log.info("[IPO] No HK listings today")
            return

        for item in listings:
            if len(self._active) >= self.cfg["max_concurrent_positions"]:
                break
            code      = item["code"]
            ipo_price = item["ipo_price"]
            if ipo_price <= 0:
                continue

            grey = fetch_grey_premium(code)
            if grey is None:
                log.info(f"[IPO] {code}: no grey market data")
                continue

            trade = place_ipo_trade(
                self.broker, self.risk_mgr, code, ipo_price, grey, self.cfg
            )
            if trade:
                self._active[code] = trade

    def close_all(self):
        """Force-close all IPO positions at EOD."""
        for code in list(self._active):
            try:
                pos = self.broker.positions().get(code, 0)
                if pos > 0:
                    self.broker.market_order(code, pos, "SELL")
                    log.info(f"[IPO] EOD close {code}  shares={pos}")
            except Exception as e:
                log.error(f"[IPO] EOD close {code} failed: {e}")
        self._active.clear()
