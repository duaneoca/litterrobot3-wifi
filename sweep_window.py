#!/usr/bin/env python3 -u
"""Wait for a live onboarding window, then sweep the LR3 command vocabulary.

Liveness is defined as "the LR3 verb answers". The access point stays up and
udp/2379 stays bound after the onboarding timer expires, so neither of those
tells you anything. Every batch of probes is bracketed by a liveness check, and
the sweep aborts the moment the device stops answering -- otherwise a run of
"silent" results is indistinguishable from a closed window, which is the exact
mistake that wasted an earlier window.
"""
import socket, select, subprocess, sys, time

# Unbuffered stdout. These scripts are always run under `timeout ... | tee`,
# and block buffering means a SIGTERM at the end of the run discards the whole
# log -- which has already cost one full onboarding window of observations.
try:
    sys.stdout.reconfigure(line_buffering=True)
except AttributeError:
    pass

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


TARGETS = ["192.168.4.1", "192.168.2.202"]   # AP address, and LAN address via
                                             # the router -- poll both, since
                                             # the responder binds to whichever
                                             # the device currently holds.
TARGET = AP_IP


def ask(verb, wait=1.3, term=b"\r\n", host=None):
    _send.sendto(verb + term, (host or TARGET, 2379))
    end, out = time.time() + wait, []
    while time.time() < end:
        r, _, _ = select.select(_socks, [], [], 0.15)
        for s in r:
            d, _a = s.recvfrom(4096)
            out.append(d)
    return out


def alive(host=None):
    return bool(ask(b"LR3", 1.2, host=host))


def find_live():
    """Return the address that answers, or None. Only a reply counts."""
    for host in TARGETS:
        try:
            if alive(host):
                return host
        except OSError:
            continue
    return None


def on_ap():
    out = subprocess.run(["ip", "-4", "-br", "addr"], capture_output=True, text=True).stdout
    return "192.168.4." in out


def ap_visible():
    out = subprocess.run(["nmcli", "-t", "-f", "SSID", "dev", "wifi", "list",
                          "--rescan", "yes"], capture_output=True, text=True).stdout
    return any(line.strip() == "Litter-Robot" for line in out.splitlines())


def rejoin():
    """Only attempt a join when the AP is actually on the air."""
    if not ap_visible():
        return False
    subprocess.run(["nmcli", "--wait", "8", "dev", "wifi", "connect",
                    "Litter-Robot", "password", "neverscoop"],
                   capture_output=True)
    return on_ap()


print("Waiting for a LIVE window (a reply to 'LR3'), not just a visible AP.")
print(">>> Unplug the unit 15s, wait for solid blue, then hold Cycle+Empty. <<<\n")

deadline = time.time() + WAIT_MAX
last_note = 0.0
while time.time() < deadline:
    host = find_live()
    if host:
        TARGET = host
        print(f"=== LIVE on {host} at {time.strftime('%H:%M:%S')} -- sweeping ===\n")
        break
    if not on_ap():
        rejoin()
    if time.time() - last_note > 30:
        state = "on AP" if on_ap() else ("AP visible" if ap_visible() else "no AP")
        print(f"  [{time.strftime('%H:%M:%S')}] waiting... ({state}, no reply yet)")
        last_note = time.time()
    time.sleep(3)
else:
    print("!! no live window within the wait period.")
    raise SystemExit(1)

# We are hunting a config/status DUMP verb. Known good: wsu,v1 / Rdy / LR3.
# 'x' is skipped everywhere: xsu is the write/provisioning verb -- no writes.
#
# Strategy, cheapest-signal first:
#  (a) whole <letter>su,v1 space (wsu's siblings -- most likely to be real)
#  (b) 3-letter config/status tokens, both bare and ,v1, both cases
#  (c) the known verbs with alternate args, in case an arg selects "dump"
def variants(tok):
    b = tok if isinstance(tok, bytes) else tok.encode()
    out = [b, b + b",v1", b.capitalize(), b.upper()]
    seen, uniq = set(), []
    for x in out:
        if x not in seen and b"x" != x[:1]:
            seen.add(x); uniq.append(x)
    return uniq

cands = [bytes([c]) + b"su,v1" for c in range(ord("a"), ord("z") + 1)
         if chr(c) != "x"]
for tok in ["cfg", "cnf", "con", "get", "inf", "ver", "sta", "dev", "sys",
            "net", "aws", "crt", "cer", "key", "top", "srl", "idn", "mac",
            "sta", "dmp", "dump", "all", "reg", "prm", "par", "rd"]:
    cands += variants(tok)
# Known verbs with alternate args -- maybe an arg switches mode to "dump".
cands += [b"wsu,v2", b"wsu,v0", b"Rdy,v1", b"LR3,v1", b"LR3,cfg",
          b"LR3,all", b"LR3?", b"Rdy,all", b"Wsu,v1"]
# De-dup while preserving order.
_seen=set(); cands=[c for c in cands if not (c in _seen or _seen.add(c))]

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
