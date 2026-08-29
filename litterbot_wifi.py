#!/usr/bin/env python3
"""
litterbot_wifi.py -- talk to a Litter-Robot 3 Connect over its local UDP
provisioning protocol, bypassing the Whisker phone app.

Background
----------
During onboarding the LR3 Connect (ESP32-WROOM-32D) starts its own Wi-Fi
access point:

    SSID:     Litter-Robot     (exact case matters)
    password: neverscoop
    device IP: 192.168.4.1

The phone app then speaks a plain-text UDP protocol to the device:

    * app  -> device   destination UDP port 2379
    * device -> app    the app listens on UDP port 2380

Documented message flow (from elttam's teardown, initial onboarding):

    app  -> "wsu,v1\r\n"                     ask device to scan for networks
                                             (LOWERCASE w -- capital is ignored)
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
    1. On this computer, join Wi-Fi network "Litter-Robot" (password neverscoop).
       (Put the LR3 into onboarding/AP mode first if needed.)
    2. python3 litterbot_wifi.py probe
       (or: LR3_HOST=<lan-ip> python3 litterbot_wifi.py probe|diag)
"""

import os
import socket
import subprocess
import sys
import time

# Default is the robot's own AP address during onboarding. Override with
# LR3_HOST when the robot is already joined to a normal network -- the
# provisioning listener binds to whichever address it currently holds.
DEVICE_IP = os.environ.get("LR3_HOST", "192.168.4.1")
DEVICE_PORT = 2379      # we send here

# CASE MATTERS, and this is the whole ballgame. The device answers "wsu,v1"
# with a lowercase w. Capital-W "Wsu,v1" -- as written up in the public
# teardown -- is silently ignored. Same for the other verbs: "Rdy" and "LR3"
# work, "rdy" and "lr3" do not.
SCAN_VERB = b"wsu,v1\r\n"     # -> "SSID,<name>,<rssi>,..." scan list
READY_VERB = b"Rdy\r\n"       # -> same scan list
ID_VERB = b"LR3\r\n"          # -> "Rdy,LR3<ID>"
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
    print("Joined to the 'Litter-Robot' AP, or set LR3_HOST to its LAN address.\n")
    try:
        s = _open_socket()
    except OSError as e:
        print(f"!! could not bind udp/{LISTEN_PORT}: {e}")
        print("   (another process may hold the port; close it and retry)")
        return 1

    with s:
        _send(s, SCAN_VERB)
        replies = _drain(s, seconds=TIMEOUT_S)

    if not replies:
        print("\nNo response.")
        print("Checklist:")
        print("  * Are you actually joined to the 'Litter-Robot' AP (not your home Wi-Fi)?")
        print("    Your IP on that interface should be 192.168.4.x.")
        print("  * Is the LR3 in onboarding/AP mode? (AP disappears once it joins a network)")
        print("  * macOS may need Local Network / firewall permission for Terminal.")
        return 2

    print("\nGot a response -- the local UDP channel works.")
    print("Look above for a line like 'Rdy,LR3<ID>' and the scanned SSID list.")
    return 0


def _preflight():
    """Check we can actually reach 192.168.4.1 before blaming the device.

    On a dual-homed machine (Wi-Fi on the robot's AP, Ethernet for internet)
    this matters more than it looks: if the Wi-Fi is NOT joined to the robot's
    AP, there is no 192.168.4.0/24 link route, so packets for 192.168.4.1 fall
    through to the default route and leave via Ethernet toward the internet.
    They vanish silently, and it looks exactly like a device that won't answer.
    """
    problems = []

    route = subprocess.run(
        ["ip", "route", "get", DEVICE_IP],
        capture_output=True, text=True,
    ).stdout.strip()

    if not route:
        problems.append(f"no route to {DEVICE_IP} at all")
    elif " via " in route.split(" dev ")[0]:
        dev = route.split(" dev ")[1].split()[0] if " dev " in route else "?"
        problems.append(
            f"{DEVICE_IP} routes via a gateway on '{dev}' -- you are NOT on the "
            f"robot's AP.\n     Packets are leaking out your default route "
            f"instead of reaching the robot.\n     Route: {route}"
        )

    addrs = subprocess.run(
        ["ip", "-4", "-br", "addr"], capture_output=True, text=True,
    ).stdout
    if "192.168.4." not in addrs:
        problems.append(
            "this machine has no 192.168.4.x address -- the robot's DHCP has "
            "not given us a lease"
        )

    return problems, route


# Message variants to try when the documented one gets no answer. The device is
# an early-release unit and may not speak exactly what elttam documented.
DIAG_VARIANTS = [
    ("wsu,v1 (works)",        b"wsu,v1\r\n",  DEVICE_IP,        LISTEN_PORT),
    ("Rdy (works)",           b"Rdy\r\n",     DEVICE_IP,        LISTEN_PORT),
    ("LR3 -> device id",      b"LR3\r\n",     DEVICE_IP,        LISTEN_PORT),
    ("Wsu,v1 capital W",      b"Wsu,v1\r\n",  DEVICE_IP,        LISTEN_PORT),
    ("subnet broadcast",      b"wsu,v1\r\n",  "192.168.4.255",  LISTEN_PORT),
    ("ephemeral source port", b"wsu,v1\r\n",  DEVICE_IP,        0),
]


def diag():
    """Try several message + source-port variants and report what answers.

    Run this under a packet capture (see probe_diag.sh). The capture is what
    makes the result conclusive: if bytes come back on the wire but nothing
    reaches Python, the local firewall is dropping them; if the wire stays
    silent, the device really is not answering.
    """
    problems, route = _preflight()
    print(f"Route to {DEVICE_IP}: {route or '(none)'}\n")
    if problems:
        print("!! preflight failed:")
        for p in problems:
            print(f"   - {p}")
        print("\n   Join the 'Litter-Robot' AP first. Not sending anything.")
        return 2

    answered = []
    for label, payload, dest, src_port in DIAG_VARIANTS:
        print(f"--- variant: {label}")
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            s.bind(("0.0.0.0", src_port))
            s.settimeout(3.0)
        except OSError as e:
            print(f"    !! socket setup failed: {e}\n")
            continue

        with s:
            bound = s.getsockname()[1]
            print(f"    >>> {payload!r} -> {dest}:{DEVICE_PORT}  (from :{bound})")
            try:
                s.sendto(payload, (dest, DEVICE_PORT))
            except OSError as e:
                print(f"    !! send failed: {e}\n")
                continue
            replies = _drain(s, seconds=3.0)

        if replies:
            answered.append(label)
        else:
            print("    (silence)")
        print()

    if answered:
        print(f"ANSWERED: {', '.join(answered)}")
        return 0

    print("No variant got a reply.")
    print("Check the packet capture taken alongside this run:")
    print("  * packets from 192.168.4.1 present  -> local firewall ate them")
    print("  * nothing inbound at all            -> device is not answering Wsu")
    return 2


# Ports to compare when deciding whether the provisioning listener is running.
# The controls matter: ESP32/lwIP rate-limits ICMP error generation, so a single
# silent result proves nothing. Interleaving with known-closed ports and
# repeating shows whether the difference is real or just throttling.
PORTS_UNDER_TEST = [(2379, "provisioning"), (2378, "control"), (48291, "control")]


def ports(rounds=5):
    """Is anything listening on udp/2379? Interleaved ICMP-unreachable test.

    No root required. Sending to a closed UDP port makes the device emit an
    ICMP port-unreachable, which the kernel surfaces to a *connected* UDP
    socket as ConnectionRefusedError. Silence where controls are refused means
    something is bound. Silence everywhere means ICMP is throttled or filtered
    and the test is inconclusive -- which is why we repeat.
    """
    print(f"Interleaved port test against {DEVICE_IP}, {rounds} rounds.\n")
    header = "  round  " + "".join(f"{p}/{lbl:<9}" for p, lbl in PORTS_UNDER_TEST)
    print(header)

    results = {p: [] for p, _ in PORTS_UNDER_TEST}
    for i in range(1, rounds + 1):
        row = []
        for port, _ in PORTS_UNDER_TEST:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(2.0)
            try:
                s.connect((DEVICE_IP, port))
                s.send(SCAN_VERB)
                try:
                    s.recv(4096)
                    verdict = "REPLY"
                except socket.timeout:
                    verdict = "silent"
                except ConnectionRefusedError:
                    verdict = "closed"
            except OSError:
                verdict = "err"
            finally:
                s.close()
            results[port].append(verdict)
            row.append(verdict)
            time.sleep(1.2)
        print(f"  {i:<7}" + "".join(f"{v:<14}" for v in row))

    print()
    open_ports = [
        p for p, _ in PORTS_UNDER_TEST
        if all(v == "silent" for v in results[p])
    ]
    closed = [
        p for p, _ in PORTS_UNDER_TEST
        if all(v == "closed" for v in results[p])
    ]
    if 2379 in open_ports and closed:
        print("VERDICT: udp/2379 is OPEN -- a listener is bound, controls refused.")
        return 0
    if all(v == "silent" for vals in results.values() for v in vals):
        print("VERDICT: INCONCLUSIVE -- everything silent, ICMP likely filtered.")
        return 3
    if 2379 in closed:
        print("VERDICT: udp/2379 is CLOSED -- no provisioning listener running here.")
        return 1
    print("VERDICT: unstable results -- likely ICMP rate-limiting; rerun slower.")
    return 3


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "probe"
    if cmd == "probe":
        return probe()
    if cmd == "diag":
        return diag()
    if cmd == "ports":
        return ports()
    print(__doc__)
    print(f"Unknown command: {cmd!r}. Try: python3 {argv[0]} probe|diag|ports")
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
