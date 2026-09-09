# Energy Monitor — Installation Guide

## Requirements

- Docker Engine + Docker Compose plugin (Debian/Ubuntu)
- OR Container Manager DSM 7.2+ (Synology)
- Cisco switches with SNMP v2c enabled

## Installation

### Method A: Synology NAS (GUI via Container Manager)

1. **Prepare Folders and Configs:**
   * Open File Station and create directory `/docker/em_monitor/config`.
   * Create or copy `devices.json` and `snmp.json` inside `/docker/em_monitor/config`.

2. **Run Container:**
   * Open **Container Manager** -> **Image** -> Download `liveitcz/em-monitor:latest`.
   * Select the image and click **Run**.
   * **Port Settings:** Local port `3013` (or any free port) -> Container port `4999`.
   * **Volume Settings:** Map NAS folder `/docker/em_monitor/config` to container path `/app/config` (Read/Write).
   * **Environment:** Add variable `TZ=Europe/Prague`.

3. **Open Web UI:** `http://<nas-ip>:3013`

---

### Method B: CLI (Debian / Ubuntu / Synology SSH)

#### 1. Clone repository

```bash
git clone https://github.com/liveitcz/em-monitor.git
cd em-monitor
```

### 2. Run setup

```bash
bash setup.sh
```

### 3. Configure devices

```bash
cp config/devices.json.example config/devices.json
cp config/snmp.json.example config/snmp.json
nano config/devices.json   # add your switch IPs and names
nano config/snmp.json      # set your SNMP community string
```

### 4. Build and start

**Debian:**
```bash
docker compose up -d --build
```

**Synology:**
```bash
docker compose -f compose.synology.yaml up -d --build
```

### 5. Open web UI

- Debian: `http://<server-ip>:4999`
- Synology: `http://<nas-ip>:3013`

## Config files

### config/devices.json

```json
{
  "devices": {
    "192.168.1.1": "Switch-Name"
  },
  "slow_switches": {},
  "slow_switch_delay": 0.3
}
```

### config/snmp.json

```json
{
  "community": "your-community-string",
  "version": "2c",
  "timeout": 5,
  "retries": 1
}
```

## Ports

| Platform | Port |
|---|---|
| Debian | 4999 |
| Synology | 3013 → 4999 |
