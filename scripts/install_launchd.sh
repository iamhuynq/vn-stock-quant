#!/usr/bin/env bash
# Installs a per-user launchd agent that triggers scripts/daily.sh Mon-Fri every 30 minutes from 18:30 to
# 23:30 (Asia/Ho_Chi_Minh, assuming the Mac uses that time zone) and at login. launchd runs a missed slot
# when the Mac wakes. daily.sh exits in about a second once the day is done.
# Usage: scripts/install_launchd.sh install | uninstall | status      (nothing happens without an argument)
set -eu
LABEL="com.stock.daily"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

plist() {
  echo '<?xml version="1.0" encoding="UTF-8"?>'
  echo '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">'
  echo '<plist version="1.0"><dict>'
  echo "  <key>Label</key><string>$LABEL</string>"
  echo "  <key>ProgramArguments</key><array><string>$ROOT/scripts/daily.sh</string></array>"
  echo "  <key>WorkingDirectory</key><string>$ROOT</string>"
  echo "  <key>EnvironmentVariables</key><dict><key>PATH</key><string>$HOME/.local/bin:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin</string></dict>"
  echo "  <key>RunAtLoad</key><true/>"
  echo "  <key>StandardOutPath</key><string>$ROOT/data/logs/launchd.out</string>"
  echo "  <key>StandardErrorPath</key><string>$ROOT/data/logs/launchd.err</string>"
  echo "  <key>StartCalendarInterval</key><array>"
  for wd in 1 2 3 4 5; do
    for hm in 18:30 19:00 19:30 20:00 20:30 21:00 21:30 22:00 22:30 23:00 23:30; do
      echo "    <dict><key>Weekday</key><integer>$wd</integer><key>Hour</key><integer>${hm%%:*}</integer><key>Minute</key><integer>$((10#${hm##*:}))</integer></dict>"
    done
  done
  echo "  </array>"
  echo '</dict></plist>'
}

case "${1:-}" in
  install)
    mkdir -p "$HOME/Library/LaunchAgents" "$ROOT/data/logs"
    plist > "$PLIST"
    plutil -lint "$PLIST"
    launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
    launchctl bootstrap "gui/$(id -u)" "$PLIST"
    echo "Installed $PLIST" ;;
  uninstall)
    launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
    rm -f "$PLIST"
    echo "Removed $PLIST" ;;
  status)
    launchctl print "gui/$(id -u)/$LABEL" 2>/dev/null | head -20 || echo "Not installed" ;;
  print)
    plist ;;
  *)
    echo "Usage: $0 install | uninstall | status | print" ; exit 2 ;;
esac
