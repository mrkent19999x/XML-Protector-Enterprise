#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
XML Protector Advanced Monitoring System
Hệ thống giám sát nâng cao với real-time analytics
"""

import os
import sys
import json
import time
import sqlite3
import logging
import requests
import threading
import psutil
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict, deque

try:
    from security_manager import SecurityManager
except ImportError:
    SecurityManager = None

class AdvancedMonitoringSystem:
    """Hệ thống giám sát nâng cao cho XML Protector."""
    
    def __init__(self):
        self.app_dir = Path(os.getenv('APPDATA', Path.home())) / 'XMLProtectorMonitoring'
        self.app_dir.mkdir(parents=True, exist_ok=True)
        
        self.db_file = self.app_dir / 'monitoring.db'
        self.metrics_buffer = deque(maxlen=1000)  # Buffer cho real-time metrics
        self.alert_queue = deque(maxlen=100)      # Queue cho alerts
        self.running = True
        
        self.init_database()
        self.init_logging()
        
    def init_database(self):
        """Khởi tạo database cho monitoring."""
        try:
            conn = sqlite3.connect(str(self.db_file))
            cursor = conn.cursor()
            
            # Bảng system metrics
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS system_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    metric_type TEXT NOT NULL,
                    metric_name TEXT NOT NULL,
                    metric_value REAL,
                    client_id TEXT,
                    additional_data TEXT
                )
            ''')
            
            # Bảng performance stats
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS performance_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    cpu_percent REAL,
                    memory_percent REAL,
                    disk_usage REAL,
                    network_io TEXT,
                    active_connections INTEGER,
                    xml_files_processed INTEGER
                )
            ''')
            
            # Bảng security events
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS security_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    event_type TEXT NOT NULL,
                    severity TEXT DEFAULT 'info',
                    client_id TEXT,
                    source_ip TEXT,
                    description TEXT,
                    raw_data TEXT
                )
            ''')
            
            # Bảng auto-update logs
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS update_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    update_type TEXT NOT NULL,
                    client_id TEXT,
                    old_version TEXT,
                    new_version TEXT,
                    status TEXT,
                    error_message TEXT
                )
            ''')
            
            conn.commit()
            conn.close()
            logging.info("✅ Monitoring database initialized")
            
        except Exception as e:
            logging.error(f"❌ Error initializing monitoring database: {e}")
    
    def init_logging(self):
        """Khởi tạo logging cho monitoring system."""
        log_file = self.app_dir / 'monitoring.log'
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(str(log_file), encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
    
    def collect_system_metrics(self):
        """Thu thập system metrics."""
        try:
            # CPU và Memory
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            
            # Network I/O
            net_io = psutil.net_io_counters()
            network_data = {
                'bytes_sent': net_io.bytes_sent,
                'bytes_recv': net_io.bytes_recv,
                'packets_sent': net_io.packets_sent,
                'packets_recv': net_io.packets_recv
            }
            
            # Active processes
            xml_processes = []
            for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
                try:
                    if 'xml' in proc.info['name'].lower() or 'protector' in proc.info['name'].lower():
                        xml_processes.append(proc.info)
                except:
                    continue
            
            # Lưu vào database
            conn = sqlite3.connect(str(self.db_file))
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO performance_stats 
                (cpu_percent, memory_percent, disk_usage, network_io, active_connections, xml_files_processed)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                cpu_percent,
                memory.percent,
                disk.percent,
                json.dumps(network_data),
                len(xml_processes),
                0  # Will be updated by XML processing stats
            ))
            
            conn.commit()
            conn.close()
            
            # Add to real-time buffer
            metric = {
                'timestamp': datetime.now(),
                'cpu_percent': cpu_percent,
                'memory_percent': memory.percent,
                'disk_usage': disk.percent,
                'active_connections': len(xml_processes)
            }
            self.metrics_buffer.append(metric)
            
            return metric
            
        except Exception as e:
            logging.error(f"❌ Error collecting system metrics: {e}")
            return None
    
    def record_security_event(self, event_type, severity, client_id=None, description="", raw_data=None):
        """Ghi lại security event."""
        try:
            conn = sqlite3.connect(str(self.db_file))
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO security_events 
                (event_type, severity, client_id, description, raw_data)
                VALUES (?, ?, ?, ?, ?)
            ''', (event_type, severity, client_id, description, json.dumps(raw_data) if raw_data else None))
            
            conn.commit()
            conn.close()
            
            # Add to alert queue nếu severity cao
            if severity in ['high', 'critical']:
                alert = {
                    'timestamp': datetime.now(),
                    'type': event_type,
                    'severity': severity,
                    'client_id': client_id,
                    'description': description
                }
                self.alert_queue.append(alert)
                
            logging.info(f"🚨 Security event recorded: {event_type} ({severity})")
            
        except Exception as e:
            logging.error(f"❌ Error recording security event: {e}")
    
    def get_real_time_stats(self, minutes=60):
        """Lấy thống kê real-time trong N phút gần nhất."""
        try:
            conn = sqlite3.connect(str(self.db_file))
            cursor = conn.cursor()
            
            since_time = datetime.now() - timedelta(minutes=minutes)
            
            # Performance stats
            cursor.execute('''
                SELECT timestamp, cpu_percent, memory_percent, disk_usage, active_connections
                FROM performance_stats 
                WHERE timestamp > ?
                ORDER BY timestamp DESC
                LIMIT 100
            ''', (since_time,))
            
            perf_data = cursor.fetchall()
            
            # Security events
            cursor.execute('''
                SELECT COUNT(*) as count, severity
                FROM security_events 
                WHERE timestamp > ?
                GROUP BY severity
            ''', (since_time,))
            
            security_stats = dict(cursor.fetchall())
            
            # XML protection stats
            cursor.execute('''
                SELECT COUNT(*) as xml_events
                FROM security_events 
                WHERE timestamp > ? AND event_type LIKE '%xml%'
            ''', (since_time,))
            
            xml_protection_count = cursor.fetchone()[0]
            
            conn.close()
            
            return {
                'performance_data': perf_data,
                'security_stats': security_stats,
                'xml_protection_count': xml_protection_count,
                'real_time_metrics': list(self.metrics_buffer)[-20:],  # Last 20 metrics
                'recent_alerts': list(self.alert_queue)[-10:]  # Last 10 alerts
            }
            
        except Exception as e:
            logging.error(f"❌ Error getting real-time stats: {e}")
            return {}
    
    def generate_compliance_report(self, days=30):
        """Tạo báo cáo compliance."""
        try:
            conn = sqlite3.connect(str(self.db_file))
            cursor = conn.cursor()
            
            since_date = datetime.now() - timedelta(days=days)
            
            # Tổng quan hoạt động
            cursor.execute('''
                SELECT 
                    COUNT(*) as total_events,
                    COUNT(DISTINCT client_id) as unique_clients
                FROM security_events 
                WHERE timestamp > ?
            ''', (since_date,))
            
            overview = cursor.fetchone()
            
            # Events theo severity
            cursor.execute('''
                SELECT severity, COUNT(*) as count
                FROM security_events 
                WHERE timestamp > ?
                GROUP BY severity
                ORDER BY count DESC
            ''', (since_date,))
            
            severity_breakdown = cursor.fetchall()
            
            # Top event types
            cursor.execute('''
                SELECT event_type, COUNT(*) as count
                FROM security_events 
                WHERE timestamp > ?
                GROUP BY event_type
                ORDER BY count DESC
                LIMIT 10
            ''', (since_date,))
            
            top_events = cursor.fetchall()
            
            # Performance summary
            cursor.execute('''
                SELECT 
                    AVG(cpu_percent) as avg_cpu,
                    AVG(memory_percent) as avg_memory,
                    AVG(disk_usage) as avg_disk,
                    MAX(active_connections) as max_connections
                FROM performance_stats 
                WHERE timestamp > ?
            ''', (since_date,))
            
            performance_summary = cursor.fetchone()
            
            conn.close()
            
            # Generate report
            report = {
                'report_period': f"{days} days",
                'generated_at': datetime.now().isoformat(),
                'overview': {
                    'total_events': overview[0] if overview else 0,
                    'unique_clients': overview[1] if overview else 0
                },
                'security': {
                    'severity_breakdown': dict(severity_breakdown),
                    'top_event_types': dict(top_events)
                },
                'performance': {
                    'avg_cpu_percent': round(performance_summary[0] or 0, 2),
                    'avg_memory_percent': round(performance_summary[1] or 0, 2),
                    'avg_disk_usage': round(performance_summary[2] or 0, 2),
                    'max_active_connections': performance_summary[3] or 0
                }
            }
            
            # Save report
            report_file = self.app_dir / f"compliance_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            with open(report_file, 'w', encoding='utf-8') as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            
            return report, str(report_file)
            
        except Exception as e:
            logging.error(f"❌ Error generating compliance report: {e}")
            return None, None
    
    def start_monitoring(self):
        """Bắt đầu monitoring trong background thread."""
        def monitoring_loop():
            while self.running:
                try:
                    # Collect metrics mỗi 30 giây
                    self.collect_system_metrics()
                    
                    # Cleanup old data (giữ lại 7 ngày)
                    if int(time.time()) % 3600 == 0:  # Mỗi giờ
                        self.cleanup_old_data(days=7)
                    
                    time.sleep(30)
                    
                except Exception as e:
                    logging.error(f"❌ Error in monitoring loop: {e}")
                    time.sleep(60)  # Wait longer nếu có lỗi
        
        monitoring_thread = threading.Thread(target=monitoring_loop, daemon=True)
        monitoring_thread.start()
        logging.info("✅ Advanced monitoring started")
    
    def cleanup_old_data(self, days=7):
        """Dọn dẹp data cũ."""
        try:
            conn = sqlite3.connect(str(self.db_file))
            cursor = conn.cursor()
            
            cutoff_date = datetime.now() - timedelta(days=days)
            
            # Cleanup các bảng
            tables = ['system_metrics', 'performance_stats', 'security_events', 'update_logs']
            for table in tables:
                cursor.execute(f'DELETE FROM {table} WHERE timestamp < ?', (cutoff_date,))
            
            conn.commit()
            conn.close()
            
            logging.info(f"✅ Cleaned up data older than {days} days")
            
        except Exception as e:
            logging.error(f"❌ Error cleaning up old data: {e}")
    
    def stop_monitoring(self):
        """Dừng monitoring."""
        self.running = False
        logging.info("⏹️ Advanced monitoring stopped")

class AutoUpdateSystem:
    """Hệ thống auto-update cho XML Protector."""
    
    def __init__(self, monitoring_system=None):
        self.monitoring = monitoring_system
        self.app_dir = Path(os.getenv('APPDATA', Path.home())) / 'XMLProtectorUpdates'
        self.app_dir.mkdir(parents=True, exist_ok=True)
        
        self.current_version = "2.0.0-secure"
        self.update_server = "https://api.github.com/repos/xml-protector/releases"  # Example
        self.auto_update_enabled = True
        
    def check_for_updates(self):
        """Kiểm tra updates từ server."""
        try:
            if not self.auto_update_enabled:
                return None
            
            # Simulate checking for updates
            # Trong thực tế sẽ call API server
            latest_version = self.get_latest_version()
            
            if self.is_newer_version(latest_version, self.current_version):
                return {
                    'current_version': self.current_version,
                    'latest_version': latest_version,
                    'update_available': True,
                    'update_url': f"{self.update_server}/download/{latest_version}",
                    'changelog': f"Update to version {latest_version} with security improvements"
                }
            
            return None
            
        except Exception as e:
            logging.error(f"❌ Error checking for updates: {e}")
            return None
    
    def get_latest_version(self):
        """Lấy version mới nhất từ server."""
        # Placeholder - trong thực tế sẽ call API
        return "2.1.0-secure"
    
    def is_newer_version(self, latest, current):
        """So sánh version."""
        try:
            latest_parts = latest.split('-')[0].split('.')
            current_parts = current.split('-')[0].split('.')
            
            for i in range(max(len(latest_parts), len(current_parts))):
                latest_num = int(latest_parts[i]) if i < len(latest_parts) else 0
                current_num = int(current_parts[i]) if i < len(current_parts) else 0
                
                if latest_num > current_num:
                    return True
                elif latest_num < current_num:
                    return False
            
            return False
            
        except:
            return False
    
    def download_update(self, update_info):
        """Download update package."""
        try:
            update_url = update_info['update_url']
            version = update_info['latest_version']
            
            # Placeholder download logic
            # Trong thực tế sẽ download file thật
            update_file = self.app_dir / f"xml_protector_update_{version}.exe"
            
            # Log update attempt
            if self.monitoring:
                self.monitoring.record_security_event(
                    "auto_update_download",
                    "info",
                    description=f"Downloading update {version}",
                    raw_data=update_info
                )
            
            # Simulate successful download
            return str(update_file)
            
        except Exception as e:
            logging.error(f"❌ Error downloading update: {e}")
            if self.monitoring:
                self.monitoring.record_security_event(
                    "auto_update_error",
                    "high",
                    description=f"Failed to download update: {e}"
                )
            return None
    
    def apply_update(self, update_file):
        """Áp dụng update."""
        try:
            # Placeholder update logic
            # Trong thực tế sẽ:
            # 1. Backup current version
            # 2. Stop services  
            # 3. Replace files
            # 4. Restart services
            # 5. Verify update
            
            if self.monitoring:
                self.monitoring.record_security_event(
                    "auto_update_applied",
                    "info", 
                    description=f"Update applied successfully: {update_file}"
                )
            
            return True
            
        except Exception as e:
            logging.error(f"❌ Error applying update: {e}")
            if self.monitoring:
                self.monitoring.record_security_event(
                    "auto_update_failed",
                    "high",
                    description=f"Failed to apply update: {e}"
                )
            return False

# Test the monitoring system
if __name__ == '__main__':
    print("🚀 Starting XML Protector Advanced Monitoring System...")
    
    monitoring = AdvancedMonitoringSystem()
    auto_updater = AutoUpdateSystem(monitoring)
    
    # Start monitoring
    monitoring.start_monitoring()
    
    # Test record some events
    monitoring.record_security_event("fake_xml_detected", "high", "client_001", "Fake XML file blocked")
    monitoring.record_security_event("template_overwrite", "info", "client_001", "Template applied successfully")
    
    # Test compliance report
    report, report_file = monitoring.generate_compliance_report(days=1)
    if report:
        print(f"✅ Compliance report generated: {report_file}")
        print(f"📊 Report summary: {report['overview']}")
    
    # Test auto-update
    update_info = auto_updater.check_for_updates()
    if update_info:
        print(f"🆙 Update available: {update_info}")
    else:
        print("✅ System is up to date")
    
    print("✅ Monitoring system is running. Press Ctrl+C to stop.")
    
    try:
        while True:
            time.sleep(5)
            stats = monitoring.get_real_time_stats(minutes=5)
            if stats.get('recent_alerts'):
                print(f"🚨 Recent alerts: {len(stats['recent_alerts'])}")
    except KeyboardInterrupt:
        monitoring.stop_monitoring()
        print("⏹️ Monitoring system stopped")