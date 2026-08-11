#!/bin/zsh
set -e
PROJECT_DIR="${0:A:h:h}"
cd "$PROJECT_DIR"
PYTHON_BIN="$(command -v python3.13 || command -v python3.12 || command -v python3.11 || command -v python3.10 || true)"
if [[ -z "$PYTHON_BIN" ]]; then echo "Python 3.10 or newer is required."; exit 1; fi
"$PYTHON_BIN" -m venv .venv
.venv/bin/pip install -r requirements.txt
cd frontend
pnpm install
pnpm build
cd "$PROJECT_DIR"
.venv/bin/python -m app.cli init
.venv/bin/python -m app.cli seed-companies
mkdir -p "$HOME/Library/LaunchAgents" data
sed "s|__PROJECT_DIR__|$PROJECT_DIR|g" scripts/com.local.job-tracker.plist.template > "$HOME/Library/LaunchAgents/com.local.job-tracker.plist"
launchctl bootout "gui/$UID/com.local.job-tracker" 2>/dev/null || true
launchctl bootstrap "gui/$UID" "$HOME/Library/LaunchAgents/com.local.job-tracker.plist"
echo "Installed. Open http://127.0.0.1:8765"
