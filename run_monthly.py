"""
每月最后一个交易日运行这个脚本
输出本月操作清单，你确认后手动在 IBKR 下单

用法：
    conda activate quant
    cd ~/Desktop/量化
    python run_monthly.py
"""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from strategy.monthly_rotation import get_momentum_scores, generate_orders

# ── 填写你的当前持仓（首次运行全填 0）────────────────────────────────────────
CURRENT_HOLDINGS = {
    # "AAPL": 5,
    # "NVDA": 3,
}

EQUITY = 10_000   # 你的账户净值（美元），每月更新


def main():
    print("\n" + "="*55)
    print("  月度动量轮动  —  操作清单")
    print("="*55)

    print("\n正在拉取行情数据...\n")
    scores = get_momentum_scores()

    # ── 全量排名 ─────────────────────────────────────────────────────────────
    print(f"{'排名':>4}  {'标的':>6}  {'3月动量':>8}  {'最新价':>8}  {'入选'}")
    print("-" * 42)
    for _, row in scores.iterrows():
        flag = "★ 买入" if row["selected"] else ""
        print(f"{int(row['rank']):>4}  {row['symbol']:>6}  "
              f"{row['momentum']:>+8.1%}  {row['price']:>8.2f}  {flag}")

    # ── 操作指令 ─────────────────────────────────────────────────────────────
    orders = generate_orders(scores, CURRENT_HOLDINGS, EQUITY)

    print(f"\n{'─'*55}")
    print("【本月操作清单】\n")

    if orders["sell"]:
        print("▼ 卖出（清仓）：")
        for o in orders["sell"]:
            print(f"    SELL  {o['symbol']:6}  {o['shares']} 股  "
                  f"预计回收 ${o['est_proceeds']:.0f}")

    if orders["buy"]:
        print("\n▲ 买入（建仓）：")
        for o in orders["buy"]:
            print(f"    BUY   {o['symbol']:6}  {o['shares']} 股  "
                  f"预计花费 ${o['est_cost']:.0f}")

    if orders["hold"]:
        print("\n● 持有不动：")
        for o in orders["hold"]:
            print(f"    HOLD  {o['symbol']:6}  {o['shares']} 股")

    if not orders["sell"] and not orders["buy"]:
        print("    本月无需操作，持仓不变。")

    # ── 目标持仓汇总 ─────────────────────────────────────────────────────────
    print(f"\n{'─'*55}")
    print("【下月目标持仓】\n")
    total_cost = 0
    for t in orders["target"]:
        cost = t["shares"] * t["price"]
        total_cost += cost
        print(f"    {t['symbol']:6}  {t['shares']:>4} 股 × ${t['price']:>8.2f}"
              f"  = ${cost:>8.0f}  ({t['weight']})")
    print(f"    {'─'*44}")
    print(f"    {'合计':>6}  {'':>4}   {'':>10}    ${total_cost:>8.0f}")
    cash = EQUITY - total_cost
    print(f"    {'剩余现金':>6}                          ${cash:>8.0f}")

    print(f"\n{'='*55}")
    print("  确认后请登录 IBKR 手动执行以上订单")
    print("  建议：收盘前 30 分钟用限价单操作")
    print("="*55 + "\n")


if __name__ == "__main__":
    main()
