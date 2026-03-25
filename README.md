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
| `robot_ip_<address>` | Optional: pin a robot to a specific IP for direct local connection |

### Pinning a robot's IP address

By default the plugin uses the IP address reported by the Roborock cloud. If your vacuum has
a static IP (via DHCP reservation), you can pin it to guarantee local communication even if
the cloud reports a stale address.

After the first successful connection, the plugin logs each robot's **node address** and
**discovered IP**:

```
Device: 'Living Room'  address=livingroom  discovered_ip=192.168.1.50  ip_override=(none — set robot_ip_livingroom to pin)
```

Add a Custom Parameter using that address:

| Parameter | Example value |
|-----------|---------------|
| `robot_ip_livingroom` | `192.168.1.50` |
| `robot_ip_kitchen` | `192.168.1.51` |

When an IP override is set, the plugin connects directly via local TCP (port 58867) and falls
back to cloud MQTT only if the local connection fails.

> **Note:** Cloud authentication is still required once on first install — the local key used
> to authenticate the direct connection is obtained during that initial login.

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

**Commands:**

| Command | Description |
|---------|-------------|
| Set Fan Speed | Quiet / Balanced / Turbo / Max |
| Set Water Level | Off / Mild / Moderate / Intense |
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

```
ISY / PG3x  →  LAN port 58867  →  Roborock vacuum (preferred)
ISY / PG3x  →  Internet MQTT   →  Roborock cloud  →  vacuum (fallback)
```

The plugin uses `python-roborock` which automatically negotiates local vs. cloud per device. Assign a static IP (DHCP reservation) to your vacuum for reliable local communication.
