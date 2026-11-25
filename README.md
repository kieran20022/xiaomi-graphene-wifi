# Graphene Heater

A small Windows tray app for the **Xiaomi Smart Graphene Heater** (EAN 6932554440725, model `xiaomi.heater.ma8`).
It talks to the heater directly over your LAN (miIO/MIoT protocol, UDP 54321), with no cloud round-trips.

## Features

Everything the heater exposes over MIoT:

| Control | Notes |
|---|---|
| Power on / off | Also available from the tray icon's right-click menu |
| Target temperature | 22–28 °C, used in Thermostat mode |
| Mode | Thermostat · High · Low · Fan |
| Room temperature | Shown in the dial and the tray tooltip |
| Oscillation | Horizontal swing |
| Child lock | Locks the physical buttons |
| Beep | Button sounds |
| Display | Indicator light on/off |
| Auto shut-off timer | 1–8 h, with remaining time |
| Fault status | Warning banner if the heater reports a sensor fault |

The tray icon is orange when the heater is on, grey when off, and dimmed when unreachable.

## Install

1. Get `GrapheneHeater.exe`: either build it with `python build.py` (output in `dist\`) or use a prebuilt copy.
2. Move it somewhere permanent **before pinning it**, e.g. `%LOCALAPPDATA%\Programs\GrapheneHeater\GrapheneHeater.exe`.
   Taskbar pins and autostart point to this exact path.
3. Start it. The Settings screen opens on first run. Enter your heater's **IP address** and **token**
   (see below) and click *Save & connect*. The status dot turns green once the heater answers.
4. Optional: tick **Start with Windows** so the app loads into the tray every time you log in.

## Putting it on the taskbar

The app can sit in two places, and you can use either or both:

**Pinned to the taskbar (an app button)**
- In File Explorer, right-click `GrapheneHeater.exe` → *Show more options* → *Pin to taskbar*, or
- start the app, right-click its button on the taskbar → *Pin to taskbar*.

Clicking the pinned button opens the control panel, and starts the app first if it isn't running.

**In the system tray (next to the clock)**
The tray icon appears automatically while the app runs. Windows 11 hides new tray icons behind the `^` arrow at
first. To keep it always visible, open *Settings → Personalization → Taskbar → Other system tray icons* and switch
on the **Graphene Heater** entry, or drag the icon from the `^` overflow onto the taskbar.

Left-click the tray icon to show or hide the panel. Right-click it to turn the heater on or off, or to quit.
Closing the panel (✕ or Esc) only hides it. Use *Quit* to exit the app.

## Finding the IP address and token

The heater only accepts commands signed with its 32-character device token, which is stored in your Xiaomi account.
The easiest way to get it is
[Xiaomi-cloud-tokens-extractor](https://github.com/PiotrMachowski/Xiaomi-cloud-tokens-extractor):

1. Download `token_extractor.exe` from its Releases page and run it.
2. Log in with your Xiaomi Home account and pick the server region your app uses (e.g. `de` for Europe).
3. Find the heater (model `xiaomi.heater.ma8`) in the list and copy its **IP** and **TOKEN**.

You can also find the IP in the Xiaomi Home app (heater → ⋯ → *Network info*) or in your router's list of
connected devices. Give the heater a fixed or reserved IP in your router so it doesn't change.

The token changes if the heater is reset or paired again in the Xiaomi Home app. If that happens, fetch it again.

## Troubleshooting

- **Red dot / "No reply from the heater"**: either the token is wrong or the heater is offline. Check that the PC
  and the heater are on the same network, and that the IP is still correct.
- Logs are written to `%APPDATA%\GrapheneHeater\app.log`.

## Development

```
pip install pywebview pystray pillow cryptography requests pyinstaller
python app.py
```

- `heater/miio.py`: miIO protocol (handshake, AES-128-CBC, MIoT get/set properties)
- `heater/device.py`: maps the MIoT spec to named features. If another model is detected it downloads that spec
  from miot-spec.org, so similar Xiaomi heaters (e.g. `ma8a`/`ma8b`, which number their modes differently) work too.
- `ui/index.html`: the panel UI
- `app.py`: tray icon, window, settings and autostart

Config (`config.json`) and logs are stored in `%APPDATA%\GrapheneHeater\`.
