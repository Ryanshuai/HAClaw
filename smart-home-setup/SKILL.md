---
name: smart-home-setup
description: "Set up or migrate a complete smart home system on Raspberry Pi: Zigbee2MQTT + Python automation + Apple HomeKit. Use this skill when the user mentions smart home setup, Zigbee2MQTT installation, Home Assistant migration, RPi home automation, HomeKit bridge setup, or wants to deploy/update automation rules on their smart home Pi. Also trigger when they mention adding new Zigbee devices, creating automation rules, or troubleshooting their HAClaw setup."
---

# Smart Home Setup — Zigbee2MQTT + Python + HomeKit on Raspberry Pi

This skill guides you through setting up a lightweight smart home stack on a Raspberry Pi, replacing Home Assistant with direct Zigbee2MQTT control, a Python automation service, and Apple HomeKit integration.

## Architecture

```
Zigbee Devices → Coordinator (USB) → RPi
  ├── Zigbee2MQTT (:8080)  — device management
  ├── Mosquitto (:1883)    — MQTT message bus
  ├── Python/FastAPI (:8000) — automation rules + REST API
  └── Homebridge (:51826)  — Apple HomeKit bridge
```

## Phase -1: Hardware Selection

If the user is starting from scratch or buying new hardware, help them choose compatible components. If they share product links (Amazon, Taobao, AliExpress, etc.), read the product description and check compatibility.

### Raspberry Pi
Any model works. Choose based on budget and availability:
- **RPi 3B** — 1GB RAM, enough for this stack (~400MB used). Cheapest option.
- **RPi 4** — 2/4/8GB, overkill but fine. USB 3.0 ports may cause Zigbee interference — use a short USB extension cable for the coordinator.
- **RPi 5** — Same as 4, newest.
- **RPi Zero 2W** — Works but tight on RAM (512MB). Not recommended.

Also need: SD card (16GB+), USB-C power supply (5V 3A), ethernet cable or WiFi.

### Zigbee Coordinator (USB Dongle)
This is the bridge between Zigbee devices and the RPi. Must be Z2M compatible.

**Recommended (widely tested with Z2M):**
- **SONOFF Zigbee 3.0 USB Dongle Plus-E** (EFR32MG21, model ZBDongle-E) — best value
- **SONOFF Zigbee 3.0 USB Dongle Plus-P** (CC2652P) — also great
- **ITead/SONOFF ZBDongle** variants — check the chip matters more than the brand
- **Conbee II / Conbee III** (Dresden Elektronik) — well supported
- **SMLIGHT SLZB-06/07** — Ethernet + USB options
- **TubesZB** coordinators

**Check compatibility**: The key factor is the **Zigbee chip**. Z2M supports:
- **TI CC2652** series (CC2652P, CC2652R, CC2652RB) — widely used
- **Silicon Labs EFR32MG21** — used in SONOFF-E dongles
- **Dresden ConBee** series
- **Ember EZSPv8** based

**Red flags — NOT compatible or problematic:**
- CC2531 — old, limited to ~20 devices, no longer recommended
- WiFi-only Zigbee gateways (Tuya WiFi gateway, Philips Hue bridge) — these are closed systems, not USB coordinators
- Bluetooth-only devices
- Z-Wave dongles (different protocol entirely)

When the user shares a product link, look for: chip model, "Zigbee 3.0", "coordinator", "CC2652" or "EFR32" or "ConBee". If it just says "Zigbee gateway" without USB or specific chip info, it's probably a closed WiFi gateway — not compatible.

### Zigbee Devices
Z2M supports 4000+ devices. Check https://www.zigbee2mqtt.io/supported-devices/ for the full list.

**Common compatible brands:**
- **SONOFF** — switches, sensors, plugs
- **IKEA TRÅDFRI** — lights, blinds, remotes
- **Aqara / Xiaomi** — sensors, switches, curtains (most models work)
- **Tuya** — huge variety, most Zigbee models work (but verify specific model)
- **Philips Hue** — lights work (but you lose the Hue bridge features)
- **GLEDOPTO** — LED controllers
- **Moes** — knobs, switches, thermostats

When the user shares a product, check:
1. Does it say "Zigbee" (not just "WiFi" or "Bluetooth")?
2. Search the model number on https://www.zigbee2mqtt.io/supported-devices/
3. If the exact model isn't listed, similar models from the same brand often work

### What NOT to buy
- **WiFi-only** smart devices — won't work with Zigbee coordinator
- **Proprietary hub-required** devices (some brands lock devices to their own hub)
- **Zigbee devices with custom firmware** that only work with specific gateways
- **Thread/Matter-only** devices (different protocol, though some dual-protocol devices exist)

---

## Determine the Scenario

Ask the user which scenario applies:

1. **Fresh setup** — No existing HA, brand new RPi, new Zigbee devices
2. **Migration from HA** — Existing HA with Z2M addon, moving to standalone
3. **Adding devices** — System already running, adding new Zigbee devices
4. **Deploying rule changes** — Updating automation rules on existing system

For scenarios 3 and 4, skip to the relevant phase.

### Fresh Setup vs Migration — Key Differences

| | Fresh Setup | Migration from HA |
|---|---|---|
| network_key | Omit — Z2M auto-generates | Must copy from backup |
| database.db | Not needed — pair from scratch | Must copy to preserve pairings |
| Device names | User decides from scratch | Map from HA entity names |
| Automation rules | Interview user for needs | Recreate from HA automations |
| Coordinator | Plug in, Z2M auto-detects | Same coordinator, same port |

**Fresh setup**: Skip Phase 1 entirely. In Phase 2, omit `network_key` from Z2M config (auto-generated). After Z2M starts, pair each device one by one via Z2M frontend (:8080) or `permit_join`. Then interview the user about what automations they want.

**Migration**: Follow all phases. The key goal is preserving the network_key + database.db so devices don't need re-pairing.

---

## Phase 0: Discovery & Network Setup

### Find the RPi
```bash
arp -a   # Look for RPi in the local subnet
```
If the user knows the IP, use it directly. If not, check the router admin page.

### Establish SSH
1. Try `ssh <user>@<ip>` — if it works, proceed
2. If connection refused: user needs to flash SD card first (see Phase 2)
3. If password works, set up key auth for passwordless access:
```bash
# Find the local public key (try both)
cat ~/.ssh/id_ed25519.pub 2>/dev/null || cat ~/.ssh/id_rsa.pub
# Then either:
ssh-copy-id <user>@<ip>
# Or manually — user pastes the public key on RPi:
# mkdir -p ~/.ssh && echo "<key>" >> ~/.ssh/authorized_keys
```
4. Verify: `ssh <user>@<ip> "hostname"` should work without password

### Check for existing Home Assistant
```bash
# From the RPi or local machine
ping -c 1 homeassistant.local
curl -s http://homeassistant.local:8123/api/ -H "Authorization: Bearer <token>"
```
If HA exists and user wants to migrate, get a **Long-Lived Access Token**:
- HA UI → User Profile (bottom-left) → Long-Lived Access Tokens → Create Token

### Pull device inventory from HA (if migrating)
```bash
curl -s -H "Authorization: Bearer <TOKEN>" http://<HA_IP>:8123/api/states | \
  python -c "import json,sys; data=json.load(sys.stdin); ..."
```
Document all devices, their entity IDs, friendly names, and current automations. This information is needed to recreate rules later.

---

## Phase 1: Backup from HA (Migration Only)

### Get Z2M backup
The Z2M backup contains everything needed to preserve device pairings:
1. Open HA → Sidebar → Zigbee2MQTT → Settings → Tools → **Request Z2m backup**
2. Download the zip file
3. Extract — critical files:
   - `configuration.yaml` — contains **network_key** (lose this = re-pair all devices)
   - `database.db` — device pairing database
   - `coordinator_backup.json` — coordinator state

### Key values to preserve from configuration.yaml
```yaml
advanced:
  network_key: [176, 109, ...]   # 16 integers — CRITICAL
  channel: 11
  pan_id: 26379
  ext_pan_id: [149, 238, ...]    # 8 integers
serial:
  port: /dev/ttyUSB0
  adapter: zstack
```
Without the network_key, all devices must be re-paired manually.

---

## Phase 2: RPi Base Setup

### Flash the SD Card

User needs: Raspberry Pi, SD card (16GB+), Raspberry Pi Imager on their computer.

1. Open **Raspberry Pi Imager**
2. Select device: Raspberry Pi 3 / 4 / 5
3. Select OS: **Raspberry Pi OS (other)** → **Raspberry Pi OS Lite**
   - **RPi 3B (1GB)**: pick **32-bit** — 64-bit wastes memory on 1GB
   - **RPi 4/5**: pick **64-bit**
4. Select storage: the SD card
5. Click the **gear icon** ⚙️ (OS Customization) — this is important:
   - **Enable SSH** (password authentication)
   - **Set username and password** — ask user what they want
   - **Configure WiFi** — SSID and password (if not using ethernet)
   - **Set hostname** — e.g. `haclaw` or user's choice
   - **Set locale/timezone**
6. Click **Write**, wait for completion
7. Insert SD card into RPi, connect power

After ~1 minute the RPi should be on the network. Proceed to Phase 0 to find it and set up SSH key auth.

### Install Mosquitto
```bash
sudo apt-get update
sudo apt-get install -y mosquitto mosquitto-clients
echo -e 'listener 1883\nallow_anonymous true' | sudo tee /etc/mosquitto/conf.d/default.conf
sudo systemctl restart mosquitto
```

### Install Zigbee2MQTT

**Important**: Z2M requires pnpm for building. `npm ci` alone will fail.

```bash
sudo apt-get install -y nodejs npm
sudo npm install -g pnpm
sudo mkdir -p /opt/zigbee2mqtt && sudo chown -R $USER:$USER /opt/zigbee2mqtt
git clone --depth 1 https://github.com/Koenkk/zigbee2mqtt.git /opt/zigbee2mqtt
cd /opt/zigbee2mqtt
pnpm install
pnpm run build
```

### Z2M Configuration

Write `/opt/zigbee2mqtt/data/configuration.yaml`. 

**CRITICAL for HomeKit compatibility**: Use ASCII/English snake_case for all `friendly_name` values. Non-ASCII characters (Chinese, Japanese, etc.) will cause Homebridge to crash because HomeKit's name sanitizer strips them to empty strings.

```yaml
homeassistant: false
permit_join: false    # true temporarily for fresh setup pairing
mqtt:
  base_topic: zigbee2mqtt
  server: mqtt://localhost
serial:
  port: /dev/ttyUSB0  # Check with: ls /dev/ttyUSB* /dev/ttyACM*
  adapter: zstack
advanced:
  log_level: info
  channel: 11
  # Migration: copy network_key, pan_id, ext_pan_id from backup
  # Fresh setup: omit these — Z2M auto-generates on first start
  last_seen: ISO_8601
frontend:
  port: 8080
devices:
  '0xIEEE_ADDRESS':
    friendly_name: living_room_light  # English snake_case!
```

**Migration**: Copy `database.db` and `coordinator_backup.json` to `/opt/zigbee2mqtt/data/`.

**Fresh setup**: Set `permit_join: true` initially. After Z2M starts, pair devices one by one:
1. Open Z2M frontend at `http://<RPi_IP>:8080`
2. Put each device in pairing mode (per manufacturer instructions)
3. Once paired, rename to English snake_case in Z2M frontend or config
4. After all devices paired, set `permit_join: false`

### Register systemd services

**Zigbee2MQTT service** (`/etc/systemd/system/zigbee2mqtt.service`):
```ini
[Unit]
Description=Zigbee2MQTT
After=network.target mosquitto.service
Requires=mosquitto.service

[Service]
Type=simple
User=<username>
WorkingDirectory=/opt/zigbee2mqtt
ExecStart=/usr/bin/node index.js
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable zigbee2mqtt
sudo systemctl start zigbee2mqtt
```

### Verify
```bash
ls /dev/ttyUSB*                    # Coordinator detected?
sudo systemctl status zigbee2mqtt  # Service running?
# Check logs for "Currently N devices are joined"
sudo journalctl -u zigbee2mqtt --no-pager -n 30
```

---

## Phase 3: Python Automation Service

### Setup
```bash
sudo mkdir -p /opt/smart-home/rules
sudo chown -R $USER:$USER /opt/smart-home
python3 -m venv /opt/smart-home/.venv
```

**Important**: Debian 12+ requires venv — system pip is locked (PEP 668).

```bash
/opt/smart-home/.venv/bin/pip install fastapi uvicorn[standard] aiomqtt watchdog astral
```

### Deploy main.py

The main service (`/opt/smart-home/main.py`) provides:
- **MQTT listener**: Subscribes to `zigbee2mqtt/#`, tracks all device states
- **REST API**: 
  - `GET /api/devices` — all device states
  - `POST /api/devices/{name}` — control a device
  - `GET/PUT/DELETE /api/rules/{name}` — manage automation rules
  - `GET /api/health` — service status
- **Rule engine**: Loads `.py` files from `rules/` directory
  - `schedule` — time-based ("23:30" or {"time": "09:45", "weekdays": [0,1,2,3,4]})
  - `trigger` — device event-based (supports multi-trigger via trigger2, trigger3, ...)
  - `run(home, device, payload)` — rule entry point (device/payload for trigger rules)
- **Hot-reload**: watchdog monitors rules/ for file changes
- **MQTT auto-reconnect**: Handles broker disconnections gracefully

Reference implementation is in the project's `smart-home/main.py`.

### Writing Automation Rules

Each rule is a `.py` file in `rules/`. Structure:

```python
name = "Rule Display Name"
enabled = True
schedule = None  # or "HH:MM" or {"time": "HH:MM", "weekdays": [0..4]}
trigger = {"device": "device_name", "field": "field_name", "value": expected_value}
trigger2 = {"device": "other_device", "field": "action", "value": "single"}  # optional

async def run(home, device=None, payload=None):
    # home.get(name) — get device state
    # home.get_all() — get all states
    # await home.set(name, payload) — control device
    pass
```

### Gotchas when writing rules

These are hard-won lessons — each one caused real debugging time:

1. **Presence field name**: Z2M uses `"presence"`, not `"occupancy"` (which is HA's name). Always check actual MQTT payload:
   ```bash
   mosquitto_sub -h localhost -t 'zigbee2mqtt/device_name' -C 1
   ```

2. **Switch action values vary by brand**: Don't assume `"toggle"` — SONOFF buttons send `"single"`, Moes knobs send `"toggle"`. Always capture real events first:
   ```bash
   mosquitto_sub -h localhost -t 'zigbee2mqtt/device_name' -v -C 1
   ```

3. **Double-click detection**: Some devices send `toggle` then `double` in quick succession. The toggle fires first and interferes. Solution: delay toggle execution by 0.4s with asyncio, cancel if double follows:
   ```python
   if action == "toggle":
       _pending = asyncio.create_task(delayed_toggle())
   elif action == "double":
       if _pending and not _pending.done():
           _pending.cancel()
       # handle double-click
   ```

4. **Cooldown after manual switch-off**: If user manually turns off a light, presence detection will immediately turn it back on. Add a cooldown:
   ```python
   _cooldown_until = time.monotonic() + 60  # 1 minute
   # In presence handler:
   if time.monotonic() < _cooldown_until:
       return
   ```

5. **Delayed off with cancellation**: For "no presence for 5 min → off":
   ```python
   _off_task: asyncio.Task | None = None
   # On presence=False: start 5min timer
   # On presence=True: cancel timer if running
   ```

6. **Sun-based scheduling**: Use `astral` library for sunrise/sunset:
   ```python
   from astral import LocationInfo
   from astral.sun import sun
   loc = LocationInfo("City", "Country", "Timezone", lat, lon)
   s = sun(loc.observer, date=now.date(), tzinfo=now.tzinfo)
   ```

### Register systemd service

```ini
[Unit]
Description=Smart Home Python Service
After=network.target mosquitto.service zigbee2mqtt.service

[Service]
Type=simple
User=<username>
WorkingDirectory=/opt/smart-home
ExecStart=/opt/smart-home/.venv/bin/python main.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

---

## Phase 4: Homebridge (Apple HomeKit)

### Install
```bash
sudo apt-get install -y libavahi-compat-libdnssd-dev avahi-daemon avahi-utils
sudo npm install -g homebridge homebridge-z2m
```

**avahi-daemon is required** — without it, HomeKit can't discover the bridge via mDNS.

### Configure

Write `~/.homebridge/config.json` (generate a unique username MAC and PIN for each setup):

```json
{
  "bridge": {
    "name": "<user's choice, e.g. MyHome>",
    "username": "<random MAC, e.g. CC:22:3D:E3:CE:30>",
    "port": 51826,
    "pin": "<3-2-3 digit format, e.g. 031-45-154>"
  },
  "platforms": [
    {
      "platform": "zigbee2mqtt",
      "mqtt": {
        "server": "mqtt://localhost:1883",
        "base_topic": "zigbee2mqtt"
      },
      "defaults": {
        "ignore_availability": true
      }
    }
  ]
}
```

**Critical**: Platform must be `"zigbee2mqtt"`, NOT `"z2m"`. The plugin registers under the full name.

### Gotchas
- Z2M `friendly_name` MUST be ASCII English — HomeKit sanitizes non-ASCII to empty strings, causing `"Accessories must be created with a non-empty displayName"` crash
- If re-pairing after config changes: `rm -rf ~/.homebridge/accessories ~/.homebridge/persist`
- User must remove old bridge from iPhone Home app before re-pairing
- To exclude devices (buttons, knobs) from HomeKit: add `"exclude": true` in device config

### Register systemd service and pair

```bash
sudo systemctl daemon-reload && sudo systemctl enable homebridge && sudo systemctl start homebridge
```

User pairs on iPhone: Home App → Add Accessory → More Options → select bridge → enter PIN.

---

## Phase 5: Verification Checklist

```bash
# All services running?
systemctl is-active mosquitto zigbee2mqtt smart-home homebridge

# Memory OK? (should be <500MB used on RPi 3B)
free -h

# Z2M devices discovered?
sudo journalctl -u zigbee2mqtt | grep "devices are joined"

# Smart Home rules loaded?
curl -s http://localhost:8000/api/health

# Auto-start after reboot?
sudo reboot
# ... wait ... then SSH back in and check services
```

---

## Deploying Rule Changes

When updating rules on an existing system:

```bash
# Copy rule files to RPi
scp rules/*.py user@rpi:/opt/smart-home/rules/

# Option A: Hot-reload (watchdog detects changes automatically)
# Option B: Restart service
ssh user@rpi "sudo systemctl restart smart-home"

# Verify
ssh user@rpi "curl -s http://localhost:8000/api/rules"
```

If Z2M config changed (device names, network settings):
```bash
scp configuration.yaml user@rpi:/opt/zigbee2mqtt/data/
ssh user@rpi "sudo systemctl restart zigbee2mqtt"
```

---

## Adding New Devices

1. Enable permit_join temporarily:
   ```bash
   mosquitto_pub -h localhost -t 'zigbee2mqtt/bridge/request/permit_join' \
     -m '{"value": true, "time": 120}'
   ```
   Or use Z2M frontend at `:8080`

2. Put the new device in pairing mode (per manufacturer instructions)

3. Once paired, check its capabilities:
   ```bash
   mosquitto_sub -h localhost -t 'zigbee2mqtt/bridge/devices' -C 1 | \
     python3 -c "import json,sys; [print(d['friendly_name'], [e.get('type') for e in d.get('definition',{}).get('exposes',[])]) for d in json.load(sys.stdin)]"
   ```

4. Give it an English snake_case friendly_name in Z2M config

5. Capture actual event values by operating the device:
   ```bash
   mosquitto_sub -h localhost -t 'zigbee2mqtt/<device_name>' -v -C 5
   ```

6. Write automation rule, deploy, test

7. Restart Homebridge if the new device should appear in HomeKit
