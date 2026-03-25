# udi-roborock-poly

GPL-3.0 License — Polyglot v3 NodeServer for Roborock vacuums, using [python-roborock](https://github.com/Python-roborock/python-roborock) as the backend.

> **License note:** This plugin uses `python-roborock` which is GPL-3.0. The plugin is therefore also GPL-3.0.

## Features

- **One node per vacuum** discovered on your Roborock account
- **State tracking** — Idle, Cleaning, Returning, Charging, Paused, Error, Emptying Bin, Washing Mop
- **Battery, fan speed, error code, clean area and time** updated every 30 seconds
- **Consumable wear** (main brush, side brush, filter) updated every 5 minutes
- **Room cleaning** — individual rooms shown by name in ISY dropdown (fetched from your map)
- **Fan speed and water level control**
- **Works across VLANs** — prefers local LAN (port 58867), falls back to cloud MQTT automatically
- **ISY programs** — trigger automations on vacuum state, battery level, or error codes

## Requirements

- Python 3.11+
- Roborock account (the same login used in the Roborock app)
- `python-roborock` and `udi_interface` (installed by `install.sh`)

## Installation

Clone directly on your eisy:

```bash
cd /home/admin
git clone https://github.com/csteenwyk/udi-roborock-poly.git
cd udi-roborock-poly
chmod +x install.sh
./install.sh
```

## First-Time Authentication

Roborock uses email + one-time code authentication (no password).

1. In PG3x, add the NodeServer and set `email` in **Custom Parameters**
2. Click **Request Login Code** on the controller node — a code is sent to your email
3. Enter the code in the `login_code` Custom Parameter
4. The plugin exchanges the code for credentials, **caches them securely in Polyglot**, and clears the code field
5. Future restarts use the cached credentials automatically — no re-authentication needed

## Configuration

| Parameter | Description |
|-----------|-------------|
| `email` | Your Roborock account email **(required)** |
| `login_code` | One-time code from email (set once to authenticate, then cleared) |

## Nodes

### Controller
| Command | Description |
|---------|-------------|
| Re-Discover | Re-query devices and refresh room list |
| Request Login Code | Send verification code to configured email |

### Vacuum (one per device)

**Drivers:**

| Driver | Description |
|--------|-------------|
| ST | State: Idle / Cleaning / Returning / Charging / Paused / Error / Emptying Bin / Washing Mop / Charging Complete / Offline |
| BATLVL | Battery % |
| GV1 | Fan speed: Quiet / Balanced / Turbo / Max |
| GV2 | Error code (0 = no error) |
| GV3 | Clean area this session (m²) |
| GV4 | Clean time this session (minutes) |
| GV5 | Main brush remaining % |
| GV6 | Side brush remaining % |
| GV7 | Filter remaining % |
| GV8 | Water box attached |
| GV9 | Water level (current read-back) |
| GV10 | Mop mode: Standard / Deep / Deep+ |
| GV11 | Child lock: On / Off |

**Commands:**

| Command | Description |
|---------|-------------|
| Set Fan Speed | Quiet / Balanced / Turbo / Max |
| Set Water Level | Off / Mild / Moderate / Intense |
| Set Mop Mode | Standard / Deep / Deep+ |
| Child Lock | On / Off |
| Clean Room | Pick a room by name from ISY dropdown |
| Start Cleaning | Start a full clean |
| Stop | Stop current task |
| Pause | Pause current task |
| Return to Dock | Send vacuum home |
| Locate (Find Me) | Play audible alert to find the vacuum |

## ISY Programs

```
If 'Roborock' State is Charging Complete
Then ...

If 'Roborock' Battery is below 20
Then ...

If 'Roborock' Error is not 0
Then ...

If 'Roborock' Main Brush is below 20
Then Send Notification 'Time to replace main brush'
```

## Network Notes

The plugin uses `python-roborock` which automatically negotiates local vs. cloud communication per device — no manual IP configuration needed. If your vacuum is reachable on the LAN it will be used directly; otherwise the cloud MQTT path is used as fallback.
