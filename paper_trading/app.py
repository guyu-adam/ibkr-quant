"""
模拟盘 — Flask Web 仪表盘。
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask

app = Flask(__name__)


@app.route("/")
def index():
    return """
    <html>
    <head><title>quant — Paper Trading</title>
    <meta charset="utf-8">
    <style>
      body { font-family: monospace; margin: 40px; background: #111; color: #0f0; }
      h1 { border-bottom: 1px solid #333; padding-bottom: 10px; }
      .status { background: #1a1a1a; padding: 20px; border-radius: 8px; }
    </style>
    </head>
    <body>
      <h1>quant — Paper Trading Dashboard</h1>
      <div class="status">
        <p>Status: Running</p>
        <p>Mode: Paper Trading</p>
        <p>Interfaces: IBKR | OKX | Binance | Schwab | THS</p>
        <p>Strategies: Contracts | Options | Leverage | Fast | Slow | Long-Term</p>
      </div>
    </body>
    </html>
    """


@app.route("/api/status")
def api_status():
    return {"status": "ok", "mode": "paper"}
