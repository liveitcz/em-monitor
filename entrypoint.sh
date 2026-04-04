#!/bin/bash
set -e

echo ""
echo "╔════════════════════════════════════════════════════════╗"
echo "║     PoE Monitor - Starting                                                ║"
echo "╚════════════════════════════════════════════════════════╝"

############################################
# DATABASE INITIALIZATION
############################################

echo "[1/3] Initializing database with ifIndex schema..."
python3 /app/init_db.py

############################################
# LOAD DEVICES
############################################

echo "[2/3] Loading devices from config..."
python3 << 'LOAD_DEVICES'
import json
import sqlite3
from datetime import datetime

DB_PATH = '/app/data/energy.db'
CONFIG_PATH = '/app/config/devices.json'

try:
    with open(CONFIG_PATH) as f:
        config = json.load(f)
    devices = config.get('devices', {})

    if not devices:
        print("⚠️  No devices in config!")
    else:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        for ip, name in devices.items():
            cursor.execute('''
                INSERT OR IGNORE INTO poe_devices
                (device_ip, device_name, device_model, device_serial,
                 poe_available, poe_used, poe_remaining, poe_percentage,
                 port_count, status, last_scan)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (ip, name, 'Unknown', 'Unknown', 0, 0, 0, 0, 0, 'PENDING', datetime.now().isoformat()))

        conn.commit()
        conn.close()
        print(f"✓ Loaded {len(devices)} devices with PENDING status")

except FileNotFoundError:
    print("❌ devices.json not found!")
except Exception as e:
    print(f"❌ Error: {e}")
LOAD_DEVICES

############################################
# START SERVICES
############################################

echo "[3/3] Starting services..."
echo ""
echo "✅ Web interface READY on port 4999 (external: 3020)"
echo ""
echo "🔄 Background services:"
echo "   📊 Database: energy.db (WAL mode + ifIndex schema)"
echo "   🔍 Scanner: ProcessPoolExecutor (10 workers)"
echo "   ⬇️  Priority: nice -n 10 (lower than web)"
echo "   📝 Device changes LOG enabled"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "🔄 Starting scanner with lower priority..."
nice -n 10 nohup python3 /app/arp.py 2>&1 &
ARP_PID=$!
sleep 3
echo "   Scanner PID=$ARP_PID (priority: 10)"
echo ""

exec python3 /app/detail_ports.py
