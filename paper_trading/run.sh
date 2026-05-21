#!/bin/bash
cd "$(dirname "$0")"
source ../venv/bin/activate

# 绕过代理直连东方财富
unset http_proxy HTTP_PROXY https_proxy HTTPS_PROXY

echo "========================================="
echo "  A股纸上交易系统 Paper Trading"
echo "  标的: 000001 600519 300750 000858 601318"
echo "  初始资金: ¥10,000"
echo "  Web: http://0.0.0.0:8888"
echo "========================================="
exec python app.py
