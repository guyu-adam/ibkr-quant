"""
模拟盘 — Flask Web 仪表盘 v2。

新增:
  - /api/positions — 实时持仓
  - /api/equity — 权益曲线
  - /api/trades — 交易历史
  - /api/signals — 最近信号
  - 前端实时刷新
"""

import os
import json
from flask import Flask, jsonify

from core.persistence import TradeJournal

app = Flask(__name__)

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "trades.db")
_journal: TradeJournal | None = None


def get_journal() -> TradeJournal:
    global _journal
    if _journal is None:
        _journal = TradeJournal()
    return _journal


@app.route("/")
def index():
    journal = get_journal()
    summary = journal.trade_summary()
    return f"""
    <html>
    <head>
      <title>quant — Paper Trading</title>
      <meta charset="utf-8">
      <meta http-equiv="refresh" content="30">
      <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: 'Consolas', monospace; background: #0d1117; color: #c9d1d9; padding: 24px; }}
        h1 {{ color: #58a6ff; border-bottom: 1px solid #21262d; padding-bottom: 12px; margin-bottom: 20px; }}
        .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
        .card {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 16px; }}
        .card h2 {{ color: #58a6ff; font-size: 14px; margin-bottom: 10px; }}
        table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
        th, td {{ text-align: left; padding: 6px 8px; border-bottom: 1px solid #21262d; }}
        th {{ color: #8b949e; font-weight: normal; }}
        .buy {{ color: #3fb950; }} .sell {{ color: #f85149; }}
        .metric {{ font-size: 32px; font-weight: bold; color: #58a6ff; }}
        .metric-label {{ font-size: 12px; color: #8b949e; }}
        .risk {{ color: #f85149; }}
      </style>
    </head>
    <body>
      <h1>quant v4 — Paper Trading Dashboard</h1>
      <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:20px;">
        <div class="card" style="text-align:center;">
          <div class="metric" id="total-trades">{summary['total_trades']}</div>
          <div class="metric-label">Total Trades</div>
        </div>
        <div class="card" style="text-align:center;">
          <div class="metric" id="buys">{summary['buys']}</div>
          <div class="metric-label">Buys</div>
        </div>
        <div class="card" style="text-align:center;">
          <div class="metric" id="sells">{summary['sells']}</div>
          <div class="metric-label">Sells</div>
        </div>
        <div class="card" style="text-align:center;">
          <div class="metric" id="risk-count" class="risk">{summary['risk_events']}</div>
          <div class="metric-label">Risk Events</div>
        </div>
      </div>

      <div class="grid">
        <div class="card">
          <h2>Recent Trades</h2>
          <div id="trades-table"><p style="color:#8b949e">Loading...</p></div>
        </div>
        <div class="card">
          <h2>Recent Signals</h2>
          <div id="signals-table"><p style="color:#8b949e">Loading...</p></div>
        </div>
        <div class="card">
          <h2>Equity Curve</h2>
          <div id="equity-data"><p style="color:#8b949e">Loading...</p></div>
        </div>
        <div class="card">
          <h2>Risk Events</h2>
          <div id="risk-data"><p style="color:#8b949e">Loading...</p></div>
        </div>
      </div>

      <script>
        async function loadData() {{
          try {{
            let trades = await fetch('/api/trades').then(r=>r.json());
            let signals = await fetch('/api/signals').then(r=>r.json());
            let equity = await fetch('/api/equity').then(r=>r.json());
            let risks = await fetch('/api/risk-events').then(r=>r.json());

            document.getElementById('trades-table').innerHTML = '<table><tr><th>Time</th><th>Symbol</th><th>Action</th><th>Shares</th><th>Price</th><th>Strategy</th><th>Reason</th></tr>' +
              trades.slice(0,20).map(t => `<tr><td>${{t.ts}}</td><td>${{t.symbol}}</td><td class="${{t.action.toLowerCase()}}">${{t.action}}</td><td>${{t.shares}}</td><td>${{t.price}}</td><td>${{t.strategy}}</td><td style="font-size:11px">${{t.reason||''}}</td></tr>`).join('') + '</table>';

            document.getElementById('signals-table').innerHTML = '<table><tr><th>Time</th><th>Symbol</th><th>Strategy</th><th>Signal</th><th>Price</th><th>Score</th><th>Reason</th></tr>' +
              signals.slice(0,20).map(s => `<tr><td>${{s.ts}}</td><td>${{s.symbol}}</td><td>${{s.strategy}}</td><td class="${{s.signal=='buy'?'buy':'sell'}}">${{s.signal}}</td><td>${{s.price}}</td><td>${{s.score?.toFixed(1)}}</td><td style="font-size:11px">${{s.reason||''}}</td></tr>`).join('') + '</table>';

            if(equity.length > 0) {{
              let pts = equity.slice(0,30).reverse();
              document.getElementById('equity-data').innerHTML = '<table><tr><th>Time</th><th>Equity</th></tr>' +
                pts.map(e => `<tr><td>${{e.ts}}</td><td class="buy">$${{e.equity.toFixed(2)}}</td></tr>`).join('') + '</table>';
            }}

            document.getElementById('risk-data').innerHTML = risks.length === 0 ? '<p style="color:#3fb950">No risk events</p>' :
              '<table><tr><th>Time</th><th>Type</th><th>Reason</th><th>Equity</th></tr>' +
              risks.slice(0,20).map(r => `<tr><td>${{r.ts}}</td><td class="risk">${{r.event_type}}</td><td>${{r.reason}}</td><td>$${{r.equity?.toFixed(2)||0}}</td></tr>`).join('') + '</table>';

          }} catch(e) {{ console.error(e); }}
        }}
        loadData();
        setInterval(loadData, 15000);
      </script>
    </body>
    </html>
    """


@app.route("/api/status")
def api_status():
    j = get_journal()
    return jsonify({"status": "ok", "mode": "paper", **j.trade_summary()})


@app.route("/api/trades")
def api_trades():
    return jsonify(get_journal().recent_trades())


@app.route("/api/signals")
def api_signals():
    return jsonify(get_journal().recent_signals())


@app.route("/api/equity")
def api_equity():
    return jsonify(get_journal().equity_curve())


@app.route("/api/risk-events")
def api_risk_events():
    return jsonify(get_journal().risk_events())
