#!/usr/bin/env bash
# Join the Litter-Robot AP, run the probe, then restore the previous Wi-Fi.
#
# The robot's AP has no internet, and most laptops have a single Wi-Fi radio --
# so you lose connectivity for the duration. This does the whole round trip
# unattended and restores your network even if the probe fails or you Ctrl-C.
#
# Usage: ./run_probe.sh
set -uo pipefail

AP_SSID="${AP_SSID:-Litter-Robot}"     # exact case matters
AP_PASS="${AP_PASS:-neverscoop}"
IFACE="${IFACE:-$(nmcli -t -f DEVICE,TYPE dev | awk -F: '$2=="wifi"{print $1; exit}')}"
LOG="captures/probe-$(date +%Y%m%d-%H%M%S).log"

HOME_CON="$(nmcli -t -f NAME,DEVICE con show --active | awk -F: -v i="$IFACE" '$2==i{print $1; exit}')"

restore() {
  if [ -n "${HOME_CON:-}" ]; then
    echo "--- restoring '$HOME_CON' on $IFACE"
    nmcli con up id "$HOME_CON" >/dev/null 2>&1 \
      && echo "--- back on '$HOME_CON'" \
      || echo "!! could not restore '$HOME_CON' -- reconnect manually"
  fi
}
trap restore EXIT

mkdir -p captures

# Don't drop a working connection unless the AP is actually in range.
echo "--- scanning for '$AP_SSID'"
if ! nmcli -t -f SSID dev wifi list --rescan yes | grep -qxF "$AP_SSID"; then
  echo "!! '$AP_SSID' not in range. Is the robot in pairing mode?"
  echo "   Hold Cycle + Empty ~3s until the Power button turns blue, then retry."
  HOME_CON=""   # nothing was changed; nothing to restore
  exit 1
fi

echo "--- joining '$AP_SSID' (was on '${HOME_CON:-none}')"
nmcli dev wifi connect "$AP_SSID" password "$AP_PASS" ifname "$IFACE" || exit 1

# Wait for a 192.168.4.x lease before sending anything.
for _ in $(seq 20); do
  ip -4 -br addr show "$IFACE" | grep -q '192\.168\.4\.' && break
  sleep 0.5
done
ip -4 -br addr show "$IFACE"
if ! ip -4 -br addr show "$IFACE" | grep -q '192\.168\.4\.'; then
  echo "!! joined but no 192.168.4.x address -- the AP may not be serving DHCP"
  exit 1
fi

echo "--- probing (output -> $LOG)"
python3 litterbot_wifi.py probe 2>&1 | tee "$LOG"

echo "--- probe done, log: $LOG"
