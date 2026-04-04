# Energy Monitor (EM)

Web-based MAC, VLANs and PoE device mapping

Monitors power consumption, port status and device inventory via SNMP.

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
default credentials admin/admin

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
default credentials admin/admin

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
