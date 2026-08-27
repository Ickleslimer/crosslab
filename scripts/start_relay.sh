#!/usr/bin/env bash
PORT=${1:-8080}

echo -e "\033[0;32m[CrossLab] Starting Central Relay Hub on port $PORT...\033[0m"
uv run crosslab relay --port "$PORT"
