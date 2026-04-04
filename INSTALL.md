# Energy Monitor — Installation Guide

## Requirements

- Docker Engine + Docker Compose plugin (Debian/Ubuntu)
- OR Container Manager DSM 7.2+ (Synology)
- Cisco switches with SNMP v2c enabled

## Installation

### 1. Clone repository

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

default username: admin
default password: admin

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
