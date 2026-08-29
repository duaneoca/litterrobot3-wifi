#!/usr/bin/env bash
# Run the probe/diag under a packet capture, to tell these two apart:
#
#   * bytes arrive from 192.168.4.1 but Python sees nothing -> local firewall
#   * nothing on the wire at all                            -> device is silent
#
# Needs root for tcpdump.  Usage:  sudo ./probe_diag.sh
set -uo pipefail

cd "$(dirname "$0")" || exit 1

AP_SSID="${AP_SSID:-Litter-Robot}"
AP_PASS="${AP_PASS:-neverscoop}"
IFACE="${IFACE:-$(nmcli -t -f DEVICE,TYPE dev | awk -F: '$2=="wifi"{print $1; exit}')}"
STAMP="$(date +%Y%m%d-%H%M%S)"
PCAP="captures/lr3-$STAMP.pcap"
LOG="captures/lr3-$STAMP.log"

[ "$(id -u)" -eq 0 ] || { echo "!! run me with sudo (tcpdump needs root)"; exit 1; }
mkdir -p captures

# Join the AP if we aren't already on it.
if ! ip -4 -br addr show "$IFACE" | grep -q '192\.168\.4\.'; then
  echo "--- not on the robot's AP; scanning for '$AP_SSID'"
  if ! nmcli -t -f SSID dev wifi list --rescan yes | grep -qxF "$AP_SSID"; then
    echo "!! '$AP_SSID' not broadcasting."
    echo "   Hold Cycle + Empty ~3s until the Power button turns blue, then rerun."
    exit 1
  fi
  nmcli dev wifi connect "$AP_SSID" password "$AP_PASS" ifname "$IFACE" || exit 1
  for _ in $(seq 20); do
    ip -4 -br addr show "$IFACE" | grep -q '192\.168\.4\.' && break
    sleep 0.5
  done
fi
ip -4 -br addr show "$IFACE"

# Capture everything on the provisioning ports, both directions, plus ICMP
# (an ICMP port-unreachable back from the robot is itself a useful answer:
# it means the robot is up but nothing is listening on that port).
echo "--- capturing on $IFACE -> $PCAP"
tcpdump -i "$IFACE" -n -s0 -w "$PCAP" \
  '(udp port 2379 or udp port 2380) or icmp' >/dev/null 2>&1 &
TCPDUMP_PID=$!
trap 'kill "$TCPDUMP_PID" 2>/dev/null' EXIT
sleep 1

echo "--- running diag"
python3 litterbot_wifi.py diag 2>&1 | tee "$LOG"

sleep 1
kill "$TCPDUMP_PID" 2>/dev/null
wait "$TCPDUMP_PID" 2>/dev/null

echo
echo "=== what actually crossed the wire ==="
tcpdump -r "$PCAP" -n -A 2>/dev/null | head -60
echo
# Count only real protocol replies: UDP from the robot to our listen port.
# Do NOT count every packet from 192.168.4.1 -- the robot also emits ICMP
# port-unreachables in response to DNS queries this machine sends it once
# NetworkManager adopts the AP as a nameserver. Those are not replies.
INBOUND=$(tcpdump -r "$PCAP" -n 'udp and src 192.168.4.1 and dst port 2380' 2>/dev/null | wc -l)
ICMP=$(tcpdump -r "$PCAP" -n 'icmp and src 192.168.4.1' 2>/dev/null | wc -l)
[ "$ICMP" -gt 0 ] && echo "(ignoring $ICMP ICMP packets from the robot -- not protocol replies)"
echo "packets FROM the robot: $INBOUND"
if [ "$INBOUND" -gt 0 ]; then
  echo ">>> The robot IS transmitting. If Python saw nothing, the local"
  echo ">>> firewall (ufw) is dropping the reply -- open udp/2380 inbound."
else
  echo ">>> Nothing came back from the robot at all. Not a firewall problem:"
  echo ">>> this unit is not answering 'Wsu' on udp/2379."
fi

# Hand the capture back to the invoking user, not root.
[ -n "${SUDO_UID:-}" ] && chown "$SUDO_UID:${SUDO_GID:-$SUDO_UID}" "$PCAP" "$LOG" 2>/dev/null
echo
echo "pcap: $PCAP"
echo "log:  $LOG"
