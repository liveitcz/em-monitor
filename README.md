# Energy Monitor (EM)

Web-based PoE monitoring platform for Cisco switches.
Monitors power consumption, port status and device inventory via SNMP (MAC on ports, descriptions, etc...).

If you want to monitor END devices you need to enable LLDP in your network. 
Check if END devices support LLDP feature.

Tested on Cisco switches from 29xx to 9xxx. 
On some old switches you can see high CPUs, so better remove it from EM.

---

## Quick Start

### Debian / Ubuntu

```bash
git clone https://github.com/liveitcz/em-monitor.git
cd em-monitor
bash setup.sh
# Edit config files
nano config/devices.json
nano config/snmp.json
docker compose up -d --build
```

Open: `http://<server-ip>:4999`

### Synology NAS

```bash
git clone https://github.com/liveitcz/em-monitor.git
cd em-monitor
bash setup.sh
# Edit config files
nano config/devices.json
nano config/snmp.json
docker compose -f compose.synology.yaml up -d --build
```

### Synology NAS (GUI - Container Manager)
```bash
Prepare directories in File Station:

Create folder /docker/em_monitor/config
Place devices.json and snmp.json inside this folder.

Container Manager setup:
Download image liveitcz/em-monitor:latest and click Run.

Port settings: Local Port 3013 -> Container Port 4999
Volume settings: /docker/em_monitor/config -> /app/config (Read/Write)
```

Open: `http://<nas-ip>:3013`

---

## Documentation

- [Installation Guide (EN)](INSTALL.md)
- [Instalační příručka (CS)](INSTALL-CS.md)

---

## Requirements

| Platform | Requirement |
|---|---|
| Debian/Ubuntu | Docker Engine + Compose plugin |
| Synology NAS | Container Manager (DSM 7.2+) |
| RAM | 512 MB minimum |
| Switches | Cisco IOS/IOS-XE with SNMP v2c |
