# Litter-Robot 3 Connect — Wi-Fi re-provisioning project

## Goal
Change the Wi-Fi network on an **early-release Litter-Robot 3 Connect** without the
Whisker phone app. Every normal method (app "Update Network", button dances,
re-onboarding from the phone) has been tried repeatedly and failed. We are now
bypassing the app by talking to the device directly over its local protocol.
Fallback goal: if that fails, cut Whisker out entirely via custom firmware.

## Key finding — the "atypical protocol"
The LR3 Connect (**ESP32-WROOM-32D**) is provisioned over a **plain-text UDP**
protocol while the device is in onboarding/AP mode:

- Robot's own AP: SSID **`Litter-Robot`** (exact case), password **`neverscoop`**
- Robot IP: **`192.168.4.1`**
- App → robot: **UDP port 2379**
- Robot → app: replies to **UDP port 2380** (so bind local source port 2380)

Reverse-engineered message flow (elttam, initial onboarding):
```
app  → "Wsu,v1"                 # scan request
robot→ <visible SSID list> + "Rdy,LR3<ID>"
app  → "AOK"  then "DATA,CERT"  # AWS IoT cert, sent line-by-line
app  → "LN,<n>..."  / robot → "AOK,<n>"
app  → "DONE,<CRC32>"           # repeats for "DATA,KEY" (RSA private key)
app  → final config line (carries the home Wi-Fi creds):
       "Xsu,<SSID>,<password>,,,2000,LR3,<Id>,<CRC>,LR3<Serial>,<aws-endpoint>,prod/cloud/<..>,prod/lr3/<..>"
```
Config line field order:
`Type,SSID,Password,Dispatch,Port,Web,Type,Id,CRC,Serial,endpoint,cloud,lr3`

## Why the phone fails but a laptop should work
The usual failure is the phone bouncing off the credential-less `Litter-Robot`
AP (Android smart-network-switch; iOS won't hold a "no internet" network). A
laptop stays joined reliably and can send the UDP packets itself.

## Session findings (2026-08-29, real unit)
- The robot is **already joined to the home Wi-Fi** as `192.168.2.202`
  (MAC `3c:71:bf:29:d3:6c`). Its AP BSSID is `3e:71:bf:29:d3:6c` — same ESP32,
  station vs AP interface. Find it on any LAN with `ip neigh | grep -i 3c:71:bf`.
- **`udp/2379` open/closed is TIME-DEPENDENT — the listener looks transient.**
  Minutes after arming pairing mode: silent 5/5 on the STA address while controls
  were refused 5/5 (= open). ~30 min later: closed 4/5 on the same host. Both runs
  clean. Theory: the listener exists only during onboarding mode, bound to the
  STA address, not `192.168.4.1`. ALWAYS re-measure; never assume.
- The single "closed on 192.168.4.1" sample was taken without interleaved
  controls, so it is weak. Re-run `ports` against 192.168.4.1 during a live
  pairing window before trusting it.
- **It still does not answer `Wsu,v1`** — not CRLF / bare LF / no terminator /
  broadcast / ephemeral source port, on either address. Confirmed by packet
  capture that no reply is emitted; this is NOT a firewall drop.
- Robot answers ICMP echo on both addresses. No TCP ports open on either.
- Working hypothesis: the listener ignores scan requests unless the unit is
  genuinely in onboarding mode, and this early-release unit isn't entering it.

## Traps that produce silent, identical-looking failures
- SSID case: `Litter-Robot`, not `litter-robot`.
- `ufw` default-deny eats the inbound reply to udp/2380.
- Dual-homed: with Ethernet up and Wi-Fi off the AP, `192.168.4.1` leaks out the
  default route. `_preflight()` in the script now blocks this.
- The robot's ICMP port-53-unreachables (answering our DNS) are not protocol
  replies — don't count them as evidence the device is transmitting.

## Current state / files
- `litterbot_wifi.py` — `probe` (read-only `Wsu,v1`) and `diag` (message +
  source-port variants, with an on-link route preflight). Honours `LR3_HOST` to
  target the robot on a normal LAN instead of `192.168.4.1`. Write path NOT
  implemented.
- `run_probe.sh` — join AP, probe, restore previous Wi-Fi (for single-NIC machines).
- `probe_diag.sh` — runs `diag` under tcpdump; needs root. Distinguishes a
  dropped reply from a silent device.

## Pairing / onboarding mode (verified against Whisker support docs)
- Enter it: hold **`Cycle` + `Empty` together ~3 s, until the Power button turns
  blue.** (Not the Reset button.) Blue Power = AP is broadcasting.
- Verify from the laptop, not the LED:
  `nmcli device wifi list --rescan yes | grep -i litter-robot`
- Window is ~10 minutes; the AP vanishes the instant the robot joins a network.
- Connected state: blue Power light off, Ready light blue.
- Clean retry: unplug from base 15 s, wait for solid blue, redo the hold.

## Next steps (in order)
1. Put LR3 in onboarding mode (above); join laptop to `Litter-Robot` / `neverscoop`.
2. Run: `python3 litterbot_wifi.py probe`  → expect a `Rdy,LR3<ID>` reply.
   (macOS: allow Terminal's Local Network permission if prompted.)
3. Capture ONE real app exchange with Wireshark/tcpdump on UDP 2379/2380 to learn:
   - whether "Update Network" re-sends certs or just the short config line, and
   - this unit's real values (`Id`, `CRC`, `Serial`, AWS endpoint, topic strings).
   This works even if the app fails at the final join — the outgoing packets
   still reveal the format and the device values.
4. Implement the write path: replay the exact final config line with SSID +
   password swapped, everything else byte-identical.

## Open questions / risks
- Does WiFi-only re-provisioning require re-sending the AWS cert + RSA key, or
  does the device reuse stored creds and accept just the `Xsu,...` line?
  (elttam documented *initial* onboarding, which sends certs.)
- Password constraints seen in the wild: 8–31 chars, no `\ / . ` or spaces.
- LR3 supports 2.4 GHz only (no 5 GHz), and is not IPv6-compatible.

## Nuclear option (if UDP path fails, or to ditch Whisker permanently)
Reflash the ESP32 with ESPHome for fully-local control + native Home Assistant
integration (user already runs Home Assistant).
- Repo: https://codeberg.org/Joseph-DiGiovanni/esphome-litter-robot
- Caveats: tested on LR4 (LR3 "suspected similar", unverified); requires opening
  the unit and attaching an **ESP-Prog-2** to flash; voids warranty; reversible
  by flashing stock firmware back; safety logic is on a separate MCU (untouched).

## Sources
- elttam teardown (protocol spec): https://www.elttam.com/blog/re-of-lr3
- Firmware dumps: https://github.com/huntergregal/litterrobot_firmware
- ESPHome firmware: https://codeberg.org/Joseph-DiGiovanni/esphome-litter-robot
  (NOTE: huntergregal/litterrobot_firmware has LR4 images ONLY -- no LR3)
- Cloud API (not useful for provisioning): https://github.com/natekspencer/pylitterbot
- Whisker onboarding doc: https://www.litter-robot.com/support/article/whisker-app-onboarding-your-litter-robot-3-connect/
- Whisker onboarding troubleshooting: https://www.litter-robot.com/support/article/i-cannot-onboard-the-whisker-app/
