"""
告警通知模块 — 熔断/异常/大额亏损时推送通知。

支持渠道: 控制台 / Webhook / 文件日志
Usage:
    from core.alerts import AlertManager
    alerts = AlertManager(webhook_url="https://hooks.slack.com/...")
    alerts.send("risk_halt", "Daily loss limit reached", equity=9500)
"""

import json
import logging
from datetime import datetime
from core.persistence import TradeJournal

log = logging.getLogger(__name__)


class AlertManager:
    """Multi-channel alert dispatcher for trading events."""

    def __init__(self, webhook_url: str = "", journal: TradeJournal | None = None):
        self._webhook = webhook_url
        self._journal = journal
        self._alert_log: list[dict] = []
        self._max_log = 200

    def send(self, event_type: str, reason: str = "", equity: float = 0.0,
             positions: dict | None = None, **kwargs):
        """Send alert to all configured channels."""
        ts = datetime.now().isoformat()
        msg = {
            "ts": ts, "event_type": event_type, "reason": reason,
            "equity": equity, "positions": positions or {},
            **kwargs,
        }

        # 1. Console / log
        level = "WARNING" if event_type in ("risk_halt", "stop_hit") else "INFO"
        log.log(
            logging.WARNING if level == "WARNING" else logging.INFO,
            f"[ALERT:{event_type}] {reason}  equity={equity:.0f}",
        )

        # 2. Webhook
        if self._webhook:
            self._send_webhook(msg)

        # 3. Journal
        if self._journal:
            self._journal.log_risk_event(event_type, reason, equity)

        # 4. In-memory
        self._alert_log.append(msg)
        if len(self._alert_log) > self._max_log:
            self._alert_log = self._alert_log[-self._max_log:]

    def _send_webhook(self, msg: dict):
        try:
            import urllib.request
            data = json.dumps({"text": f"[quant:{msg['event_type']}] {msg['reason']}  "
                                       f"equity={msg['equity']:.0f}  ts={msg['ts']}"}).encode()
            req = urllib.request.Request(self._webhook, data=data,
                                         headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=5)
        except Exception as e:
            log.debug(f"Webhook send failed: {e}")

    def recent(self, limit: int = 20) -> list[dict]:
        return self._alert_log[-limit:]

    # ── Convenience methods ──────────────────────────────────────────────
    def on_halt(self, reason: str, equity: float):
        self.send("risk_halt", reason, equity)

    def on_stop(self, symbol: str, price: float, stop: float):
        self.send("stop_hit", f"{symbol} stop triggered: {price:.2f} <= {stop:.2f}")

    def on_large_loss(self, symbol: str, pnl: float, pct: float):
        self.send("large_loss", f"{symbol} loss: {pnl:.0f} ({pct:.1%})")

    def on_startup(self, equity: float, strategies: list):
        self.send("startup", f"Engine started with {len(strategies)} strategies",
                  equity=equity)

    def on_shutdown(self, equity: float):
        self.send("shutdown", f"Engine shutdown", equity=equity)
