#!/usr/bin/env bash
PEER=${1:-"http://127.0.0.1:8765"}
PORT=${2:-8766}
SESSION=${3:-"fear3-debug"}

echo -e "\033[0;32m[CrossLab] Starting Client Node on port $PORT, connecting to peer $PEER...\033[0m"
echo -e "\033[0;36m[CrossLab] Web Dashboard available at http://localhost:$PORT/dashboard\033[0m"
uv run crosslab node --role client --port "$PORT" --peer "$PEER" --session "$SESSION"
