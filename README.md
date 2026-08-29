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
| Robot's AP SSID | `litter-robot` |
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
its `litter-robot` access point. Note that it's Cycle + Empty — *not* the Reset
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

## Current status

- ✅ `probe` — read-only. Sends `Wsu,v1`, prints whatever comes back. Writes
  nothing to the device.
- ❌ Write path — not implemented, deliberately.

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
- [huntergregal/litterrobot_firmware](https://github.com/huntergregal/litterrobot_firmware) — firmware dumps
- [esphome-litter-robot](https://codeberg.org/Joseph-DiGiovanni/esphome-litter-robot) — replacement firmware
- [pylitterbot](https://github.com/natekspencer/pylitterbot) — cloud API client (not useful for provisioning, but good for control once connected)
- [Whisker — Onboarding your Litter-Robot 3 Connect](https://www.litter-robot.com/support/article/whisker-app-onboarding-your-litter-robot-3-connect/) — source for the pairing-mode button sequence
- [Whisker — Onboard troubleshooting guide](https://www.litter-robot.com/support/article/i-cannot-onboard-the-whisker-app/) — the 10-minute window and power-cycle retry

## Disclaimer

Not affiliated with or endorsed by Whisker. This is interoperability work on
hardware I own, so that it keeps working on my own network. Use at your own
risk.
