#!/bin/zsh
launchctl bootout "gui/$UID/com.local.job-tracker" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/com.local.job-tracker.plist"
echo "Service removed. Project data was preserved."

