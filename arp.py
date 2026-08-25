#!/usr/bin/env python3
"""
arp.py - STABLE VERSION with optimizations
- ProcessPoolExecutor (10 workers)
- Writes to energy.db (single database, no replica)
- Fast and reliable
"""

import sqlite3
import json
import logging
import sys
import time
import os
from datetime import datetime
from concurrent.futures import ProcessPoolExecutor, as_completed
from apscheduler.schedulers.blocking import BlockingScheduler

from snmp_helper import (
    get_poe_data,
    save_all_ports_to_db,
    save_vlan_names_to_db,
    save_mac_addresses_to_db
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DB_PATH = '/app/data/energy.db'
DEVICES_PATH = '/app/config/devices.json'
LOGS_DIR = '/app/logs'
MAX_WORKERS = 10  # Optimized for stability

os.makedirs(LOGS_DIR, exist_ok=True)


def cleanup_old_logs():
    try:
        now = datetime.now()
        deleted_count = 0
        for filename in os.listdir(LOGS_DIR):
            if filename.startswith('scan_devices_') and filename.endswith('.log'):
                filepath = os.path.join(LOGS_DIR, filename)
                file_mtime = datetime.fromtimestamp(os.path.getmtime(filepath))
                if (now - file_mtime).days >= 7:
                    os.remove(filepath)
                    deleted_count += 1
        if deleted_count > 0:
            logger.info(f"✅ Deleted {deleted_count} old logs")
    except Exception as e:
        logger.error(f"Log cleanup failed: {e}")


def setup_scan_logger():
    now = datetime.now()
    log_filename = now.strftime('scan_devices_%d-%m-%Y_%H-%M.log')
    log_path = os.path.join(LOGS_DIR, log_filename)
    file_handler = logging.FileHandler(log_path, encoding='utf-8')
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logging.getLogger().addHandler(file_handler)
    logger.info(f"📝 Scan log: {log_filename}")
    return file_handler


def save_device_to_db(device_ip, device_name, poe_data):
    max_retries = 3
    for attempt in range(max_retries):
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
                device_ip, device_name,
                poe_data.get('model', 'Unknown'),
                poe_data.get('serial', 'Unknown'),
                poe_data.get('poe_available', 0),
                poe_data.get('poe_used', 0),
                poe_data.get('poe_remaining', 0),
                poe_data.get('poe_percentage', 0),
                poe_data.get('port_count', 0),
                'OK',
                datetime.now().isoformat()
            ))
            conn.commit()
            conn.close()
            
            save_all_ports_to_db(device_ip, poe_data.get('port_map', {}), poe_data.get('vlan_names', {}))
            save_vlan_names_to_db(device_ip, poe_data.get('vlan_names', {}))
            save_mac_addresses_to_db(device_ip, poe_data.get('mac_by_ifindex', {}))
            break
        except sqlite3.OperationalError as e:
            if 'database is locked' in str(e) and attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue
            else:
                logger.error(f"{device_name}: DB locked, skipping")
                break
        except Exception as e:
            logger.error(f"{device_name}: Save failed: {e}")
            break


def scan_single_device_worker(device_ip, device_name):
    start_time = time.time()
    try:
        poe_data = get_poe_data(device_ip)
        save_device_to_db(device_ip, device_name, poe_data)
        duration = time.time() - start_time
        logger.info(f"✓ {device_name}: {poe_data.get('poe_used', 0):.1f}W / {poe_data.get('poe_available', 0):.1f}W ({duration:.1f}s)")
        return (device_name, True, duration)
    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"✗ {device_name}: {e} ({duration:.1f}s)")
        return (device_name, False, duration)


def scan_all_devices_parallel():
    file_handler = None
    try:
        file_handler = setup_scan_logger()
        
        with open(DEVICES_PATH) as f:
            config = json.load(f)
        # Merge devices + slow_switches — slow_switches are already handled separately
        # but we need their names; scanning rate is controlled by slow_switch_delay
        devices = {**config.get('devices', {}), **config.get('slow_switches', {})}
        
        total = len(devices)
        logger.info(f"🚀 PROCESS POOL SCAN: {total} devices with {MAX_WORKERS} workers")
        
        start_time = time.time()
        success_count = 0
        fail_count = 0
        
        with ProcessPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {
                executor.submit(scan_single_device_worker, ip, name): (ip, name)
                for ip, name in devices.items()
            }
            
            for future in as_completed(futures):
                ip, name = futures[future]
                try:
                    device_name, success, duration = future.result()
                    if success:
                        success_count += 1
                    else:
                        fail_count += 1
                except Exception as e:
                    logger.error(f"Worker exception for {name}: {e}")
                    fail_count += 1
        
        total_duration = time.time() - start_time
        avg_time = total_duration / total if total > 0 else 0
        
        logger.info("="*60)
        logger.info(f"✅ PROCESS POOL SCAN COMPLETE")
        logger.info(f"   Total time: {total_duration:.1f}s")
        logger.info(f"   Devices: {success_count} success, {fail_count} failed")
        logger.info(f"   Average: {avg_time:.1f}s per device")
        logger.info(f"   Speed: {total/total_duration*60:.1f} devices/minute")
        logger.info("="*60)
        
    except Exception as e:
        logger.error(f"Process pool scan failed: {e}")
    finally:
        if file_handler:
            logging.getLogger().removeHandler(file_handler)
            file_handler.close()


def scan_single_device(device_ip):
    try:
        with open(DEVICES_PATH) as f:
            config = json.load(f)
        devices = {**config.get('devices', {}), **config.get('slow_switches', {})}
        if device_ip not in devices:
            return
        device_name = devices[device_ip]
        logger.info(f"🔍 Quick scan: {device_name} ({device_ip})")
        scan_single_device_worker(device_ip, device_name)
    except Exception as e:
        logger.error(f"Single scan failed: {e}")


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--single':
        scan_single_device(sys.argv[2])
    elif len(sys.argv) > 1 and sys.argv[1] == '--once':
        scan_all_devices_parallel()
    else:
        logger.info("="*60)
        logger.info("✅ PoE Monitor scanner started")
        logger.info(f"   - Workers: {MAX_WORKERS} parallel (processes)")
        logger.info(f"   - Database: energy.db")
        logger.info("   - Interval: every 20 minutes")
        logger.info("="*60)
        
        scheduler = BlockingScheduler()
        scheduler.add_job(scan_all_devices_parallel, 'interval', minutes=20, next_run_time=datetime.now())
        scheduler.add_job(cleanup_old_logs, 'interval', days=7)
        logger.info("⏰ Scheduler ready")
        
        try:
            scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            logger.info("Scheduler stopped")
