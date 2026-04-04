#!/bin/bash
# =============================================================
#  Energy Monitor — setup.sh
#  Installation script for Debian/Ubuntu and Synology NAS
#
#  Usage:
#    bash setup.sh
# =============================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

ok()   { echo -e "${GREEN}  [OK] $1${NC}"; }
warn() { echo -e "${YELLOW}  [!!] $1${NC}"; }
err()  { echo -e "${RED}  [ERR] $1${NC}"; exit 1; }
info() { echo -e "${CYAN}  [>>] $1${NC}"; }

echo ""
echo -e "${CYAN}╔══════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║        Energy Monitor — Setup            ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════╝${NC}"
echo ""

# ── Detect platform ───────────────────────────────────────────
PLATFORM="debian"
if [ -f /etc/synoinfo.conf ] || uname -r 2>/dev/null | grep -qi "synology"; then
    PLATFORM="synology"
fi
info "Platform: $PLATFORM"

# ── Set EM_ROOT ───────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo -e "${CYAN}  Installation directory (press Enter to use current):${NC}"
echo -e "  Default: ${YELLOW}$SCRIPT_DIR${NC}"
read -p "  Path: " USER_PATH
if [ -z "$USER_PATH" ]; then
    EM_ROOT="$SCRIPT_DIR"
else
    EM_ROOT="${USER_PATH%/}"  # odstraň trailing slash
fi
info "EM_ROOT: $EM_ROOT"

# Vytvoř cílový adresář pokud neexistuje
mkdir -p "$EM_ROOT"

# ── Check Docker ──────────────────────────────────────────────
command -v docker >/dev/null 2>&1 || err "Docker is not installed!"
docker compose version >/dev/null 2>&1 || err "Docker Compose plugin is not available!"
ok "Docker OK"

# ── Create required directories ───────────────────────────────
info "Creating directories..."
mkdir -p "$EM_ROOT/data"
mkdir -p "$EM_ROOT/config"
mkdir -p "$EM_ROOT/templates"
mkdir -p "$EM_ROOT/static/js"
mkdir -p "$EM_ROOT/static/lang"
mkdir -p "$EM_ROOT/languages"
mkdir -p "$EM_ROOT/logs"
mkdir -p "$EM_ROOT/mibs/cisco"
mkdir -p "$EM_ROOT/mibs/standard"
ok "Directories created"

# ── Create .env with EM_ROOT ──────────────────────────────────
if [ ! -f "$EM_ROOT/.env" ]; then
    echo "EM_ROOT=$EM_ROOT" > "$EM_ROOT/.env"
    ok ".env created with EM_ROOT=$EM_ROOT"
else
    sed -i "s|EM_ROOT=.*|EM_ROOT=$EM_ROOT|g" "$EM_ROOT/.env"
    ok ".env already exists (EM_ROOT updated)"
fi

# ── Create example config if not exists ───────────────────────
if [ ! -f "$EM_ROOT/config/devices.json" ]; then
    cat > "$EM_ROOT/config/devices.json" << 'DEVJSON'
{
  "slow_switches": {},
  "slow_switch_delay": 0.3,
  "devices": {
    "192.168.1.1": "Switch-1",
    "192.168.1.2": "Switch-2"
  }
}
DEVJSON
    warn "config/devices.json created with example devices — edit before use!"
else
    ok "config/devices.json already exists"
fi

if [ ! -f "$EM_ROOT/config/snmp.json" ]; then
    cat > "$EM_ROOT/config/snmp.json" << 'SNMPJSON'
{
  "community": "public",
  "version": "2c",
  "timeout": 5,
  "retries": 1,
  "per_device": {}
}
SNMPJSON
    warn "config/snmp.json created with example SNMP config — set your community string!"
else
    ok "config/snmp.json already exists"
fi

# ── Summary ───────────────────────────────────────────────────
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║        Setup complete!                   ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════╝${NC}"
echo ""
echo -e "  Platform:  ${CYAN}$PLATFORM${NC}"
echo -e "  EM_ROOT:   ${CYAN}$EM_ROOT${NC}"
echo ""
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${CYAN}  NEXT STEPS:${NC}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "  ${GREEN}1.${NC} Edit config files:"
echo -e "     ${YELLOW}nano $EM_ROOT/config/devices.json${NC}  — add your switches"
echo -e "     ${YELLOW}nano $EM_ROOT/config/snmp.json${NC}     — set SNMP community"
echo ""
echo -e "  ${GREEN}2.${NC} Build and start:"
if [ "$PLATFORM" = "synology" ]; then
    echo -e "     ${YELLOW}docker compose -f $EM_ROOT/compose.synology.yaml up -d --build${NC}"
else
    echo -e "     ${YELLOW}docker compose -f $EM_ROOT/compose.yaml up -d --build${NC}"
fi
echo ""
echo -e "  ${GREEN}3.${NC} Open web UI:"
if [ "$PLATFORM" = "synology" ]; then
    echo -e "     ${YELLOW}http://<your-nas-ip>:3013${NC}"
else
    echo -e "     ${YELLOW}http://<your-server-ip>:4999${NC}"
fi
echo ""
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
