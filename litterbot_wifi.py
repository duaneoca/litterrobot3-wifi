#!/usr/bin/env python3
"""
litterbot_wifi.py -- talk to a Litter-Robot 3 Connect over its local UDP
provisioning protocol, bypassing the Whisker phone app.

Background
----------
During onboarding the LR3 Connect (ESP32-WROOM-32D) starts its own Wi-Fi
access point:

    SSID:     litter-robot
    password: neverscoop
    device IP: 192.168.4.1

The phone app then speaks a plain-text UDP protocol to the device:

    * app  -> device   destination UDP port 2379
    * device -> app    the app listens on UDP port 2380

Documented message flow (from elttam's teardown, initial onboarding):

    app  -> "Wsu,v1\r\n"                     ask device to scan for networks
    dev  -> <list of visible SSIDs> + "Rdy,LR3{ID}"
    app  -> "AOK\r\n"
    app  -> "DATA,CERT\r\n"                   begin AWS IoT cert transfer
    dev  -> "RDY"
    app  -> "LN,{n}<line>"  (repeated)        cert sent line by line
    dev  -> "AOK,{n}"       (per line)
    app  -> "DONE,{CRC-32}"
    (repeats for "DATA,KEY" = RSA private key)
    app  -> final config line:
            "Type,SSID,Password,Dispatch,Port,Web,Type,Id,CRC,Serial,endpoint,cloud,lr3\r\n"
        e.g.
            "Xsu,<homeSSID>,<homePassword>,,,2000,LR3,<Id>,<CRC>,LR3<Serial>,"
            "xxxx.iot.us-east-1.amazonaws.com,prod/cloud/<..>,prod/lr3/<..>\r\n"

This script currently implements the SAFE, READ-ONLY discovery step: join the
robot's AP, send "Wsu,v1", and print whatever it says back. That confirms we
can reach the device and reveals its ID -- the value we need before attempting
any write. The provisioning/write step is intentionally NOT wired up yet; see
notes at the bottom.

Usage
-----
    1. On this computer, join Wi-Fi network "litter-robot" (password neverscoop).
       (Put the LR3 into onboarding/AP mode first if needed.)
    2. python3 litterbot_wifi.py probe
"""

import socket
import sys
import time

DEVICE_IP = "192.168.4.1"
DEVICE_PORT = 2379      # we send here
LISTEN_PORT = 2380      # device replies here
TIMEOUT_S = 5.0


def _open_socket():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    except OSError:
        pass
    # Bind the source port the device expects to reply to.
    s.bind(("0.0.0.0", LISTEN_PORT))
    s.settimeout(TIMEOUT_S)
    return s


def _send(s, payload: bytes):
    print(f">>> sending {payload!r} to {DEVICE_IP}:{DEVICE_PORT}")
    s.sendto(payload, (DEVICE_IP, DEVICE_PORT))


def _drain(s, seconds=TIMEOUT_S):
    """Collect all datagrams that arrive within `seconds`."""
    out = []
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            data, addr = s.recvfrom(4096)
        except socket.timeout:
            break
        print(f"<<< {addr[0]}:{addr[1]}  {data!r}")
        out.append((addr, data))
    return out


def probe():
    """Read-only: confirm reachability and dump the device's scan reply + ID."""
    print(f"Probing Litter-Robot at {DEVICE_IP} (listening on udp/{LISTEN_PORT})")
    print("Make sure this computer is joined to the 'litter-robot' Wi-Fi AP.\n")
    try:
        s = _open_socket()
    except OSError as e:
        print(f"!! could not bind udp/{LISTEN_PORT}: {e}")
        print("   (another process may hold the port; close it and retry)")
        return 1

    with s:
        _send(s, b"Wsu,v1\r\n")
        replies = _drain(s, seconds=TIMEOUT_S)

    if not replies:
        print("\nNo response.")
        print("Checklist:")
        print("  * Are you actually joined to the 'litter-robot' AP (not your home Wi-Fi)?")
        print("    Your IP on that interface should be 192.168.4.x.")
        print("  * Is the LR3 in onboarding/AP mode? (AP disappears once it joins a network)")
        print("  * macOS may need Local Network / firewall permission for Terminal.")
        return 2

    print("\nGot a response -- the local UDP channel works.")
    print("Look above for a line like 'Rdy,LR3<ID>' and the scanned SSID list.")
    return 0


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "probe"
    if cmd == "probe":
        return probe()
    print(__doc__)
    print(f"Unknown command: {cmd!r}. Try: python3 {argv[0]} probe")
    return 64


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))


# ---------------------------------------------------------------------------
# NOT YET IMPLEMENTED -- the write/provisioning path.
#
# Two open questions decide how hard the write step is, and we should answer
# them with `probe` + a packet capture BEFORE writing any bytes to the device:
#
#   1. Does the app's "Update Network" flow re-send the AWS certificate + key,
#      or does it reuse what's already on the device and send only the final
#      "Xsu,..." config line? elttam documented INITIAL onboarding (which sends
#      certs); a WiFi-only change may be much shorter.
#
#   2. What are this unit's real field values (Id, CRC, Serial, endpoint, and
#      the prod/cloud + prod/lr3 topic strings)? The cleanest way to get them
#      is to capture one real exchange from the app (Wireshark on udp/2379-2380)
#      or read them from the device.
#
# Plan: capture once, then replay the exact final config line with the SSID and
# password swapped. Keep everything else byte-identical.
# ---------------------------------------------------------------------------
