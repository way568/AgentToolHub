#!/bin/bash
# 双击即可启动 Tool Hub
cd "$(dirname "$0")"

# 检查端口占用，清理重复进程
PID=$(lsof -ti :8765 2>/dev/null)
if [ -n "$PID" ]; then
  echo "⚠️  端口 8765 已被占用 (PID: $PID)，正在关闭旧进程..."
  kill -9 $PID 2>/dev/null
  sleep 1
fi

echo "🚀 启动 Tool Hub..."
python3 tool_hub_server.py
