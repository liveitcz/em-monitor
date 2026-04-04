#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
snmp_helper.py - ifIndex REFACTORED VERSION
Uses ifIndex as primary key (like Netdisco)
NO MORE port_number mapping - clean and scalable!
"""

import subprocess
import json
import logging
import re
import sqlite3
import time
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DB_PATH = '/app/data/energy.db'

def load_snmp_config():
    """Load SNMP config from snmp.json"""
    try:
        with open('/app/config/snmp.json') as f:
            return json.load(f)
    except:
        return {'community': 'public'}

def get_community(host):
    """Get SNMP community string for host"""
    config = load_snmp_config()
    per_device = config.get('per_device', {})
    return per_device.get(host, config.get('community', 'public'))

def snmpwalk(host, oid, community=None, timeout=10):
    """Perform SNMP walk using command-line snmpwalk"""
    if community is None:
        community = get_community(host)
    cmd = ['snmpwalk', '-v2c', '-c', community, '-On', '-Oq', host, oid]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0:
            return []
        results = []
        for line in result.stdout.strip().split('\n'):
            if not line or 'No Such' in line or 'End of MIB' in line:
                continue
            parts = line.split(' ', 1)
            if len(parts) == 2:
                results.append((parts[0].strip(), parts[1].strip().strip('"')))
        return results
    except:
        return []

def snmpbulkwalk(host, oid, community=None, timeout=15, max_repetitions=50):
    """Perform SNMP bulk walk - much faster than snmpwalk for large tables.
    Uses GETBULK requests, fetching max_repetitions rows per UDP packet.
    Falls back to snmpwalk if snmpbulkwalk fails."""
    if community is None:
        community = get_community(host)
    cmd = ['snmpbulkwalk', '-v2c', '-c', community, '-On', '-Oq',
           f'-Cr{max_repetitions}', host, oid]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0 or not result.stdout.strip():
            # Fallback to snmpwalk
            return snmpwalk(host, oid, community, timeout)
        results = []
        for line in result.stdout.strip().split('\n'):
            if not line or 'No Such' in line or 'End of MIB' in line:
                continue
            parts = line.split(' ', 1)
            if len(parts) == 2:
                results.append((parts[0].strip(), parts[1].strip().strip('"')))
        return results
    except:
        return snmpwalk(host, oid, community, timeout)

def snmpget(host, oid, community=None, timeout=5):
    """Perform SNMP get using command-line snmpget"""
    if community is None:
        community = get_community(host)
    cmd = ['snmpget', '-v2c', '-c', community, '-Oqv', host, oid]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode == 0:
            value = result.stdout.strip().strip('"')
            if 'No Such' not in value:
                return value
        return None
    except:
        return None

def get_device_model(host, community=None):
    """Get device model from SNMP"""
    try:
        class_walk = snmpwalk(host, '1.3.6.1.2.1.47.1.1.1.1.5', community)
        for oid, val in class_walk:
            try:
                if int(val) == 3:
                    idx = oid.split('.')[-1]
                    m = snmpget(host, f'1.3.6.1.2.1.47.1.1.1.1.13.{idx}', community)
                    if m and len(m) > 2 and 'Unknown' not in m and 'No Such' not in m:
                        return m.strip()
            except:
                pass
        sys_descr = snmpget(host, '1.3.6.1.2.1.1.1.0', community)
        if sys_descr:
            match = re.search(r'(C\d{4}[A-Z0-9-]*|WS-C\d{4}[A-Z0-9-]*)', sys_descr)
            if match:
                return match.group(1)
        return 'Unknown'
    except:
        return 'Unknown'

def get_device_serial(host, community=None):
    """Get device serial number"""
    try:
        class_walk = snmpwalk(host, '1.3.6.1.2.1.47.1.1.1.1.5', community)
        for oid, val in class_walk:
            try:
                if int(val) == 3:
                    idx = oid.split('.')[-1]
                    sn = snmpget(host, f'1.3.6.1.2.1.47.1.1.1.1.11.{idx}', community)
                    if sn and len(sn) > 5 and sn != 'Unknown':
                        return sn.strip()
            except:
                pass
        return 'Unknown'
    except:
        return 'Unknown'

def is_physical_port(port_name):
    """Check if port is physical"""
    if not port_name:
        return False
    physical_patterns = [
        r'^Fa\d+',        # FastEthernet: Fa0/1
        r'^Gi\d+',        # GigabitEthernet: Gi0/1, Gi1/0/1
        r'^gi\d+',        # Catalyst 1300 lowercase: gi1, gi2
        r'^G\d+',         # Old GigabitEthernet: G0/1 (WS-C2950G)
        r'^Te\d+',        # TenGigabitEthernet: Te0/1, Te1/1/1
        r'^Eth\d+',       # Nexus short: Eth1/1
        r'^Ethernet\d+',  # Nexus full: Ethernet1/1
        r'^Twe\d+',     # TwentyFiveGigE: Twe1/1
        r'^Fo\d+',      # FortyGigE: Fo1/1
        r'^Hu\d+',      # HundredGigE: Hu1/1
        r'^Po\d+'       # PortChannel
    ]
    return any(re.match(p, port_name) for p in physical_patterns)

def db_execute_with_retry(operation, max_retries=5, base_delay=1.0):
    """Execute DB operation with retry on lock"""
    for attempt in range(max_retries):
        try:
            conn = sqlite3.connect(DB_PATH, timeout=60.0)
            conn.execute('PRAGMA busy_timeout=60000')
            result = operation(conn)
            conn.close()
            return result
        except sqlite3.OperationalError as e:
            if 'database is locked' in str(e) and attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                logger.warning(f"DB locked, retrying in {delay}s... (attempt {attempt+1}/{max_retries})")
                time.sleep(delay)
                continue
            raise

def get_vlan_names(host, community=None):
    """Get VLAN names - FIXED to read ALL VLANs"""
    if community is None:
        community = get_community(host)
    
    vlan_names = {}
    try:
        # FIX: Remove .1 suffix to get ALL VLANs
        results = snmpwalk(host, '1.3.6.1.4.1.9.9.46.1.3.1.1.4', community, timeout=5)
        for oid, name in results:
            parts = oid.split('.')
            if len(parts) >= 2:
                vlan_id = int(parts[-1])
                vlan_names[vlan_id] = name
        logger.info(f"{host}: Found {len(vlan_names)} VLANs: {sorted(vlan_names.keys())}")
    except Exception as e:
        logger.warning(f"{host}: Cannot get VLAN names: {e}")
    return vlan_names

def get_port_vlan_config(host, community=None):
    """Get port VLAN configuration.
    Reads both dynamic (hardcoded) and static (802.1x) port VLAN assignments.
    vmVlanType: 1=static(802.1x), 2=dynamic(hardcoded), 3=multiVlan(trunk)
    """
    if community is None:
        community = get_community(host)
    
    port_vlans = {}
    try:
        # Primary: vmAccessVlan (1.3.6.1.4.1.9.9.68.1.2.2.1.2) - works for dynamic ports
        results = snmpwalk(host, '1.3.6.1.4.1.9.9.68.1.2.2.1.2', community, timeout=10)
        for oid, vlan_id in results:
            ifidx = oid.split('.')[-1]
            try:
                vlan = int(vlan_id)
                if vlan > 0:
                    port_vlans[ifidx] = vlan
            except:
                pass

        # Secondary: dot1qPvid (1.3.6.1.2.1.17.7.1.4.5.1.1) - works for 802.1x static ports
        # This is the PVID (native/untagged VLAN) assigned after 802.1x auth
        results2 = snmpwalk(host, '1.3.6.1.2.1.17.7.1.4.5.1.1', community, timeout=10)
        for oid, vlan_id in results2:
            ifidx = oid.split('.')[-1]
            try:
                vlan = int(vlan_id)
                if vlan > 0 and ifidx not in port_vlans:
                    port_vlans[ifidx] = vlan
            except:
                pass
        logger.info(f"{host}: Found VLAN config for {len(port_vlans)} ports")
    except Exception as e:
        logger.debug(f"{host}: Cannot get VLAN config: {e}")
    return port_vlans

def get_trunk_ports(host, community=None):
    """Get trunk port status"""
    if community is None:
        community = get_community(host)
    
    trunk_ports = {}
    try:
        # vmVlanType: 1=static, 2=dynamic, 3=multiVlan(trunk)
        results = snmpwalk(host, '1.3.6.1.4.1.9.9.68.1.2.2.1.1', community, timeout=10)
        for oid, vlan_type in results:
            ifidx = oid.split('.')[-1]
            try:
                if int(vlan_type) == 3:
                    trunk_ports[ifidx] = 1
            except:
                pass
        logger.info(f"{host}: Found {len(trunk_ports)} trunk ports")
    except Exception as e:
        logger.debug(f"{host}: Cannot get trunk ports: {e}")
    return trunk_ports

def get_mac_addresses_vlan_context(host, vlan_names, community=None):
    """
    Collect MAC addresses per VLAN - REFACTORED for ifIndex
    Returns mac_by_ifindex[ifIndex] = [{'mac': ..., 'vlan_id': ..., 'vlan_name': ...}]
    """
    if community is None:
        community = get_community(host)
    
    # Get all port names for logging
    port_names_all = {}
    for oid, name in snmpwalk(host, '1.3.6.1.2.1.31.1.1.1.1', community):
        ifidx = oid.split('.')[-1]
        port_names_all[ifidx] = name
    
    logger.info(f"{host}: Found {len(port_names_all)} interfaces")
    
    mac_by_ifindex = {}

    # Load scan_delay from config (for old/slow switches like 2960S IOS 12.2)
    scan_delay = 0.0
    try:
        import json
        with open('/app/config/devices.json') as _f:
            _cfg = json.load(_f)
        slow_switches = _cfg.get('slow_switches', [])
        if host in slow_switches:
            scan_delay = float(_cfg.get('slow_switch_delay', 0.3))
            logger.info(f"{host}: slow_switch mode, inter-VLAN delay={scan_delay}s")
    except:
        pass

    for vlan_id, vlan_name in vlan_names.items():
        community_vlan = f"{community}@{vlan_id}"

        if scan_delay > 0:
            import time
            time.sleep(scan_delay)

        # Use smaller repetitions for slow switches to reduce CPU spikes
        bulk_rep = 15 if scan_delay > 0 else 50

        try:
            # Bulk fetch all 3 tables at once instead of per-MAC snmpget calls
            # Table 1: dot1dTpFdbAddress - MAC addresses keyed by MAC OID suffix
            mac_table = {}
            for oid, _ in snmpbulkwalk(host, '1.3.6.1.2.1.17.4.3.1.1', community_vlan, timeout=10, max_repetitions=bulk_rep):
                mac_dec = oid.split('.')[-6:]
                if len(mac_dec) == 6:
                    mac_key = '.'.join(mac_dec)
                    mac = ':'.join(f"{int(x):02x}" for x in mac_dec)
                    mac_table[mac_key] = mac

            if not mac_table:
                continue

            # Table 2: dot1dTpFdbPort - bridge port number per MAC
            port_table = {}
            for oid, val in snmpbulkwalk(host, '1.3.6.1.2.1.17.4.3.1.2', community_vlan, timeout=10, max_repetitions=bulk_rep):
                mac_key = '.'.join(oid.split('.')[-6:])
                try:
                    port_table[mac_key] = int(val)
                except:
                    pass

            # Table 3: dot1dTpFdbStatus
            # 1=other, 2=invalid, 3=learned(DYNAMIC), 4=self, 5=mgmt(STATIC/dot1x)
            # Accept 1, 3, 5 — reject only 2 (invalid) and 4 (switch own MAC)
            status_table = {}
            for oid, val in snmpbulkwalk(host, '1.3.6.1.2.1.17.4.3.1.3', community_vlan, timeout=10, max_repetitions=bulk_rep):
                mac_key = '.'.join(oid.split('.')[-6:])
                try:
                    status_table[mac_key] = int(val)
                except:
                    pass

            # Table 4: dot1dBasePortIfIndex - bridge port → ifIndex mapping
            bridge_to_ifindex = {}
            for oid, val in snmpbulkwalk(host, '1.3.6.1.2.1.17.1.4.1.2', community_vlan, timeout=10, max_repetitions=bulk_rep):
                bridge_port = oid.split('.')[-1]
                try:
                    bridge_to_ifindex[bridge_port] = str(int(val))
                except:
                    pass

            # Combine all tables in memory
            # dot1dTpFdbStatus values:
            #   1=other, 2=invalid, 3=learned, 4=self, 5=mgmt/STATIC
            # Accept: 1 (other), 3 (learned/DYNAMIC), 5 (mgmt/STATIC = dot1x authenticated)
            # Skip:   2 (invalid), 4 (self = switch own MAC), missing
            for mac_key, mac in mac_table.items():
                status_val = status_table.get(mac_key)
                if status_val not in (1, 3, 5):
                    continue
                bridge_port = port_table.get(mac_key)
                if not bridge_port:
                    continue
                ifidx = bridge_to_ifindex.get(str(bridge_port))
                if not ifidx:
                    continue

                if ifidx not in mac_by_ifindex:
                    mac_by_ifindex[ifidx] = []
                mac_by_ifindex[ifidx].append({
                    'mac': mac,
                    'vlan_id': vlan_id,
                    'vlan_name': vlan_name or ''
                })

        except Exception as e:
            logger.debug(f"{host}: VLAN {vlan_id} error: {e}")
            continue
    
    logger.info(f"{host}: Found MACs on {len(mac_by_ifindex)} interfaces (by ifIndex)")
    return mac_by_ifindex

def extract_poe_index_from_port_name(port_name):
    """Extract PoE index from port name.
    
    Returns 'group.port' string to match 2-segment SNMP OID suffix.
    
    Standard single-module switches (2960, 3750):
      Gi0/12 → '1.12'  (module 0 = PoE group 1)
    
    Modular chassis (4500, 6500):
      Gi4/12 → '4.12'  (slot 4 = PoE group 4)
      Gi2/1  → '2.1'   (slot 2 = PoE group 2)
    
    Stacked 3-level (9200, 3850):
      Gi1/0/12 → '1.12' (stack member 1, slot 0, port 12)
    """
    # 3-level: Gi1/0/2, Te1/1/1 (stacked/modular with sub-slot)
    match = re.search(r'(\d+)/(\d+)/(\d+)$', port_name)
    if match:
        stack = int(match.group(1))
        slot  = int(match.group(2))
        port  = int(match.group(3))
        # PoE group = stack member (1-based), port = port number
        group = stack if stack > 0 else 1
        if slot == 0:
            return f'{group}.{port}'
        elif slot == 1 and port_name.startswith('Te'):
            return f'{group}.{48 + port}'  # Uplinks after 48 access ports
        else:
            return f'{group}.{100 + port}'
    
    # 2-level: Gi4/12 (modular chassis) or Gi0/12 (standard switch)
    match = re.search(r'(\d+)/(\d+)$', port_name)
    if match:
        module = int(match.group(1))
        port   = int(match.group(2))
        # module 0 on standard switches = PoE group 1
        group = module if module > 0 else 1
        return f'{group}.{port}'
    
    return None

def get_poe_data(host):
    """
    Get PoE data - REFACTORED for ifIndex
    Returns port_map indexed by ifIndex (like Netdisco!)
    """
    community = get_community(host)

    OID_POE_BUDGET        = '1.3.6.1.2.1.105.1.3.1.1.2'
    OID_POE_CONSUMPTION   = '1.3.6.1.2.1.105.1.3.1.1.4'
    OID_CISCO_REAL_POWER  = '1.3.6.1.4.1.9.9.402.1.2.1.9'
    OID_CISCO_ALLOC_POWER = '1.3.6.1.4.1.9.9.402.1.2.1.7'
    OID_IF_NAME           = '1.3.6.1.2.1.31.1.1.1.1'
    OID_IF_ALIAS          = '1.3.6.1.2.1.31.1.1.1.18'
    OID_IF_OPER_STATUS    = '1.3.6.1.2.1.2.2.1.8'

    result = {
        'poe_available': 0, 'poe_used': 0, 'poe_remaining': 0,
        'poe_percentage': 0, 'port_count': 0,
        'model': 'Unknown', 'serial': 'Unknown'
    }

    try:
        result['model']  = get_device_model(host, community)
        result['serial'] = get_device_serial(host, community)

        for oid, val in snmpwalk(host, OID_POE_BUDGET, community):
            try: result['poe_available'] += float(val)
            except: pass

        for oid, val in snmpwalk(host, OID_POE_CONSUMPTION, community):
            try: result['poe_used'] += float(val)
            except: pass

        # Get all interface names
        port_names = {}
        for oid, name in snmpbulkwalk(host, OID_IF_NAME, community):
            ifidx = oid.split('.')[-1]
            port_names[ifidx] = name

        logger.info(f"{host}: Found {len(port_names)} interfaces")

        # Get interface descriptions
        port_descriptions = {}
        for oid, desc in snmpbulkwalk(host, OID_IF_ALIAS, community):
            ifidx = oid.split('.')[-1]
            port_descriptions[ifidx] = desc

        # Get VLAN config and trunk status
        port_vlan_config = get_port_vlan_config(host, community)
        trunk_status = get_trunk_ports(host, community)

        # Get operational status
        port_status = {}
        for oid, status in snmpbulkwalk(host, OID_IF_OPER_STATUS, community):
            ifidx = oid.split('.')[-1]
            try:
                port_status[ifidx] = int(status)
            except:
                port_status[ifidx] = 2

        logger.info(f"{host}: Found status for {len(port_status)} interfaces")

        # Get Cisco PoE power data
        cisco_power = {}
        source = ''
        
        real_power_data = snmpbulkwalk(host, OID_CISCO_REAL_POWER, community)
        if real_power_data:
            for oid, power_mw in real_power_data:
                # Use last 2 OID segments (slot.port) to support modular chassis (4500/6500)
                # For single-module switches: suffix is "1.port", for 4506: "slot.port"
                parts = oid.split('.')
                poe_idx = '.'.join(parts[-2:]) if len(parts) >= 2 else parts[-1]
                try:
                    cisco_power[poe_idx] = float(power_mw) / 1000.0
                except:
                    cisco_power[poe_idx] = 0.0
            source = '.9 (real)'
        else:
            alloc_data = snmpbulkwalk(host, OID_CISCO_ALLOC_POWER, community)
            for oid, power_mw in alloc_data:
                parts = oid.split('.')
                poe_idx = '.'.join(parts[-2:]) if len(parts) >= 2 else parts[-1]
                try:
                    cisco_power[poe_idx] = float(power_mw) / 1000.0
                except:
                    cisco_power[poe_idx] = 0.0
            source = '.7 (allocated)'

        logger.info(f"{host}: Cisco PoE data: {len(cisco_power)} entries [{source}]")

        # BUILD port_map indexed by ifIndex
        port_map = {}
        
        for ifidx, name in port_names.items():
            if not is_physical_port(name):
                continue
            
            port_desc = port_descriptions.get(ifidx, '')
            vlan_id = port_vlan_config.get(ifidx)
            status = port_status.get(ifidx, 2)
            is_trunk = trunk_status.get(ifidx, 0)
            
            # Extract PoE index and get power
            # CRITICAL PoE LOGIC:
            # ✅ Fa (FastEthernet) = copper → HAS PoE
            # ✅ Gi (GigabitEthernet) = copper → HAS PoE
            # ❌ Te (TenGig) = fiber (SFP) → NO PoE
            # ❌ Twe (TwentyFiveGig) = fiber (SFP28) → NO PoE
            # ❌ Hu (HundredGig) = fiber (QSFP) → NO PoE
            # ❌ Fo (FortyGig) = fiber (QSFP) → NO PoE
            power_watts = 0.0
            
            # Only copper ports (Fa, Gi) have PoE
            if name.startswith(('Fa', 'Gi', 'Te', 'Twe', 'Fo', 'Hu')):
                poe_index = extract_poe_index_from_port_name(name)
                if poe_index and poe_index in cisco_power:
                    power_watts = cisco_power[poe_index]
            
            # Build VLAN string
            port_vlan = None
            if is_trunk:
                port_vlan = 'TRUNK'
            elif vlan_id:
                port_vlan = str(vlan_id)
            
            # Store indexed by ifIndex!
            port_map[ifidx] = {
                'ifIndex':          ifidx,
                'port_name':        name,
                'port_description': port_desc,
                'power_watts':      round(power_watts, 3),
                'vlan_id':          vlan_id,
                'port_status':      status,
                'is_trunk':         is_trunk,
                'port_vlan':        port_vlan
            }
        
        result['port_map'] = port_map
        result['port_count'] = len([p for p in port_map.values() if p['power_watts'] > 0])
        # Recalculate poe_used as sum of per-port watts (more precise than SNMP OID
        # pethMainPseConsumption which returns integer milliwatts causing rounding errors)
        port_used = sum(p['power_watts'] for p in port_map.values() if p['power_watts'] > 0)
        if port_used > 0:
            result['poe_used'] = round(port_used, 3)
        result['poe_remaining'] = result['poe_available'] - result['poe_used']
        
        if result['poe_available'] > 0:
            result['poe_percentage'] = round((result['poe_used'] / result['poe_available']) * 100, 2)
        
        # Get VLAN names
        result['vlan_names'] = get_vlan_names(host, community)

        # Skip MAC collection for slow/old switches (IOS 12.2 / 2960S)
        # These switches hit 100% CPU when walking 65 VLANs × 4 SNMP tables
        _slow_switches = []
        try:
            import json as _json
            with open('/app/config/devices.json') as _f:
                _cfg = _json.load(_f)
            _slow_switches = list(_cfg.get('slow_switches', {}).keys())
        except:
            pass

        if host in _slow_switches:
            logger.info(f"{host}: slow_switch — skipping MAC collection to protect CPU")
            result['mac_by_ifindex'] = {}
        else:
            result['mac_by_ifindex'] = get_mac_addresses_vlan_context(host, result['vlan_names'], community)

            # Fix VLAN for dot1x ports: vmAccessVlan returns configured VLAN (e.g. 1)
            # but dot1x assigns a different VLAN after auth (e.g. 2).
            # Override port_map VLAN from MAC table which has the real authenticated VLAN.
            for ifidx, macs in result['mac_by_ifindex'].items():
                if not macs or ifidx not in port_map:
                    continue
                port = port_map[ifidx]
                if port.get('is_trunk'):
                    continue
                # Get VLAN from first MAC entry
                mac_vlan = macs[0].get('vlan_id')
                mac_vlan_name = macs[0].get('vlan_name', '')
                if mac_vlan and mac_vlan != port.get('vlan_id'):
                    logger.debug(f"{host}: Port {port.get('port_name')} VLAN override: {port.get('vlan_id')} → {mac_vlan} (dot1x/STATIC)")
                    port_map[ifidx]['vlan_id'] = mac_vlan
                    port_map[ifidx]['port_vlan'] = str(mac_vlan)
                    if mac_vlan_name:
                        port_map[ifidx]['port_vlan'] = f"{mac_vlan}"
        
        logger.info(f"✓ {host}: {result['poe_available']}W budget, {result['poe_used']}W used, {len(port_map)} ports total, {result['port_count']} PoE ports")

    except Exception as e:
        logger.error(f"Error getting data from {host}: {e}")
        import traceback
        traceback.print_exc()

    return result

def save_vlan_names_to_db(device_ip, vlan_names):
    """Save VLAN names to DB"""
    try:
        def save_op(conn):
            cursor = conn.cursor()
            cursor.execute('DELETE FROM poe_vlan_names WHERE device_ip = ?', (device_ip,))
            
            count = 0
            for vlan_id, vlan_name in vlan_names.items():
                cursor.execute('''
                    INSERT INTO poe_vlan_names (device_ip, vlan_id, vlan_name)
                    VALUES (?, ?, ?)
                ''', (device_ip, vlan_id, vlan_name or ''))
                count += 1
            
            conn.commit()
            return count
        
        count = db_execute_with_retry(save_op)
        logger.info(f"{device_ip}: Saved {count} VLAN names")
    except Exception as e:
        logger.error(f"{device_ip}: Cannot save VLAN names: {e}")

def save_mac_addresses_to_db(device_ip, mac_by_ifindex):
    """Save MAC addresses to DB - ifIndex version"""
    try:
        def save_op(conn):
            cursor = conn.cursor()
            cursor.execute('DELETE FROM poe_mac_addresses WHERE device_ip = ?', (device_ip,))
            conn.commit()
            
            count = 0
            for ifidx, mac_list in mac_by_ifindex.items():
                for mac_data in mac_list:
                    try:
                        cursor.execute('''
                            INSERT INTO poe_mac_addresses 
                            (device_ip, ifIndex, mac_address, vlan_id, vlan_name, last_seen)
                            VALUES (?, ?, ?, ?, ?, ?)
                        ''', (
                            device_ip,
                            ifidx,
                            mac_data['mac'],
                            mac_data['vlan_id'],
                            mac_data.get('vlan_name', ''),
                            datetime.now().isoformat()
                        ))
                        count += 1
                    except sqlite3.IntegrityError:
                        continue
            
            conn.commit()
            return count
        
        count = db_execute_with_retry(save_op)
        logger.info(f"{device_ip}: Saved {count} MAC addresses")
    except Exception as e:
        logger.error(f"{device_ip}: Cannot save MAC: {e}")

def save_all_ports_to_db(device_ip, port_map, vlan_names):
    """Save ports to DB - ifIndex version"""
    try:
        def save_op(conn):
            cursor = conn.cursor()
            
            cursor.execute("PRAGMA table_info(poe_ports)")
            columns = [row[1] for row in cursor.fetchall()]
            
            if 'port_vlan_id' not in columns:
                cursor.execute('ALTER TABLE poe_ports ADD COLUMN port_vlan_id INTEGER')
            if 'port_status' not in columns:
                cursor.execute('ALTER TABLE poe_ports ADD COLUMN port_status INTEGER')
            if 'port_vlan' not in columns:
                cursor.execute('ALTER TABLE poe_ports ADD COLUMN port_vlan TEXT')
            if 'is_trunk' not in columns:
                cursor.execute('ALTER TABLE poe_ports ADD COLUMN is_trunk INTEGER DEFAULT 0')
            if 'timestamp' not in columns:
                cursor.execute('ALTER TABLE poe_ports ADD COLUMN timestamp TEXT')
            
            cursor.execute('DELETE FROM poe_ports WHERE device_ip = ?', (device_ip,))
            conn.commit()
            
            count = 0
            for ifidx, port_data in port_map.items():
                try:
                    cursor.execute('''
                        INSERT INTO poe_ports 
                        (device_ip, ifIndex, port_name, port_description, power_watts, 
                         port_vlan_id, port_status, port_vlan, is_trunk, timestamp)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        device_ip,
                        ifidx,
                        port_data['port_name'],
                        port_data['port_description'] or '',
                        port_data['power_watts'],
                        port_data.get('vlan_id'),
                        port_data.get('port_status'),
                        port_data.get('port_vlan'),
                        port_data.get('is_trunk', 0),
                        datetime.now().isoformat()
                    ))
                    count += 1
                except Exception as e:
                    logger.error(f"Failed insert {port_data['port_name']}: {e}")
                    continue
            
            conn.commit()
            return count
        
        count = db_execute_with_retry(save_op)
        logger.info(f"{device_ip}: Saved {count} ports (ifIndex-based)")
    except Exception as e:
        logger.error(f"{device_ip}: Cannot save ports: {e}")