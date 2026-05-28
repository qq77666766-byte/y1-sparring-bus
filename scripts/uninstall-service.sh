#!/usr/bin/env bash
# Remove the optional user-level LaunchAgent.
set -e

LABEL="com.y1.sparring-bus"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

launchctl bootout "gui/$(id -u)" "$PLIST" >/dev/null 2>&1 || launchctl unload "$PLIST" >/dev/null 2>&1 || true

if [ -f "$PLIST" ]; then
    rm -f "$PLIST"
    echo "✓ Removed $PLIST"
else
    echo "LaunchAgent plist was not installed"
fi

echo "Logs, jobs, and repository files were not deleted."
