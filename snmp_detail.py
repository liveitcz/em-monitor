#!/usr/bin/env python3
"""
snmp_detail.py - KOMPLETNÍ FINÁLNÍ VERZE
Změny:
- Zobrazuje VLAN i pro DOWN porty (z port_vlan_id)
- Detekuje trunk (více VLANů) - vrací is_trunk
- Načítá port_status (UP/DOWN)
- Rychlé (čte z DB)
"""

import subprocess
import json
import logging
import re
import sqlite3

DB_PATH = '/app/data/energy.db'
logger = logging.getLogger(__name__)


def load_snmp_config():
    try:
        with open('/app/config/snmp.json') as f:
            return json.load(f)
    except:
        return {'community': 'public'}


def get_community(host):
    config = load_snmp_config()
    per_device = config.get('per_device', {})
    return per_device.get(host, config.get('community', 'public'))


def get_port_power_from_db(host):
    """Načíst power + description + VLAN config + Status z DB"""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Zkontrolovat zda sloupce existují
        cursor.execute("PRAGMA table_info(poe_ports)")
        columns = [row[1] for row in cursor.fetchall()]
        
        # Sestavit SELECT podle dostupných sloupců
        select_cols = ['port_number', 'port_name', 'port_description', 'power_watts']
        if 'port_vlan_id' in columns:
            select_cols.append('port_vlan_id')
        if 'port_status' in columns:
            select_cols.append('port_status')
        
        query = f'''
            SELECT {', '.join(select_cols)}
            FROM poe_ports 
            WHERE device_ip = ? 
            ORDER BY port_number ASC
        '''
        
        cursor.execute(query, (host,))
        rows = cursor.fetchall()
        conn.close()
        return {row['port_number']: dict(row) for row in rows}
    except Exception as e:
        logger.error(f"DB read error: {e}")
        return {}


def get_vlan_names_from_db(host):
    """Načíst VLAN jména Z DB"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT vlan_id, vlan_name 
            FROM poe_vlan_names 
            WHERE device_ip = ?
        ''', (host,))
        rows = cursor.fetchall()
        conn.close()
        
        vlan_names = {row[0]: row[1] for row in rows}
        logger.info(f"VLAN names from DB: {len(vlan_names)}")
        return vlan_names
    except Exception as e:
        logger.error(f"DB VLAN read error: {e}")
        return {}


def get_mac_addresses_from_db(host):
    """
    Načíst MAC adresy Z DB
    Detekuje trunk porty (více VLANů)
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT port_number, mac_address, vlan_id, vlan_name
            FROM poe_mac_addresses 
            WHERE device_ip = ?
            ORDER BY port_number, vlan_id
        ''', (host,))
        
        mac_by_port = {}
        for row in cursor.fetchall():
            port_num, mac, vlan_id, vlan_name = row
            if port_num not in mac_by_port:
                mac_by_port[port_num] = {
                    'vlans': set(),
                    'macs': []
                }
            
            mac_by_port[port_num]['vlans'].add(vlan_id)
            mac_by_port[port_num]['macs'].append({
                'mac': mac,
                'vlan_id': vlan_id,
                'vlan_name': vlan_name or ''
            })
        
        conn.close()
        
        # Detekovat trunk porty
        result = {}
        for port_num, data in mac_by_port.items():
            if len(data['vlans']) > 1:
                # TRUNK port - více VLANů
                result[port_num] = {
                    'is_trunk': True,
                    'mac_vlan': []  # Prázdné - zobrazíme "ALL VLANs"
                }
            else:
                # ACCESS port - jeden VLAN
                result[port_num] = {
                    'is_trunk': False,
                    'mac_vlan': data['macs'][:3]  # Max 3 MAC
                }
        
        total = sum(len(v['mac_vlan']) for v in result.values())
        trunk_count = sum(1 for v in result.values() if v['is_trunk'])
        logger.info(f"MAC from DB: {total} MACs, {trunk_count} trunk ports")
        return result
    except Exception as e:
        logger.error(f"Failed to read MAC from DB: {e}")
        return {}


def get_detail_data(host):
    """
    Rychlá detail data Z DB
    VRACÍ:
    - port_vlan: VLAN string pro zobrazení
    - port_status: 1=up, 2=down
    - is_trunk: boolean
    - mac_vlan: list MAC adres
    """
    logger.info(f"=== Detail for {host} (from DB cache) ===")
    
    # 1. Power + descriptions + VLAN config + Status Z DB
    db_ports = get_port_power_from_db(host)
    if not db_ports:
        logger.warning(f"No ports in DB for {host}")
        return []
    
    # 2. VLAN jména Z DB
    vlan_names = get_vlan_names_from_db(host)
    
    # 3. MAC adresy Z DB (s trunk detekcí)
    mac_addresses = get_mac_addresses_from_db(host)
    
    # 4. Sestavit výsledek
    ports = []
    for port_num, db_data in sorted(db_ports.items()):
        mac_data = mac_addresses.get(port_num, {'is_trunk': False, 'mac_vlan': []})
        
        # VLAN pro port (z konfigurace nebo z MAC)
        port_vlan_id = db_data.get('port_vlan_id')
        port_vlan_name = ''
        port_name = db_data['port_name']
        
        if port_vlan_id:
            port_vlan_name = vlan_names.get(port_vlan_id, '')
        
        # TRUNK DETECTION:
        # 1. Port má více VLANů (z MAC tabulky) → trunk
        # 2. Port nemá port_vlan_id (NULL) A je Po/Te/Twe/Hu → trunk
        is_trunk_port = mac_data['is_trunk']
        if not is_trunk_port and not port_vlan_id:
            # Port nemá konkrétní VLAN - zkontrolovat typ portu
            if any(port_name.startswith(prefix) for prefix in ['Po', 'Te', 'Twe', 'Hu', 'Fo']):
                is_trunk_port = True
        
        # Pokud je trunk, VLAN přepsat na "ALL VLANs"
        if is_trunk_port:
            port_vlan_display = 'ALL VLANs'
        elif port_vlan_id:
            port_vlan_display = f"{port_vlan_id} ({port_vlan_name})" if port_vlan_name else str(port_vlan_id)
        else:
            port_vlan_display = '-'
        
        # Status (1=up, 2=down)
        port_status = db_data.get('port_status', 2)  # Default 2 = down
        
        ports.append({
            'port_number':      port_num,
            'port_name':        port_name,
            'port_description': db_data.get('port_description', '') or '-',
            'power_watts':      round(db_data['power_watts'], 3),
            'is_trunk':         is_trunk_port,
            'mac_vlan':         mac_data['mac_vlan'] if not is_trunk_port else [],
            'port_vlan':        port_vlan_display,  # ← VLAN pro zobrazení
            'port_status':      port_status         # ← 1=up, 2=down
        })
    
    desc_cnt = sum(1 for p in ports if p['port_description'] != '-')
    mac_cnt = sum(1 for p in ports if p['mac_vlan'])
    trunk_cnt = sum(1 for p in ports if p['is_trunk'])
    up_cnt = sum(1 for p in ports if p['port_status'] == 1)
    logger.info(f"=== Done: {len(ports)} ports, {desc_cnt} desc, {mac_cnt} MAC, {trunk_cnt} trunk, {up_cnt} UP ===")
    return ports


def get_model_and_serial(host):
    """Get model and serial from DB"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT device_model, device_serial 
            FROM poe_devices 
            WHERE device_ip = ?
        ''', (host,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return row[0], row[1]
    except:
        pass
    
    return 'Unknown', 'Unknown'


if __name__ == '__main__':
    import sys
    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) > 1:
        host = sys.argv[1]
        data = get_detail_data(host)
        print(f"\n{'Port':4s} | {'Name':20s} | {'Description':25s} | {'VLAN':15s} | {'Status':6s} | {'Power':8s} | {'MAC'}")
        print("-" * 130)
        for p in data:
            status_str = "UP" if p['port_status'] == 1 else "DOWN"
            if p['is_trunk']:
                mac_str = "ALL VLANs"
            else:
                mac_str = ', '.join(f"{mv['mac']}" for mv in p['mac_vlan']) if p['mac_vlan'] else '-'
            print(f"{p['port_number']:4d} | {p['port_name']:20s} | {p['port_description']:25s} | "
                  f"{p['port_vlan']:15s} | {status_str:6s} | {p['power_watts']:8.3f}W | {mac_str}")