#!/bin/bash
# 双击即可启动 AgentToolHub
cd "$(dirname "$0")" || exit 1

PORT=8998
PID=$(lsof -ti :"$PORT" 2>/dev/null)
if [ -n "$PID" ]; then
  echo "⚠️  端口 $PORT 已被占用 (PID: $PID)"
  echo "请先关闭现有 AgentToolHub 进程，或改用其他端口启动。"
  exit 1
fi

echo "🚀 启动 AgentToolHub..."
python3 -m tool_hub.cli web
