"""Flask Web App — 纸上交易仪表盘"""

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import threading
import time
import logging
from flask import Flask, jsonify, render_template_string
from flask_socketio import SocketIO
from engine import PaperTradingEngine
from universe import SYMBOLS, SYMBOL_NAMES
from pt_strategy import run_strategy

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(message)s')
logger = logging.getLogger('app')

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins='*')
engine = PaperTradingEngine(initial_cash=100000.0)

# ── HTML 模板 ─────────────────────────────────────────────────
HTML = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
<title>纸上交易 A股</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0f172a;color:#e2e8f0;min-height:100vh;padding:16px}
h1{font-size:22px;text-align:center;margin-bottom:12px;color:#f1f5f9}
.card{background:#1e293b;border-radius:12px;padding:16px;margin-bottom:12px;border:1px solid #334155}
.row{display:flex;gap:12px;flex-wrap:wrap}
.stat{flex:1;min-width:120px;text-align:center;padding:12px;border-radius:8px;background:#0f172a}
.stat .label{font-size:12px;color:#94a3b8;margin-bottom:4px}
.stat .value{font-size:22px;font-weight:800}
.green{color:#22c55e}
.red{color:#ef4444}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{padding:8px 6px;text-align:right;border-bottom:1px solid #334155}
th{color:#94a3b8;font-weight:500;font-size:11px;text-transform:uppercase}
td:first-child,th:first-child{text-align:left}
.badge{display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600}
.badge-buy{background:rgba(34,197,94,.15);color:#22c55e}
.badge-sell{background:rgba(239,68,68,.15);color:#ef4444}
.footer{text-align:center;color:#64748b;font-size:11px;padding:8px}
.spinner{display:inline-block;width:14px;height:14px;border:2px solid #334155;border-top-color:#3b82f6;border-radius:50%;animation:spin .6s linear infinite;vertical-align:middle;margin-right:6px}
@keyframes spin{to{transform:rotate(360deg)}}
</style>
</head>
<body>
<h1>📊 A股纸上交易系统</h1>

<div class="row">
  <div class="stat card">
    <div class="label">总资产</div>
    <div class="value" id="total_value">--</div>
  </div>
  <div class="stat card">
    <div class="label">可用现金</div>
    <div class="value" id="cash">--</div>
  </div>
  <div class="stat card">
    <div class="label">总盈亏</div>
    <div class="value" id="pnl">--</div>
  </div>
  <div class="stat card">
    <div class="label">收益率</div>
    <div class="value" id="pnl_pct">--</div>
  </div>
</div>

<div class="card">
  <div style="font-size:15px;font-weight:600;margin-bottom:10px">持仓明细 <span style="font-size:11px;color:#94a3b8" id="quote_time"></span></div>
  <table>
    <thead><tr><th>标的</th><th>持仓</th><th>成本</th><th>现价</th><th>市值</th><th>盈亏</th><th>盈亏%</th></tr></thead>
    <tbody id="pos_body"><tr><td colspan="7" style="text-align:center;color:#64748b">暂无持仓</td></tr></tbody>
  </table>
</div>

<div class="card">
  <div style="font-size:15px;font-weight:600;margin-bottom:10px">最近交易</div>
  <table>
    <thead><tr><th>时间</th><th>标的</th><th>方向</th><th>股数</th><th>价格</th><th>金额</th></tr></thead>
    <tbody id="trade_body"><tr><td colspan="6" style="text-align:center;color:#64748b">暂无交易</td></tr></tbody>
  </table>
</div>

<div class="footer" id="status"><span class="spinner"></span> 数据刷新中...</div>

<script>
function fmt(n){return n==null?'--':Number(n).toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2})}
function pct(n){return n==null?'--':(n>=0?'+':'')+Number(n).toFixed(2)+'%'}

async function refresh(){
  try{
    let [p,t]=await Promise.all([fetch('/api/portfolio').then(r=>r.json()),fetch('/api/trades').then(r=>r.json())]);
    document.getElementById('total_value').textContent='¥'+fmt(p.total_value);
    document.getElementById('cash').textContent='¥'+fmt(p.cash);
    let pnlEl=document.getElementById('pnl');
    pnlEl.textContent='¥'+fmt(Math.abs(p.pnl));
    pnlEl.className='value '+(p.pnl>=0?'green':'red');
    let pctEl=document.getElementById('pnl_pct');
    pctEl.textContent=pct(p.pnl_pct);
    pctEl.className='value '+(p.pnl_pct>=0?'green':'red');
    document.getElementById('quote_time').textContent='行情: '+p.quote_time;

    let posHtml='';
    if(p.positions.length===0){
      posHtml='<tr><td colspan="7" style="text-align:center;color:#64748b">暂无持仓</td></tr>';
    }else{
      p.positions.forEach(pos=>{
        let mv=pos.shares*pos.price;
        posHtml+='<tr>'+
          '<td>'+pos.symbol+' '+pos.name+'</td>'+
          '<td>'+pos.shares+'</td>'+
          '<td>'+fmt(pos.avg_cost)+'</td>'+
          '<td>'+fmt(pos.price)+'</td>'+
          '<td>'+fmt(mv)+'</td>'+
          '<td class="'+(pos.pnl>=0?'green':'red')+'">'+fmt(pos.pnl)+'</td>'+
          '<td class="'+(pos.pnl_pct>=0?'green':'red')+'">'+pct(pos.pnl_pct)+'</td>'+
          '</tr>';
      });
    }
    document.getElementById('pos_body').innerHTML=posHtml;

    let tradeHtml='';
    if(t.length===0){
      tradeHtml='<tr><td colspan="6" style="text-align:center;color:#64748b">暂无交易</td></tr>';
    }else{
      t.slice(-20).reverse().forEach(tr=>{
        tradeHtml+='<tr>'+
          '<td>'+tr.time+'</td>'+
          '<td>'+tr.symbol+' '+tr.name+'</td>'+
          '<td><span class="badge '+(tr.action==='BUY'?'badge-buy':'badge-sell')+'">'+tr.action+'</span></td>'+
          '<td>'+tr.shares+'</td>'+
          '<td>'+fmt(tr.price)+'</td>'+
          '<td>'+fmt(tr.amount)+'</td>'+
          '</tr>';
      });
    }
    document.getElementById('trade_body').innerHTML=tradeHtml;
    document.getElementById('status').innerHTML='最后刷新: '+new Date().toLocaleTimeString('zh-CN');
  }catch(e){
    document.getElementById('status').textContent='刷新失败: '+e.message;
  }
}
refresh();
setInterval(refresh,30000);
</script>
</body>
</html>"""


@app.route('/')
def index():
    return render_template_string(HTML)


@app.route('/api/portfolio')
def api_portfolio():
    return jsonify(engine.snapshot())


@app.route('/api/trades')
def api_trades():
    return jsonify(engine.trades)


def _check_trading_hours():
    """判断当前是否在A股交易时段 (北京时间 9:30-11:30, 13:00-15:00, 周一至周五)"""
    import datetime
    now = datetime.datetime.now()
    if now.weekday() >= 5:
        return False
    t = now.hour * 100 + now.minute
    return (930 <= t <= 1130) or (1300 <= t <= 1500)


def engine_loop():
    """后台线程：每分钟更新行情 + 运行策略"""
    logger.info("交易引擎启动，初始资金 ¥100,000")

    # 预热日线基准数据（异步，仅拉取一次 yfinance）
    from pt_strategy import warmup_daily_ref
    import threading as _th
    _th.Thread(target=warmup_daily_ref, daemon=True).start()

    while engine.running:
        try:
            engine.update_quotes()
            if _check_trading_hours():
                run_strategy(engine)
            else:
                logger.debug("非交易时段，跳过策略")
        except Exception as e:
            logger.error(f"引擎循环异常: {e}")
        time.sleep(60)


@socketio.on('connect')
def on_connect():
    logger.info("WebSocket 客户端连接")


if __name__ == '__main__':
    engine.running = True
    t = threading.Thread(target=engine_loop, daemon=True)
    t.start()
    debug_mode = os.environ.get("PAPER_TRADING_DEBUG", "0") == "1"
    logger.info(f"Flask 启动于 http://127.0.0.1:8888  (debug={debug_mode})")
    socketio.run(app, host='127.0.0.1', port=8888, debug=debug_mode)
