#!/usr/bin/env bash
# CrossLab Automated Linux/macOS Installer
# Installs uv (if missing), creates .venv, installs dependencies, and runs self-test.

set -e

echo -e "\033[0;36m======================================================"
echo -e "CrossLab Installer: A2A Empirical Collaboration Layer"
echo -e "======================================================\033[0m"

# 1. Check for uv
if ! command -v uv &> /dev/null; then
    echo -e "\033[0;33m[*] uv not found. Installing uv via Astral installer...\033[0m"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.cargo/bin:$PATH"
fi

echo -e "\033[0;32m[+] uv is available: $(uv --version)\033[0m"

# 2. Sync dependencies
echo -e "\033[0;33m[*] Syncing virtual environment and dependencies...\033[0m"
uv sync --all-extras

# 3. Run Self-Test
echo -e "\033[0;33m[*] Running CrossLab self-test suite...\033[0m"
uv run --extra dev pytest -q

echo -e "\n\033[0;32m[+] CrossLab successfully installed and verified!\033[0m"
echo -e "\n\033[1;37mQuick Commands:\033[0m"
echo -e "  Start Host Node:   \033[0;36m./scripts/start_host.sh\033[0m"
echo -e "  Start Client Node: \033[0;36m./scripts/start_client.sh <host_url>\033[0m"
echo -e "  Start Relay Hub:   \033[0;36m./scripts/start_relay.sh\033[0m"
echo -e "  Open Web HUD:      \033[0;36mhttp://localhost:8765/dashboard\033[0m"
