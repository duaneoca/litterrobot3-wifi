# Litter-Robot 3 Connect — Wi-Fi re-provisioning without the app

Change the Wi-Fi network on a **Litter-Robot 3 Connect** by talking to the device
directly over its local UDP provisioning protocol, instead of going through the
Whisker phone app.

This exists because on some early-release LR3 Connect units, every normal method
fails: the app's "Update Network" flow, the button sequences, and full
re-onboarding. If you've moved house, changed routers, or renamed your SSID and
the app simply will not re-provision the robot, you're in the right place.

> **Status: partial.** The read-only `probe` step works and is safe to run. The
> write path — actually setting a new SSID and password — is **not implemented
> yet**. See [Current status](#current-status) before you get your hopes up.

## Why the app fails but a laptop should work

To be provisioned, the robot starts its own Wi-Fi access point with no internet
access. Phones fight this: Android's smart-network-switch drops off a network
with no connectivity, and iOS won't hold one either. The app gets bounced off
the robot's AP mid-conversation.

A laptop stays joined to that AP reliably, and can send the provisioning packets
itself.

## The protocol

While in onboarding/AP mode, the LR3 Connect (an ESP32-WROOM-32D) speaks a
**plain-text UDP** protocol:

| | |
|---|---|
| Robot's AP SSID | `Litter-Robot` (exact case — not `litter-robot`) |
| Robot's AP password | `neverscoop` |
| Robot IP | `192.168.4.1` |
| You → robot | UDP port **2379** |
| Robot → you | replies to UDP port **2380** (bind that as your source port) |

The initial-onboarding message flow, as reverse-engineered by
[elttam](https://www.elttam.com/blog/re-of-lr3):

```
app   → "Wsu,v1"                  # ask the device to scan for networks
robot → <visible SSID list> + "Rdy,LR3<ID>"
app   → "AOK"  then "DATA,CERT"   # AWS IoT certificate, sent line by line
app   → "LN,<n>..."   robot → "AOK,<n>"
app   → "DONE,<CRC32>"            # then the same again for "DATA,KEY"
app   → final config line, carrying the home Wi-Fi credentials:
        "Xsu,<SSID>,<password>,,,2000,LR3,<Id>,<CRC>,LR3<Serial>,<aws-endpoint>,prod/cloud/<..>,prod/lr3/<..>"
```

Config line field order:
`Type,SSID,Password,Dispatch,Port,Web,Type,Id,CRC,Serial,endpoint,cloud,lr3`

## Putting the robot in pairing mode

On the LR3 Connect's control panel, **press and hold `Cycle` + `Empty` together
for about 3 seconds, until the Power button glows blue.**

A blue Power button means the robot is in onboarding mode and is broadcasting
its `Litter-Robot` access point. Note that it's Cycle + Empty — *not* the Reset
button, which is the usual wrong guess.

Rather than trusting the LED, confirm the AP is actually up from your computer:

```bash
# Linux
nmcli device wifi list --rescan yes | grep -i litter-robot

# macOS
system_profiler SPAirPortDataType | grep -i -A2 litter-robot
```

Things worth knowing once you're in:

- **You have about 10 minutes.** Whisker's docs say to complete the process
  within that window.
- **The AP disappears the moment the robot joins a network.** If the
  `litter-robot` SSID vanishes mid-session, the robot either connected to
  something or dropped out of onboarding mode — re-do the button hold.
- **Success looks like:** the blue Power light turns off and the Ready light
  turns blue. (Which, if you're reading this repo, is probably the thing that
  isn't happening.)
- **To retry from a clean slate:** unplug the unit from its base for 15
  seconds, wait for the solid blue light, then repeat the button hold.

## Usage

```bash
# 1. Put the LR3 into onboarding/AP mode (Cycle + Empty, ~3s, Power goes blue).
# 2. Join this computer to the "litter-robot" Wi-Fi network (password: neverscoop).
#    Your IP on that interface should be 192.168.4.x.
# 3. Probe it:
python3 litterbot_wifi.py probe
```

A working probe prints the device's scanned SSID list and a line like
`Rdy,LR3<ID>`. That confirms the local UDP channel works and reveals the device
ID. Requires Python 3, no dependencies.

macOS may prompt for Local Network permission for your terminal — allow it.

## Field notes

Things learned the hard way on a real unit. Each one produces a *silent* failure
that looks identical to "the robot is ignoring me."

**The AP SSID is `Litter-Robot`, not `litter-robot`.** Case matters if you script
an exact-match connect. Several writeups (and earlier versions of this repo) have
it lowercase.

**A default-deny firewall eats the reply.** The robot answers *to* your udp/2380,
and depending on its source port your firewall may see an unsolicited inbound
datagram rather than a conntrack-matched reply. On Linux with `ufw` active:

```bash
sudo ufw allow from 192.168.4.0/24 to any port 2380 proto udp comment 'litter-robot'
```

**If you have a second interface, packets can leak out of it.** With Ethernet up
and Wi-Fi *not* joined to the AP, there is no `192.168.4.0/24` link route, so
traffic for `192.168.4.1` follows your default route out the Ethernet toward the
internet and vanishes. `litterbot_wifi.py` now preflights `ip route get` and
refuses to send unless the route is on-link. Check it yourself with:

```bash
ip route get 192.168.4.1     # must say "dev <wifi>", not "via <gateway>"
```

**Not every packet from the robot is a protocol reply.** Once NetworkManager
adopts the AP as a nameserver, your machine sends DNS to `192.168.4.1` and the
robot answers with ICMP port-unreachables. Counting those as "the robot is
transmitting" gives a false firewall diagnosis. Match on
`udp and src 192.168.4.1 and dst port 2380` instead.

**The onboarding window is ~10 minutes and it really does close.** Have your
tooling ready *before* you press the buttons.

## The AP and the station are the same chip

The ESP32 runs its AP and its normal Wi-Fi connection at the same time, on MAC
addresses that differ only in the second nibble of the first octet:

```
3c:71:bf:29:d3:6c   station  (on your LAN, e.g. 192.168.2.202)
3e:71:bf:29:d3:6c   AP BSSID (192.168.4.1)
```

Both are Espressif (`3c:71:bf`). So if the robot is on your LAN at all, you can
find it by MAC prefix — `ip neigh | grep -i 3c:71:bf` — and talk to it there
without touching the AP.

**The provisioning listener appears to be transient.** Minutes after arming
pairing mode, `udp/2379` measured open on the robot's *station* address (silent
5/5 rounds while control ports were refused 5/5). Half an hour later the same
test on the same host read closed 4/5. Both runs were clean; the device state
changed between them. Working theory: the listener is bound only while the unit
is in onboarding mode, and it binds to the station address rather than
`192.168.4.1`. Treat "2379 is open" as time-dependent and re-measure every time.
Point the tools at whichever address you mean with:

```bash
LR3_HOST=192.168.2.202 python3 litterbot_wifi.py probe
```

Confirming a UDP port is open without root: send to it and to a control port,
and watch for ICMP unreachable. Interleave several rounds — ESP32/lwIP rate-limits
ICMP errors, so a single silent result proves nothing.

```
round  2379      2378 ctl  48291 ctl
1      open?     CLOSED    CLOSED
...    (stable across 5 rounds -> genuinely open, not rate-limiting)
```

## Current status

- ✅ `probe` — read-only. Sends `Wsu,v1`, prints whatever comes back. Writes
  nothing to the device.
- ✅ `diag` — tries message and source-port variants, with an on-link preflight.
- ✅ `probe_diag.sh` — runs `diag` under a `tcpdump` capture, so you can tell a
  dropped reply apart from a silent device. Needs root.
- ❌ Write path — not implemented, deliberately.

**Open puzzle on the test unit:** `udp/2379` measured open on the robot's LAN
address shortly after arming pairing mode (and closed again later), but it never
answers `Wsu,v1` there — not with CRLF, bare LF, no
terminator, broadcast, or an ephemeral source port. Nothing is dropping the
reply; the device simply doesn't send one. The working hypothesis is that the
listener ignores scan requests unless the unit is actually in onboarding mode,
and that this early-release unit doesn't enter that mode properly — which is the
original bug. A packet capture of the app mid-conversation is still the thing
that would settle it.

Two questions have to be answered before writing bytes to a device that has no
easy recovery path:

1. **Does a Wi-Fi-only change require re-sending the AWS certificate and RSA
   private key, or does the device reuse what it has stored and accept just the
   `Xsu,...` line?** elttam documented *initial* onboarding, which sends the
   certs. "Update Network" may be far shorter.
2. **What are a given unit's real field values** — `Id`, `CRC`, `Serial`, the
   AWS endpoint, and the `prod/cloud/*` / `prod/lr3/*` topic strings?

Both are answered by capturing one real exchange from the app with Wireshark or
tcpdump on UDP 2379–2380. Usefully, **this works even if the app fails at the
final join** — the outgoing packets still reveal the format and the device's
values. The plan is then to replay the final config line with the SSID and
password swapped and everything else byte-identical.

If you capture an exchange — especially an "Update Network" one — please open an
issue. That's the missing piece.

### Handling your capture safely

A capture of this exchange contains **your home Wi-Fi password in plain text**,
plus the unit's AWS IoT certificate, RSA private key, and serial number. Put
captures in `captures/`, which is git-ignored here, and redact before sharing
one publicly.

## Known constraints

- 2.4 GHz only — the LR3 has no 5 GHz radio, and is not IPv6-compatible.
- Wi-Fi passwords seen in the wild are 8–31 characters, with no backslash,
  forward slash, period, backtick, or spaces.

## Fallback: ditch the cloud entirely

If the UDP path is a dead end — or you'd rather not depend on Whisker's cloud at
all — the ESP32 can be reflashed with
[ESPHome firmware](https://codeberg.org/Joseph-DiGiovanni/esphome-litter-robot)
for fully-local control and native Home Assistant integration.

Caveats: it's tested on the LR4 and only *suspected* to work on the LR3; it
requires opening the unit and attaching an ESP-Prog-2 to flash; it voids your
warranty. It is reversible by flashing the stock firmware back, and the safety
logic lives on a separate MCU that this doesn't touch.

## Sources

- [elttam — Reverse engineering the Litter-Robot 3](https://www.elttam.com/blog/re-of-lr3) — the protocol spec this is built on
- [huntergregal/litterrobot_firmware](https://github.com/huntergregal/litterrobot_firmware) — firmware dumps, but **LR4 only**; it contains no LR3 images
- [esphome-litter-robot](https://codeberg.org/Joseph-DiGiovanni/esphome-litter-robot) — replacement firmware
- [pylitterbot](https://github.com/natekspencer/pylitterbot) — cloud API client (not useful for provisioning, but good for control once connected)
- [Whisker — Onboarding your Litter-Robot 3 Connect](https://www.litter-robot.com/support/article/whisker-app-onboarding-your-litter-robot-3-connect/) — source for the pairing-mode button sequence
- [Whisker — Onboard troubleshooting guide](https://www.litter-robot.com/support/article/i-cannot-onboard-the-whisker-app/) — the 10-minute window and power-cycle retry

## Disclaimer

Not affiliated with or endorsed by Whisker. This is interoperability work on
hardware I own, so that it keeps working on my own network. Use at your own
risk.
