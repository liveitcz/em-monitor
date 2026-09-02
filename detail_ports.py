#!/usr/bin/env python3
# REFACTORED for ifIndex - uses ifIndex as primary key instead of port_number

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
detail_ports.py - IP SORTED VERSION
CHANGES:
- Devices.json sorted by IP address NUMERICALLY (not alphabetically)
- Uses ipaddress module for proper IP sorting
"""

from flask import Flask, render_template, request, jsonify, redirect, url_for, session
import sqlite3
import logging
import os
import json
import datetime
from functools import wraps
import ipaddress
import re
import threading
from concurrent.futures import ProcessPoolExecutor
try:
    import bcrypt
    BCRYPT_AVAILABLE = True
except ImportError:
    BCRYPT_AVAILABLE = False
    import logging as _log
    _log.getLogger(__name__).error('bcrypt not installed! Run: pip install bcrypt')

# ================================================================
# PRIORITY SCAN POOL - SEPARATE FROM SCHEDULER!
# ================================================================
# This ensures RE-SCAN NOW always has available workers
# even when main scheduler is running with 15 workers
PRIORITY_POOL = ProcessPoolExecutor(max_workers=2)
# ================================================================

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
app.config['JSON_AS_ASCII'] = False

DB_PATH = '/app/data/energy.db'
DEVICES_CONFIG = '/app/config/devices.json'


def get_device_name(ip):
    """Read device name from devices.json — checks both 'devices' and 'slow_switches'."""
    try:
        with open(DEVICES_CONFIG) as f:
            cfg = json.load(f)
        name = cfg.get('devices', {}).get(ip) or cfg.get('slow_switches', {}).get(ip)
        return name or 'Unknown'
    except Exception:
        return 'Unknown'
AUTH_CONFIG = '/app/config/auth.json'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configure priority_scan logger with handler
logger_priority = logging.getLogger('priority_scan')
logger_priority.setLevel(logging.INFO)
if not logger_priority.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logger_priority.addHandler(handler)


@app.template_filter('format_date_cz')
def format_date_cz(value):
    """Format datetime for Czech locale"""
    if not value:
        return ''
    try:
        if isinstance(value, str):
            dt = datetime.datetime.fromisoformat(value.replace('Z', '+00:00'))
        else:
            dt = value
        return dt.strftime('%d.%m.%Y %H:%M:%S')
    except:
        return str(value)


def get_user_from_db(username):
    """Get user record from DB. Returns dict or None."""
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10.0)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            'SELECT id, username, password_hash, role, full_name, email, is_active FROM users WHERE username = ?',
            (username,)
        )
        row = cursor.fetchone()
        conn.close()
        if row:
            return dict(row)
        return None
    except Exception as e:
        logger.error(f"get_user_from_db error: {e}")
        return None


def verify_password(plain, hashed):
    """Verify password against bcrypt hash."""
    if not BCRYPT_AVAILABLE:
        # Fallback: plaintext comparison (should not happen in production)
        if hashed.startswith('PLAIN:'):
            return plain == hashed[6:]
        return False
    try:
        return bcrypt.checkpw(plain.encode('utf-8'), hashed.encode('utf-8'))
    except Exception:
        return False


def hash_password(plain):
    """Hash password with bcrypt."""
    if not BCRYPT_AVAILABLE:
        return f'PLAIN:{plain}'
    return bcrypt.hashpw(plain.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def update_last_login(username):
    """Update last_login timestamp in DB."""
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10.0)
        cursor = conn.cursor()
        cursor.execute(
            'UPDATE users SET last_login = ? WHERE username = ?',
            (datetime.datetime.now().isoformat(), username)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"update_last_login error: {e}")


def sort_devices_by_ip(devices_dict):
    """Sort devices dictionary by IP address numerically"""
    try:
        return dict(sorted(
            devices_dict.items(),
            key=lambda x: ipaddress.ip_address(x[0])
        ))
    except (ValueError, ipaddress.AddressValueError):
        # Fallback to string sorting if IP parsing fails
        logger.warning("IP parsing failed, falling back to string sorting")
        return dict(sorted(devices_dict.items()))


def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=30000')
    conn.execute('PRAGMA cache_size=-32000')    # 32 MB query cache
    conn.execute('PRAGMA temp_store=MEMORY')
    return conn


def ensure_mac_vlans_indexes(conn):
    """Create performance indexes if they don't exist yet (idempotent)."""
    idxs = [
        "CREATE INDEX IF NOT EXISTS idx_mac_vlan_id ON poe_mac_addresses(vlan_id)",
        "CREATE INDEX IF NOT EXISTS idx_mac_dev_ifidx_vlan ON poe_mac_addresses(device_ip, ifIndex, vlan_id)",
        "CREATE INDEX IF NOT EXISTS idx_ports_vlan_id ON poe_ports(port_vlan_id)",
        "CREATE INDEX IF NOT EXISTS idx_ports_status ON poe_ports(port_status)",
    ]
    for sql in idxs:
        try:
            conn.execute(sql)
        except Exception:
            pass


# ================================================================
# APP SETTINGS HELPERS
# ================================================================

def get_setting(key, default=''):
    """Read single setting from app_settings table."""
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5.0)
        cursor = conn.cursor()
        cursor.execute('SELECT value FROM app_settings WHERE key = ?', (key,))
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else default
    except Exception:
        return default


def set_setting(key, value):
    """Write single setting to app_settings table."""
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5.0)
        cursor = conn.cursor()
        cursor.execute(
            'INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)',
            (key, str(value))
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f'set_setting error: {e}')
        return False


def get_all_settings():
    """Return all settings as dict."""
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5.0)
        cursor = conn.cursor()
        cursor.execute('SELECT key, value FROM app_settings')
        rows = cursor.fetchall()
        conn.close()
        return {r[0]: r[1] for r in rows}
    except Exception:
        return {}


def ensure_device_changes_table():
    """Ensure device_changes table exists"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS device_changes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                device_ip TEXT NOT NULL,
                device_name TEXT NOT NULL,
                action TEXT NOT NULL,
                username TEXT
            )
        ''')
        conn.commit()
        conn.close()
        logger.info("✓ device_changes table ready")
    except Exception as e:
        logger.error(f"Error creating device_changes table: {e}")


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


def admin_required(f):
    """Decorator: only admin role allowed."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            return redirect(url_for('login'))
        if session.get('role') != 'admin':
            return jsonify({'error': 'Přístup odepřen - vyžaduje roli admin'}), 403
        return f(*args, **kwargs)
    return decorated_function


@app.context_processor
def inject_user():
    """Inject current_user into all templates."""
    return {
        'current_user': session.get('username', ''),
        'current_role': session.get('role', ''),
        'is_admin': session.get('role') == 'admin',
        'app_lang': session.get('lang', get_setting('lang', 'cs')),
    }


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        
        user = get_user_from_db(username)
        
        if user and user['is_active'] and verify_password(password, user['password_hash']):
            session['logged_in'] = True
            session['username'] = user['username']
            session['role'] = user['role']
            session['full_name'] = user.get('full_name', '') or user['username']
            session['lang'] = get_setting('lang', 'cs')
            update_last_login(username)
            logger.info(f"User {username} ({user['role']}) logged in")
            return redirect(url_for('index'))
        else:
            logger.warning(f"Failed login attempt for user: {username}")
            return render_template('login.html', error='Neplatné přihlašovací údaje')
    
    return render_template('login.html')


@app.route('/logout')
def logout():
    username = session.get('username', 'unknown')
    session.clear()
    logger.info(f"User {username} logged out")
    return redirect(url_for('login'))


@app.route('/')
@login_required
def index():
    return render_template('index.html')


@app.route('/devedit')
@login_required
def devedit():
    return render_template('devedit.html')


@app.route('/add-remove')
@login_required
def add_remove():
    """Display device changes log"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT timestamp, device_ip, device_name, action, username
            FROM device_changes
            ORDER BY timestamp DESC
            LIMIT 100
        ''')
        
        entries = []
        for row in cursor.fetchall():
            entries.append({
                'timestamp': row['timestamp'],
                'ip': row['device_ip'],
                'name': row['device_name'],
                'action': row['action'],
                'username': row['username'] if row['username'] else 'system'
            })
        
        conn.close()
        
        last_change = entries[0]['timestamp'] if entries else None
        
        return render_template('add-remove.html', 
                             entries=entries, 
                             last_change=last_change,
                             error=None)
    except Exception as e:
        logger.error(f"Error loading device changes: {e}")
        return render_template('add-remove.html', 
                             entries=[], 
                             last_change=None,
                             error=str(e))


@app.route('/api/devices')
@login_required
def api_devices():
    """API: Get all devices — only IPs present in devices.json"""
    try:
        # Load known IPs from config — smazané zařízení se nevrátí
        try:
            with open(DEVICES_CONFIG) as f:
                _cfg = json.load(f)
            known_ips = set(_cfg.get('devices', {}).keys()) | set(_cfg.get('slow_switches', {}).keys())
        except Exception:
            known_ips = None  # fallback: show all

        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT d.device_ip, d.device_name, d.device_model, d.device_serial,
                   d.poe_available, d.poe_used, d.poe_remaining, d.poe_percentage,
                   d.port_count, d.status, d.last_scan,
                   COUNT(p.ifIndex) as total_ports
            FROM poe_devices d
            LEFT JOIN poe_ports p ON d.device_ip = p.device_ip
            GROUP BY d.device_ip
            ORDER BY d.device_name
        ''')
        
        devices = []
        for row in cursor.fetchall():
            # Skip IPs not in devices.json (deleted but still in DB until next scan cycle)
            if known_ips is not None and row['device_ip'] not in known_ips:
                continue
            devices.append({
                'device_ip': row['device_ip'],
                'device_name': row['device_name'],
                'device_model': row['device_model'],
                'device_serial': row['device_serial'],
                'poe_available': row['poe_available'],
                'poe_used': row['poe_used'],
                'poe_remaining': row['poe_remaining'],
                'poe_percentage': row['poe_percentage'],
                'port_count': row['port_count'],
                'total_ports': row['total_ports'] or 0,
                'status': row['status'],
                'last_scan': row['last_scan']
            })
        
        conn.close()
        
        logger.info(f"API /devices: {len(devices)} active devices")
        return jsonify(devices)
        
    except Exception as e:
        logger.error(f"API /devices error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/devices/list')
@login_required
def api_devices_list():
    """API: List devices for management"""
    try:
        with open(DEVICES_CONFIG) as f:
            config = json.load(f)
        
        # Merge both sections so devedit shows all devices
        all_devs = {**config.get('devices', {}), **config.get('slow_switches', {})}
        devices = []
        for ip, name in all_devs.items():
            is_slow = ip in config.get('slow_switches', {})
            devices.append({'ip': ip, 'name': name, 'slow_switch': is_slow})
        
        # Sort by IP (numerically, not alphabetically)
        try:
            devices.sort(key=lambda d: ipaddress.ip_address(d['ip']))
        except (ValueError, ipaddress.AddressValueError):
            # Fallback to string sorting if IP parsing fails
            devices.sort(key=lambda d: d['ip'])
        
        return jsonify({'devices': devices})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def immediate_scan_device(ip, name):
    """Run immediate scan on newly added device in background"""
    try:
        logger.info(f"🚀 Starting immediate scan for {name} ({ip})")
        
        import snmp_helper
        
        poe_data = snmp_helper.get_poe_data(ip)
        
        if poe_data and poe_data.get('port_count', 0) > 0:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE poe_devices SET
                    device_name = ?,
                    device_model = ?,
                    device_serial = ?,
                    poe_available = ?,
                    poe_used = ?,
                    poe_remaining = ?,
                    poe_percentage = ?,
                    port_count = ?,
                    status = 'OK',
                    last_scan = ?
                WHERE device_ip = ?
            ''', (name, poe_data['model'], poe_data['serial'],
                  poe_data['poe_available'], poe_data['poe_used'],
                  poe_data['poe_remaining'], poe_data['poe_percentage'],
                  poe_data['port_count'], datetime.datetime.now().isoformat(), ip))
            conn.commit()
            conn.close()
            
            snmp_helper.save_all_ports_to_db(ip, poe_data['port_map'], poe_data['vlan_names'])
            snmp_helper.save_vlan_names_to_db(ip, poe_data['vlan_names'])
            snmp_helper.save_mac_addresses_to_db(ip, poe_data['mac_by_port'])
            
            logger.info(f"✓ Immediate scan completed for {name} ({ip})")
        else:
            logger.warning(f"⚠️ Immediate scan returned no data for {name} ({ip})")
    except Exception as e:
        logger.error(f"❌ Immediate scan failed for {name} ({ip}): {e}")


@app.route('/api/devices/add', methods=['POST'])
@login_required
def api_devices_add():
    """API: Add new device"""
    try:
        data = request.get_json()
        name = data.get('name')
        ip = data.get('ip')
        community = data.get('community', '').strip()

        if not name or not ip:
            return jsonify({'error': 'Name and IP required'}), 400

        with open(DEVICES_CONFIG, 'r') as f:
            config = json.load(f)

        if 'devices' not in config:
            config['devices'] = {}

        config['devices'][ip] = name

        # Handle slow_switch flag — also clean up duplicate entries
        is_slow = data.get('slow_switch', False)
        if 'slow_switches' not in config:
            config['slow_switches'] = {}
        if is_slow:
            config['slow_switches'][ip] = name
            # Remove from main devices if it was there (avoid duplicate)
            config.get('devices', {}).pop(ip, None)
        else:
            config['slow_switches'].pop(ip, None)
            # Ensure it's in main devices
            config.setdefault('devices', {})[ip] = name

        # Sort devices by IP (numerically, not alphabetically)
        config['devices'] = sort_devices_by_ip(config['devices'])

        with open(DEVICES_CONFIG, 'w') as f:
            json.dump(config, f, indent=2)

        # Handle per-device community string in snmp.json
        SNMP_CONFIG = '/app/config/snmp.json'
        try:
            with open(SNMP_CONFIG, 'r') as f:
                snmp_config = json.load(f)
        except:
            snmp_config = {'community': 'public'}
        if 'per_device' not in snmp_config:
            snmp_config['per_device'] = {}
        if community:
            snmp_config['per_device'][ip] = community
        else:
            snmp_config['per_device'].pop(ip, None)
        with open(SNMP_CONFIG, 'w') as f:
            json.dump(snmp_config, f, indent=2)
        
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT OR REPLACE INTO poe_devices
            (device_ip, device_name, device_model, device_serial,
             poe_available, poe_used, poe_remaining, poe_percentage,
             port_count, status, last_scan)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (ip, name, 'Unknown', 'Unknown', 0, 0, 0, 0, 0, 'PENDING', datetime.datetime.now().isoformat()))
        
        cursor.execute('''
            INSERT INTO device_changes
            (timestamp, device_ip, device_name, action, username)
            VALUES (?, ?, ?, ?, ?)
        ''', (datetime.datetime.now().isoformat(), ip, name, 'PŘIDÁNO', session.get('username')))
        
        conn.commit()
        conn.close()
        
        logger.info(f"Device {name} ({ip}) added by {session.get('username')}")
        
        scan_thread = threading.Thread(target=immediate_scan_device, args=(ip, name))
        scan_thread.daemon = True
        scan_thread.start()
        logger.info(f"🔄 Immediate scan triggered for {name} ({ip})")
        
        return jsonify({'success': True, 'message': f'Device {name} added, scan started'})
    except Exception as e:
        logger.error(f"Add device error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/devices/remove', methods=['POST'])
@login_required
def api_devices_remove():
    """API: Remove devices"""
    try:
        data = request.get_json()
        ips = data.get('ips', [])
        
        if not ips:
            return jsonify({'error': 'No IPs provided'}), 400
        
        with open(DEVICES_CONFIG, 'r') as f:
            config = json.load(f)
        
        conn = get_db()
        cursor = conn.cursor()
        
        # Handle per-device community cleanup in snmp.json
        SNMP_CONFIG = '/app/config/snmp.json'
        try:
            with open(SNMP_CONFIG, 'r') as f:
                snmp_config = json.load(f)
        except:
            snmp_config = {'community': 'public'}

        for ip in ips:
            cursor.execute('SELECT device_name FROM poe_devices WHERE device_ip = ?', (ip,))
            row = cursor.fetchone()
            device_name = row['device_name'] if row else ip

            cursor.execute('''
                INSERT INTO device_changes
                (timestamp, device_ip, device_name, action, username)
                VALUES (?, ?, ?, ?, ?)
            ''', (datetime.datetime.now().isoformat(), ip, device_name, 'ODEBRÁNO', session.get('username')))

            # Remove from BOTH sections — device may be in either or both
            config.get('devices', {}).pop(ip, None)
            config.get('slow_switches', {}).pop(ip, None)
            snmp_config.get('per_device', {}).pop(ip, None)

        conn.commit()

        # Sort devices by IP (numerically, not alphabetically)
        config['devices'] = sort_devices_by_ip(config['devices'])

        with open(DEVICES_CONFIG, 'w') as f:
            json.dump(config, f, indent=2)

        with open(SNMP_CONFIG, 'w') as f:
            json.dump(snmp_config, f, indent=2)
        
        for ip in ips:
            cursor.execute('DELETE FROM poe_devices WHERE device_ip = ?', (ip,))
            cursor.execute('DELETE FROM poe_ports WHERE device_ip = ?', (ip,))
            cursor.execute('DELETE FROM poe_vlan_names WHERE device_ip = ?', (ip,))
            cursor.execute('DELETE FROM poe_mac_addresses WHERE device_ip = ?', (ip,))
        conn.commit()
        conn.close()
        
        logger.info(f"{len(ips)} device(s) removed by {session.get('username')}")
        return jsonify({'success': True, 'message': f'{len(ips)} device(s) removed'})
    except Exception as e:
        logger.error(f"Remove devices error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/detail/<device_ip>')
@login_required
def device_detail(device_ip):
    return render_template('detail.html', device_ip=device_ip)


@app.route('/api/device/<device_ip>')
@login_required
def api_device(device_ip):
    """API: Get single device info"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT device_ip, device_name, device_model, device_serial,
                   poe_available, poe_used, poe_remaining, poe_percentage,
                   port_count, status, last_scan
            FROM poe_devices
            WHERE device_ip = ?
        ''', (device_ip,))
        
        row = cursor.fetchone()
        
        if row:
            device = {
                'current': {
                    'device_ip': row['device_ip'],
                    'device_name': row['device_name'],
                    'device_model': row['device_model'],
                    'device_serial': row['device_serial'],
                    'poe_available': row['poe_available'],
                    'poe_used': row['poe_used'],
                    'poe_remaining': row['poe_remaining'],
                    'poe_percentage': row['poe_percentage'],
                    'port_count': row['port_count'],
                    'status': row['status'],
                    'last_scan': row['last_scan']
                }
            }
            conn.close()
            return jsonify(device)
        else:
            conn.close()
            return jsonify({'error': 'Device not found'}), 404
            
    except Exception as e:
        logger.error(f"API /device/{device_ip} error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/device_detail/<device_ip>')
@login_required
def api_device_detail(device_ip):
    """API: Get device ports detail"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute("PRAGMA table_info(poe_ports)")
        columns = [row[1] for row in cursor.fetchall()]
        
        # Get VLAN names for this device
        vlan_names_map = {}
        cursor.execute('SELECT vlan_id, vlan_name FROM poe_vlan_names WHERE device_ip = ?', (device_ip,))
        for vrow in cursor.fetchall():
            vlan_names_map[vrow['vlan_id']] = vrow['vlan_name']
        
        select_cols = ['ifIndex', 'port_name', 'port_description', 'power_watts', 'timestamp']
        if 'port_status' in columns:
            select_cols.append('port_status')
        if 'port_vlan' in columns:
            select_cols.append('port_vlan')
        if 'port_vlan_id' in columns:
            select_cols.append('port_vlan_id')
        if 'is_trunk' in columns:
            select_cols.append('is_trunk')
        
        cursor.execute(f'''
            SELECT {', '.join(select_cols)}
            FROM poe_ports
            WHERE device_ip = ?
            AND port_name NOT LIKE '%--Uncontrolled'
            AND port_name NOT LIKE '%--Controlled'
            ORDER BY ifIndex
        ''', (device_ip,))
        
        ports = []
        for row in cursor.fetchall():
            port_num = row['ifIndex']
            
            cursor.execute('''
                SELECT DISTINCT vlan_id, vlan_name, mac_address
                FROM poe_mac_addresses
                WHERE device_ip = ? AND ifIndex = ?
            ''', (device_ip, port_num))
            
            mac_rows = cursor.fetchall()
            mac_vlan = []
            seen = set()
            for mr in mac_rows:
                key = (mr['mac_address'], mr['vlan_id'])
                if key not in seen:
                    seen.add(key)
                    mac_vlan.append({
                        'mac': mr['mac_address'],
                        'vlan_id': mr['vlan_id'],
                        'vlan_name': mr['vlan_name'] or ''
                    })
            
            port_data = {
                'ifIndex': port_num,
                'port_name': row['port_name'],
                'port_description': row['port_description'],
                'power_watts': row['power_watts'],
                'timestamp': row['timestamp'],
                'mac_vlan': mac_vlan
            }
            
            if 'port_status' in columns:
                port_data['port_status'] = row['port_status']
            
            # Build port_vlan with name if available
            if 'port_vlan' in columns:
                port_vlan_text = row['port_vlan']
                # If it's a number and we have a name, add it
                if port_vlan_text and port_vlan_text != 'TRUNK' and 'port_vlan_id' in columns:
                    vlan_id = row['port_vlan_id']
                    if vlan_id and vlan_id in vlan_names_map:
                        vlan_name = vlan_names_map[vlan_id]
                        if vlan_name:
                            port_vlan_text = f"{vlan_id} ({vlan_name})"
                port_data['port_vlan'] = port_vlan_text
            
            # CRITICAL: Identify trunk ports and clear MAC list
            # Rule 1: If port has >5 MAC addresses → it's a trunk
            if len(mac_vlan) > 5:
                port_data['mac_vlan'] = []
                port_data['is_trunk'] = True
            # Rule 2: If marked as trunk in DB
            elif 'is_trunk' in columns and row['is_trunk']:
                port_data['mac_vlan'] = []
                port_data['is_trunk'] = True
            # Rule 3: Otherwise use DB value or default to False
            elif 'is_trunk' in columns:
                port_data['is_trunk'] = row['is_trunk']
            else:
                port_data['is_trunk'] = False
            
            ports.append(port_data)
        
        conn.close()
        
        return jsonify({'ports': ports})
        
    except Exception as e:
        logger.error(f"API /device_detail/{device_ip} error: {e}")
        return jsonify({'error': str(e)}), 500


def normalize_mac(raw):
    """
    Normalize MAC address to xx:xx:xx:xx:xx:xx format.
    Accepts:
      00:fc:ba:04:f7:2d  (colon-separated)   → 00:fc:ba:04:f7:2d
      00-fc-ba-04-f7-2d  (dash-separated)    → 00:fc:ba:04:f7:2d
      00fc.ba04.f72d     (Cisco dot notation) → 00:fc:ba:04:f7:2d
      00fcba04f72d       (raw hex 12 chars)   → 00:fc:ba:04:f7:2d
    Returns normalized string, or None if input is invalid.
    """
    s = raw.lower().strip()
    # Remove all separators and whitespace
    hex_only = re.sub(r'[:\-\. ]', '', s)
    if not re.fullmatch(r'[0-9a-f]{12}', hex_only):
        return None
    # Rebuild as colon-separated pairs
    return ':'.join(hex_only[i:i+2] for i in range(0, 12, 2))


@app.route('/api/search_mac')
@login_required
def search_mac():
    """
    Search for MAC address across all devices.
    Accepts multiple MAC formats:
      00:fc:ba:04:f7:2d  (colon-separated)
      00-fc-ba-04-f7-2d  (dash-separated)
      00fc.ba04.f72d     (Cisco dot notation)
      00fcba04f72d       (raw hex)
    Returns: {found: true/false, device_name, port_name, ...}
    """
    raw_mac = request.args.get('mac', '').strip()
    mac = normalize_mac(raw_mac)

    if not mac:
        response = jsonify({'found': False, 'error': f'Invalid MAC address format: {raw_mac}'})
        response.headers['Content-Type'] = 'application/json; charset=utf-8'
        return response, 400
    
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # Search: same logic as mac-vlans.html
        # 1) Qualifying ports: 1 VLAN on port AND <=10 MACs on that port
        # 2) Prefer access port (port_vlan_id IS NOT NULL) over AP trunk port
        # 3) Pick best result in Python (same dedup as mac-vlans)
        # Subquery counts ALL MACs on each port (not filtered by searched MAC)
        # so the <=10 threshold correctly identifies uplink/trunk ports
        cursor.execute('''
            SELECT
                m.device_ip,
                m.ifIndex,
                m.mac_address,
                m.vlan_id,
                m.vlan_name,
                d.device_name,
                p.port_name,
                p.port_vlan_id,
                CASE WHEN p.port_vlan_id = m.vlan_id THEN 2
                     WHEN p.port_vlan_id IS NOT NULL AND p.port_vlan_id != 0 THEN 1
                     ELSE 0 END as is_access
            FROM poe_mac_addresses m
            LEFT JOIN poe_devices d ON m.device_ip = d.device_ip
            LEFT JOIN poe_ports p ON m.device_ip = p.device_ip AND m.ifIndex = p.ifIndex
            INNER JOIN (
                SELECT device_ip, ifIndex
                FROM poe_mac_addresses
                GROUP BY device_ip, ifIndex
                HAVING COUNT(DISTINCT vlan_id) = 1
                   AND COUNT(DISTINCT mac_address) <= 10
            ) qualifying ON m.device_ip = qualifying.device_ip
                       AND m.ifIndex = qualifying.ifIndex
            WHERE m.mac_address = ?
              AND p.port_name NOT LIKE 'Po%'
            ORDER BY is_access DESC
        ''', (mac,))
        all_rows = cursor.fetchall()
        conn.close()

        # Pick best: prefer access port (is_access=1), fallback to first AP trunk
        row = None
        for r in all_rows:
            if row is None:
                row = r
            elif r['is_access'] > row['is_access']:
                row = r
                if row['is_access'] == 2:
                    break  # exact VLAN match found, done
        
        if row:
            result = {
                'found': True,
                'mac': row['mac_address'],
                'device_ip': row['device_ip'],
                'device_name': row['device_name'] or 'Unknown',
                'ifIndex': row['ifIndex'],
                'port_name': row['port_name'] or f"Port {row['ifIndex']}",
                'vlan_id': row['vlan_id'],
                'vlan_name': row['vlan_name'] or ''
            }
            logger.info(f"MAC search: {mac} found on {result['device_name']} ({result['device_ip']}) - {result['port_name']}")
        else:
            result = {'found': False}
            logger.info(f"MAC search: {mac} not found")
        
        response = jsonify(result)
        response.headers['Content-Type'] = 'application/json; charset=utf-8'
        return response
            
    except Exception as e:
        logger.error(f"MAC search error: {e}")
        response = jsonify({'found': False, 'error': str(e)})
        response.headers['Content-Type'] = 'application/json; charset=utf-8'
        return response, 500




def priority_scan_worker(ip):
    """
    Worker function for priority scan - MODULE LEVEL for ProcessPoolExecutor!
    
    CRITICAL: This runs in a SEPARATE PROCESS via ProcessPoolExecutor
    Must be top-level function to be picklable!
    """
    try:
        logger_priority.info(f"🚀 PRIORITY SCAN STARTED for {ip} (using dedicated worker)")
        
        # Import inside function to avoid circular imports
        from snmp_helper import get_poe_data, save_all_ports_to_db, save_vlan_names_to_db, save_mac_addresses_to_db, scan_lldp, save_lldp_to_db
        
        # Get device name from devices.json (checks both devices + slow_switches)
        device_name = get_device_name(ip)
        
        # Scan device
        data = get_poe_data(ip)
        
        if data and 'model' in data:
            # Save to database (same as arp.py does)
            try:
                conn = sqlite3.connect(DB_PATH, timeout=60.0)
                conn.execute('PRAGMA busy_timeout=60000')
                cursor = conn.cursor()
                
                cursor.execute('''
                    INSERT OR REPLACE INTO poe_devices 
                    (device_ip, device_name, device_model, device_serial, poe_available, poe_used, 
                     poe_remaining, poe_percentage, port_count, status, last_scan)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    ip, device_name,
                    data.get('model', 'Unknown'),
                    data.get('serial', 'Unknown'),
                    data.get('poe_available', 0),
                    data.get('poe_used', 0),
                    data.get('poe_remaining', 0),
                    data.get('poe_percentage', 0),
                    data.get('port_count', 0),
                    'OK',
                    datetime.datetime.now().isoformat()
                ))
                conn.commit()
                conn.close()
                
                # Save ports, VLANs, MACs
                save_all_ports_to_db(ip, data.get('port_map', {}), data.get('vlan_names', {}))
                save_vlan_names_to_db(ip, data.get('vlan_names', {}))
                save_mac_addresses_to_db(ip, data.get('mac_by_ifindex', {}))
                
                logger_priority.info(f"✅ PRIORITY SCAN COMPLETED for {ip}: {data['model']}, {data['port_count']} ports - DATA SAVED TO DB")
                return {'success': True, 'ip': ip, 'model': data['model']}
            except Exception as e:
                logger_priority.error(f"DB save error for {ip}: {e}")
                return {'success': False, 'ip': ip, 'error': f'DB save failed: {e}'}
        else:
            logger_priority.warning(f"⚠️ PRIORITY SCAN FAILED for {ip}: No data returned")
            return {'success': False, 'ip': ip, 'error': 'No data'}
    except Exception as e:
        logger_priority.error(f"❌ PRIORITY SCAN ERROR for {ip}: {e}")
        import traceback
        traceback.print_exc()
        return {'success': False, 'ip': ip, 'error': str(e)}


@app.route('/api/rescan/<device_ip>', methods=['POST'])
@login_required
def rescan_device(device_ip):
    """
    RE-SCAN NOW - Scan single device in PRIORITY POOL
    
    CRITICAL: Uses separate ProcessPoolExecutor (2 workers)
    This ensures priority scans run even when scheduler is using all 15 workers!
    
    Returns: {success: true} immediately, scan runs in background
    """
    try:
        logger.info(f"🔄 MAKING PRIORITY SCAN FOR IP {device_ip}")
        
        # Submit to PRIORITY POOL (separate from scheduler!)
        # priority_scan_worker is defined at module level so it can be pickled
        future = PRIORITY_POOL.submit(priority_scan_worker, device_ip)
        
        # Return immediately
        return jsonify({
            'success': True, 
            'message': f'Priority scan queued for {device_ip}. Refresh page in 12 seconds.'
        })
            
    except Exception as e:
        logger.error(f"RE-SCAN error for {device_ip}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


def cleanup_priority_pool():
    """Cleanup PRIORITY_POOL on shutdown"""
    logger.info("Shutting down PRIORITY_POOL...")
    PRIORITY_POOL.shutdown(wait=True)
    logger.info("PRIORITY_POOL shutdown complete")


# ================================================================
# PROFILE & USER MANAGEMENT ROUTES
# ================================================================

@app.route('/profile')
@login_required
def profile():
    """User profile page"""
    username = session.get('username')
    user = get_user_from_db(username)
    return render_template('profile.html', user=user)


@app.route('/api/profile/update', methods=['POST'])
@login_required
def api_profile_update():
    """Update own profile (full_name, email, password)"""
    username = session.get('username')
    data = request.get_json() or {}
    
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10.0)
        cursor = conn.cursor()
        
        # Update full_name and email
        if 'full_name' in data or 'email' in data:
            cursor.execute('''
                UPDATE users SET full_name = ?, email = ? WHERE username = ?
            ''', (
                data.get('full_name', ''),
                data.get('email', ''),
                username
            ))
            session['full_name'] = data.get('full_name', '') or username
        
        # Change password
        if data.get('new_password'):
            current_password = data.get('current_password', '')
            user = get_user_from_db(username)
            
            if not verify_password(current_password, user['password_hash']):
                conn.close()
                return jsonify({'success': False, 'error': 'Aktuální heslo je nesprávné'}), 400
            
            if len(data['new_password']) < 4:
                conn.close()
                return jsonify({'success': False, 'error': 'Nové heslo musí mít alespoň 4 znaky'}), 400
            
            new_hash = hash_password(data['new_password'])
            cursor.execute('UPDATE users SET password_hash = ? WHERE username = ?', (new_hash, username))
        
        conn.commit()
        conn.close()
        logger.info(f"User {username} updated their profile")
        return jsonify({'success': True})
        
    except Exception as e:
        logger.error(f"Profile update error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/admin/users')
@login_required
def admin_users():
    """Admin: User management page"""
    if session.get('role') != 'admin':
        return redirect(url_for('index'))
    return render_template('user_mgmt.html')


@app.route('/api/admin/users', methods=['GET'])
@login_required
def api_admin_users_list():
    """Admin: List all users"""
    if session.get('role') != 'admin':
        return jsonify({'error': 'Přístup odepřen'}), 403
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10.0)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, username, role, full_name, email, created_at, last_login, is_active
            FROM users ORDER BY username
        ''')
        users = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return jsonify({'users': users})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/users/add', methods=['POST'])
@login_required
def api_admin_users_add():
    """Admin: Add new user"""
    if session.get('role') != 'admin':
        return jsonify({'error': 'Přístup odepřen'}), 403
    
    data = request.get_json() or {}
    username = data.get('username', '').strip()
    password = data.get('password', '')
    role = data.get('role', 'operator')
    full_name = data.get('full_name', '')
    email = data.get('email', '')
    
    if not username or not password:
        return jsonify({'success': False, 'error': 'Username a heslo jsou povinné'}), 400
    if len(password) < 4:
        return jsonify({'success': False, 'error': 'Heslo musí mít alespoň 4 znaky'}), 400
    if role not in ('admin', 'operator'):
        return jsonify({'success': False, 'error': 'Neplatná role'}), 400
    
    try:
        pw_hash = hash_password(password)
        conn = sqlite3.connect(DB_PATH, timeout=10.0)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO users (username, password_hash, role, full_name, email, created_at, is_active)
            VALUES (?, ?, ?, ?, ?, ?, 1)
        ''', (username, pw_hash, role, full_name, email, datetime.datetime.now().isoformat()))
        conn.commit()
        conn.close()
        logger.info(f"Admin {session.get('username')} created user {username} ({role})")
        return jsonify({'success': True, 'message': f'Uživatel {username} vytvořen'})
    except sqlite3.IntegrityError:
        return jsonify({'success': False, 'error': f'Uživatelské jméno "{username}" již existuje'}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/admin/users/update', methods=['POST'])
@login_required
def api_admin_users_update():
    """Admin: Update user (role, active, reset password)"""
    if session.get('role') != 'admin':
        return jsonify({'error': 'Přístup odepřen'}), 403
    
    data = request.get_json() or {}
    target_username = data.get('username', '').strip()
    
    if not target_username:
        return jsonify({'success': False, 'error': 'Username chybí'}), 400
    
    # Prevent admin from deactivating themselves
    if target_username == session.get('username') and data.get('is_active') == 0:
        return jsonify({'success': False, 'error': 'Nemůžeš deaktivovat sám sebe'}), 400
    
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10.0)
        cursor = conn.cursor()
        
        updates = []
        params = []
        
        if 'role' in data and data['role'] in ('admin', 'operator'):
            updates.append('role = ?')
            params.append(data['role'])
        if 'is_active' in data:
            updates.append('is_active = ?')
            params.append(1 if data['is_active'] else 0)
        if 'full_name' in data:
            updates.append('full_name = ?')
            params.append(data['full_name'])
        if 'email' in data:
            updates.append('email = ?')
            params.append(data['email'])
        if data.get('new_password'):
            if len(data['new_password']) < 4:
                conn.close()
                return jsonify({'success': False, 'error': 'Heslo musí mít alespoň 4 znaky'}), 400
            updates.append('password_hash = ?')
            params.append(hash_password(data['new_password']))
        
        if not updates:
            conn.close()
            return jsonify({'success': False, 'error': 'Žádné změny'}), 400
        
        params.append(target_username)
        cursor.execute(f"UPDATE users SET {', '.join(updates)} WHERE username = ?", params)
        conn.commit()
        conn.close()
        logger.info(f"Admin {session.get('username')} updated user {target_username}")
        return jsonify({'success': True})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/admin/users/delete', methods=['POST'])
@login_required
def api_admin_users_delete():
    """Admin: Delete user"""
    if session.get('role') != 'admin':
        return jsonify({'error': 'Přístup odepřen'}), 403
    
    data = request.get_json() or {}
    target_username = data.get('username', '').strip()
    
    if target_username == session.get('username'):
        return jsonify({'success': False, 'error': 'Nemůžeš smazat sám sebe'}), 400
    
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10.0)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM users WHERE username = ?', (target_username,))
        if cursor.rowcount == 0:
            conn.close()
            return jsonify({'success': False, 'error': 'Uživatel nenalezen'}), 404
        conn.commit()
        conn.close()
        logger.info(f"Admin {session.get('username')} deleted user {target_username}")
        return jsonify({'success': True, 'message': f'Uživatel {target_username} smazán'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/mac-vlans')
@login_required
def mac_vlans():
    """MAC & VLANs overview page"""
    return render_template('mac_vlans.html')


@app.route('/user_devices')
@login_required
def user_devices():
    """LLDP Network devices overview page"""
    return render_template('user_devices.html')


@app.route('/api/lldp_data')
@login_required
def api_lldp_data():
    """
    Returns LLDP neighbor data for /user_devices page.
    ?type=KAMERA|AP|SWITCH|...  filter by device type
    ?all=1  return all types
    ?scan=1  trigger fresh LLDP scan before returning data
    """
    type_filter = request.args.get('type', '')
    scan_fresh  = request.args.get('scan', type=int, default=0)

    try:
        conn = get_db()
        cursor = conn.cursor()

        # Optional fresh scan
        if scan_fresh:
            cursor.execute('SELECT device_ip FROM poe_devices ORDER BY device_ip')
            ips = [r['device_ip'] for r in cursor.fetchall()]
            conn.close()
            for ip in ips:
                try:
                    neighbors = scan_lldp(ip)
                    save_lldp_to_db(ip, neighbors)
                except Exception as e:
                    logger.warning(f"LLDP scan failed for {ip}: {e}")
            conn = get_db()
            cursor = conn.cursor()

        # Get distinct device types for the category pills
        cursor.execute("""
            SELECT device_type, COUNT(*) as cnt
            FROM (
                SELECT device_type
                FROM lldp_neighbors
                GROUP BY scanner_ip, local_port
            )
            GROUP BY device_type
            ORDER BY cnt DESC
        """)
        type_counts = {r['device_type']: r['cnt'] for r in cursor.fetchall()}

        # Get neighbors
        if type_filter:
            cursor.execute("""
                SELECT n.*, d.device_name,
                       p.port_vlan_id,
                       COALESCE(vn.vlan_name, '') as vlan_name
                FROM lldp_neighbors n
                LEFT JOIN poe_devices d ON n.scanner_ip = d.device_ip
                LEFT JOIN poe_ports p
                    ON n.scanner_ip = p.device_ip AND p.port_name = n.local_port
                LEFT JOIN poe_vlan_names vn
                    ON p.port_vlan_id = vn.vlan_id AND vn.device_ip = p.device_ip
                WHERE n.device_type = ?
                GROUP BY n.scanner_ip, n.local_port
                ORDER BY n.device_type, n.sys_name, n.scanner_ip, n.local_port
            """, (type_filter,))
        else:
            cursor.execute("""
                SELECT n.*, d.device_name,
                       p.port_vlan_id,
                       COALESCE(vn.vlan_name, '') as vlan_name
                FROM lldp_neighbors n
                LEFT JOIN poe_devices d ON n.scanner_ip = d.device_ip
                LEFT JOIN poe_ports p
                    ON n.scanner_ip = p.device_ip AND p.port_name = n.local_port
                LEFT JOIN poe_vlan_names vn
                    ON p.port_vlan_id = vn.vlan_id AND vn.device_ip = p.device_ip
                GROUP BY n.scanner_ip, n.local_port
                ORDER BY n.device_type, n.sys_name, n.scanner_ip, n.local_port
            """)

        rows = cursor.fetchall()
        conn.close()

        neighbors = [{
            'scanner_ip':   row['scanner_ip'],
            'scanner_name': row['device_name'] or row['scanner_ip'],
            'local_port':   row['local_port'] or f"ifIdx:{row['local_ifindex']}",
            'vlan_id':      row['port_vlan_id'] or '',
            'vlan_name':    row['vlan_name'] or '',
            'sys_name':     row['sys_name'] or '-',
            'sys_desc':     row['sys_desc'] or '-',
            'port_desc':    row['port_desc'] or '',
            'mgmt_ip':      row['mgmt_ip'] or '',
            'device_type':  row['device_type'] or 'NEZARAZENO',
            'timestamp':    row['timestamp'] or '',
        } for row in rows]

        return jsonify({
            'neighbors':   neighbors,
            'type_counts': type_counts,
            'total':       len(neighbors),
        })

    except Exception as e:
        logger.error(f"api_lldp_data error: {e}")
        response = jsonify({'error': str(e), 'neighbors': [], 'type_counts': {}, 'total': 0})
        response.headers['Content-Type'] = 'application/json; charset=utf-8'
        return response, 500


@app.route('/api/lldp_scan_now', methods=['POST'])
@login_required
def api_lldp_scan_now():
    """Trigger LLDP scan on all devices in background."""
    if session.get('role') != 'admin':
        return jsonify({'success': False, 'error': 'Admin required'}), 403

    def _scan_all():
        import snmp_helper as _sh
        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute('SELECT device_ip FROM poe_devices ORDER BY device_ip')
            ips = [r['device_ip'] for r in cursor.fetchall()]
            conn.close()
            for ip in ips:
                try:
                    neighbors = _sh.scan_lldp(ip)
                    _sh.save_lldp_to_db(ip, neighbors)
                except Exception as ex:
                    logger.warning(f"LLDP scan {ip}: {ex}")
        except Exception as ex:
            logger.error(f"LLDP scan_all error: {ex}")

    import threading
    t = threading.Thread(target=_scan_all, daemon=True)
    t.start()
    return jsonify({'success': True, 'message': 'LLDP scan started in background'})


@app.route('/api/mac_vlans_data')
@login_required
def api_mac_vlans_data():
    """
    Returns:
    - vlans: list of {vlan_id, vlan_name, mac_count} - excludes system VLANs 1002-1005
    - total_macs: int
    - macs: list of {mac, device_name, device_ip, port_name, port_description, vlan_id, vlan_name}
             only from ACCESS ports (not trunk, not Po)
    Optionally filtered by ?vlan=<id>
    """
    SYSTEM_VLANS = {1002, 1003, 1004, 1005}
    vlan_filter  = request.args.get('vlan', type=int)
    vlans_only   = request.args.get('vlans_only', type=int, default=0)
    all_vlans    = request.args.get('all', type=int, default=0)
    include_down = request.args.get('include_down', type=int, default=0)

    try:
        conn = get_db()
        ensure_mac_vlans_indexes(conn)   # create indexes on existing DBs
        conn.execute('PRAGMA optimize')  # update query planner stats
        cursor = conn.cursor()

        # Always fetch VLANs + MAC counts (lightweight)
        cursor.execute("""
            SELECT vlan_id, vlan_name
            FROM poe_vlan_names
            WHERE vlan_id NOT IN (1002, 1003, 1004, 1005)
            GROUP BY vlan_id
            ORDER BY vlan_id
        """)
        vlan_rows = cursor.fetchall()

        # Fast VLAN MAC count — only ACTIVE ports (port_status=1), matches "Aktivní porty" view
        cursor.execute("""
            SELECT m.vlan_id, COUNT(DISTINCT m.mac_address) as mac_count
            FROM poe_mac_addresses m
            INNER JOIN poe_ports p ON m.device_ip = p.device_ip AND m.ifIndex = p.ifIndex
            WHERE m.vlan_id NOT IN (1002, 1003, 1004, 1005)
              AND p.port_name NOT LIKE 'Po%'
              AND p.port_status = 1
            GROUP BY m.vlan_id
        """)
        vlan_mac_counts = {row['vlan_id']: row['mac_count'] for row in cursor.fetchall()}

        vlans = []
        for row in vlan_rows:
            vid = row['vlan_id']
            if vid in SYSTEM_VLANS:
                continue
            vlans.append({
                'vlan_id': vid,
                'vlan_name': row['vlan_name'] or '',
                'mac_count': vlan_mac_counts.get(vid, 0)
            })

        # If vlans_only=1, skip fetching MAC rows entirely
        if vlans_only:
            conn.close()
            return jsonify({'vlans': vlans, 'macs': [], 'total_macs': sum(v['mac_count'] for v in vlans)})

        # all=1: load all MACs from all VLANs
        if all_vlans:
            cursor.execute("""
                SELECT
                    m.mac_address, m.vlan_id, m.vlan_name,
                    d.device_name, d.device_ip, p.port_name, p.port_description,
                    COALESCE(p.port_status, 2) as port_status
                FROM poe_mac_addresses m
                INNER JOIN poe_ports p ON m.device_ip = p.device_ip AND m.ifIndex = p.ifIndex
                LEFT JOIN poe_devices d ON m.device_ip = d.device_ip
                WHERE m.vlan_id NOT IN (1002, 1003, 1004, 1005)
                  AND p.port_name NOT LIKE 'Po%'
                GROUP BY m.device_ip, m.ifIndex
                HAVING COUNT(DISTINCT m.vlan_id) = 1
                   AND COUNT(DISTINCT m.mac_address) <= 10
                ORDER BY m.vlan_id, d.device_name, p.port_name, m.mac_address
            """)
            all_rows = cursor.fetchall()
            conn.close()
            macs = [{
                'mac': row['mac_address'], 'vlan_id': row['vlan_id'],
                'vlan_name': row['vlan_name'] or '',
                'device_name': row['device_name'] or row['device_ip'] or '?',
                'device_ip': row['device_ip'] or '',
                'port_name': row['port_name'] or '?',
                'port_description': row['port_description'] or '',
                'port_status': row['port_status']
            } for row in all_rows]
            return jsonify({'vlans': vlans, 'macs': macs, 'total_macs': len(macs)})

        # vlan_filter is REQUIRED when not vlans_only (prevent full table dump)
        if not vlan_filter:
            conn.close()
            return jsonify({'vlans': vlans, 'macs': [], 'total_macs': 0,
                            'info': 'Select a VLAN to load MAC addresses'})

        # include_down=1: query ALL ports (incl. DOWN) via poe_ports + LEFT JOIN macs
        # DOWN ports have port_vlan_id set from last known scan even when down.
        # We search both port_vlan_id = vlan AND any MAC learned on that VLAN.
        if include_down:
            # Query ALL ports configured on this VLAN (from poe_ports.port_vlan_id).
            # LEFT JOIN macs only for this VLAN — one row per port via GROUP BY.
            # HAVING <= 10 MACs excludes uplink/trunk ports that slipped through.
            cursor.execute("""
                SELECT
                    p.port_name,
                    p.port_description,
                    COALESCE(p.port_status, 2)  AS port_status,
                    p.port_vlan_id,
                    d.device_name,
                    d.device_ip,
                    m.mac_address,
                    COALESCE(m.vlan_id, p.port_vlan_id) AS vlan_id,
                    COALESCE(m.vlan_name, '')            AS vlan_name
                FROM poe_ports p
                LEFT JOIN poe_devices d ON p.device_ip = d.device_ip
                LEFT JOIN poe_mac_addresses m
                    ON  p.device_ip = m.device_ip
                    AND p.ifIndex   = m.ifIndex
                    AND m.vlan_id   = ?
                WHERE p.port_vlan_id = ?
                  AND p.port_name NOT LIKE 'Po%%'
                  AND COALESCE(p.is_trunk, 0) = 0
                GROUP BY p.device_ip, p.ifIndex
                HAVING COUNT(DISTINCT m.mac_address) <= 10
                ORDER BY p.port_status ASC, d.device_name, p.port_name
            """, (vlan_filter, vlan_filter))
            down_rows = cursor.fetchall()
            conn.close()
            macs = [{
                'mac':              row['mac_address'] or '-',
                'vlan_id':          row['vlan_id'] or vlan_filter,
                'vlan_name':        row['vlan_name'] or '',
                'device_name':      row['device_name'] or row['device_ip'] or '?',
                'device_ip':        row['device_ip'] or '',
                'port_name':        row['port_name'] or '?',
                'port_description': row['port_description'] or '',
                'port_status':      row['port_status']
            } for row in down_rows]
            return jsonify({'vlans': vlans, 'macs': macs,
                            'total_macs': len(macs), 'vlan_filter': vlan_filter})

        # Prefer: access port (port_vlan_id IS NOT NULL)
        # Fallback: AP trunk port (port_vlan_id NULL, 1 VLAN, ≤10 MAC)
        cursor.execute("""
            SELECT
                m.mac_address,
                m.vlan_id,
                m.vlan_name,
                d.device_name,
                d.device_ip,
                p.port_name,
                p.port_description,
                COALESCE(p.port_status, 2) as port_status,
                CASE WHEN p.port_vlan_id = m.vlan_id THEN 2
                     WHEN p.port_vlan_id IS NOT NULL AND p.port_vlan_id != 0 THEN 1
                     ELSE 0 END as is_access
            FROM poe_mac_addresses m
            INNER JOIN poe_ports p ON m.device_ip = p.device_ip AND m.ifIndex = p.ifIndex
            LEFT JOIN poe_devices d ON m.device_ip = d.device_ip
            WHERE m.vlan_id = ?
              AND m.vlan_id NOT IN (1002, 1003, 1004, 1005)
              AND p.port_name NOT LIKE 'Po%'
            GROUP BY m.device_ip, m.ifIndex
            HAVING COUNT(DISTINCT m.vlan_id) = 1
               AND COUNT(DISTINCT m.mac_address) <= 10
            ORDER BY is_access DESC, d.device_name, p.port_name, m.mac_address
        """, (vlan_filter,))
        all_rows = cursor.fetchall()

        # Deduplicate per MAC: keep only the best port (access preferred over AP trunk)
        seen_macs = {}
        for row in all_rows:
            mac_addr = row['mac_address']
            if mac_addr not in seen_macs:
                seen_macs[mac_addr] = row
            elif row['is_access'] > seen_macs[mac_addr]['is_access']:
                seen_macs[mac_addr] = row  # upgrade: 0→1→2 (exact VLAN match wins)
        mac_rows = list(seen_macs.values())
        conn.close()

        macs = [{
            'mac': row['mac_address'],
            'vlan_id': row['vlan_id'],
            'vlan_name': row['vlan_name'] or '',
            'device_name': row['device_name'] or row['device_ip'] or '?',
            'device_ip': row['device_ip'] or '',
            'port_name': row['port_name'] or '?',
            'port_description': row['port_description'] or '',
            'port_status': row['port_status']
        } for row in mac_rows]

        return jsonify({
            'vlans': vlans,
            'macs': macs,
            'total_macs': len(macs),
            'vlan_filter': vlan_filter
        })

    except Exception as e:
        logger.error(f"api_mac_vlans_data error: {e}")
        return jsonify({'error': str(e)}), 500


# ================================================================
# SETTINGS ROUTES
# ================================================================

@app.route('/settings')
@login_required
def settings_page():
    if session.get('role') != 'admin':
        return redirect(url_for('index'))
    s = get_all_settings()
    return render_template('settings.html', settings=s)


@app.route('/api/settings')
@login_required
def api_settings_get():
    return jsonify(get_all_settings())


@app.route('/api/settings/save', methods=['POST'])
@login_required
def api_settings_save():
    if session.get('role') != 'admin':
        return jsonify({'success': False, 'error': 'Admin required'}), 403
    data = request.get_json() or {}
    allowed = {'lang', 'poe_unit', 'poe_detail_unit', 'timezone', 'datetime_format',
               'name_separator', 'name_fields', 'show_type_filter', 'show_model_filter'}
    pairs = []
    for key, val in data.items():
        if key in allowed:
            v = val if isinstance(val, str) else json.dumps(val, ensure_ascii=False)
            pairs.append((key, v))
    if not pairs:
        return jsonify({'success': True, 'saved': []})
    try:
        conn = sqlite3.connect(DB_PATH, timeout=30.0)
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA busy_timeout=30000')
        conn.execute('PRAGMA synchronous=NORMAL')
        cursor = conn.cursor()
        cursor.executemany(
            'INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)', pairs
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f'api_settings_save DB error: {e}')
        return jsonify({'success': False, 'error': str(e)})
    saved = [k for k, _ in pairs]
    if 'lang' in saved:
        session['lang'] = data.get('lang', 'cs')
    logger.info(f"Settings saved by {session.get('username')}: {saved}")
    return jsonify({'success': True, 'saved': saved})


# ================================================================
# BACKUP ROUTES
# ================================================================

BACKUP_DIR = '/app/data/backups'


def _export_users_sql():
    """Export users table as SQL INSERT statements."""
    lines = [
        '-- EM users backup\n',
        '-- Restore: sqlite3 /app/data/energy.db < users_backup.sql\n\n',
    ]
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5.0)
        cursor = conn.cursor()
        cursor.execute(
            'SELECT id, username, password_hash, role, full_name, email, created_at, is_active FROM users'
        )
        rows = cursor.fetchall()
        conn.close()
        lines.append('DELETE FROM users;\n')
        for row in rows:
            vals = ', '.join([
                'NULL' if v is None
                else f"'{str(v).replace(chr(39), chr(39)*2)}'"
                for v in row
            ])
            lines.append(
                'INSERT INTO users (id, username, password_hash, role, full_name, email, created_at, is_active)'
                f' VALUES ({vals});\n'
            )
    except Exception as e:
        lines.append(f'-- Error exporting users: {e}\n')
    return ''.join(lines)


@app.route('/api/backup/create', methods=['POST'])
@login_required
def api_backup_create():
    import tarfile, io
    if session.get('role') != 'admin':
        return jsonify({'ok': False, 'msg': 'Admin required'}), 403
    data   = request.get_json() or {}
    btype  = data.get('type', 'core')   # 'core' | 'credentials'
    os.makedirs(BACKUP_DIR, exist_ok=True)
    now    = datetime.datetime.now().strftime('%d-%m-%Y_%H-%M')
    suffix = 'core' if btype == 'core' else 'with_credentials'
    fname  = f'em-backup_{now}_{suffix}.tar.gz'
    out    = os.path.join(BACKUP_DIR, fname)
    try:
        with tarfile.open(out, 'w:gz') as tar:
            config_dir = '/app/config'
            if os.path.isdir(config_dir):
                tar.add(config_dir, arcname='config')
            if btype == 'credentials':
                sql_bytes = _export_users_sql().encode('utf-8')
                ti = tarfile.TarInfo(name='users_backup.sql')
                ti.size = len(sql_bytes)
                tar.addfile(ti, io.BytesIO(sql_bytes))
        size_kb = os.path.getsize(out) // 1024
        size_str = f'{size_kb} KB' if size_kb < 1024 else f'{size_kb/1024:.1f} MB'
        logger.info(f"Backup created by {session.get('username')}: {fname} ({size_str})")
        return jsonify({'ok': True, 'filename': fname, 'size': size_str,
                        'download_url': f'/api/backup/download/{fname}'})
    except Exception as e:
        return jsonify({'ok': False, 'msg': str(e)})


@app.route('/api/backup/download/<filename>')
@login_required
def api_backup_download(filename):
    from flask import send_file
    if session.get('role') != 'admin':
        return 'Forbidden', 403
    if '/' in filename or '..' in filename or not filename.endswith('.tar.gz'):
        return 'Invalid filename', 400
    path = os.path.join(BACKUP_DIR, filename)
    if not os.path.exists(path):
        return 'Not found', 404
    return send_file(path, as_attachment=True, download_name=filename)


@app.route('/api/backup/list')
@login_required
def api_backup_list():
    if session.get('role') != 'admin':
        return jsonify({'backups': []})
    os.makedirs(BACKUP_DIR, exist_ok=True)
    backups = []
    for fname in sorted(os.listdir(BACKUP_DIR), reverse=True):
        if not fname.endswith('.tar.gz'):
            continue
        path = os.path.join(BACKUP_DIR, fname)
        st   = os.stat(path)
        size_kb = st.st_size // 1024
        size_str = f'{size_kb} KB' if size_kb < 1024 else f'{size_kb/1024:.1f} MB'
        btype = 'credentials' if 'with_credentials' in fname else 'core'
        backups.append({
            'filename': fname,
            'size':     size_str,
            'date':     datetime.datetime.fromtimestamp(st.st_mtime).strftime('%d.%m.%Y %H:%M'),
            'type':     btype,
        })
    return jsonify({'backups': backups})


@app.route('/api/backup/delete', methods=['POST'])
@login_required
def api_backup_delete():
    if session.get('role') != 'admin':
        return jsonify({'ok': False, 'msg': 'Admin required'}), 403
    data  = request.get_json() or {}
    fname = data.get('filename', '')
    if '/' in fname or '..' in fname or not fname.endswith('.tar.gz'):
        return jsonify({'ok': False, 'msg': 'Invalid filename'})
    path = os.path.join(BACKUP_DIR, fname)
    try:
        os.remove(path)
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'msg': str(e)})


if __name__ == '__main__':
    import atexit
    atexit.register(cleanup_priority_pool)
    
    logger.info("="*60)
    logger.info("✅ Flask web interface starting")
    logger.info(f"   - Database: {DB_PATH}")
    logger.info(f"   - Auth config: {AUTH_CONFIG}")
    logger.info(f"   - Priority scan pool: 2 dedicated workers")
    logger.info("   - Port: 4999")
    logger.info("="*60)
    
    ensure_device_changes_table()

    # ── LLDP background scheduler (every 6 hours) ──────────────────────────────
    def _lldp_scheduler():
        import time as _time
        import snmp_helper as _sh
        LLDP_INTERVAL = 6 * 3600  # 6 hours
        logger.info("LLDP scheduler started (interval: 6h)")
        while True:
            _time.sleep(LLDP_INTERVAL)
            try:
                conn = get_db()
                cursor = conn.cursor()
                cursor.execute('SELECT device_ip FROM poe_devices ORDER BY device_ip')
                ips = [r['device_ip'] for r in cursor.fetchall()]
                conn.close()
                logger.info(f"LLDP scheduled scan: {len(ips)} devices")
                for ip in ips:
                    try:
                        neighbors = _sh.scan_lldp(ip)
                        _sh.save_lldp_to_db(ip, neighbors)
                    except Exception as ex:
                        logger.warning(f"LLDP scheduled scan {ip}: {ex}")
            except Exception as ex:
                logger.error(f"LLDP scheduler error: {ex}")

    _lldp_thread = threading.Thread(target=_lldp_scheduler, daemon=True)
    _lldp_thread.start()
    logger.info("LLDP background scheduler started (every 6h)")
    # ──────────────────────────────────────────────────────────────────────────
    
    app.run(host='0.0.0.0', port=4999, debug=False)