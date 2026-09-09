# Energy Monitor (EM)

Web-based PoE monitoring platform for Cisco switches.
Monitors power consumption, port status and device inventory via SNMP.

If you want to monitor END devices you need to enable LLDP in your network. 
Check if END devices support LLDP feature.

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
