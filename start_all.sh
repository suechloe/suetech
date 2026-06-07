#!/bin/bash
# Sue Tech 完整启动脚本
# 同时启动 Dashboard (server.py) 和 Bot Manager (bot_manager.py)

set -e

echo "🚀 启动 Sue Tech 完整服务..."

# 启动 Bot Manager（后台）
echo "📋 启动 Bot Manager..."
python bot_manager.py &
BOT_MANAGER_PID=$!
echo "✅ Bot Manager PID: $BOT_MANAGER_PID"

# 启动 Dashboard（前台）
echo "📊 启动 Dashboard..."
python server.py

# 如果 server.py 退出，也清理 bot_manager
kill $BOT_MANAGER_PID 2>/dev/null || true
