#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Database Initialization Script - ifIndex VERSION
Creates tables using ifIndex as primary key instead of port_number
This matches how Netdisco and other professional tools work.

CRITICAL CHANGES:
- poe_ports: port_number → ifIndex
- poe_mac_addresses: port_number → ifIndex
- All indexes updated
- Backward compatible with new data structure
"""

import sqlite3
import os
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DB_PATH = '/app/data/energy.db'

def init_database():
    """Initialize database with ifIndex-based schema"""
    
    # Create data directory if not exists
    os.makedirs('/app/data', exist_ok=True)
    
    logger.info("Initializing database with ifIndex schema...")
    
    try:
        conn = sqlite3.connect(DB_PATH, timeout=30.0)
        cursor = conn.cursor()
        
        # Enable WAL mode for better concurrent access
        cursor.execute('PRAGMA journal_mode=WAL')
        cursor.execute('PRAGMA busy_timeout=30000')  # 30 sec timeout
        
        # Create poe_devices table (no changes)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS poe_devices (
                device_ip TEXT PRIMARY KEY,
                device_name TEXT NOT NULL,
                device_model TEXT,
                device_serial TEXT,
                poe_available REAL DEFAULT 0,
                poe_used REAL DEFAULT 0,
                poe_remaining REAL DEFAULT 0,
                poe_percentage REAL DEFAULT 0,
                port_count INTEGER DEFAULT 0,
                status TEXT DEFAULT 'PENDING',
                last_scan TEXT
            )
        ''')
        
        # Create poe_ports table with ifIndex
        # CHANGE: port_number → ifIndex
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS poe_ports (
                device_ip TEXT NOT NULL,
                ifIndex INTEGER NOT NULL,
                port_name TEXT,
                port_description TEXT,
                power_watts REAL DEFAULT 0,
                port_vlan_id INTEGER,
                port_status INTEGER,
                port_vlan TEXT,
                is_trunk INTEGER DEFAULT 0,
                timestamp TEXT,
                PRIMARY KEY (device_ip, ifIndex),
                FOREIGN KEY (device_ip) REFERENCES poe_devices(device_ip) ON DELETE CASCADE
            )
        ''')
        
        # MAC addresses table with ifIndex
        # CHANGE: port_number → ifIndex
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS poe_mac_addresses (
                device_ip TEXT NOT NULL,
                ifIndex INTEGER NOT NULL,
                mac_address TEXT NOT NULL,
                vlan_id INTEGER,
                vlan_name TEXT,
                last_seen TEXT,
                PRIMARY KEY (device_ip, ifIndex, mac_address)
            )
        ''')
        
        # VLAN names cache (no changes)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS poe_vlan_names (
                device_ip TEXT NOT NULL,
                vlan_id INTEGER NOT NULL,
                vlan_name TEXT,
                PRIMARY KEY (device_ip, vlan_id)
            )
        ''')
        
        # Create indexes for faster queries
        # UPDATED: Use ifIndex instead of port_number
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_ports_device_ip 
            ON poe_ports(device_ip)
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_ports_ifindex 
            ON poe_ports(device_ip, ifIndex)
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_mac_device_ip 
            ON poe_mac_addresses(device_ip)
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_mac_ifindex 
            ON poe_mac_addresses(device_ip, ifIndex)
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_mac_address 
            ON poe_mac_addresses(mac_address)
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_vlan_device_ip 
            ON poe_vlan_names(device_ip)
        ''')

        # Indexes for mac_vlans_data performance
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_mac_vlan_id
            ON poe_mac_addresses(vlan_id)
        ''')

        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_mac_dev_ifidx_vlan
            ON poe_mac_addresses(device_ip, ifIndex, vlan_id)
        ''')

        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_ports_vlan_id
            ON poe_ports(port_vlan_id)
        ''')

        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_ports_status
            ON poe_ports(port_status)
        ''')
        
        # ================================================================
        # USERS TABLE
        # ================================================================
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT DEFAULT 'operator',
                full_name TEXT DEFAULT '',
                email TEXT DEFAULT '',
                created_at TEXT,
                last_login TEXT,
                is_active INTEGER DEFAULT 1
            )
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)
        ''')

        # ================================================================
        # APP SETTINGS TABLE
        # ================================================================
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS app_settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL DEFAULT \'\'
            )
        ''')
        _defaults = [
            ('lang',              'cs'),
            ('timezone',          'Europe/Prague'),
            ('datetime_format',   '%d.%m.%Y %H:%M'),
            ('name_separator',    '-'),
            ('name_fields',       '[{"pos":0,"label_cs":"Oblast","label_en":"Area"},{"pos":-1,"label_cs":"Rozva\u010de\u010d","label_en":"Rack"}]'),
            ('show_type_filter',  '1'),
            ('show_model_filter', '1'),
        ]
        for _k, _v in _defaults:
            cursor.execute(
                'INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)',
                (_k, _v)
            )

        conn.commit()
        
        # Migrate from auth.json
        _migrate_auth_json(cursor, conn)
        
        conn.commit()
        
        logger.info("✅ Database initialized successfully with ifIndex schema")
        logger.info("   - poe_devices: device_ip (PK)")
        logger.info("   - poe_ports: (device_ip, ifIndex) (PK)")
        logger.info("   - poe_mac_addresses: (device_ip, ifIndex, mac_address) (PK)")
        logger.info("   - poe_vlan_names: (device_ip, vlan_id) (PK)")
        logger.info("   - users: username (UNIQUE)")
        logger.info("   - app_settings: global configuration")
        
        conn.close()
        return True
        
    except Exception as e:
        logger.error(f"❌ Database initialization failed: {e}")
        return False


def _migrate_auth_json(cursor, conn):
    """Migrate users from auth.json to DB. Runs at every startup - safe to re-run."""
    import json
    import os
    
    # Check if any admin already exists → skip
    cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'")
    if cursor.fetchone()[0] > 0:
        logger.info("Users table already populated, skipping migration")
        return
    
    try:
        import bcrypt
    except ImportError:
        logger.error("bcrypt not installed! Run: pip install bcrypt")
        _create_default_admin(cursor)
        return
    
    auth_path = '/app/config/auth.json'
    migrated = 0
    
    try:
        with open(auth_path) as f:
            config = json.load(f)
        users = config.get('users', {})
        
        for username, password in users.items():
            pw_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            try:
                cursor.execute('''
                    INSERT OR IGNORE INTO users (username, password_hash, role, created_at)
                    VALUES (?, ?, ?, ?)
                ''', (username, pw_hash, 'admin', datetime.now().isoformat()))
                migrated += 1
            except Exception as e:
                logger.warning(f"Could not migrate user {username}: {e}")
        
        conn.commit()
        logger.info(f"✅ Migrated {migrated} user(s) from auth.json to DB")
    
    except FileNotFoundError:
        logger.warning("auth.json not found, creating default admin")
        _create_default_admin(cursor)
    except Exception as e:
        logger.error(f"Migration error: {e}")
        _create_default_admin(cursor)


def _create_default_admin(cursor):
    """Create default admin:admin if no users exist."""
    try:
        import bcrypt
        pw_hash = bcrypt.hashpw(b'admin', bcrypt.gensalt()).decode('utf-8')
    except ImportError:
        # Fallback: store plaintext marker (will fail login gracefully)
        pw_hash = 'PLAIN:admin'
    
    cursor.execute('''
        INSERT OR IGNORE INTO users (username, password_hash, role, created_at)
        VALUES (?, ?, ?, ?)
    ''', ('admin', pw_hash, 'admin', datetime.now().isoformat()))
    logger.warning("⚠️  Created default admin user (password: admin) - CHANGE IT!")


if __name__ == '__main__':
    success = init_database()
    if success:
        logger.info("Database ready for ifIndex-based port mapping")
    else:
        logger.error("Database initialization failed!")
