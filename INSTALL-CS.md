# Energy Monitor — Instalační příručka

## Požadavky

- Docker Engine + Docker Compose plugin (Debian/Ubuntu)
- NEBO Container Manager DSM 7.2+ (Synology)
- Cisco switche s povoleným SNMP v2c

## Instalace

### 1. Stáhni repozitář

```bash
git clone https://github.com/liveitcz/em-monitor.git
cd em-monitor
```

### 2. Spusť setup

```bash
bash setup.sh
```

### 3. Nakonfiguruj zařízení

```bash
cp config/devices.json.example config/devices.json
cp config/snmp.json.example config/snmp.json
nano config/devices.json   # přidej IP adresy a názvy switchů
nano config/snmp.json      # nastav SNMP community string
```

### 4. Sestav a spusť

**Debian:**
```bash
docker compose up -d --build
```

**Synology:**
```bash
docker compose -f compose.synology.yaml up -d --build
```

### 5. Otevři webové rozhraní

- Debian: `http://<ip-serveru>:4999`
- Synology: `http://<ip-nas>:3013`

default username: admin
default password: admin

## Konfigurační soubory

### config/devices.json

```json
{
  "devices": {
    "192.168.1.1": "Název-switche"
  },
  "slow_switches": {},
  "slow_switch_delay": 0.3
}
```

### config/snmp.json

```json
{
  "community": "tvuj-community-string",
  "version": "2c",
  "timeout": 5,
  "retries": 1
}
```

## Porty

| Platforma | Port |
|---|---|
| Debian | 4999 |
| Synology | 3013 → 4999 |
