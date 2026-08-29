#!/usr/bin/env python3
"""Wait for a live onboarding window, then sweep the LR3 command vocabulary.

Liveness is defined as "the LR3 verb answers". The access point stays up and
udp/2379 stays bound after the onboarding timer expires, so neither of those
tells you anything. Every batch of probes is bracketed by a liveness check, and
the sweep aborts the moment the device stops answering -- otherwise a run of
"silent" results is indistinguishable from a closed window, which is the exact
mistake that wasted an earlier window.
"""
import socket, select, subprocess, sys, time

AP_IP = "192.168.4.1"
WAIT_MAX = int(sys.argv[1]) if len(sys.argv) > 1 else 600

_socks = []
for p in (2379, 2380):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.bind(("0.0.0.0", p))
        _socks.append(s)
    except OSError as e:
        print(f"(could not bind {p}: {e})")
_send = _socks[-1]


def ask(verb, wait=1.3, term=b"\r\n"):
    _send.sendto(verb + term, (AP_IP, 2379))
    end, out = time.time() + wait, []
    while time.time() < end:
        r, _, _ = select.select(_socks, [], [], 0.15)
        for s in r:
            d, _a = s.recvfrom(4096)
            out.append(d)
    return out


def alive():
    return bool(ask(b"LR3", 1.2))


def on_ap():
    out = subprocess.run(["ip", "-4", "-br", "addr"], capture_output=True, text=True).stdout
    return "192.168.4." in out


def rejoin():
    subprocess.run(["nmcli", "dev", "wifi", "connect", "Litter-Robot",
                    "password", "neverscoop"], capture_output=True)


print("Waiting for a LIVE window (a reply to 'LR3'), not just a visible AP.")
print(">>> Unplug the unit 15s, wait for solid blue, then hold Cycle+Empty. <<<\n")

deadline = time.time() + WAIT_MAX
while time.time() < deadline:
    if not on_ap():
        rejoin()
        time.sleep(3)
    if alive():
        print(f"=== LIVE at {time.strftime('%H:%M:%S')} -- sweeping ===\n")
        break
    time.sleep(4)
else:
    print("!! no live window within the wait period.")
    raise SystemExit(1)

# 'wsu' is the known verb, so sweep the whole <letter>su,v1 space rather than
# guessing English words. 'x' is skipped: xsu is the write/provisioning verb.
cands = [bytes([c]) + b"su,v1" for c in range(ord("a"), ord("z") + 1)
         if chr(c) != "x"]
cands += [b"cfg,v1", b"get,v1", b"inf,v1", b"ver,v1", b"sta,v1", b"cnf,v1",
          b"dev,v1", b"sys,v1", b"net,v1", b"aws,v1", b"crt,v1", b"top,v1",
          b"srl,v1", b"idn,v1", b"Cfg", b"Inf", b"Ver", b"Sta", b"Dev",
          b"Net", b"Aws", b"Top", b"Crc", b"Cer", b"Sn", b"Wsu,v1"]

hits = []
for i, v in enumerate(cands):
    rep = ask(v)
    if rep:
        for d in rep:
            print(f"  *** {v.decode():10} -> {d[:200]!r}")
        hits.append((v, rep))
    else:
        print(f"  {v.decode():10} -> silent")
    if i % 6 == 5 and not alive():
        print(f"\n!! window died after {i+1} probes -- everything above the last")
        print("   liveness check is valid; nothing after it is.")
        break

print()
print("ANSWERED:", [v.decode() for v, _ in hits] or "none")
print("still live:", alive())
