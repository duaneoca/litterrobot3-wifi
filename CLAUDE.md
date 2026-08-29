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

- Robot's own AP: SSID **`litter-robot`**, password **`neverscoop`**
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
The usual failure is the phone bouncing off the credential-less `litter-robot`
AP (Android smart-network-switch; iOS won't hold a "no internet" network). A
laptop stays joined reliably and can send the UDP packets itself.

## Current state / files
- `litterbot_wifi.py` — implements the **safe, read-only** `probe` step only:
  sends `Wsu,v1`, prints the reply (confirms reachability + reveals `LR3<ID>`).
  The write/provisioning path is intentionally NOT implemented yet.

## Pairing / onboarding mode (verified against Whisker support docs)
- Enter it: hold **`Cycle` + `Empty` together ~3 s, until the Power button turns
  blue.** (Not the Reset button.) Blue Power = AP is broadcasting.
- Verify from the laptop, not the LED:
  `nmcli device wifi list --rescan yes | grep -i litter-robot`
- Window is ~10 minutes; the AP vanishes the instant the robot joins a network.
- Connected state: blue Power light off, Ready light blue.
- Clean retry: unplug from base 15 s, wait for solid blue, redo the hold.

## Next steps (in order)
1. Put LR3 in onboarding mode (above); join laptop to `litter-robot` / `neverscoop`.
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
- Cloud API (not useful for provisioning): https://github.com/natekspencer/pylitterbot
- Whisker onboarding doc: https://www.litter-robot.com/support/article/whisker-app-onboarding-your-litter-robot-3-connect/
- Whisker onboarding troubleshooting: https://www.litter-robot.com/support/article/i-cannot-onboard-the-whisker-app/
