#!/usr/bin/env bash
# Wait for the robot to enter pairing mode, then measure BOTH addresses inside
# the live onboarding window -- the station address first (no disruption), then
# the AP address. The listener appears to exist only during this window, so
# every measurement has to happen now, not later.
set -uo pipefail
cd "$(dirname "$0")" || exit 1

AP_SSID="${AP_SSID:-Litter-Robot}"
AP_PASS="${AP_PASS:-neverscoop}"
STA_IP="${STA_IP:-192.168.2.202}"
IFACE="${IFACE:-wlp4s0}"
WAIT_MAX="${WAIT_MAX:-300}"
STAMP="$(date +%Y%m%d-%H%M%S)"
LOG="captures/window-$STAMP.log"
mkdir -p captures

HOME_CON="$(nmcli -t -f NAME,DEVICE con show --active | awk -F: -v i="$IFACE" '$2==i{print $1; exit}')"
restore() {
  [ -n "${HOME_CON:-}" ] && nmcli con up id "$HOME_CON" >/dev/null 2>&1 && echo "--- restored '$HOME_CON'"
}
trap restore EXIT

echo "Waiting up to ${WAIT_MAX}s for '$AP_SSID' to appear."
echo ">>> Hold Cycle + Empty ~3s until the Power button turns blue. <<<"
echo
deadline=$(( $(date +%s) + WAIT_MAX ))
while [ "$(date +%s)" -lt "$deadline" ]; do
  if nmcli -t -f SSID dev wifi list --rescan yes 2>/dev/null | grep -qxF "$AP_SSID"; then
    echo "=== AP detected at $(date +%H:%M:%S) -- window is LIVE ==="
    break
  fi
  sleep 5
done
if ! nmcli -t -f SSID dev wifi list 2>/dev/null | grep -qxF "$AP_SSID"; then
  echo "!! '$AP_SSID' never appeared within ${WAIT_MAX}s."
  exit 1
fi

{
  echo "### PHASE 1: station address ($STA_IP), still on home Wi-Fi"
  LR3_HOST="$STA_IP" python3 litterbot_wifi.py ports
  echo
  LR3_HOST="$STA_IP" python3 litterbot_wifi.py probe
  echo

  echo "### PHASE 2: AP address (192.168.4.1)"
  nmcli dev wifi connect "$AP_SSID" password "$AP_PASS" ifname "$IFACE" >/dev/null 2>&1
  for _ in $(seq 20); do
    ip -4 -br addr show "$IFACE" | grep -q '192\.168\.4\.' && break
    sleep 0.5
  done
  ip -4 -br addr show "$IFACE"
  if ip -4 -br addr show "$IFACE" | grep -q '192\.168\.4\.'; then
    LR3_HOST=192.168.4.1 python3 litterbot_wifi.py ports
    echo
    LR3_HOST=192.168.4.1 python3 litterbot_wifi.py probe
  else
    echo "!! could not get a 192.168.4.x lease"
  fi
} 2>&1 | tee "$LOG"

echo
echo "log: $LOG"
