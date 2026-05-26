"""
嘉信 Charles Schwab v2 — OAuth 2.0 完整实现。

Setup:
  1. Register app at https://developer.schwab.com
  2. Set callback URL to https://127.0.0.1:8080
  3. Copy .env.example to .env and fill SCHWAB_API_KEY / SCHWAB_SECRET

OAuth flow:
  1. broker.connect() opens browser for authorization
  2. User authorizes → redirect to callback → exchange code for token
  3. Token auto-refreshes
"""

import logging
import time
import json
import os
import webbrowser
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler

from core.broker_interface import BrokerInterface
from config.settings import SCHWAB_API_KEY, SCHWAB_SECRET, SCHWAB_CALLBACK

log = logging.getLogger(__name__)

AUTH_URL = "https://api.schwabapi.com/v1/oauth/authorize"
TOKEN_URL = "https://api.schwabapi.com/v1/oauth/token"
API_BASE = "https://api.schwabapi.com/trader/v1"
TOKEN_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".schwab_token.json")

_auth_code = None


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global _auth_code
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        _auth_code = params.get("code", [None])[0]
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Schwab authorized. You may close this window.")
        if _auth_code:
            self.wfile.write(b"<script>window.close()</script>".encode())

    def log_message(self, fmt, *args):
        pass


def _run_callback_server(port: int = 8080, timeout: int = 120):
    """Run a local HTTP server to capture OAuth callback."""
    global _auth_code
    _auth_code = None
    server = HTTPServer(("127.0.0.1", port), _CallbackHandler)
    server.timeout = 1
    deadline = time.time() + timeout
    while _auth_code is None and time.time() < deadline:
        server.handle_request()
    server.server_close()
    return _auth_code


class SchwabBroker(BrokerInterface):
    """Charles Schwab API adapter with OAuth 2.0."""

    def __init__(self, api_key=SCHWAB_API_KEY, secret=SCHWAB_SECRET,
                 callback=SCHWAB_CALLBACK):
        self.api_key = api_key
        self.secret = secret
        self.callback = callback
        self._token: dict | None = None
        self._connected = False
        self._load_token()

    def connect(self):
        if not self.api_key or not self.secret:
            log.warning("Schwab: no API credentials — read-only mode")
            return

        if self._token and self._token.get("access_token"):
            if self._token_expired():
                self._refresh_token()
            else:
                self._connected = True
                log.info("Schwab connected (cached token)")
                return

        # Interactive OAuth flow
        callback_port = urllib.parse.urlparse(self.callback).port or 8080
        params = urllib.parse.urlencode({
            "client_id": self.api_key,
            "redirect_uri": self.callback,
            "response_type": "code",
            "scope": "readonly",  # or "trade" for full access
        })
        auth_url = f"{AUTH_URL}?{params}"
        print(f"\nOpening browser for Schwab authorization...\n{auth_url}\n")
        webbrowser.open(auth_url)

        code = _run_callback_server(callback_port)
        if not code:
            log.error("Schwab OAuth: no authorization code received")
            return

        self._exchange_code(code)
        if self._token:
            self._connected = True
            log.info("Schwab connected (OAuth complete)")

    def disconnect(self):
        self._connected = False

    def net_liquidation(self) -> float:
        return self._api_get("/accounts/accountNumbers") or 0.0

    def daily_pnl(self) -> float:
        return 0.0

    def positions(self) -> dict[str, float]:
        return {}

    def last_price(self, symbol: str) -> float:
        try:
            import requests
            resp = requests.get(
                f"{API_BASE}/accounts/positions",
                headers=self._auth_headers(),
                timeout=10,
            )
            if resp.status_code == 200:
                for pos in resp.json():
                    if pos.get("instrument", {}).get("symbol") == symbol:
                        return float(pos.get("marketValue", 0))
        except Exception as e:
            log.error(f"Schwab last_price: {e}")
        return 0.0

    def market_order(self, symbol: str, shares: int, action: str):
        if not self._connected:
            log.warning("Schwab not connected")
            return
        try:
            import requests
            resp = requests.post(
                f"{API_BASE}/accounts/{self._account_id}/orders",
                json={
                    "orderType": "MARKET",
                    "session": "NORMAL",
                    "duration": "DAY",
                    "orderStrategyType": "SINGLE",
                    "orderLegCollection": [{
                        "instruction": f"{action.upper()}",
                        "quantity": abs(shares),
                        "instrument": {"symbol": symbol, "assetType": "EQUITY"},
                    }],
                },
                headers=self._auth_headers(),
                timeout=10,
            )
            if resp.status_code == 201:
                log.info(f"Schwab {action} {shares} {symbol}")
            else:
                log.error(f"Schwab order failed: {resp.text}")
        except Exception as e:
            log.error(f"Schwab order: {e}")

    # ── OAuth helpers ─────────────────────────────────────────────────────
    @property
    def _account_id(self) -> str:
        data = self._api_get("/accounts/accountNumbers")
        if data and isinstance(data, list) and len(data) > 0:
            return data[0].get("accountNumber", "")
        return ""

    def _auth_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._token.get('access_token', '')}",
            "Content-Type": "application/json",
        }

    def _token_expired(self) -> bool:
        if not self._token:
            return True
        return self._token.get("expires_at", 0) < time.time() + 60

    def _exchange_code(self, code: str):
        try:
            import requests
            resp = requests.post(
                TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": self.callback,
                    "client_id": self.api_key,
                    "client_secret": self.secret,
                },
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                data["expires_at"] = time.time() + data.get("expires_in", 1800)
                self._token = data
                self._save_token()
        except Exception as e:
            log.error(f"Schwab token exchange: {e}")

    def _refresh_token(self):
        if not self._token:
            return
        try:
            import requests
            resp = requests.post(
                TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": self._token.get("refresh_token"),
                    "client_id": self.api_key,
                    "client_secret": self.secret,
                },
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                data["expires_at"] = time.time() + data.get("expires_in", 1800)
                self._token = data
                self._save_token()
        except Exception as e:
            log.error(f"Schwab token refresh: {e}")

    def _api_get(self, path: str):
        try:
            import requests
            resp = requests.get(
                f"{API_BASE}{path}",
                headers=self._auth_headers(),
                timeout=10,
            )
            return resp.json() if resp.status_code == 200 else None
        except Exception:
            return None

    def _save_token(self):
        try:
            with open(TOKEN_FILE, "w") as f:
                json.dump(self._token, f)
        except Exception:
            pass

    def _load_token(self):
        try:
            if os.path.exists(TOKEN_FILE):
                with open(TOKEN_FILE) as f:
                    self._token = json.load(f)
        except Exception:
            pass
