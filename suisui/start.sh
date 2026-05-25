#!/bin/bash
# 岁岁桌面宠物启动脚本
# Launch script for Suisui desktop pet

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$HOME/sue-tech/.venv/bin/python"
APP="$SCRIPT_DIR/main.py"

echo "🐱 启动岁岁..."

# Kill any existing instance
pkill -f "python.*suisui/main.py" 2>/dev/null

# Launch in background
nohup "$PYTHON" "$APP" > "$SCRIPT_DIR/suisui.log" 2>&1 &
PID=$!

sleep 2
if pgrep -f "python.*suisui/main.py" > /dev/null; then
    echo "✅ 岁岁已启动！PID: $PID"
else
    echo "❌ 启动失败，查看日志: $SCRIPT_DIR/suisui.log"
    tail -20 "$SCRIPT_DIR/suisui.log"
fi
