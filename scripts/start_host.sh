#!/usr/bin/env bash
PORT=${1:-8765}
SESSION=${2:-"fear3-debug"}

echo -e "\033[0;32m[CrossLab] Starting Host Node on port $PORT (Session: $SESSION)...\033[0m"
echo -e "\033[0;36m[CrossLab] Web Dashboard available at http://localhost:$PORT/dashboard\033[0m"
uv run crosslab node --role host --port "$PORT" --session "$SESSION"
