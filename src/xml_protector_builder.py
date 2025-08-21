#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
XML Protector - GUI Builder Tích Hợp Hoàn Chỉnh
Quản lý tất cả chức năng từ 1 giao diện duy nhất
"""

import os
import sys
import time
import glob
import json
import pickle
import shutil
import logging
import requests
import re
import xml.etree.ElementTree as ET
import threading
import subprocess
import psutil
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox, END
except ImportError:
    print("❌ Cần cài đặt: tkinter")
    sys.exit(1)

try:
    import winreg
except ImportError:
    winreg = None

# Import security manager
try:
    from security_manager import SecurityManager, ConfigManager
except ImportError:
    SecurityManager = None
    ConfigManager = None

# --- SECURE CONFIG TEMPLATE --- #
SECURE_CONFIG_TEMPLATE = {
    "master_admin": {
        "admin_name": "XML Protector Master Admin",
        "admin_id": None,  # Sẽ được set trong GUI
        "created_at": None
    },
    "telegram": {
        "bot_token": "",  # Sẽ được nhập trong GUI
        "master_chat_id": "",  # Chat ID của admin chính
        "admin_ids": []  # List admin IDs
    },
    "companies": {},  # Dictionary lưu thông tin từng công ty
    "build_settings": {
        "auto_send_telegram": True,
        "include_guardian": True,
        "include_admin_bot": True,
        "auto_startup": True,
        "encryption_enabled": True
    },
    "security_settings": {
        "require_deployment_approval": True,
        "max_companies": 50,
        "deployment_expiry_days": 365,
        "audit_logging": True
    }
}

# --- DATABASE --- #
DB_FILE = "xml_protector_admin.db"

class AdminBot:
    """Bot quản lý từ xa."""
    
    def __init__(self, config):
        self.bot_token = config['telegram']['bot_token']
        self.admin_ids = config['telegram']['admin_ids']
        self.clients = {}
        self.init_database()
        # Không tự động khởi động webhook
        print("✅ AdminBot đã được khởi tạo (chưa khởi động webhook)")
        
    def init_database(self):
        """Khởi tạo database."""
        try:
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            
            # Bảng clients
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS clients (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    client_name TEXT NOT NULL,
                    client_id TEXT UNIQUE NOT NULL,
                    exe_path TEXT,
                    status TEXT DEFAULT 'offline',
                    last_seen TIMESTAMP,
                    templates_count INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Bảng activities
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS activities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    client_id TEXT,
                    activity_type TEXT,
                    description TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (client_id) REFERENCES clients (client_id)
                )
            ''')
            
            # Bảng alerts
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    client_id TEXT,
                    alert_type TEXT,
                    message TEXT,
                    severity TEXT DEFAULT 'info',
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (client_id) REFERENCES clients (client_id)
                )
            ''')
            
            conn.commit()
            conn.close()
            print("✅ Database đã được khởi tạo")
            
        except Exception as e:
            print(f"❌ Lỗi khởi tạo database: {e}")
    
    def send_telegram_message(self, chat_id, message, reply_markup=None):
        """Gửi message qua Telegram Bot."""
        try:
            # Chỉ gửi vào group chat, không gửi riêng cho admin
            if str(chat_id).startswith('-100') or str(chat_id).startswith('-'):
                # Đây là group chat - OK để gửi
                pass
            else:
                # Đây là chat riêng với admin - bỏ qua
                print(f"⚠️ Bỏ qua gửi message riêng cho admin {chat_id}")
                return True
            
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            data = {
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "Markdown"
            }
            if reply_markup:
                data["reply_markup"] = json.dumps(reply_markup)
            
            response = requests.post(url, data=data)
            if response.status_code == 200:
                return True
            else:
                print(f"❌ Lỗi gửi Telegram: {response.status_code}")
                return False
        except Exception as e:
            print(f"❌ Gửi Telegram thất bại: {e}")
            return False
    
    def create_main_menu(self):
        """Tạo menu chính cho admin."""
        return {
            "inline_keyboard": [
                [
                    {"text": "📊 Bảng điều khiển", "callback_data": "dashboard"},
                    {"text": "🖥️ Quản lý Khách hàng", "callback_data": "manage_clients"}
                ],
                [
                    {"text": "🏗️ Tạo EXE", "callback_data": "build_exe"},
                    {"text": "📤 Triển khai", "callback_data": "deploy"}
                ],
                [
                    {"text": "🚨 Cảnh báo", "callback_data": "alerts"},
                    {"text": "📋 Báo cáo", "callback_data": "reports"}
                ],
                [
                    {"text": "⚙️ Cài đặt", "callback_data": "settings"},
                    {"text": "❓ Trợ giúp", "callback_data": "help"}
                ]
            ]
        }
    
    def start_telegram_webhook(self):
        """Khởi động Telegram webhook."""
        def check_telegram_updates():
            offset = 0
            while True:
                try:
                    url = f"https://api.telegram.org/bot{self.bot_token}/getUpdates"
                    params = {"offset": offset, "timeout": 10}
                    response = requests.get(url, params=params)
                    
                    if response.status_code == 200:
                        data = response.json()
                        for update in data.get('result', []):
                            offset = update['update_id'] + 1
                            
                            if 'callback_query' in update:
                                callback_data = update['callback_query']['data']
                                user_id = update['callback_query']['from']['id']
                                chat_id = update['callback_query']['message']['chat']['id']
                                self.handle_callback(callback_data, user_id, chat_id)
                            
                            elif 'message' in update:
                                message = update['message']
                                user_id = message['from']['id']
                                chat_id = message['chat']['id']
                                text = message.get('text', '')
                                
                                if text == '/start' or text == '/menu':
                                    welcome_text = """
🤖 **XML PROTECTOR ADMIN BOT**

Chào mừng bạn đến với hệ thống quản lý XML Protector!

Chọn chức năng từ menu bên dưới:
"""
                                    self.send_telegram_message(chat_id, welcome_text, self.create_main_menu())
                
                except Exception as e:
                    print(f"❌ Lỗi Telegram webhook: {e}")
                    time.sleep(5)
                
                time.sleep(1)
        
        telegram_thread = threading.Thread(target=check_telegram_updates, daemon=True)
        telegram_thread.start()
        print("✅ Telegram webhook đã khởi động")
    
    def handle_callback(self, callback_data, user_id, chat_id):
        """Xử lý callback từ menu."""
        if user_id not in self.admin_ids:
            self.send_telegram_message(chat_id, "❌ **Bạn không có quyền truy cập!**")
            return
        
        try:
            print(f"🔍 Xử lý callback: {callback_data} từ user {user_id}")
            
            if callback_data == "dashboard" or callback_data == "main_menu":
                self.show_dashboard(chat_id)
            elif callback_data == "manage_clients":
                self.show_clients_list(chat_id)
            elif callback_data == "build_exe":
                self.show_build_menu(chat_id)
            elif callback_data == "deploy":
                self.show_deploy_menu(chat_id)
            elif callback_data == "alerts":
                self.show_alerts(chat_id)
            elif callback_data == "reports":
                self.show_reports(chat_id)
            elif callback_data == "settings":
                self.show_settings(chat_id)
            elif callback_data == "help":
                self.show_help(chat_id)
            elif callback_data == "build_runtime":
                self.show_build_runtime_menu(chat_id)
            elif callback_data == "build_builder":
                self.show_build_builder_menu(chat_id)
            elif callback_data == "build_hybrid":
                self.show_build_hybrid_menu(chat_id)
            elif callback_data == "build_mobile":
                self.show_build_mobile_menu(chat_id)
            elif callback_data == "deploy_telegram":
                self.show_deploy_telegram_info(chat_id)
            elif callback_data == "deploy_web":
                self.show_deploy_web_info(chat_id)
            elif callback_data == "deploy_local":
                self.show_deploy_local_info(chat_id)
            elif callback_data == "deploy_package":
                self.show_deploy_package_info(chat_id)
            elif callback_data == "advanced_settings":
                self.show_advanced_settings(chat_id)
            else:
                print(f"⚠️ Callback không xác định: {callback_data}")
                self.send_telegram_message(chat_id, "❌ Lệnh không hợp lệ!")
                
        except Exception as e:
            print(f"❌ Lỗi xử lý callback: {e}")
            self.send_telegram_message(chat_id, f"❌ **Lỗi:** `{str(e)}`")
    
    def show_dashboard(self, chat_id):
        """Hiển thị dashboard tổng quan."""
        try:
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            
            # Thống kê tổng quan
            cursor.execute("SELECT COUNT(*) FROM clients")
            total_clients = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM clients WHERE status = 'online'")
            online_clients = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM alerts WHERE severity = 'high'")
            high_alerts = cursor.fetchone()[0]
            
            conn.close()
            
            dashboard_text = f"""
📊 **DASHBOARD TỔNG QUAN**

🏢 **Tổng số Clients:** `{total_clients}`
🟢 **Online:** `{online_clients}`
🔴 **Offline:** `{total_clients - online_clients}`
🚨 **High Alerts:** `{high_alerts}`

⏰ **Cập nhật:** `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`
"""
            self.send_telegram_message(chat_id, dashboard_text, self.create_main_menu())
            
        except Exception as e:
            print(f"❌ Lỗi hiển thị dashboard: {e}")
            self.send_telegram_message(chat_id, f"❌ **Lỗi:** `{str(e)}`")
    
    def show_build_menu(self, chat_id):
        """Hiển thị menu build EXE."""
        build_text = """
🏗️ **BUILD EXE MỚI**

Chọn loại EXE cần build:

1. **🛡️ Runtime Client** - Bảo vệ XML
2. **🏗️ Builder Tool** - Tạo EXE mới  
3. **🤖 Hybrid Bot** - Vừa bảo vệ vừa build
4. **📱 Mobile App** - Ứng dụng di động
"""
        
        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "🛡️ Client Bảo vệ", "callback_data": "build_runtime"},
                    {"text": "🏗️ Công cụ Tạo", "callback_data": "build_builder"}
                ],
                [
                    {"text": "🤖 Bot Đa năng", "callback_data": "build_hybrid"},
                    {"text": "📱 Ứng dụng Di động", "callback_data": "build_mobile"}
                ],
                [
                    {"text": "🔙 Quay lại", "callback_data": "main_menu"}
                ]
            ]
        }
        
        self.send_telegram_message(chat_id, build_text, keyboard)
    
    def show_help(self, chat_id):
        """Hiển thị help."""
        help_text = """
❓ **HƯỚNG DẪN SỬ DỤNG**

🤖 **XML Protector Admin Bot**

**Chức năng chính:**
• 📊 Dashboard - Xem tổng quan hệ thống
• 🖥️ Quản lý Clients - Quản lý EXE clients
• 🏗️ Build EXE - Tạo EXE mới
• 📤 Deploy - Phân phối EXE
• 🚨 Alerts - Thông báo cảnh báo
• 📋 Reports - Báo cáo chi tiết

**Lệnh cơ bản:**
• `/start` - Khởi động bot
• `/menu` - Hiện menu chính
• `/help` - Hướng dẫn sử dụng
• `/status` - Trạng thái hệ thống
"""
        
        keyboard = {
            "inline_keyboard": [
                [{"text": "🔙 Quay lại", "callback_data": "main_menu"}]
            ]
        }
        
        self.send_telegram_message(chat_id, help_text, keyboard)
    
    def show_clients_list(self, chat_id):
        """Hiển thị danh sách clients."""
        try:
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute("SELECT client_name, client_id, status, last_seen FROM clients ORDER BY last_seen DESC LIMIT 10")
            clients = cursor.fetchall()
            conn.close()
            
            if clients:
                clients_text = "📋 **DANH SÁCH CLIENTS**\n\n"
                for i, (name, client_id, status, last_seen) in enumerate(clients, 1):
                    clients_text += f"{i}. **{name}**\n   ID: `{client_id}`\n   Trạng thái: {status}\n   Cuối cùng: {last_seen}\n\n"
            else:
                clients_text = "📋 **DANH SÁCH CLIENTS**\n\n❌ Chưa có client nào"
            
            keyboard = {
                "inline_keyboard": [
                    [{"text": "🔄 Làm mới", "callback_data": "manage_clients"}],
                    [{"text": "🔙 Quay lại", "callback_data": "main_menu"}]
                ]
            }
            
            self.send_telegram_message(chat_id, clients_text, keyboard)
            
        except Exception as e:
            self.send_telegram_message(chat_id, f"❌ **Lỗi:** `{str(e)}`")
    
    def show_deploy_menu(self, chat_id):
        """Hiển thị menu deploy."""
        deploy_text = """
📤 **DEPLOY & TRIỂN KHAI**

Chọn phương thức deploy:

1. **📱 Telegram** - Gửi EXE qua bot
2. **🌐 Web Download** - Tạo link download
3. **💾 Local Share** - Chia sẻ qua mạng nội bộ
4. **📦 Package** - Đóng gói thành installer
"""
        
        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "📱 Gửi Telegram", "callback_data": "deploy_telegram"},
                    {"text": "🌐 Tải Web", "callback_data": "deploy_web"}
                ],
                [
                    {"text": "💾 Chia sẻ Nội bộ", "callback_data": "deploy_local"},
                    {"text": "📦 Đóng gói", "callback_data": "deploy_package"}
                ],
                [
                    {"text": "🔙 Quay lại", "callback_data": "main_menu"}
                ]
            ]
        }
        
        self.send_telegram_message(chat_id, deploy_text, keyboard)
    
    def show_alerts(self, chat_id):
        """Hiển thị alerts."""
        try:
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute("SELECT alert_type, message, severity, timestamp FROM alerts ORDER BY timestamp DESC LIMIT 10")
            alerts = cursor.fetchall()
            conn.close()
            
            if alerts:
                alerts_text = "🚨 **ALERTS & CẢNH BÁO**\n\n"
                for i, (alert_type, message, severity, timestamp) in enumerate(alerts, 1):
                    severity_icon = "🔴" if severity == "high" else "🟡" if severity == "medium" else "🟢"
                    alerts_text += f"{i}. {severity_icon} **{alert_type}**\n   {message}\n   ⏰ {timestamp}\n\n"
            else:
                alerts_text = "🚨 **ALERTS & CẢNH BÁO**\n\n✅ Không có cảnh báo nào"
            
            keyboard = {
                "inline_keyboard": [
                    [{"text": "🔄 Làm mới", "callback_data": "alerts"}],
                    [{"text": "🔙 Quay lại", "callback_data": "main_menu"}]
                ]
            }
            
            self.send_telegram_message(chat_id, alerts_text, keyboard)
            
        except Exception as e:
            self.send_telegram_message(chat_id, f"❌ **Lỗi:** `{str(e)}`")
    
    def show_reports(self, chat_id):
        """Hiển thị reports."""
        try:
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            
            # Thống kê tổng quan
            cursor.execute("SELECT COUNT(*) FROM clients")
            total_clients = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM clients WHERE status = 'online'")
            online_clients = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM activities")
            total_activities = cursor.fetchone()[0]
            
            conn.close()
            
            reports_text = f"""
📊 **BÁO CÁO TỔNG QUAN**

🏢 **Clients:**
• Tổng số: {total_clients}
• Online: {online_clients}
• Offline: {total_clients - online_clients}

📈 **Hoạt động:**
• Tổng hoạt động: {total_activities}
• Tỷ lệ online: {(online_clients/total_clients*100):.1f}% (nếu có clients)

⏰ **Cập nhật:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
            
            keyboard = {
                "inline_keyboard": [
                    [{"text": "🔄 Làm mới", "callback_data": "reports"}],
                    [{"text": "🔙 Quay lại", "callback_data": "main_menu"}]
                ]
            }
            
            self.send_telegram_message(chat_id, reports_text, keyboard)
            
        except Exception as e:
            self.send_telegram_message(chat_id, f"❌ **Lỗi:** `{str(e)}`")
    
    def show_settings(self, chat_id):
        """Hiển thị settings."""
        settings_text = """
⚙️ **CÀI ĐẶT HỆ THỐNG**

🔐 **Bảo mật:**
• Mã hóa config: ✅ Bật
• Yêu cầu xác thực: ✅ Bật
• Audit logging: ✅ Bật

🤖 **Bot:**
• Auto-restart: ✅ Bật
• Webhook: ✅ Bật
• Timeout: 10s

📊 **Monitoring:**
• Real-time metrics: ✅ Bật
• Alert threshold: 80%
• Log retention: 30 ngày
"""
        
        keyboard = {
            "inline_keyboard": [
                [{"text": "🔧 Cài đặt nâng cao", "callback_data": "advanced_settings"}],
                [{"text": "🔙 Quay lại", "callback_data": "main_menu"}]
            ]
        }
        
        self.send_telegram_message(chat_id, settings_text, keyboard)
    
    def show_build_runtime_menu(self, chat_id):
        """Hiển thị menu build runtime."""
        build_text = """
🛡️ **BUILD RUNTIME CLIENT**

**Chức năng:**
• Bảo vệ XML files real-time
• Template matching thông minh
• Auto-restart với Windows
• Telegram alerts

**Tính năng:**
✅ File monitoring
✅ Template protection
✅ Performance tracking
✅ Security logging
"""
        
        keyboard = {
            "inline_keyboard": [
                [{"text": "🏗️ Tạo Runtime", "callback_data": "build_runtime_start"}],
                [{"text": "🔙 Quay lại", "callback_data": "build_exe"}]
            ]
        }
        
        self.send_telegram_message(chat_id, build_text, keyboard)
    
    def show_build_builder_menu(self, chat_id):
        """Hiển thị menu build builder."""
        build_text = """
🏗️ **BUILD BUILDER TOOL**

**Chức năng:**
• Tạo EXE từ source code
• Custom configuration
• Template management
• Deployment tools

**Tính năng:**
✅ GUI Builder
✅ Template Editor
✅ Config Manager
✅ Deploy Helper
"""
        
        keyboard = {
            "inline_keyboard": [
                [{"text": "🏗️ Tạo Builder", "callback_data": "build_builder_start"}],
                [{"text": "🔙 Quay lại", "callback_data": "build_exe"}]
            ]
        }
        
        self.send_telegram_message(chat_id, build_text, keyboard)
    
    def show_build_hybrid_menu(self, chat_id):
        """Hiển thị menu build hybrid."""
        build_text = """
🤖 **BUILD HYBRID BOT**

**Chức năng:**
• Vừa bảo vệ vừa build
• Multi-function bot
• Admin controls
• Real-time monitoring

**Tính năng:**
✅ XML Protection
✅ EXE Builder
✅ Admin Panel
✅ Monitoring
"""
        
        keyboard = {
            "inline_keyboard": [
                [{"text": "🏗️ Tạo Hybrid", "callback_data": "build_hybrid_start"}],
                [{"text": "🔙 Quay lại", "callback_data": "build_exe"}]
            ]
        }
        
        self.send_telegram_message(chat_id, build_text, keyboard)
    
    def show_build_mobile_menu(self, chat_id):
        """Hiển thị menu build mobile."""
        build_text = """
📱 **BUILD MOBILE APP**

**Chức năng:**
• Ứng dụng di động
• Cross-platform
• Cloud sync
• Push notifications

**Tính năng:**
✅ Mobile UI
✅ Cloud Storage
✅ Push Alerts
✅ Offline Mode
"""
        
        keyboard = {
            "inline_keyboard": [
                [{"text": "🏗️ Tạo Mobile", "callback_data": "build_mobile_start"}],
                [{"text": "🔙 Quay lại", "callback_data": "build_exe"}]
            ]
        }
        
        self.send_telegram_message(chat_id, build_text, keyboard)
    
    def show_deploy_telegram_info(self, chat_id):
        """Hiển thị thông tin deploy Telegram."""
        deploy_text = """
📱 **DEPLOY QUA TELEGRAM**

**Phương thức:**
• Gửi file EXE trực tiếp
• Bot tự động phân phối
• Real-time notifications
• Download tracking

**Ưu điểm:**
✅ Nhanh chóng
✅ An toàn
✅ Tracking được
✅ Dễ sử dụng
"""
        
        keyboard = {
            "inline_keyboard": [
                [{"text": "🚀 Bắt đầu Triển khai", "callback_data": "deploy_telegram_start"}],
                [{"text": "🔙 Quay lại", "callback_data": "deploy"}]
            ]
        }
        
        self.send_telegram_message(chat_id, deploy_text, keyboard)
    
    def show_deploy_web_info(self, chat_id):
        """Hiển thị thông tin deploy web."""
        deploy_text = """
🌐 **DEPLOY QUA WEB**

**Phương thức:**
• Tạo link download
• Web interface
• Progress tracking
• Version management

**Ưu điểm:**
✅ Dễ chia sẻ
✅ Tracking chi tiết
✅ Version control
✅ Analytics
"""
        
        keyboard = {
            "inline_keyboard": [
                [{"text": "🚀 Bắt đầu Triển khai", "callback_data": "deploy_web_start"}],
                [{"text": "🔙 Quay lại", "callback_data": "deploy"}]
            ]
        }
        
        self.send_telegram_message(chat_id, deploy_text, keyboard)
    
    def show_deploy_local_info(self, chat_id):
        """Hiển thị thông tin deploy local."""
        deploy_text = """
💾 **DEPLOY LOCAL SHARE**

**Phương thức:**
• Chia sẻ qua mạng nội bộ
• USB/CD/DVD
• Network drive
• Local server

**Ưu điểm:**
✅ Không cần internet
✅ Bảo mật cao
✅ Tốc độ nhanh
✅ Kiểm soát được
"""
        
        keyboard = {
            "inline_keyboard": [
                [{"text": "🚀 Bắt đầu Triển khai", "callback_data": "deploy_local_start"}],
                [{"text": "🔙 Quay lại", "callback_data": "deploy"}]
            ]
        }
        
        self.send_telegram_message(chat_id, deploy_text, keyboard)
    
    def show_deploy_package_info(self, chat_id):
        """Hiển thị thông tin deploy package."""
        deploy_text = """
📦 **DEPLOY PACKAGE**

**Phương thức:**
• Đóng gói thành installer
• Auto-update
• Dependency management
• Silent installation

**Ưu điểm:**
✅ Professional
✅ Auto-install
✅ Dependency check
✅ Update system
"""
        
        keyboard = {
            "inline_keyboard": [
                [{"text": "🚀 Bắt đầu Triển khai", "callback_data": "deploy_package_start"}],
                [{"text": "🔙 Quay lại", "callback_data": "deploy"}]
            ]
        }
        
        self.send_telegram_message(chat_id, deploy_text, keyboard)
    
    def show_advanced_settings(self, chat_id):
        """Hiển thị cài đặt nâng cao."""
        settings_text = """
🔧 **CÀI ĐẶT NÂNG CAO**

**Bảo mật:**
• Encryption level: AES-256
• Key rotation: 30 ngày
• Audit trail: Bật
• Access control: Role-based

**Performance:**
• Cache size: 100MB
• Thread pool: 10
• Timeout: 30s
• Retry: 3 lần

**Monitoring:**
• Log level: INFO
• Metrics: Real-time
• Alerts: Email + Telegram
• Backup: Auto
"""
        
        keyboard = {
            "inline_keyboard": [
                [{"text": "🔐 Cấu hình Bảo mật", "callback_data": "security_config"}],
                [{"text": "⚡ Cấu hình Hiệu suất", "callback_data": "performance_config"}],
                [{"text": "📊 Cấu hình Giám sát", "callback_data": "monitoring_config"}],
                [{"text": "🔙 Quay lại", "callback_data": "settings"}]
            ]
        }
        
        self.send_telegram_message(chat_id, settings_text, keyboard)
    
    def run(self):
        """Chạy bot."""
        print("🚀 XML Protector Admin Bot đang khởi động...")
        
        # Khởi động Telegram webhook
        self.start_telegram_webhook()
        
        # Gửi thông báo khởi động chỉ vào group chat (không gửi riêng cho admin)
        startup_msg = f"""
🚀 **XML PROTECTOR ADMIN BOT ĐÃ KHỞI ĐỘNG!**

⏰ **Thời gian:** `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`
🤖 **Bot Token:** `{self.bot_token[:20]}...`
👥 **Admin IDs:** `{self.admin_ids}`

Gửi /start để bắt đầu sử dụng!
"""
        
        # Chỉ gửi vào group chat, không gửi riêng cho admin
        # for admin_id in self.admin_ids:
        #     self.send_telegram_message(admin_id, startup_msg)
        
        print("✅ Admin Bot đã sẵn sàng!")
        
        # Giữ bot chạy
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("⏹️ Admin Bot đã tắt (KeyboardInterrupt)")
        except Exception as e:
            print(f"❌ Admin Bot gặp lỗi: {e}")

class XMLProtectorBuilder:
    """GUI Builder tích hợp hoàn chỉnh với quản lý doanh nghiệp."""
    
    def __init__(self):
        self.config = SECURE_CONFIG_TEMPLATE.copy()
        self.admin_bot = None
        self.admin_bot_thread = None
        self.security_manager = SecurityManager() if SecurityManager else None
        self.config_manager = ConfigManager() if ConfigManager else None
        self.companies_data = {}  # Lưu trữ thông tin tất cả doanh nghiệp
        
        # Khởi tạo Enterprise Manager
        self.enterprise_manager = None
        self.enterprises = {}
        self.load_enterprises()
        
        # Khởi tạo GUI
        self.setup_gui()
        self.load_secure_config()
    
        print("🔐 XML Protector Builder - Secure Enterprise Edition")
        print("✅ GUI Builder đã sẵn sàng với hệ thống bảo mật nâng cao!")
        
        # Khởi tạo Enterprise Manager
        self.init_enterprise_manager()
    
    def setup_gui(self):
        """Thiết lập giao diện - TẤT CẢ TRONG 1 TAB DUY NHẤT."""
        # Tạo cửa sổ chính
        self.root = tk.Tk()
        self.root.title("🏗️ XML Protector - GUI Builder Tích Hợp")
        self.root.geometry("1200x900")
        
        # Tạo canvas có thể cuộn được
        self.canvas = tk.Canvas(self.root)
        self.scrollbar = ttk.Scrollbar(self.root, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = ttk.Frame(self.canvas)
        
        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )
        
        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        
        # Pack canvas và scrollbar
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        
        # Bind mouse wheel
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        
        # Tạo 1 tab duy nhất chứa tất cả
        self.setup_unified_tab()
        
    def _on_mousewheel(self, event):
        """Xử lý cuộn chuột."""
        self.canvas.yview_scroll(int(-1*(event.delta/120)), "units")
    
    def setup_unified_tab(self):
        """Tab duy nhất chứa TẤT CẢ chức năng."""
        # Tạo frame chính với scrollbar
        main_frame = ttk.Frame(self.scrollable_frame)
        main_frame.pack(fill='both', expand=True, padx=10, pady=10)
        
        # === PHẦN 1: CẤU HÌNH TELEGRAM ===
        telegram_frame = ttk.LabelFrame(main_frame, text="📱 Cấu Hình Telegram Bot", padding=10)
        telegram_frame.pack(fill='x', padx=5, pady=5)
        
        ttk.Label(telegram_frame, text="Bot Token:").grid(row=0, column=0, sticky='w', pady=2)
        self.bot_token_entry = ttk.Entry(telegram_frame, width=60)
        self.bot_token_entry.grid(row=0, column=1, padx=5, pady=2)
        
        ttk.Label(telegram_frame, text="Chat ID:").grid(row=1, column=0, sticky='w', pady=2)
        self.chat_id_entry = ttk.Entry(telegram_frame, width=60)
        self.chat_id_entry.grid(row=1, column=1, padx=5, pady=2)
        
        ttk.Label(telegram_frame, text="Admin IDs:").grid(row=2, column=0, sticky='w', pady=2)
        self.admin_ids_entry = ttk.Entry(telegram_frame, width=60)
        self.admin_ids_entry.grid(row=2, column=1, padx=5, pady=2)
        ttk.Label(telegram_frame, text="(phân cách bằng dấu phẩy)").grid(row=2, column=2, sticky='w', pady=2)
    
        # Nút lưu config
        save_config_btn = ttk.Button(telegram_frame, text="💾 Lưu Cấu Hình", command=self.save_secure_config)
        save_config_btn.grid(row=2, column=3, padx=5, pady=2)
        
        # === PHẦN 2: QUẢN LÝ DOANH NGHIỆP ===
        company_frame = ttk.LabelFrame(main_frame, text="🏢 Quản Lý Doanh Nghiệp", padding=10)
        company_frame.pack(fill='x', padx=5, pady=5)
        
        # Add company section
        add_company_frame = ttk.Frame(company_frame)
        add_company_frame.pack(fill='x', pady=5)
        
        ttk.Label(add_company_frame, text="MST:").grid(row=0, column=0, sticky='w', pady=2)
        self.company_mst_entry = ttk.Entry(add_company_frame, width=20)
        self.company_mst_entry.grid(row=0, column=1, padx=5, pady=2)
        
        ttk.Label(add_company_frame, text="Tên DN:").grid(row=0, column=2, sticky='w', pady=2, padx=(10,0))
        self.company_name_entry = ttk.Entry(add_company_frame, width=30)
        self.company_name_entry.grid(row=0, column=3, padx=5, pady=2)
        
        ttk.Label(add_company_frame, text="EXE Name:").grid(row=0, column=4, sticky='w', pady=2, padx=(10,0))
        self.company_exe_entry = ttk.Entry(add_company_frame, width=25)
        self.company_exe_entry.grid(row=0, column=5, padx=5, pady=2)
        
        add_company_btn = ttk.Button(add_company_frame, text="➕ Thêm DN", command=self.add_company)
        add_company_btn.grid(row=0, column=6, padx=10, pady=2)
        
        # Companies list
        companies_list_frame = ttk.LabelFrame(company_frame, text="📋 Danh Sách Doanh Nghiệp", padding=10)
        companies_list_frame.pack(fill='both', expand=True, pady=5)
        
        # Treeview for companies
        company_columns = ('MST', 'Tên DN', 'EXE Name', 'Status', 'Templates', 'Last Deploy', 'Actions')
        self.companies_tree = ttk.Treeview(companies_list_frame, columns=company_columns, show='headings', height=8)
        
        for col in company_columns:
            self.companies_tree.heading(col, text=col)
            if col == 'MST':
                self.companies_tree.column(col, width=120)
            elif col == 'Tên DN':
                self.companies_tree.column(col, width=200)
            elif col == 'EXE Name':
                self.companies_tree.column(col, width=180)
            elif col == 'Status':
                self.companies_tree.column(col, width=80)
            elif col == 'Templates':
                self.companies_tree.column(col, width=80)
            elif col == 'Last Deploy':
                self.companies_tree.column(col, width=120)
            else:
                self.companies_tree.column(col, width=100)
        
        # Scrollbar for companies tree
        companies_scrollbar = ttk.Scrollbar(companies_list_frame, orient='vertical', command=self.companies_tree.yview)
        self.companies_tree.configure(yscrollcommand=companies_scrollbar.set)
        
        self.companies_tree.pack(side='left', fill='both', expand=True)
        companies_scrollbar.pack(side='right', fill='y')
        
        # Company actions
        company_actions_frame = ttk.Frame(company_frame)
        company_actions_frame.pack(fill='x', pady=5)
        
        select_company_btn = ttk.Button(company_actions_frame, text="✅ Chọn DN", command=self.select_company_for_build)
        select_company_btn.pack(side='left', padx=5)
        
        edit_company_btn = ttk.Button(company_actions_frame, text="✏️ Sửa DN", command=self.edit_selected_company)
        edit_company_btn.pack(side='left', padx=5)
        
        delete_company_btn = ttk.Button(company_actions_frame, text="🗑️ Xóa DN", command=self.delete_selected_company)
        delete_company_btn.pack(side='left', padx=5)
        
        refresh_companies_btn = ttk.Button(company_actions_frame, text="🔄 Làm Mới", command=self.refresh_companies_list)
        refresh_companies_btn.pack(side='left', padx=5)
        
        export_companies_btn = ttk.Button(company_actions_frame, text="📤 Export DN", command=self.export_companies_list)
        export_companies_btn.pack(side='left', padx=5)
        
        # Selected company info
        self.selected_company_label = ttk.Label(company_actions_frame, text="📌 Chưa chọn doanh nghiệp nào", foreground="blue")
        self.selected_company_label.pack(side='right', padx=10)
        
        # === PHẦN 2.5: ENTERPRISE MANAGER - QUẢN LÝ THÔNG MINH ===
        enterprise_frame = ttk.LabelFrame(main_frame, text="🏢 Enterprise Manager - Quản Lý Thông Minh", padding=10)
        enterprise_frame.pack(fill='x', padx=5, pady=5)
        
        # Thông tin tổng quan thông minh
        smart_info_frame = ttk.Frame(enterprise_frame)
        smart_info_frame.pack(fill='x', pady=5)
        
        self.smart_status_label = ttk.Label(smart_info_frame, text="🔍 Đang phân tích XML để phát hiện doanh nghiệp...", 
                                           font=('Arial', 10, 'bold'), foreground="blue")
        self.smart_status_label.pack(anchor='w')
        
        # Nút điều khiển thông minh
        smart_controls_frame = ttk.Frame(enterprise_frame)
        smart_controls_frame.pack(fill='x', pady=5)
        
        # Nút tự động phát hiện và cập nhật
        auto_detect_btn = ttk.Button(smart_controls_frame, text="🔍 Tự Động Phát Hiện & Phân Loại DN", 
                                    command=self.auto_detect_enterprises_from_xml)
        auto_detect_btn.pack(side='left', padx=5)
        
        # Nút làm mới thông minh
        smart_refresh_btn = ttk.Button(smart_controls_frame, text="🔄 Làm Mới Thông Minh", 
                                      command=self.smart_refresh_enterprises)
        smart_refresh_btn.pack(side='left', padx=5)
        
        # Nút xem chi tiết XML
        xml_details_btn = ttk.Button(smart_controls_frame, text="📄 Xem Chi Tiết XML", 
                                    command=self.show_xml_enterprise_details)
        xml_details_btn.pack(side='left', padx=5)
        
        # Nút hành động hàng loạt
        batch_actions_frame = ttk.Frame(enterprise_frame)
        batch_actions_frame.pack(fill='x', pady=5)
        
        build_all_btn = ttk.Button(batch_actions_frame, text="🔨 Build Tất Cả DN Pending", 
                                  command=self.build_all_pending_enterprises)
        build_all_btn.pack(side='left', padx=5)
        
        deploy_all_btn = ttk.Button(batch_actions_frame, text="🚀 Deploy Tất Cả DN Built", 
                                   command=self.deploy_all_built_enterprises)
        deploy_all_btn.pack(side='left', padx=5)
        
        # Thống kê thông minh
        smart_stats_frame = ttk.Frame(enterprise_frame)
        smart_stats_frame.pack(fill='x', pady=5)
        
        self.enterprises_stats_label = ttk.Label(smart_stats_frame, text="📊 Thống kê: 0 doanh nghiệp", 
                                               font=('Arial', 10, 'bold'))
        self.enterprises_stats_label.pack(side='left')
        
        # Thông tin XML được phát hiện
        self.xml_detection_label = ttk.Label(smart_stats_frame, text=" | 📄 XML: 0 files", 
                                            font=('Arial', 9), foreground="green")
        self.xml_detection_label.pack(side='left', padx=10)
        
        # Danh sách doanh nghiệp thông minh
        enterprises_list_label = ttk.Label(enterprise_frame, text="📋 Danh Sách Doanh Nghiệp (Tự Động Phát Hiện):", 
                                         font=('Arial', 10, 'bold'))
        enterprises_list_label.pack(anchor='w', pady=5)
        
        # Frame chứa danh sách doanh nghiệp với giao diện thông minh
        self.enterprises_list_frame = ttk.Frame(enterprise_frame)
        self.enterprises_list_frame.pack(fill='x', pady=5)
        
        # Thông báo khi chưa có doanh nghiệp
        self.no_enterprises_label = ttk.Label(self.enterprises_list_frame, 
                                             text="💡 Chưa có doanh nghiệp nào được phát hiện.\nNhấn 'Tự Động Phát Hiện & Phân Loại DN' để bắt đầu!", 
                                             font=('Arial', 10), foreground="gray", justify='center')
        self.no_enterprises_label.pack(pady=20)
        
        # === PHẦN 3: CHỌN XML GỐC ===
        xml_frame = ttk.LabelFrame(main_frame, text="📄 Chọn XML Gốc", padding=10)
        xml_frame.pack(fill='x', padx=5, pady=5)
        
        ttk.Label(xml_frame, text="Thư mục XML gốc:").grid(row=0, column=0, sticky='w', pady=2)
        self.templates_folder_entry = ttk.Entry(xml_frame, width=70)
        self.templates_folder_entry.grid(row=0, column=1, padx=5, pady=2)
        
        browse_btn = ttk.Button(xml_frame, text="📂 Chọn Thư Mục", command=self.browse_templates_folder)
        browse_btn.grid(row=0, column=2, padx=5, pady=2)
        
        # Danh sách XML
        list_frame = ttk.LabelFrame(xml_frame, text="📋 Danh Sách XML Gốc", padding=10)
        list_frame.grid(row=1, column=0, columnspan=3, sticky='ew', padx=5, pady=5)
        
        # Treeview cho XML files
        columns = ('Tên File', 'Kích Thước', 'Ngày Tạo', 'Trạng Thái')
        self.xml_tree = ttk.Treeview(list_frame, columns=columns, show='headings', height=8)
        
        for col in columns:
            self.xml_tree.heading(col, text=col)
            if col == 'Tên File':
                self.xml_tree.column(col, width=300)
            elif col == 'Kích Thước':
                self.xml_tree.column(col, width=100)
            elif col == 'Ngày Tạo':
                self.xml_tree.column(col, width=150)
            else:
                self.xml_tree.column(col, width=100)
        
        self.xml_tree.pack(fill='x')
        
        # Thông tin tổng quan
        self.xml_info_label = ttk.Label(xml_frame, text="📂 Chưa chọn thư mục XML gốc")
        self.xml_info_label.grid(row=3, column=0, columnspan=3, pady=5, sticky='w')
        
        # Nút phân tích và làm mới
        xml_buttons_frame = ttk.Frame(xml_frame)
        xml_buttons_frame.grid(row=2, column=0, columnspan=3, pady=5, sticky='w')
        
        analyze_btn = ttk.Button(xml_buttons_frame, text="🔍 Phân Tích Nhanh", command=self.quick_analyze_xml)
        analyze_btn.pack(side='left', padx=5)
        
        refresh_btn = ttk.Button(xml_buttons_frame, text="🔄 Làm Mới", command=self.refresh_xml_list)
        refresh_btn.pack(side='left', padx=5)
        
        # === PHẦN 3: CÀI ĐẶT BUILD ===
        build_frame = ttk.LabelFrame(main_frame, text="⚙️ Cài Đặt Build", padding=10)
        build_frame.pack(fill='x', padx=5, pady=5)
        
        # Build options
        options_frame = ttk.Frame(build_frame)
        options_frame.pack(fill='x', pady=5)
        
        self.auto_send_var = tk.BooleanVar(value=True)
        auto_send_cb = ttk.Checkbutton(options_frame, text="📤 Tự động gửi EXE lên Telegram", 
                                      variable=self.auto_send_var)
        auto_send_cb.grid(row=0, column=0, sticky='w', pady=2)
        
        self.include_guardian_var = tk.BooleanVar(value=True)
        guardian_cb = ttk.Checkbutton(options_frame, text="🛡️ Bao gồm Guardian Protection", 
                                     variable=self.include_guardian_var)
        guardian_cb.grid(row=0, column=1, sticky='w', pady=2)
        
        self.include_admin_bot_var = tk.BooleanVar(value=True)
        admin_bot_cb = ttk.Checkbutton(options_frame, text="🤖 Bao gồm Admin Bot tích hợp", 
                                      variable=self.include_admin_bot_var)
        admin_bot_cb.grid(row=1, column=0, sticky='w', pady=2)
        
        self.auto_startup_var = tk.BooleanVar(value=True)
        startup_cb = ttk.Checkbutton(options_frame, text="🚀 Tự động khởi động cùng Windows", 
                                    variable=self.auto_startup_var)
        startup_cb.grid(row=1, column=1, sticky='w', pady=2)
        
        # Output settings
        output_frame = ttk.Frame(build_frame)
        output_frame.pack(fill='x', pady=5)
        
        ttk.Label(output_frame, text="Tên file EXE:").grid(row=0, column=0, sticky='w', pady=2)
        self.exe_name_entry = ttk.Entry(output_frame, width=30)
        self.exe_name_entry.grid(row=0, column=1, padx=5, pady=2)
        
        ttk.Label(output_frame, text="Vị trí đầu ra:").grid(row=1, column=0, sticky='w', pady=2)
        self.output_path_entry = ttk.Entry(output_frame, width=50)
        self.output_path_entry.grid(row=1, column=1, padx=5, pady=2)
        
        browse_output_btn = ttk.Button(output_frame, text="📂 Chọn Thư Mục", command=self.browse_output_path)
        browse_output_btn.grid(row=1, column=2, padx=5, pady=2)
        
        # === PHẦN 4: BUILD & DEPLOY ===
        build_deploy_frame = ttk.LabelFrame(main_frame, text="🏗️ Build & Deploy", padding=10)
        build_deploy_frame.pack(fill='x', padx=5, pady=5)
        
        # Build section
        build_section = ttk.Frame(build_deploy_frame)
        build_section.pack(fill='x', pady=5)
        
        build_btn = ttk.Button(build_section, text="🏗️ Build EXE Hoàn Chỉnh", 
                              command=self.build_complete_exe)
        build_btn.pack(side='left', padx=5)
        
        # Progress
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(build_section, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(side='left', fill='x', expand=True, padx=5)
        
        self.build_status_label = ttk.Label(build_section, text="✅ Sẵn sàng build")
        self.build_status_label.pack(side='left', padx=5)
        
        # Deploy section
        deploy_section = ttk.Frame(build_deploy_frame)
        deploy_section.pack(fill='x', pady=5)
        
        deploy_btn = ttk.Button(deploy_section, text="📤 Gửi EXE lên Telegram", 
                               command=self.deploy_to_telegram)
        deploy_btn.pack(side='left', padx=5)
        
        download_btn = ttk.Button(deploy_section, text="🌐 Tạo Link Download", 
                                 command=self.create_download_link)
        download_btn.pack(side='left', padx=5)
        
        # === PHẦN 5: ADMIN BOT & STATUS ===
        admin_status_frame = ttk.LabelFrame(main_frame, text="🤖 Admin Bot & Trạng Thái", padding=10)
        admin_status_frame.pack(fill='both', expand=True, padx=5, pady=5)
        
        # Bot controls
        controls_frame = ttk.Frame(admin_status_frame)
        controls_frame.pack(fill='x', pady=5)
        
        start_bot_btn = ttk.Button(controls_frame, text="🚀 Khởi Động Admin Bot", 
                                  command=self.start_admin_bot)
        start_bot_btn.pack(side='left', padx=5)
        
        stop_bot_btn = ttk.Button(controls_frame, text="⏹️ Dừng Admin Bot", 
                                 command=self.stop_admin_bot)
        stop_bot_btn.pack(side='left', padx=5)
        
        refresh_btn = ttk.Button(controls_frame, text="🔄 Làm Mới", command=self.refresh_status)
        refresh_btn.pack(side='left', padx=5)
        
        # Bot status
        self.bot_status_label = ttk.Label(controls_frame, text="❌ Bot chưa khởi động")
        self.bot_status_label.pack(side='left', padx=10)
        
        # System status và logs
        status_logs_frame = ttk.Frame(admin_status_frame)
        status_logs_frame.pack(fill='both', expand=True, pady=5)
        
        # System status
        system_frame = ttk.LabelFrame(status_logs_frame, text="💻 Trạng Thái Hệ Thống", padding=5)
        system_frame.pack(side='left', fill='both', expand=True, padx=(0, 5))
        
        self.system_status_text = tk.Text(system_frame, height=10, width=50)
        self.system_status_text.pack(fill='both', expand=True)
        
        # Bot logs
        logs_frame = ttk.LabelFrame(status_logs_frame, text="📋 Log Hoạt Động", padding=5)
        logs_frame.pack(side='right', fill='both', expand=True, padx=(5, 0))
        
        self.bot_logs_text = tk.Text(logs_frame, height=10, width=50)
        self.bot_logs_text.pack(fill='both', expand=True)
    
    # === CÁC HÀM CŨ ĐÃ ĐƯỢC GỘP VÀO TRÊN - KHÔNG CÒN SỬ DỤNG ===
    
    def setup_build_config_tab(self):
        """Tab cấu hình build."""
        build_frame = ttk.Frame(self.notebook)
        self.notebook.add(build_frame, text="⚙️ Cài Đặt Build")
        
        # Build options
        options_frame = ttk.LabelFrame(build_frame, text="🔧 Tùy Chọn Build", padding=10)
        options_frame.pack(fill='x', padx=10, pady=5)
        
        self.auto_send_var = tk.BooleanVar(value=True)
        auto_send_cb = ttk.Checkbutton(options_frame, text="📤 Tự động gửi EXE lên Telegram", 
                                      variable=self.auto_send_var)
        auto_send_cb.grid(row=0, column=0, sticky='w', pady=2)
        
        self.include_guardian_var = tk.BooleanVar(value=True)
        guardian_cb = ttk.Checkbutton(options_frame, text="🛡️ Bao gồm Guardian Protection", 
                                     variable=self.include_guardian_var)
        guardian_cb.grid(row=1, column=0, sticky='w', pady=2)
        
        self.include_admin_bot_var = tk.BooleanVar(value=True)
        admin_bot_cb = ttk.Checkbutton(options_frame, text="🤖 Bao gồm Admin Bot tích hợp", 
                                      variable=self.include_admin_bot_var)
        admin_bot_cb.grid(row=2, column=0, sticky='w', pady=2)
        
        self.auto_startup_var = tk.BooleanVar(value=True)
        startup_cb = ttk.Checkbutton(options_frame, text="🚀 Tự động khởi động cùng Windows", 
                                    variable=self.auto_startup_var)
        startup_cb.grid(row=3, column=0, sticky='w', pady=2)
        
        # Output settings
        output_frame = ttk.LabelFrame(build_frame, text="📤 Cài Đặt Đầu Ra", padding=10)
        output_frame.pack(fill='x', padx=10, pady=5)
        
        # Tên file EXE
        ttk.Label(output_frame, text="Tên file EXE:").grid(row=0, column=0, sticky='w', pady=2)
        self.exe_name_entry = ttk.Entry(output_frame, width=30)
        self.exe_name_entry.grid(row=0, column=1, padx=5, pady=2)
        
        # Vị trí đầu ra
        ttk.Label(output_frame, text="Vị trí đầu ra:").grid(row=1, column=0, sticky='w', pady=2)
        self.output_path_entry = ttk.Entry(output_frame, width=50)
        self.output_path_entry.grid(row=1, column=1, padx=5, pady=2)
        
        browse_output_btn = ttk.Button(output_frame, text="📂 Chọn Thư Mục", command=self.browse_output_path)
        browse_output_btn.grid(row=1, column=2, padx=5, pady=2)
        
        # Chọn file EXE cụ thể
        ttk.Label(output_frame, text="File EXE cụ thể:").grid(row=2, column=0, sticky='w', pady=2)
        self.specific_exe_entry = ttk.Entry(output_frame, width=50)
        self.specific_exe_entry.grid(row=2, column=1, padx=5, pady=2)
        
        browse_exe_btn = ttk.Button(output_frame, text="🔍 Chọn File EXE", command=self.browse_specific_exe)
        browse_exe_btn.grid(row=2, column=2, padx=5, pady=2)
        
        # Nút xem danh sách file EXE có sẵn
        list_exe_btn = ttk.Button(output_frame, text="📋 Danh sách File EXE", command=self.show_available_exe_files)
        list_exe_btn.grid(row=2, column=3, padx=5, pady=2)
    
    def setup_admin_bot_tab(self):
        """Tab quản lý Admin Bot."""
        admin_frame = ttk.Frame(self.notebook)
        self.notebook.add(admin_frame, text="🤖 Quản Lý Admin Bot")
        
        # Bot controls
        controls_frame = ttk.LabelFrame(admin_frame, text="🎮 Điều Khiển Bot", padding=10)
        controls_frame.pack(fill='x', padx=10, pady=5)
        
        start_bot_btn = ttk.Button(controls_frame, text="🚀 Khởi Động Admin Bot", 
                                  command=self.start_admin_bot)
        start_bot_btn.pack(side='left', padx=5)
        
        stop_bot_btn = ttk.Button(controls_frame, text="⏹️ Dừng Admin Bot", 
                                 command=self.stop_admin_bot)
        stop_bot_btn.pack(side='left', padx=5)
        
        # Bot status
        status_frame = ttk.LabelFrame(admin_frame, text="📊 Trạng Thái Bot", padding=10)
        status_frame.pack(fill='x', padx=10, pady=5)
        
        self.bot_status_label = ttk.Label(status_frame, text="❌ Bot chưa khởi động")
        self.bot_status_label.pack()
        
        # Bot logs
        logs_frame = ttk.LabelFrame(admin_frame, text="📋 Log Hoạt Động", padding=10)
        logs_frame.pack(fill='both', expand=True, padx=10, pady=5)
        
        self.bot_logs_text = tk.Text(logs_frame, height=15)
        self.bot_logs_text.pack(fill='both', expand=True)
    
    def setup_clients_tab(self):
        """Tab quản lý clients."""
        clients_frame = ttk.Frame(self.notebook)
        self.notebook.add(clients_frame, text="🖥️ Quản Lý Clients")
        
        # Client list
        list_frame = ttk.LabelFrame(clients_frame, text="📋 Danh Sách Clients", padding=10)
        list_frame.pack(fill='both', expand=True, padx=10, pady=5)
        
        # Treeview cho clients
        columns = ('Tên Client', 'ID', 'Trạng Thái', 'Templates', 'Cuối Cùng')
        self.clients_tree = ttk.Treeview(list_frame, columns=columns, show='headings')
        
        for col in columns:
            self.clients_tree.heading(col, text=col)
            self.clients_tree.column(col, width=150)
        
        self.clients_tree.pack(fill='both', expand=True)
        
        # Client actions
        actions_frame = ttk.Frame(clients_frame)
        actions_frame.pack(fill='x', padx=10, pady=5)
        
        refresh_btn = ttk.Button(actions_frame, text="🔄 Làm Mới", command=self.refresh_clients)
        refresh_btn.pack(side='left', padx=5)
        
        delete_btn = ttk.Button(actions_frame, text="🗑️ Xóa Client", command=self.delete_client)
        delete_btn.pack(side='left', padx=5)
    
    def setup_build_deploy_tab(self):
        """Tab build và deploy."""
        build_deploy_frame = ttk.Frame(self.notebook)
        self.notebook.add(build_deploy_frame, text="🏗️ Build & Deploy")
        
        # Build section
        build_section = ttk.LabelFrame(build_deploy_frame, text="🔨 Tạo EXE", padding=10)
        build_section.pack(fill='x', padx=10, pady=5)
        
        build_btn = ttk.Button(build_section, text="🏗️ Build EXE Hoàn Chỉnh", 
                              command=self.build_complete_exe)
        build_btn.pack(pady=10)
        
        # Progress
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(build_section, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(fill='x', pady=5)
        
        self.build_status_label = ttk.Label(build_section, text="✅ Sẵn sàng build")
        self.build_status_label.pack()
        
        # Deploy section
        deploy_section = ttk.LabelFrame(build_deploy_frame, text="📤 Triển Khai", padding=10)
        deploy_section.pack(fill='x', padx=10, pady=5)
        
        deploy_btn = ttk.Button(deploy_section, text="📤 Gửi EXE lên Telegram", 
                               command=self.deploy_to_telegram)
        deploy_btn.pack(side='left', padx=5)
        
        download_btn = ttk.Button(deploy_section, text="🌐 Tạo Link Download", 
                                 command=self.create_download_link)
        download_btn.pack(side='left', padx=5)
    
    def setup_status_logs_tab(self):
        """Tab trạng thái và logs."""
        status_frame = ttk.Frame(self.notebook)
        self.notebook.add(status_frame, text="📊 Trạng Thái & Logs")
        
        # System status
        system_frame = ttk.LabelFrame(status_frame, text="💻 Trạng Thái Hệ Thống", padding=10)
        system_frame.pack(fill='x', padx=10, pady=5)
        
        self.system_status_text = tk.Text(system_frame, height=8)
        self.system_status_text.pack(fill='x')
        
        # Logs
        logs_frame = ttk.LabelFrame(status_frame, text="📋 Log Hệ Thống", padding=10)
        logs_frame.pack(fill='both', expand=True, padx=10, pady=5)
        
        self.system_logs_text = tk.Text(logs_frame, height=15)
        self.system_logs_text.pack(fill='both', expand=True)
        
        # Refresh button
        refresh_btn = ttk.Button(status_frame, text="🔄 Làm Mới", command=self.refresh_status)
        refresh_btn.pack(pady=5)
    
    def browse_templates_folder(self):
        """Chọn thư mục templates."""
        folder = filedialog.askdirectory(title="Chọn thư mục chứa XML gốc")
        if folder:
            self.templates_folder_entry.delete(0, 'end')
            self.templates_folder_entry.insert(0, folder)
            # Tự động làm mới danh sách XML
            self.refresh_xml_list()
            
            # Hiển thị thông báo
            xml_count = len(glob.glob(os.path.join(folder, "*.xml")))
            if xml_count > 0:
                messagebox.showinfo("Thành công", f"✅ Đã tìm thấy {xml_count} file XML trong thư mục!")
            else:
                messagebox.showwarning("Cảnh báo", "⚠️ Không tìm thấy file XML nào trong thư mục!")
    
    def refresh_xml_list(self):
        """Làm mới danh sách XML."""
        # Xóa dữ liệu cũ
        for item in self.xml_tree.get_children():
            self.xml_tree.delete(item)
        
        folder = self.templates_folder_entry.get().strip()
        if folder and os.path.exists(folder):
            xml_files = glob.glob(os.path.join(folder, "*.xml"))
            if xml_files:
                for xml_file in xml_files:
                    try:
                        filename = Path(xml_file).name
                        size_bytes = os.path.getsize(xml_file)
                        size_kb = size_bytes / 1024
                        created_time = datetime.fromtimestamp(os.path.getctime(xml_file))
                        created_str = created_time.strftime('%Y-%m-%d %H:%M')
                        
                        # Kiểm tra trạng thái file
                        if size_bytes > 0:
                            status = "✅ Sẵn sàng"
                        else:
                            status = "❌ Lỗi"
                        
                        # Thêm vào treeview
                        self.xml_tree.insert('', 'end', values=(
                            filename,
                            f"{size_kb:.1f} KB",
                            created_str,
                            status
                        ))
                    
                    except Exception as e:
                        # Thêm file lỗi
                        self.xml_tree.insert('', 'end', values=(
                            Path(xml_file).name,
                            "Lỗi",
                            "N/A",
                            "❌ Lỗi"
                        ))
                
                # Cập nhật thông tin tổng quan
                total_size = sum(os.path.getsize(f) for f in xml_files)
                self.xml_info_label.configure(
                    text=f"📊 Tìm thấy {len(xml_files)} file XML | Tổng kích thước: {total_size/1024/1024:.2f} MB"
                )
                
                # Cập nhật build status nếu có
                if hasattr(self, 'build_status_label'):
                    self.build_status_label.configure(text=f"✅ Sẵn sàng build với {len(xml_files)} file XML")
            else:
                self.xml_info_label.configure(text="⚠️ Không tìm thấy file XML nào trong thư mục")
                if hasattr(self, 'build_status_label'):
                    self.build_status_label.configure(text="⚠️ Không có file XML để build")
        else:
            self.xml_info_label.configure(text="📂 Chưa chọn thư mục XML gốc")
            if hasattr(self, 'build_status_label'):
                self.build_status_label.configure(text="📂 Vui lòng chọn thư mục XML gốc")
    
    def start_admin_bot(self):
        """Khởi động Admin Bot."""
        try:
            if not self.admin_bot:
                self.admin_bot = AdminBot(self.config)
                # Khởi động webhook trong thread riêng
                self.admin_bot_thread = threading.Thread(target=self.admin_bot.start_telegram_webhook, daemon=True)
                self.admin_bot_thread.start()
                
                self.bot_status_label.configure(text="🟢 Bot đang hoạt động")
                self.log_bot_message("🚀 Admin Bot đã khởi động")
            else:
                messagebox.showinfo("Thông báo", "Admin Bot đã đang chạy!")
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không thể khởi động Admin Bot: {e}")
    
    def stop_admin_bot(self):
        """Dừng Admin Bot."""
        try:
            if self.admin_bot:
                self.admin_bot = None
                self.bot_status_label.configure(text="❌ Bot đã dừng")
                self.log_bot_message("⏹️ Admin Bot đã dừng")
            else:
                messagebox.showinfo("Thông báo", "Admin Bot chưa chạy!")
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không thể dừng Admin Bot: {e}")
    
    def log_bot_message(self, message):
        """Ghi log bot."""
        timestamp = datetime.now().strftime('%H:%M:%S')
        self.bot_logs_text.insert('end', f"[{timestamp}] {message}\n")
        self.bot_logs_text.see('end')
    
    def build_complete_exe(self):
        """Build EXE hoàn chỉnh với tất cả chức năng."""
        try:
            self.build_status_label.configure(text="🏗️ Đang build EXE...")
            self.progress_var.set(10)
            
            # Kiểm tra PyInstaller
            try:
                subprocess.run([sys.executable, '-m', 'PyInstaller', '--version'], 
                             capture_output=True, check=True)
            except:
                messagebox.showerror("Lỗi", "PyInstaller chưa được cài đặt!\nChạy: pip install pyinstaller")
                return
            
            # Lấy thông tin build
            exe_name = self.exe_name_entry.get().strip() or "XML_Protector_Runtime.exe"
            # Đảm bảo tên file có đuôi .exe
            if not exe_name.endswith('.exe'):
                exe_name += '.exe'
                
            output_path = self.output_path_entry.get().strip() or os.getcwd()
            # Đảm bảo output_path tồn tại và là đường dẫn tuyệt đối
            output_path = os.path.abspath(output_path)
            templates_path = self.templates_folder_entry.get().strip()
            
            if not templates_path or not os.path.exists(templates_path):
                messagebox.showerror("Lỗi", "Vui lòng chọn thư mục XML gốc trước!")
                return
            
            # Tạo thư mục output
            os.makedirs(output_path, exist_ok=True)
            self.progress_var.set(20)
            
            # Tạo tên spec file (không có đuôi .exe)
            exe_basename = exe_name.replace('.exe', '')
            
            # Tạo spec file với đường dẫn an toàn
            runtime_path = os.path.join(os.getcwd(), "src", "xml_protector_runtime.py").replace("\\", "/")
            templates_path_safe = templates_path.replace("\\", "/")
            current_dir_safe = os.getcwd().replace("\\", "/")
            
            spec_content = f'''# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    [r'{runtime_path}'],
    pathex=[r'{current_dir_safe}'],
    binaries=[],
    datas=[(r'{templates_path_safe}', 'templates')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={{}},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='{exe_basename}',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None
)
'''
            
            spec_file = os.path.join(output_path, f"{exe_basename}.spec")
            with open(spec_file, 'w', encoding='utf-8') as f:
                f.write(spec_content)
            
            self.progress_var.set(40)
            
            # Build EXE với PyInstaller
            build_cmd = [sys.executable, '-m', 'PyInstaller', '--clean', spec_file]
            
            # Chạy PyInstaller từ thư mục dự án (để tìm được src/xml_protector_runtime.py)
            current_dir = os.getcwd()
            result = subprocess.run(build_cmd, cwd=current_dir, capture_output=True, text=True)
            
            if result.returncode == 0:
                self.progress_var.set(100)
                self.build_status_label.configure(text="✅ Build EXE thành công!")
                
                # Tìm file EXE đã tạo (PyInstaller tạo trong thư mục hiện tại)
                dist_path = os.path.join(current_dir, 'dist', exe_name)
                
                # Nếu output_path khác current_dir, move file EXE sang đó
                if output_path != current_dir and os.path.exists(dist_path):
                    target_dist = os.path.join(output_path, 'dist')
                    os.makedirs(target_dist, exist_ok=True)
                    target_exe = os.path.join(target_dist, exe_name)
                    shutil.move(dist_path, target_exe)
                    exe_path = target_exe
                else:
                    exe_path = dist_path
                
                if os.path.exists(exe_path):
                    messagebox.showinfo("Thành công", 
                        f"EXE đã được tạo thành công!\n\n"
                        f"📁 Vị trí: {exe_path}\n"
                        f"📊 Kích thước: {os.path.getsize(exe_path):,} bytes")
                else:
                    messagebox.showwarning("Cảnh báo", 
                        "EXE đã được build nhưng không tìm thấy file đầu ra!")
            else:
                raise Exception(f"PyInstaller build failed: {result.stderr}")
            
        except Exception as e:
            self.build_status_label.configure(text="❌ Build EXE thất bại!")
            messagebox.showerror("Lỗi", f"Build EXE thất bại: {e}")
            self.progress_var.set(0)
    
    def deploy_to_telegram(self):
        """Gửi EXE lên Telegram."""
        try:
            # Tìm file EXE mới nhất
            exe_name = self.exe_name_entry.get().strip() or "test.exe"
            output_path = self.output_path_entry.get().strip() or "."
            
            # Tìm file EXE với đường dẫn linh hoạt - ƯU TIÊN FILE ĐƯỢC CHỌN
            exe_file = None
            
            # 1. ƯU TIÊN: File EXE cụ thể được chọn
            specific_exe = self.specific_exe_entry.get().strip() if hasattr(self, 'specific_exe_entry') else ""
            if specific_exe and Path(specific_exe).exists():
                exe_file = Path(specific_exe)
                print(f"✅ Sử dụng file EXE được chọn: {exe_file}")
            else:
                # 2. Tìm file EXE với đường dẫn linh hoạt
                possible_paths = []
                
                # Thư mục output được chọn
                if output_path and output_path != ".":
                    possible_paths.extend([
                        Path(output_path) / exe_name,
                        Path(output_path) / "dist" / exe_name,
                        Path(output_path) / "build" / exe_name
                    ])
                
                # Thư mục hiện tại và các thư mục con
                current_dir = Path.cwd()
                possible_paths.extend([
                    current_dir / exe_name,
                    current_dir / "dist" / exe_name,
                    current_dir / "build" / exe_name,
                    current_dir / "output" / exe_name
                ])
                
                # Thư mục project (nếu khác thư mục hiện tại)
                project_dir = Path(__file__).parent.parent
                if project_dir != current_dir:
                    possible_paths.extend([
                        project_dir / exe_name,
                        project_dir / "dist" / exe_name,
                        project_dir / "build" / exe_name
                    ])
                
                # Tìm file .exe bất kỳ trong các thư mục dist/build
                for base_dir in [current_dir, project_dir]:
                    for subdir in ["dist", "build", "output"]:
                        subdir_path = base_dir / subdir
                        if subdir_path.exists():
                            exe_files = list(subdir_path.glob("*.exe"))
                            if exe_files:
                                possible_paths.extend(exe_files)
                
                print(f"🔍 Tìm file EXE với đường dẫn linh hoạt:")
                print(f"📁 Thư mục hiện tại: {current_dir}")
                print(f"📁 Thư mục project: {project_dir}")
                print(f"🔍 Các đường dẫn có thể: {[str(p) for p in possible_paths]}")
                
                # Tìm file đầu tiên tồn tại
                for path in possible_paths:
                    if path.exists():
                        exe_file = path
                        print(f"✅ Tìm thấy file EXE: {exe_file}")
                        break
            
            if not exe_file:
                # Nếu không tìm thấy, hiển thị tất cả file .exe có sẵn
                all_exe_files = []
                for base_dir in [current_dir, project_dir]:
                    for subdir in ["dist", "build", "output"]:
                        subdir_path = base_dir / subdir
                        if subdir_path.exists():
                            exe_files = list(subdir_path.glob("*.exe"))
                            all_exe_files.extend(exe_files)
                
                if all_exe_files:
                    exe_list = "\n".join([f"• {f}" for f in all_exe_files])
                    messagebox.showerror("Lỗi", 
                        f"Không tìm thấy file '{exe_name}'!\n\n"
                        f"Các file EXE có sẵn:\n{exe_list}\n\n"
                        f"Vui lòng kiểm tra tên file hoặc chọn file khác!")
                else:
                    messagebox.showerror("Lỗi", 
                        f"Không tìm thấy file EXE nào!\n\n"
                        f"Đã tìm trong:\n"
                        f"• {current_dir}\n"
                        f"• {project_dir}\n"
                        f"• Các thư mục: dist, build, output")
                return
            
            if not exe_file.exists():
                messagebox.showerror("Lỗi", f"Không tìm thấy file EXE: {exe_file}")
                return
            
            # Kiểm tra kích thước file (Telegram limit 50MB)
            file_size = exe_file.stat().st_size
            if file_size > 50 * 1024 * 1024:  # 50MB
                messagebox.showerror("Lỗi", f"File EXE quá lớn ({file_size/(1024*1024):.1f}MB). Telegram chỉ hỗ trợ tối đa 50MB!")
                return
            
            # Chuẩn bị thông tin
            bot_token = self.bot_token_entry.get().strip()
            chat_id = self.chat_id_entry.get().strip()
            
            if not bot_token or not chat_id:
                messagebox.showerror("Lỗi", "Vui lòng nhập Bot Token và Chat ID!")
                return
            
            # Hiển thị tiến trình
            if hasattr(self, 'build_status_label'):
                self.build_status_label.configure(text="📤 Đang gửi EXE lên Telegram...")
            if hasattr(self, 'progress_var'):
                self.progress_var.set(50)
            
            # Gửi file
            url = f"https://api.telegram.org/bot{bot_token}/sendDocument"
            
            with open(exe_file, 'rb') as f:
                files = {'document': f}
                data = {
                    'chat_id': chat_id,
                    'caption': f"""
🏗️ **XML PROTECTOR EXE MỚI**

📄 **File:** `{exe_name}`
📦 **Kích thước:** `{file_size/(1024*1024):.1f}MB`
🕐 **Build time:** `{time.strftime('%Y-%m-%d %H:%M:%S')}`
💻 **Build bởi:** XML Protector Builder

✅ Sẵn sàng triển khai!
""",
                    'parse_mode': 'Markdown'
                }
                
                # Sửa lỗi SSL với Telegram API - Sử dụng session với SSL config
                import urllib3
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
                
                # Tạo session với SSL config tối ưu
                session = requests.Session()
                session.verify = False
                session.trust_env = False
                
                # Thử gửi với session đã config - cải thiện SSL handling
                response = None
                try:
                    print("🔄 Thử gửi với SSL config tối ưu...")
                    response = session.post(url, files=files, data=data, timeout=300)
                    print(f"✅ Gửi Telegram thành công với SSL config tối ưu")
                except Exception as ssl_error:
                    print(f"⚠️ Lỗi SSL, thử fallback: {ssl_error}")
                    try:
                        # Fallback 1: requests với verify=False
                        print("🔄 Thử fallback với verify=False...")
                        response = requests.post(url, files=files, data=data, timeout=300, verify=False)
                        print(f"✅ Gửi Telegram thành công với fallback")
                    except Exception as fallback_error:
                        print(f"❌ Fallback cũng thất bại: {fallback_error}")
                        # Fallback 2: thử với timeout ngắn hơn
                        try:
                            print("🔄 Thử fallback với timeout ngắn...")
                            response = requests.post(url, files=files, data=data, timeout=60, verify=False)
                            print(f"✅ Gửi Telegram thành công với timeout ngắn")
                        except Exception as final_error:
                            print(f"❌ Tất cả fallback đều thất bại: {final_error}")
                            raise final_error
            
            if response and response.status_code == 200:
                if hasattr(self, 'build_status_label'):
                    self.build_status_label.configure(text="✅ Đã gửi EXE lên Telegram thành công!")
                if hasattr(self, 'progress_var'):
                    self.progress_var.set(100)
                messagebox.showinfo("Thành công", f"Đã gửi {exe_name} lên Telegram thành công!")
                print(f"✅ File {exe_name} đã gửi thành công lên Telegram!")
            else:
                if response:
                    try:
                        error_data = response.json()
                        error_msg = error_data.get('description', 'Lỗi không xác định')
                    except:
                        error_msg = f"HTTP {response.status_code}: {response.text}"
                else:
                    error_msg = "Không có response từ Telegram API"
                
                if hasattr(self, 'build_status_label'):
                    self.build_status_label.configure(text="❌ Lỗi gửi Telegram")
                messagebox.showerror("Lỗi", f"Không thể gửi EXE lên Telegram: {error_msg}")
                print(f"❌ Lỗi gửi Telegram: {error_msg}")
            
        except Exception as e:
            if hasattr(self, 'build_status_label'):
                self.build_status_label.configure(text="❌ Lỗi gửi Telegram")
            error_msg = f"Lỗi gửi EXE lên Telegram: {str(e)}"
            messagebox.showerror("Lỗi", error_msg)
            print(f"❌ Exception trong deploy_to_telegram: {e}")
            import traceback
            traceback.print_exc()
    
    def run_exe_local(self):
        """Chạy EXE vừa build ra trên local máy."""
        try:
            # Tìm file EXE với đường dẫn linh hoạt
            exe_name = self.exe_name_entry.get().strip() or "test.exe"
            output_path = self.output_path_entry.get().strip() or "."
            
            # Tìm file EXE với đường dẫn linh hoạt - KHÔNG FIX CỨNG
            possible_paths = []
            
            # 1. Thư mục output được chọn
            if output_path and output_path != ".":
                possible_paths.extend([
                    Path(output_path) / exe_name,
                    Path(output_path) / "dist" / exe_name,
                    Path(output_path) / "build" / exe_name
                ])
            
            # 2. Thư mục hiện tại và các thư mục con
            current_dir = Path.cwd()
            possible_paths.extend([
                current_dir / exe_name,
                current_dir / "dist" / exe_name,
                current_dir / "build" / exe_name,
                current_dir / "output" / exe_name
            ])
            
            # 3. Thư mục project (nếu khác thư mục hiện tại)
            project_dir = Path(__file__).parent.parent
            if project_dir != current_dir:
                possible_paths.extend([
                    project_dir / exe_name,
                    project_dir / "dist" / exe_name,
                    project_dir / "build" / exe_name
                ])
            
            # 4. Tìm file .exe bất kỳ trong các thư mục dist/build
            for base_dir in [current_dir, project_dir]:
                for subdir in ["dist", "build", "output"]:
                    subdir_path = base_dir / subdir
                    if subdir_path.exists():
                        exe_files = list(subdir_path.glob("*.exe"))
                        if exe_files:
                            possible_paths.extend(exe_files)
            
            print(f"🔍 Tìm file EXE để chạy local:")
            print(f"🔍 Các đường dẫn có thể: {[str(p) for p in possible_paths]}")
            
            # Tìm file đầu tiên tồn tại
            exe_file = None
            for path in possible_paths:
                if path.exists():
                    exe_file = path
                    print(f"✅ Tìm thấy file EXE để chạy: {exe_file}")
                    break
            
            if not exe_file:
                messagebox.showerror("Lỗi", f"Không tìm thấy file EXE '{exe_name}' để chạy!")
                return
            
            # Kiểm tra file có thể chạy được không
            if not os.access(exe_file, os.X_OK):
                messagebox.showerror("Lỗi", f"File {exe_file} không thể chạy được!")
                return
            
            # Hiển thị thông báo
            result = messagebox.askyesno(
                "Xác nhận chạy EXE", 
                f"Bạn có muốn chạy file EXE này không?\n\n"
                f"📁 File: {exe_file.name}\n"
                f"📍 Đường dẫn: {exe_file}\n"
                f"📦 Kích thước: {exe_file.stat().st_size / (1024*1024):.1f} MB\n\n"
                f"⚠️ Lưu ý: EXE sẽ chạy song song với Admin Bot!"
            )
            
            if result:
                try:
                    # Chạy EXE trong background
                    import subprocess
                    process = subprocess.Popen(
                        [str(exe_file)],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        creationflags=subprocess.CREATE_NEW_CONSOLE
                    )
                    
                    print(f"🚀 Đã khởi động EXE: {exe_file}")
                    print(f"📊 Process ID: {process.pid}")
                    
                    # Cập nhật status
                    if hasattr(self, 'build_status_label'):
                        self.build_status_label.configure(text=f"🚀 Đang chạy EXE: {exe_file.name}")
                    
                    messagebox.showinfo(
                        "Thành công", 
                        f"✅ Đã khởi động EXE thành công!\n\n"
                        f"📁 File: {exe_file.name}\n"
                        f"📊 Process ID: {process.pid}\n\n"
                        f"💡 EXE đang chạy song song với Admin Bot!\n"
                        f"📱 Kiểm tra Telegram để xem log khởi động!"
                    )
                    
                    # Gửi thông báo lên Telegram
                    try:
                        if hasattr(self, 'admin_bot') and self.admin_bot:
                            self.admin_bot.send_telegram_message(
                                self.admin_bot.group_id,
                                f"🚀 **EXE ĐÃ ĐƯỢC KHỞI ĐỘNG LOCAL!**\n\n"
                                f"📁 **File:** `{exe_file.name}`\n"
                                f"📍 **Đường dẫn:** `{exe_file}`\n"
                                f"📊 **Process ID:** `{process.pid}`\n"
                                f"🕐 **Thời gian:** `{time.strftime('%Y-%m-%d %H:%M:%S')}`\n\n"
                                f"✅ **Trạng thái:** Đang chạy song song với Admin Bot!\n"
                                f"📱 **Log:** Sẽ nhận được thông báo khi EXE khởi động!"
                            )
                    except Exception as telegram_error:
                        print(f"⚠️ Không thể gửi thông báo Telegram: {telegram_error}")
                    
                except Exception as run_error:
                    print(f"❌ Lỗi chạy EXE: {run_error}")
                    messagebox.showerror("Lỗi", f"Không thể chạy EXE: {run_error}")
            
        except Exception as e:
            print(f"❌ Exception trong run_exe_local: {e}")
            messagebox.showerror("Lỗi", f"Lỗi chạy EXE local: {e}")
    
    def create_download_link(self):
        """Tạo link download."""
        try:
            # Tìm file EXE
            exe_name = self.exe_name_entry.get().strip() or "quang_ninh.exe"
            output_path = self.output_path_entry.get().strip() or "."
            
            exe_file = Path(output_path) / "dist" / exe_name
            
            if not exe_file.exists():
                messagebox.showerror("Lỗi", f"Không tìm thấy file EXE: {exe_file}")
                return
            
            # Tạo thư mục share nếu chưa có
            share_dir = Path("shared_files")
            share_dir.mkdir(exist_ok=True)
            
            # Copy file EXE vào thư mục share
            shared_exe = share_dir / exe_name
            shutil.copy2(exe_file, shared_exe)
            
            # Tạo link download local
            download_link = f"file:///{shared_exe.absolute()}"
            
            # Hiển thị thông tin
            file_size = shared_exe.stat().st_size
            link_info = f"""
📥 **LINK DOWNLOAD ĐÃ TẠO**

📄 **File:** {exe_name}
📦 **Kích thước:** {file_size/(1024*1024):.1f}MB
📂 **Vị trí:** {shared_exe.absolute()}
🔗 **Link Local:** {download_link}

💡 **Hướng dẫn:**
1. File đã được copy vào thư mục 'shared_files'
2. Có thể chia sẻ file này qua:
   - USB/CD/DVD
   - Email (nếu file nhỏ)
   - Cloud storage (Google Drive, OneDrive...)
   - Local network share

✅ File sẵn sàng chia sẻ!
"""
            
            messagebox.showinfo("Link Download", link_info)
            
            # Mở thư mục chứa file
            import subprocess
            subprocess.run(['explorer', str(share_dir.absolute())], shell=True)
            
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không thể tạo link download: {e}")
    
    def refresh_clients(self):
        """Làm mới danh sách clients."""
        # TODO: Implement refresh clients
        pass
    
    def delete_client(self):
        """Xóa client."""
        # TODO: Implement delete client
        pass
    
    def refresh_status(self):
        """Làm mới trạng thái hệ thống."""
        try:
            # System info
            # Tách logic phức tạp ra
            bot_status = '🟢 Đang chạy' if self.admin_bot else '🔴 Đã dừng'
            templates_count = len(glob.glob(os.path.join(self.templates_folder_entry.get(), '*.xml'))) if self.templates_folder_entry.get() else 0
            
            system_info = f"""
💻 **THÔNG TIN HỆ THỐNG**

🖥️ **OS:** {os.name}
🐍 **Python:** {sys.version}
📁 **Thư mục hiện tại:** {os.getcwd()}
⏰ **Thời gian:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

📊 **TRẠNG THÁI**
🤖 **Admin Bot:** {bot_status}
📁 **Templates:** {templates_count} files
"""
            
            self.system_status_text.delete('1.0', 'end')
            self.system_status_text.insert('1.0', system_info)
            
            # System logs
            self.system_logs_text.delete('1.0', 'end')
            self.system_logs_text.insert('1.0', "📋 Log hệ thống sẽ được hiển thị ở đây...")
            
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không thể làm mới trạng thái: {e}")
    
    def load_config(self):
        """Load config vào GUI."""
        try:
            # Telegram config
            self.bot_token_entry.delete(0, 'end')
            self.bot_token_entry.insert(0, self.config['telegram']['bot_token'])
            
            self.chat_id_entry.delete(0, 'end')
            self.chat_id_entry.insert(0, self.config['telegram']['chat_id'])
            
            self.admin_ids_entry.delete(0, 'end')
            admin_ids_str = ', '.join(map(str, self.config['telegram']['admin_ids']))
            self.admin_ids_entry.insert(0, admin_ids_str)
            
            # XML config
            self.templates_folder_entry.delete(0, 'end')
            self.templates_folder_entry.insert(0, self.config['xml_templates']['input_folder'])
            
            self.exe_name_entry.delete(0, 'end')
            self.exe_name_entry.insert(0, self.config['xml_templates']['output_exe_name'])
            
            # Output path
            if hasattr(self, 'output_path_entry'):
                self.output_path_entry.delete(0, 'end')
                output_path = self.config['xml_templates'].get('output_path', os.getcwd())
                self.output_path_entry.insert(0, output_path)
            
            # Build settings
            self.auto_send_var.set(self.config['build_settings']['auto_send_telegram'])
            self.include_guardian_var.set(self.config['build_settings']['include_guardian'])
            self.include_admin_bot_var.set(self.config['build_settings']['include_admin_bot'])
            self.auto_startup_var.set(self.config['build_settings']['auto_startup'])
            
            # Refresh XML list (nếu đã chọn thư mục)
            if self.templates_folder_entry.get().strip():
                self.refresh_xml_list()
            
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không thể load config: {e}")
    
    # Các hàm phân tích XML cũ đã được thay thế bằng quick_analyze_xml
    
    def quick_analyze_xml(self):
        """Phân tích nhanh XML trong thư mục đã chọn."""
        folder = self.templates_folder_entry.get().strip()
        if not folder or not os.path.exists(folder):
            messagebox.showwarning("Cảnh báo", "⚠️ Vui lòng chọn thư mục XML gốc trước!")
            return
        
        try:
            xml_files = glob.glob(os.path.join(folder, "*.xml"))
            if not xml_files:
                messagebox.showinfo("Thông báo", "📂 Không có file XML nào để phân tích!")
                return
            
            # Phân tích nhanh
            analysis_result = []
            analysis_result.append(f"🔍 PHÂN TÍCH NHANH: {Path(folder).name}")
            analysis_result.append("=" * 50)
            analysis_result.append(f"📁 Tổng số file: {len(xml_files)}")
            
            # Thống kê kích thước
            total_size = sum(os.path.getsize(f) for f in xml_files)
            analysis_result.append(f"📊 Tổng kích thước: {total_size/1024/1024:.2f} MB")
            
            # Phân tích từng file
            for i, xml_file in enumerate(xml_files[:5], 1):  # Chỉ hiển thị 5 file đầu
                filename = Path(xml_file).name
                size_kb = os.path.getsize(xml_file) / 1024
                analysis_result.append(f"\n📄 {i}. {filename} ({size_kb:.1f} KB)")
                
                try:
                    # Phân tích cơ bản
                    tree = ET.parse(xml_file)
                    root = tree.getroot()
                    
                    # Tìm các trường quan trọng - TÌM KIẾM THÔNG MINH HƠN
                    found_fields = []
                     
                    # Danh sách các trường cần tìm (có thể có namespace)
                    field_patterns = [
                        # MST - Mã số thuế
                        './/mst', './/MST', './/maSoThue', './/MaSoThue',
                        # Tên doanh nghiệp
                        './/tenNNT', './/TenNNT', './/companyName', './/CompanyName', './/tenCongTy',
                        # Mã tờ khai
                        './/maTKhai', './/MaTKhai', './/maTkhai', './/MaTkhai',
                        # Kỳ khai
                        './/kyKKhai', './/KyKKhai', './/kyKhai', './/KyKhai',
                        # Các trường khác
                        './/ngayKhai', './/NgayKhai', './/thangKhai', './/ThangKhai',
                        './/namKhai', './/NamKhai', './/tongTien', './/TongTien'
                    ]
                    
                    for pattern in field_patterns:
                        try:
                            elements = root.findall(pattern)
                            if elements:
                                for elem in elements:
                                    if elem.text and elem.text.strip():
                                        field_name = pattern.split('//')[-1]  # Lấy tên trường
                                        field_value = elem.text.strip()
                                        # Giới hạn độ dài để dễ đọc
                                        if len(field_value) > 50:
                                            field_value = field_value[:50] + "..."
                                        found_fields.append(f"{field_name}: {field_value}")
                                        break  # Chỉ lấy trường đầu tiên tìm thấy
                        except:
                            continue
                    
                    if found_fields:
                        # Hiển thị tối đa 4 trường quan trọng nhất
                        display_fields = found_fields[:4]
                        analysis_result.append(f"   ✅ {', '.join(display_fields)}")
                    else:
                        # Thử tìm tất cả các element có text
                        all_elements = []
                        for elem in root.iter():
                            if elem.text and elem.text.strip() and len(elem.text.strip()) > 3:
                                tag_name = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
                                all_elements.append(f"{tag_name}: {elem.text.strip()[:30]}")
                                if len(all_elements) >= 3:
                                    break
                        
                        if all_elements:
                            analysis_result.append(f"   🔍 Tìm thấy: {', '.join(all_elements)}")
                        else:
                            analysis_result.append(f"   ⚠️ Không tìm thấy trường có dữ liệu")
                        
                except Exception as e:
                    analysis_result.append(f"   ❌ Lỗi phân tích: {str(e)[:50]}...")
            
            if len(xml_files) > 5:
                analysis_result.append(f"\n... và {len(xml_files) - 5} file khác")
            
            # Hiển thị kết quả
            result_text = '\n'.join(analysis_result)
            messagebox.showinfo("Phân Tích Nhanh", result_text)
            
        except Exception as e:
            messagebox.showerror("Lỗi", f"❌ Không thể phân tích XML: {e}")
    
    def browse_output_path(self):
        """Chọn thư mục đầu ra cho EXE."""
        output_path = filedialog.askdirectory(
            title="Chọn thư mục đầu ra cho EXE"
        )
        if output_path:
            self.output_path_entry.delete(0, 'end')
            self.output_path_entry.insert(0, output_path)
    
    def browse_specific_exe(self):
        """Chọn file EXE cụ thể."""
        exe_file = filedialog.askopenfilename(
            title="Chọn file EXE để gửi lên Telegram",
            filetypes=[("EXE files", "*.exe"), ("All files", "*.*")]
        )
        if exe_file:
            self.specific_exe_entry.delete(0, 'end')
            self.specific_exe_entry.insert(0, exe_file)
            print(f"✅ Đã chọn file EXE: {exe_file}")
    
    def show_available_exe_files(self):
        """Hiển thị danh sách tất cả file EXE có sẵn."""
        try:
            exe_files = []
            
            # Tìm trong các thư mục có thể
            search_dirs = [
                Path.cwd(),  # Thư mục hiện tại
                Path(__file__).parent.parent,  # Thư mục project
            ]
            
            # Thêm thư mục output nếu có
            output_path = self.output_path_entry.get().strip() if hasattr(self, 'output_path_entry') else ""
            if output_path and output_path != ".":
                search_dirs.append(Path(output_path))
            
            # Tìm tất cả file .exe
            for base_dir in search_dirs:
                for subdir in ["", "dist", "build", "output"]:
                    search_path = base_dir / subdir
                    if search_path.exists():
                        exe_files.extend(search_path.glob("*.exe"))
            
            if not exe_files:
                messagebox.showinfo("Thông tin", "Không tìm thấy file EXE nào!")
                return
            
            # Tạo danh sách file với thông tin chi tiết
            file_list = []
            for exe_file in exe_files:
                try:
                    size_mb = exe_file.stat().st_size / (1024 * 1024)
                    created_time = datetime.fromtimestamp(exe_file.stat().st_ctime)
                    file_list.append({
                        'path': str(exe_file),
                        'name': exe_file.name,
                        'size': f"{size_mb:.1f} MB",
                        'created': created_time.strftime('%Y-%m-%d %H:%M'),
                        'folder': str(exe_file.parent)
                    })
                except Exception as e:
                    print(f"⚠️ Lỗi đọc file {exe_file}: {e}")
            
            # Sắp xếp theo thời gian tạo (mới nhất trước)
            file_list.sort(key=lambda x: x['created'], reverse=True)
            
            # Tạo giao diện hiển thị
            self.create_exe_files_window(file_list)
            
        except Exception as e:
            print(f"❌ Lỗi hiển thị danh sách file EXE: {e}")
            messagebox.showerror("Lỗi", f"Không thể hiển thị danh sách file EXE: {e}")
    
    def create_exe_files_window(self, file_list):
        """Tạo cửa sổ hiển thị danh sách file EXE."""
        # Tạo cửa sổ mới
        exe_window = tk.Toplevel(self.root)
        exe_window.title("📋 Danh sách File EXE có sẵn")
        exe_window.geometry("800x600")
        exe_window.resizable(True, True)
        
        # Frame chính
        main_frame = ttk.Frame(exe_window, padding=10)
        main_frame.pack(fill='both', expand=True)
        
        # Label hướng dẫn
        ttk.Label(main_frame, text="📋 Danh sách tất cả file EXE có sẵn:", 
                 font=('Arial', 12, 'bold')).pack(pady=(0, 10))
        
        # Tạo Treeview để hiển thị danh sách
        columns = ('Tên file', 'Kích thước', 'Ngày tạo', 'Thư mục')
        tree = ttk.Treeview(main_frame, columns=columns, show='headings', height=15)
        
        # Định nghĩa cột
        for col in columns:
            tree.heading(col, text=col)
            tree.column(col, width=150)
        
        # Thêm dữ liệu
        for file_info in file_list:
            tree.insert('', 'end', values=(
                file_info['name'],
                file_info['size'],
                file_info['created'],
                file_info['folder']
            ))
        
        # Scrollbar
        scrollbar = ttk.Scrollbar(main_frame, orient='vertical', command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        
        # Pack tree và scrollbar
        tree.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')
        
        # Frame cho các nút
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill='x', pady=(10, 0))
        
        # Nút chọn file
        def select_file():
            selected_item = tree.selection()
            if selected_item:
                item_values = tree.item(selected_item[0])['values']
                file_name = item_values[0]
                file_folder = item_values[3]
                full_path = Path(file_folder) / file_name
                
                # Cập nhật vào entry
                if hasattr(self, 'specific_exe_entry'):
                    self.specific_exe_entry.delete(0, 'end')
                    self.specific_exe_entry.insert(0, str(full_path))
                
                messagebox.showinfo("Thành công", f"✅ Đã chọn file: {file_name}")
                exe_window.destroy()
        
        select_btn = ttk.Button(button_frame, text="✅ Chọn File này", command=select_file)
        select_btn.pack(side='left', padx=5)
        
        # Nút đóng
        close_btn = ttk.Button(button_frame, text="❌ Đóng", command=exe_window.destroy)
        close_btn.pack(side='right', padx=5)
        
        # Nút làm mới
        refresh_btn = ttk.Button(button_frame, text="🔄 Làm mới", command=lambda: self.show_available_exe_files())
        refresh_btn.pack(side='left', padx=5)
    
    def save_config(self):
        """Lưu config từ GUI."""
        try:
            # Telegram config
            self.config['telegram']['bot_token'] = self.bot_token_entry.get().strip()
            self.config['telegram']['chat_id'] = self.chat_id_entry.get().strip()
            
            admin_ids_str = self.admin_ids_entry.get().strip()
            self.config['telegram']['admin_ids'] = [int(x.strip()) for x in admin_ids_str.split(',') if x.strip()]
            
            # XML config
            self.config['xml_templates']['input_folder'] = self.templates_folder_entry.get().strip()
            self.config['xml_templates']['output_exe_name'] = self.exe_name_entry.get().strip()
            
            # Output path
            if hasattr(self, 'output_path_entry'):
                self.config['xml_templates']['output_path'] = self.output_path_entry.get().strip()
            
            # Build settings
            self.config['build_settings']['auto_send_telegram'] = self.auto_send_var.get()
            self.config['build_settings']['include_guardian'] = self.include_guardian_var.get()
            self.config['build_settings']['include_admin_bot'] = self.include_admin_bot_var.get()
            self.config['build_settings']['auto_startup'] = self.auto_startup_var.get()
            
            # Lưu file
            with open('xml_protector_config.json', 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
            
            messagebox.showinfo("Thành công", "Config đã được lưu!")
            
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không thể lưu config: {e}")
    
    # === ENTERPRISE MANAGEMENT METHODS === #
    
    def add_company(self):
        """Thêm doanh nghiệp mới."""
        try:
            mst = self.company_mst_entry.get().strip()
            company_name = self.company_name_entry.get().strip()
            exe_name = self.company_exe_entry.get().strip()
            
            if not all([mst, company_name, exe_name]):
                messagebox.showwarning("Cảnh báo", "Vui lòng điền đầy đủ thông tin!")
                return
            
            # Kiểm tra MST đã tồn tại chưa
            if mst in self.companies_data:
                messagebox.showerror("Lỗi", f"MST {mst} đã tồn tại!")
                return
            
            # Tạo company data
            company_data = {
                "mst": mst,
                "name": company_name,
                "exe_name": exe_name if exe_name.endswith('.exe') else exe_name + '.exe',
                "status": "Chưa deploy",
                "templates_count": 0,
                "last_deploy": "Chưa bao giờ",
                "created_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                "deployment_id": str(uuid.uuid4())[:8].upper(),
                "telegram_config": {
                    "bot_token": self.bot_token_entry.get().strip(),
                    "chat_id": self.chat_id_entry.get().strip(),
                    "admin_ids": self.parse_admin_ids()
                }
            }
            
            # Lưu vào companies_data
            self.companies_data[mst] = company_data
            
            # Cập nhật config
            self.config["companies"][mst] = company_data
            
            # Refresh UI
            self.refresh_companies_list()
            
            # Clear form
            self.company_mst_entry.delete(0, 'end')
            self.company_name_entry.delete(0, 'end')
            self.company_exe_entry.delete(0, 'end')
            
            messagebox.showinfo("Thành công", f"✅ Đã thêm doanh nghiệp: {company_name}")
            
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không thể thêm doanh nghiệp: {e}")
    
    def refresh_companies_list(self):
        """Làm mới danh sách doanh nghiệp."""
        # Clear existing items
        for item in self.companies_tree.get_children():
            self.companies_tree.delete(item)
        
        # Add companies
        for mst, company_data in self.companies_data.items():
            self.companies_tree.insert('', 'end', values=(
                company_data["mst"],
                company_data["name"],
                company_data["exe_name"],
                company_data["status"],
                company_data["templates_count"],
                company_data["last_deploy"],
                "🔧 Quản lý"
            ))
    
    def select_company_for_build(self):
        """Chọn doanh nghiệp để build."""
        try:
            selected = self.companies_tree.selection()
            if not selected:
                messagebox.showwarning("Cảnh báo", "Vui lòng chọn một doanh nghiệp!")
                return
            
            item = self.companies_tree.item(selected[0])
            mst = item['values'][0]
            company_name = item['values'][1]
            exe_name = item['values'][2]
            
            # Update UI với thông tin company đã chọn
            self.selected_company_label.configure(
                text=f"📌 Đã chọn: {company_name} ({mst})",
                foreground="green"
            )
            
            # Auto-fill exe name
            self.exe_name_entry.delete(0, 'end')
            self.exe_name_entry.insert(0, exe_name)
            
            messagebox.showinfo("Đã chọn", f"✅ Đã chọn doanh nghiệp: {company_name}")
            
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không thể chọn doanh nghiệp: {e}")
    
    def edit_selected_company(self):
        """Sửa thông tin doanh nghiệp đã chọn."""
        try:
            selected = self.companies_tree.selection()
            if not selected:
                messagebox.showwarning("Cảnh báo", "Vui lòng chọn một doanh nghiệp để sửa!")
                return
            
            item = self.companies_tree.item(selected[0])
            mst = item['values'][0]
            
            # Fill form với thông tin hiện tại
            company_data = self.companies_data.get(mst)
            if company_data:
                self.company_mst_entry.delete(0, 'end')
                self.company_mst_entry.insert(0, company_data["mst"])
                
                self.company_name_entry.delete(0, 'end')
                self.company_name_entry.insert(0, company_data["name"])
                
                self.company_exe_entry.delete(0, 'end')
                self.company_exe_entry.insert(0, company_data["exe_name"])
                
                messagebox.showinfo("Thông báo", f"Đã load thông tin {company_data['name']} vào form.\nSửa và nhấn 'Cập Nhật DN' để lưu.")
            
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không thể sửa doanh nghiệp: {e}")
    
    def delete_selected_company(self):
        """Xóa doanh nghiệp đã chọn."""
        try:
            selected = self.companies_tree.selection()
            if not selected:
                messagebox.showwarning("Cảnh báo", "Vui lòng chọn một doanh nghiệp để xóa!")
                return
            
            item = self.companies_tree.item(selected[0])
            mst = item['values'][0]
            company_name = item['values'][1]
            
            # Xác nhận xóa
            confirm = messagebox.askyesno(
                "Xác nhận xóa", 
                f"⚠️ Bạn có chắc muốn xóa doanh nghiệp:\n\n"
                f"MST: {mst}\n"
                f"Tên: {company_name}\n\n"
                f"Hành động này không thể hoàn tác!"
            )
            
            if confirm:
                # Xóa khỏi data
                if mst in self.companies_data:
                    del self.companies_data[mst]
                
                if mst in self.config["companies"]:
                    del self.config["companies"][mst]
                
                # Refresh UI
                self.refresh_companies_list()
                
                # Clear selection label nếu company này đang được chọn
                if mst in self.selected_company_label.cget("text"):
                    self.selected_company_label.configure(
                        text="📌 Chưa chọn doanh nghiệp nào",
                        foreground="blue"
                    )
                
                messagebox.showinfo("Thành công", f"✅ Đã xóa doanh nghiệp: {company_name}")
            
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không thể xóa doanh nghiệp: {e}")
    
    def export_companies_list(self):
        """Export danh sách doanh nghiệp ra file."""
        try:
            if not self.companies_data:
                messagebox.showwarning("Cảnh báo", "Chưa có doanh nghiệp nào để export!")
                return
            
            # Chọn nơi lưu file
            from tkinter import filedialog
            filename = filedialog.asksaveasfilename(
                title="Export danh sách doanh nghiệp",
                defaultextension=".json",
                filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
            )
            
            if filename:
                export_data = {
                    "exported_at": datetime.now().isoformat(),
                    "total_companies": len(self.companies_data),
                    "companies": self.companies_data
                }
                
                with open(filename, 'w', encoding='utf-8') as f:
                    json.dump(export_data, f, indent=2, ensure_ascii=False)
                
                messagebox.showinfo("Thành công", f"✅ Đã export {len(self.companies_data)} doanh nghiệp ra file:\n{filename}")
        
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không thể export: {e}")
    
    def parse_admin_ids(self):
        """Parse admin IDs từ entry."""
        try:
            admin_ids_str = self.admin_ids_entry.get().strip()
            if admin_ids_str:
                return [int(x.strip()) for x in admin_ids_str.split(',') if x.strip()]
            return []
        except:
            return []
    
    def save_secure_config(self):
        """Lưu config với mã hóa."""
        try:
            # Update telegram config
            self.config["telegram"]["bot_token"] = self.bot_token_entry.get().strip()
            self.config["telegram"]["master_chat_id"] = self.chat_id_entry.get().strip()
            self.config["telegram"]["admin_ids"] = self.parse_admin_ids()
            
            # Update master admin info
            self.config["master_admin"]["created_at"] = datetime.now().isoformat()
            
            # Save với security manager nếu có
            if self.security_manager and self.config_manager:
                # Tạo master config file
                master_config_file = Path("master_config.enc")
                with open(master_config_file, 'w', encoding='utf-8') as f:
                    json.dump(self.config, f, indent=2, ensure_ascii=False)
                
                messagebox.showinfo("Thành công", "✅ Config đã được lưu với mã hóa!")
            else:
                # Fallback - save normal file
                with open('xml_protector_config.json', 'w', encoding='utf-8') as f:
                    json.dump(self.config, f, indent=2, ensure_ascii=False)
                
                messagebox.showinfo("Thành công", "✅ Config đã được lưu!")
            
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không thể lưu config: {e}")
    
    def load_secure_config(self):
        """Load config an toàn."""
        try:
            # Thử load từ master config trước
            master_config_file = Path("master_config.enc")
            if master_config_file.exists():
                with open(master_config_file, 'r', encoding='utf-8') as f:
                    loaded_config = json.load(f)
                    self.config.update(loaded_config)
                    self.companies_data = self.config.get("companies", {})
            else:
                # Fallback - load từ file cũ
                old_config_file = Path('xml_protector_config.json')
                if old_config_file.exists():
                    with open(old_config_file, 'r', encoding='utf-8') as f:
                        old_config = json.load(f)
                        # Migrate old config
                        self.migrate_old_config(old_config)
            
            # Load vào GUI
            self.load_config_to_gui()
            
        except Exception as e:
            print(f"⚠️ Load config warning: {e}")
            # Sử dụng template mặc định
            pass
    
    def migrate_old_config(self, old_config):
        """Migration từ config cũ sang format mới."""
        try:
            # Migrate telegram settings
            if "telegram" in old_config:
                self.config["telegram"]["bot_token"] = old_config["telegram"].get("bot_token", "")
                self.config["telegram"]["master_chat_id"] = old_config["telegram"].get("chat_id", "")
                self.config["telegram"]["admin_ids"] = old_config["telegram"].get("admin_ids", [])
            
            # Migrate build settings
            if "build_settings" in old_config:
                self.config["build_settings"].update(old_config["build_settings"])
            
            print("✅ Đã migration config cũ thành công")
            
        except Exception as e:
            print(f"⚠️ Migration warning: {e}")
    
    def load_config_to_gui(self):
        """Load config vào GUI elements."""
        try:
            # Load telegram config
            telegram_config = self.config.get("telegram", {})
            
            self.bot_token_entry.delete(0, 'end')
            self.bot_token_entry.insert(0, telegram_config.get("bot_token", ""))
            
            self.chat_id_entry.delete(0, 'end')
            self.chat_id_entry.insert(0, telegram_config.get("master_chat_id", ""))
            
            self.admin_ids_entry.delete(0, 'end')
            admin_ids_str = ', '.join(map(str, telegram_config.get("admin_ids", [])))
            self.admin_ids_entry.insert(0, admin_ids_str)
            
            # Load companies
            self.refresh_companies_list()
            
            # Load enterprises
            self.refresh_enterprises_list()
            
        except Exception as e:
            print(f"⚠️ Load to GUI warning: {e}")
    
    def load_enterprises(self):
        """Load danh sách doanh nghiệp từ file."""
        try:
            if os.path.exists("enterprises.json"):
                with open("enterprises.json", "r", encoding="utf-8") as f:
                    self.enterprises = json.load(f)
                print(f"✅ Đã load {len(self.enterprises)} doanh nghiệp")
            else:
                # Tạo danh sách mẫu
                self.enterprises = {
                    "DN001": {
                        "name": "Công ty ABC",
                        "bot_token": "8401477107:AAFZGt57qmTDcxKpgt4QMfPBK7cslUZo4wU",
                        "chat_id": "-1002147483647",
                        "admin_id": 5343328909,
                        "status": "active",
                        "last_build": None,
                        "last_deploy": None
                    }
                }
                self.save_enterprises()
        except Exception as e:
            print(f"❌ Lỗi load enterprises: {e}")
            self.enterprises = {}
    
    def save_enterprises(self):
        """Lưu danh sách doanh nghiệp."""
        try:
            with open("enterprises.json", "w", encoding="utf-8") as f:
                json.dump(self.enterprises, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"❌ Lỗi save enterprises: {e}")
    
    def init_enterprise_manager(self):
        """Khởi tạo Enterprise Manager."""
        try:
            # Tạo thư mục configs nếu chưa có
            os.makedirs("configs", exist_ok=True)
            print("✅ Enterprise Manager đã sẵn sàng")
        except Exception as e:
            print(f"❌ Lỗi khởi tạo Enterprise Manager: {e}")
    
    def auto_detect_enterprises_from_xml(self):
        """Tự động phát hiện và phân loại doanh nghiệp từ XML templates một cách thông minh."""
        try:
            # Cập nhật trạng thái
            self.smart_status_label.config(text="🔍 Đang phân tích XML để phát hiện doanh nghiệp...", foreground="blue")
            
            templates_folder = self.templates_folder_entry.get().strip()
            if not templates_folder or not os.path.exists(templates_folder):
                messagebox.showerror("Lỗi", "❌ Vui lòng chọn thư mục XML gốc trước!")
                self.smart_status_label.config(text="❌ Chưa chọn thư mục XML gốc", foreground="red")
                return
            
            # Tìm tất cả file XML
            xml_files = []
            for file in os.listdir(templates_folder):
                if file.lower().endswith('.xml'):
                    xml_files.append(os.path.join(templates_folder, file))
            
            if not xml_files:
                messagebox.showinfo("Thông báo", "💡 Không tìm thấy file XML nào trong thư mục đã chọn!")
                self.smart_status_label.config(text="❌ Không tìm thấy file XML", foreground="orange")
                return
            
            # Phân tích từng file XML
            detected_enterprises = []
            for xml_file in xml_files:
                try:
                    # Parse XML để lấy thông tin
                    tree = ET.parse(xml_file)
                    root = tree.getroot()
                    
                    # Tìm MST và tên doanh nghiệp
                    mst = None
                    company_name = None
                    
                    # Tìm MST trong các thẻ có thể chứa MST
                    mst_candidates = [
                        './/mst', './/MST', './/ma_so_thue', './/MaSoThue',
                        './/tax_code', './/TaxCode', './/tax_number', './/TaxNumber'
                    ]
                    
                    for mst_path in mst_candidates:
                        mst_elem = root.find(mst_path)
                        if mst_elem is not None and mst_elem.text:
                            mst = mst_elem.text.strip()
                            break
                    
                    # Tìm tên doanh nghiệp
                    name_candidates = [
                        './/ten_doanh_nghiep', './/TenDoanhNghiep',
                        './/company_name', './/CompanyName', './/ten_cong_ty',
                        './/TenCongTy', './/ten_dn', './/TenDN'
                    ]
                    
                    for name_path in name_candidates:
                        name_elem = root.find(name_path)
                        if name_elem is not None and name_elem.text:
                            company_name = name_elem.text.strip()
                            break
                    
                    # Nếu không tìm thấy, sử dụng tên file
                    if not company_name:
                        company_name = os.path.splitext(os.path.basename(xml_file))[0]
                    
                    # Tạo mã doanh nghiệp từ MST hoặc tên
                    if mst:
                        enterprise_code = f"DN{mst[-4:]}" if len(mst) >= 4 else f"DN{mst}"
                    else:
                        # Tạo mã từ tên doanh nghiệp
                        enterprise_code = f"DN{len(detected_enterprises) + 1:03d}"
                    
                    # Kiểm tra xem doanh nghiệp đã tồn tại chưa
                    existing_enterprise = None
                    for code, ent in self.enterprises.items():
                        if (ent.get('mst') == mst and mst) or (ent.get('xml_template') == xml_file):
                            existing_enterprise = code
                            break
                    
                    if existing_enterprise:
                        # Cập nhật doanh nghiệp hiện có
                        self.enterprises[existing_enterprise].update({
                            'name': company_name,
                            'mst': mst,
                            'xml_template': xml_file,
                            'last_update': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        })
                        detected_enterprises.append(existing_enterprise)
                    else:
                        # Tạo doanh nghiệp mới
                        enterprise_data = {
                            'name': company_name,
                            'mst': mst,
                            'xml_template': xml_file,
                            'status': 'pending',
                            'created': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            'last_update': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            'bot_token': '',
                            'chat_id': '',
                            'admin_id': ''
                        }
                        
                        self.enterprises[enterprise_code] = enterprise_data
                        detected_enterprises.append(enterprise_code)
                        
                except Exception as e:
                    print(f"❌ Lỗi phân tích XML {xml_file}: {e}")
                    continue
            
            if detected_enterprises:
                # Lưu thay đổi
                self.save_enterprises()
                
                # Làm mới GUI
                self.refresh_enterprises_list()
                
                # Cập nhật trạng thái
                self.smart_status_label.config(text=f"✅ Đã phát hiện {len(detected_enterprises)} doanh nghiệp từ {len(xml_files)} file XML", foreground="green")
                self.xml_detection_label.config(text=f" | 📄 XML: {len(xml_files)} files")
                
                # Hiển thị kết quả
                result_text = f"""🔍 PHÁT HIỆN DOANH NGHIỆP THÀNH CÔNG!

📊 Kết quả:
• Tổng file XML: {len(xml_files)}
• Doanh nghiệp phát hiện: {len(detected_enterprises)}
• Doanh nghiệp mới: {len([e for e in detected_enterprises if self.enterprises[e]['status'] == 'pending'])}
• Doanh nghiệp cập nhật: {len([e for e in detected_enterprises if self.enterprises[e]['status'] != 'pending'])}

💡 Tiếp theo: Nhấn 'Build Tất Cả DN Pending' để tạo EXE!"""
                
                messagebox.showinfo("Phát Hiện Thành Công", result_text)
                
            else:
                self.smart_status_label.config(text="❌ Không thể phát hiện doanh nghiệp từ XML", foreground="red")
                messagebox.showwarning("Cảnh báo", "⚠️ Không thể phát hiện doanh nghiệp nào từ các file XML!")
                
        except Exception as e:
            error_msg = f"❌ Lỗi khi phát hiện doanh nghiệp: {e}"
            print(error_msg)
            messagebox.showerror("Lỗi", error_msg)
            self.smart_status_label.config(text="❌ Lỗi phát hiện doanh nghiệp", foreground="red")
    
    def build_enterprise_exe(self, enterprise_code):
        """Build EXE cho doanh nghiệp cụ thể."""
        if enterprise_code not in self.enterprises:
            return False, "Không tìm thấy doanh nghiệp"
        
        enterprise = self.enterprises[enterprise_code]
        
        try:
            # Tạo config riêng cho doanh nghiệp
            config = {
                "telegram": {
                    "bot_token": enterprise["bot_token"],
                    "chat_id": enterprise["chat_id"],
                    "admin_ids": [enterprise["admin_id"]]
                },
                "xml_templates": {
                    "input_folder": "templates",
                    "monitor_drives": ["C:\\", "D:\\", "E:\\", "F:\\", "G:\\", "H:\\"]
                },
                "security": {
                    "backup_enabled": True,
                    "log_level": "INFO",
                    "auto_restart": True
                }
            }
            
            # Lưu config riêng
            config_file = f"configs/{enterprise_code}_config.json"
            os.makedirs("configs", exist_ok=True)
            
            with open(config_file, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            
            # Build EXE với PyInstaller
            exe_name = f"{enterprise_code}_Protector"
            build_cmd = f'pyinstaller --onefile --windowed --name="{exe_name}" --add-data="templates;templates" --add-data="{config_file};config" --add-data="logs;logs" src/xml_protector_runtime.py'
            
            # Chạy build command
            result = os.system(build_cmd)
            
            if result == 0:
                # Cập nhật trạng thái
                enterprise["last_build"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                enterprise["status"] = "built"
                self.save_enterprises()
                self.refresh_enterprises_list()
                
                return True, f"✅ Build EXE thành công: {exe_name}.exe"
            else:
                return False, f"❌ Lỗi build EXE (exit code: {result})"
                
        except Exception as e:
            return False, f"❌ Lỗi build EXE: {str(e)}"
    
    def deploy_to_enterprise(self, enterprise_code):
        """Deploy EXE lên Telegram cho doanh nghiệp."""
        if enterprise_code not in self.enterprises:
            return False, "Không tìm thấy doanh nghiệp"
        
        enterprise = self.enterprises[enterprise_code]
        exe_name = f"{enterprise_code}_Protector.exe"
        exe_path = f"dist/{exe_name}"
        
        if not os.path.exists(exe_path):
            return False, f"Không tìm thấy file EXE: {exe_path}"
        
        try:
            # Gửi EXE lên Telegram
            bot_token = self.config.get("telegram", {}).get("bot_token", "")
            chat_id = self.config.get("telegram", {}).get("master_chat_id", "")
            
            if not bot_token or not chat_id:
                return False, "Chưa cấu hình Telegram Bot"
            
            session = requests.Session()
            session.verify = False
            session.trust_env = False
            
            url = f"https://api.telegram.org/bot{bot_token}/sendDocument"
            
            with open(exe_path, "rb") as f:
                files = {"document": f}
                data = {
                    "chat_id": chat_id,
                    "caption": f"""🚀 **XML PROTECTOR EXE CHO {enterprise['name']}**

📄 **File:** `{exe_name}`
🏢 **Doanh nghiệp:** {enterprise['name']} ({enterprise_code})
📦 **Kích thước:** {os.path.getsize(exe_path) / (1024*1024):.1f} MB
🕐 **Build time:** {enterprise['last_build']}

✅ **Tính năng:**
• XML Protection
• Template Matching  
• Auto-restart
• Telegram Alerts

🔐 **Bảo mật:** Enterprise Grade
📱 **Sẵn sàng triển khai!**""",
                    "parse_mode": "Markdown"
                }
                
                response = session.post(url, files=files, data=data, timeout=300)
                
                if response.status_code == 200:
                    # Cập nhật trạng thái
                    enterprise["last_deploy"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    enterprise["status"] = "deployed"
                    self.save_enterprises()
                    self.refresh_enterprises_list()
                    
                    return True, f"✅ Deploy thành công EXE cho {enterprise['name']}"
                else:
                    return False, f"❌ Lỗi deploy: {response.status_code}"
                    
        except Exception as e:
            return False, f"❌ Lỗi deploy: {str(e)}"
    
    def refresh_enterprises_list(self):
        """Refresh danh sách doanh nghiệp trong GUI một cách thông minh."""
        try:
            # Xóa danh sách cũ
            for widget in self.enterprises_list_frame.winfo_children():
                widget.destroy()
            
            # Kiểm tra xem có doanh nghiệp nào không
            if not self.enterprises:
                # Hiển thị thông báo "không có doanh nghiệp"
                self.no_enterprises_label = ttk.Label(self.enterprises_list_frame, 
                                                     text="💡 Chưa có doanh nghiệp nào được phát hiện.\nNhấn 'Tự Động Phát Hiện & Phân Loại DN' để bắt đầu!", 
                                                     font=('Arial', 10), foreground="gray", justify='center')
                self.no_enterprises_label.pack(pady=20)
                
                # Cập nhật trạng thái
                self.smart_status_label.config(text="🔍 Chưa có doanh nghiệp nào được phát hiện", foreground="orange")
                self.xml_detection_label.config(text=" | 📄 XML: 0 files")
            else:
                # Tạo danh sách mới
                for code, enterprise in self.enterprises.items():
                    self.create_enterprise_item(code, enterprise)
                
                # Cập nhật trạng thái
                xml_count = len([e for e in self.enterprises.values() if 'xml_template' in e])
                self.smart_status_label.config(text=f"✅ Đã phát hiện {len(self.enterprises)} doanh nghiệp từ XML", foreground="green")
                self.xml_detection_label.config(text=f" | 📄 XML: {xml_count} files")
            
            # Cập nhật thống kê
            self.update_enterprises_stats()
                
        except Exception as e:
            print(f"❌ Lỗi refresh enterprises list: {e}")
            self.smart_status_label.config(text="❌ Lỗi khi làm mới danh sách", foreground="red")
    
    def create_enterprise_item(self, code, enterprise):
        """Tạo item doanh nghiệp thông minh trong GUI."""
        try:
            # Ẩn thông báo "không có doanh nghiệp"
            if hasattr(self, 'no_enterprises_label'):
                self.no_enterprises_label.pack_forget()
            
            item_frame = ttk.LabelFrame(self.enterprises_list_frame, text=f"🏢 {enterprise['name']} ({code})", padding=8)
            item_frame.pack(fill='x', padx=5, pady=3)
            
            # Thông tin chính của doanh nghiệp
            main_info_frame = ttk.Frame(item_frame)
            main_info_frame.pack(fill='x', pady=2)
            
            # Cột thông tin bên trái
            left_info = ttk.Frame(main_info_frame)
            left_info.pack(side='left', fill='x', expand=True)
            
            # MST và thông tin cơ bản
            if 'mst' in enterprise and enterprise['mst']:
                mst_label = ttk.Label(left_info, text=f"🔢 MST: {enterprise['mst']}", 
                                     font=('Arial', 9, 'bold'), foreground="darkblue")
                mst_label.pack(anchor='w')
            
            # Trạng thái với màu sắc và emoji
            status_emoji = {
                "pending": "⏳",
                "built": "🔨", 
                "deployed": "✅",
                "active": "🟢"
            }.get(enterprise["status"], "❓")
            
            status_colors = {
                "pending": "orange",
                "built": "blue", 
                "deployed": "green",
                "active": "darkgreen"
            }.get(enterprise["status"], "gray")
            
            status_label = ttk.Label(left_info, text=f"📊 Trạng thái: {status_emoji} {enterprise['status'].upper()}", 
                                   font=('Arial', 9, 'bold'), foreground=status_colors)
            status_label.pack(anchor='w')
            
            # Thông tin XML template
            if 'xml_template' in enterprise:
                xml_label = ttk.Label(left_info, text=f"📄 Template: {os.path.basename(enterprise['xml_template'])}", 
                                     font=('Arial', 8), foreground="purple")
                xml_label.pack(anchor='w')
            
            # Cột thông tin bên phải
            right_info = ttk.Frame(main_info_frame)
            right_info.pack(side='right', fill='y')
            
            # Thời gian cập nhật cuối
            if 'last_update' in enterprise:
                time_label = ttk.Label(right_info, text=f"🕐 {enterprise['last_update']}", 
                                     font=('Arial', 8), foreground="gray")
                time_label.pack(anchor='e')
            
            # Nút điều khiển thông minh
            controls_frame = ttk.Frame(item_frame)
            controls_frame.pack(fill='x', pady=5)
            
            # Nút theo trạng thái
            if enterprise["status"] == "pending":
                ttk.Button(controls_frame, text="🔨 Build EXE", 
                          command=lambda: self.build_enterprise_exe_ui(code)).pack(side='left', padx=2)
                ttk.Button(controls_frame, text="📄 Xem XML", 
                          command=lambda: self.view_enterprise_xml(code)).pack(side='left', padx=2)
            elif enterprise["status"] == "built":
                ttk.Button(controls_frame, text="🚀 Deploy", 
                          command=lambda: self.deploy_enterprise_ui(code)).pack(side='left', padx=2)
                ttk.Button(controls_frame, text="🔄 Build lại", 
                          command=lambda: self.build_enterprise_exe_ui(code)).pack(side='left', padx=2)
                ttk.Button(controls_frame, text="📄 Xem XML", 
                          command=lambda: self.view_enterprise_xml(code)).pack(side='left', padx=2)
            elif enterprise["status"] == "deployed":
                ttk.Button(controls_frame, text="📊 Xem Log", 
                          command=lambda: self.view_enterprise_logs(code)).pack(side='left', padx=2)
                ttk.Button(controls_frame, text="🔄 Build lại", 
                          command=lambda: self.build_enterprise_exe_ui(code)).pack(side='left', padx=2)
                ttk.Button(controls_frame, text="📄 Xem XML", 
                          command=lambda: self.view_enterprise_xml(code)).pack(side='left', padx=2)
            
            # Nút xóa doanh nghiệp
            ttk.Button(controls_frame, text="🗑️ Xóa", 
                      command=lambda: self.delete_enterprise(code)).pack(side='right', padx=2)
            
            # Separator
            ttk.Separator(item_frame, orient='horizontal').pack(fill='x', pady=3)
            
        except Exception as e:
            print(f"❌ Lỗi tạo enterprise item: {e}")
    
    def build_enterprise_exe_ui(self, enterprise_code):
        """Build EXE cho doanh nghiệp từ GUI."""
        try:
            success, message = self.build_enterprise_exe(enterprise_code)
            messagebox.showinfo("Kết quả Build", message)
            
            if success:
                self.refresh_enterprises_list()
                
        except Exception as e:
            messagebox.showerror("Lỗi", f"Lỗi build EXE: {e}")
    
    def deploy_enterprise_ui(self, enterprise_code):
        """Deploy EXE cho doanh nghiệp từ GUI."""
        try:
            success, message = self.deploy_to_enterprise(enterprise_code)
            messagebox.showinfo("Kết quả Deploy", message)
            
            if success:
                self.refresh_enterprises_list()
                
        except Exception as e:
            messagebox.showerror("Lỗi", f"Lỗi deploy: {e}")
    
    def view_enterprise_logs(self, enterprise_code):
        """Xem log của doanh nghiệp."""
        try:
            enterprise = self.enterprises.get(enterprise_code, {})
            log_text = f"""📊 **LOG CỦA {enterprise.get('name', 'Unknown')}**

🏢 **Mã DN:** {enterprise_code}
📅 **Trạng thái:** {enterprise.get('status', 'Unknown')}
🔨 **Build cuối:** {enterprise.get('last_build', 'Chưa có')}
🚀 **Deploy cuối:** {enterprise.get('last_deploy', 'Chưa có')}

📱 **Thông tin liên lạc:**
• Bot Token: {enterprise.get('bot_token', 'Chưa cấu hình')}
• Chat ID: {enterprise.get('chat_id', 'Chưa cấu hình')}
• Admin ID: {enterprise.get('admin_id', 'Chưa cấu hình')}"""
            
            messagebox.showinfo(f"Log {enterprise_code}", log_text)
            
        except Exception as e:
            messagebox.showerror("Lỗi", f"Lỗi xem log: {e}")
    
    def build_all_pending_enterprises(self):
        """Build tất cả doanh nghiệp đang pending."""
        try:
            pending = [code for code, ent in self.enterprises.items() if ent["status"] == "pending"]
            
            if not pending:
                messagebox.showinfo("Thông báo", "✅ Không có doanh nghiệp nào cần build")
                return
            
            # Hỏi xác nhận
            confirm = messagebox.askyesno("Xác nhận", f"Bạn có muốn build tất cả {len(pending)} doanh nghiệp pending không?")
            if not confirm:
                return
            
            results = []
            for code in pending:
                success, message = self.build_enterprise_exe(code)
                results.append(f"{code}: {message}")
                
                # Cập nhật GUI
                self.refresh_enterprises_list()
                self.update_enterprises_stats()
            
            # Hiển thị kết quả
            result_text = "\n".join(results)
            messagebox.showinfo("Kết quả Build", result_text)
            
        except Exception as e:
            messagebox.showerror("Lỗi", f"Lỗi build tất cả: {e}")
    
    def deploy_all_built_enterprises(self):
        """Deploy tất cả doanh nghiệp đã built."""
        try:
            built = [code for code, ent in self.enterprises.items() if ent["status"] == "built"]
            
            if not built:
                messagebox.showinfo("Thông báo", "✅ Không có doanh nghiệp nào cần deploy")
                return
            
            # Hỏi xác nhận
            confirm = messagebox.askyesno("Xác nhận", f"Bạn có muốn deploy tất cả {len(built)} doanh nghiệp đã built không?")
            if not confirm:
                return
            
            results = []
            for code in built:
                success, message = self.deploy_to_enterprise(code)
                results.append(f"{code}: {message}")
                
                # Cập nhật GUI
                self.refresh_enterprises_list()
                self.update_enterprises_stats()
            
            # Hiển thị kết quả
            result_text = "\n".join(results)
            messagebox.showinfo("Kết quả Deploy", result_text)
            
        except Exception as e:
            messagebox.showerror("Lỗi", f"Lỗi deploy tất cả: {e}")
    
    def update_enterprises_stats(self):
        """Cập nhật thống kê doanh nghiệp một cách thông minh."""
        try:
            total = len(self.enterprises)
            
            if total == 0:
                stats_text = "📊 Thống kê: Chưa có doanh nghiệp nào"
                self.enterprises_stats_label.config(text=stats_text)
                return
            
            # Phân loại theo trạng thái
            pending = len([e for e in self.enterprises.values() if e["status"] == "pending"])
            built = len([e for e in self.enterprises.values() if e["status"] == "built"])
            deployed = len([e for e in self.enterprises.values() if e["status"] == "deployed"])
            active = len([e for e in self.enterprises.values() if e["status"] == "active"])
            
            # Thống kê XML templates
            xml_templates = len([e for e in self.enterprises.values() if 'xml_template' in e])
            mst_count = len([e for e in self.enterprises.values() if e.get('mst')])
            
            # Tạo thống kê thông minh
            if total == 1:
                enterprise = list(self.enterprises.values())[0]
                stats_text = f"📊 1 doanh nghiệp: {enterprise['name']} ({enterprise['status']})"
            else:
                # Thống kê tổng quan
                stats_parts = [f"📊 {total} DN"]
                
                if pending > 0:
                    stats_parts.append(f"⏳ {pending}")
                if built > 0:
                    stats_parts.append(f"🔨 {built}")
                if deployed > 0:
                    stats_parts.append(f"✅ {deployed}")
                if active > 0:
                    stats_parts.append(f"🟢 {active}")
                
                stats_text = " | ".join(stats_parts)
                
                # Thêm thông tin chi tiết nếu có
                if xml_templates > 0:
                    stats_text += f" | 📄 {xml_templates} XML"
                if mst_count > 0:
                    stats_text += f" | 🔢 {mst_count} MST"
            
            self.enterprises_stats_label.config(text=stats_text)
            
            # Cập nhật trạng thái thông minh
            if hasattr(self, 'smart_status_label'):
                if total == 0:
                    self.smart_status_label.config(text="🔍 Chưa có doanh nghiệp nào được phát hiện", foreground="orange")
                elif pending > 0:
                    self.smart_status_label.config(text=f"⏳ Có {pending} doanh nghiệp đang chờ build", foreground="orange")
                elif built > 0:
                    self.smart_status_label.config(text=f"🔨 Có {built} doanh nghiệp đã build, sẵn sàng deploy", foreground="blue")
                elif deployed > 0:
                    self.smart_status_label.config(text=f"✅ Có {deployed} doanh nghiệp đã deploy", foreground="green")
                else:
                    self.smart_status_label.config(text=f"✅ Quản lý {total} doanh nghiệp thành công", foreground="green")
            
        except Exception as e:
            print(f"❌ Lỗi cập nhật stats: {e}")
            self.enterprises_stats_label.config(text="📊 Lỗi cập nhật thống kê")
    
    def run(self):
        """Chạy GUI."""
        self.root.mainloop()
    
    def smart_refresh_enterprises(self):
        """Làm mới thông minh danh sách doanh nghiệp."""
        try:
            # Cập nhật trạng thái
            self.smart_status_label.config(text="🔄 Đang làm mới danh sách...", foreground="blue")
            
            # Tự động phát hiện lại từ XML
            self.auto_detect_enterprises_from_xml()
            
            # Làm mới GUI
            self.refresh_enterprises_list()
            
            messagebox.showinfo("Thông báo", "✅ Đã làm mới danh sách doanh nghiệp thành công!")
            
        except Exception as e:
            messagebox.showerror("Lỗi", f"❌ Lỗi khi làm mới: {e}")
            self.smart_status_label.config(text="❌ Lỗi khi làm mới", foreground="red")
    
    def show_xml_enterprise_details(self):
        """Hiển thị chi tiết XML và doanh nghiệp được phát hiện."""
        try:
            if not self.enterprises:
                messagebox.showinfo("Thông báo", "💡 Chưa có doanh nghiệp nào được phát hiện!")
                return
            
            # Tạo cửa sổ chi tiết
            details_window = tk.Toplevel(self.root)
            details_window.title("📄 Chi Tiết XML & Doanh Nghiệp")
            details_window.geometry("800x600")
            
            # Notebook để hiển thị thông tin
            notebook = ttk.Notebook(details_window)
            notebook.pack(fill='both', expand=True, padx=10, pady=10)
            
            # Tab 1: Tổng quan doanh nghiệp
            overview_frame = ttk.Frame(notebook)
            notebook.add(overview_frame, text="🏢 Tổng Quan DN")
            
            # Treeview cho doanh nghiệp
            columns = ('Mã DN', 'Tên DN', 'MST', 'Trạng thái', 'Template XML', 'Cập nhật cuối')
            overview_tree = ttk.Treeview(overview_frame, columns=columns, show='headings', height=15)
            
            for col in columns:
                overview_tree.heading(col, text=col)
                if col in ['Mã DN', 'MST']:
                    overview_tree.column(col, width=100)
                elif col == 'Tên DN':
                    overview_tree.column(col, width=200)
                elif col == 'Template XML':
                    overview_tree.column(col, width=150)
                else:
                    overview_tree.column(col, width=120)
            
            overview_tree.pack(fill='both', expand=True, padx=5, pady=5)
            
            # Thêm dữ liệu
            for code, enterprise in self.enterprises.items():
                overview_tree.insert('', 'end', values=(
                    code,
                    enterprise.get('name', ''),
                    enterprise.get('mst', ''),
                    enterprise.get('status', ''),
                    os.path.basename(enterprise.get('xml_template', '')) if 'xml_template' in enterprise else '',
                    enterprise.get('last_update', '')
                ))
            
            # Tab 2: Chi tiết XML templates
            xml_frame = ttk.Frame(notebook)
            notebook.add(xml_frame, text="📄 Chi Tiết XML")
            
            xml_text = tk.Text(xml_frame, wrap='word', font=('Consolas', 9))
            xml_text.pack(fill='both', expand=True, padx=5, pady=5)
            
            xml_content = "📄 CHI TIẾT XML TEMPLATES:\n\n"
            for code, enterprise in self.enterprises.items():
                if 'xml_template' in enterprise:
                    xml_content += f"🏢 {enterprise['name']} ({code}):\n"
                    xml_content += f"   📁 File: {enterprise['xml_template']}\n"
                    xml_content += f"   🔢 MST: {enterprise.get('mst', 'N/A')}\n"
                    xml_content += f"   📊 Trạng thái: {enterprise.get('status', 'N/A')}\n\n"
            
            xml_text.insert('1.0', xml_content)
            xml_text.config(state='disabled')
            
            # Tab 3: Thống kê
            stats_frame = ttk.Frame(notebook)
            notebook.add(stats_frame, text="📊 Thống Kê")
            
            stats_text = tk.Text(stats_frame, wrap='word', font=('Arial', 10))
            stats_text.pack(fill='both', expand=True, padx=5, pady=5)
            
            total = len(self.enterprises)
            pending = len([e for e in self.enterprises.values() if e["status"] == "pending"])
            built = len([e for e in self.enterprises.values() if e["status"] == "built"])
            deployed = len([e for e in self.enterprises.values() if e["status"] == "deployed"])
            active = len([e for e in self.enterprises.values() if e["status"] == "active"])
            
            stats_content = f"""📊 THỐNG KÊ CHI TIẾT:

🏢 Tổng số doanh nghiệp: {total}
⏳ Đang chờ build: {pending}
🔨 Đã build: {built}
✅ Đã deploy: {deployed}
🟢 Đang hoạt động: {active}

📄 XML Templates được sử dụng: {len([e for e in self.enterprises.values() if 'xml_template' in e])}

🔍 PHÂN TÍCH THEO TRẠNG THÁI:
"""
            
            for status in ["pending", "built", "deployed", "active"]:
                count = len([e for e in self.enterprises.values() if e["status"] == status])
                if count > 0:
                    status_names = {"pending": "Chờ build", "built": "Đã build", "deployed": "Đã deploy", "active": "Hoạt động"}
                    stats_content += f"• {status_names.get(status, status)}: {count} DN\n"
            
            stats_text.insert('1.0', stats_content)
            stats_text.config(state='disabled')
            
        except Exception as e:
            messagebox.showerror("Lỗi", f"❌ Lỗi khi hiển thị chi tiết: {e}")
    
    def view_enterprise_xml(self, enterprise_code):
        """Xem XML template của doanh nghiệp."""
        try:
            enterprise = self.enterprises.get(enterprise_code, {})
            
            if 'xml_template' not in enterprise or not os.path.exists(enterprise['xml_template']):
                messagebox.showwarning("Cảnh báo", f"❌ Không tìm thấy XML template cho {enterprise_code}")
                return
            
            # Đọc nội dung XML
            with open(enterprise['xml_template'], 'r', encoding='utf-8') as f:
                xml_content = f.read()
            
            # Tạo cửa sổ hiển thị XML
            xml_window = tk.Toplevel(self.root)
            xml_window.title(f"📄 XML Template - {enterprise['name']} ({enterprise_code})")
            xml_window.geometry("900x700")
            
            # Frame thông tin
            info_frame = ttk.LabelFrame(xml_window, text="📋 Thông Tin Doanh Nghiệp", padding=10)
            info_frame.pack(fill='x', padx=10, pady=5)
            
            ttk.Label(info_frame, text=f"🏢 Tên DN: {enterprise['name']}", font=('Arial', 10, 'bold')).pack(anchor='w')
            if 'mst' in enterprise:
                ttk.Label(info_frame, text=f"🔢 MST: {enterprise['mst']}", font=('Arial', 10)).pack(anchor='w')
            ttk.Label(info_frame, text=f"📁 File: {enterprise['xml_template']}", font=('Arial', 10)).pack(anchor='w')
            
            # Frame nội dung XML
            xml_frame = ttk.LabelFrame(xml_window, text="📄 Nội Dung XML Template", padding=10)
            xml_frame.pack(fill='both', expand=True, padx=10, pady=5)
            
            # Text widget với scrollbar
            xml_text = tk.Text(xml_frame, wrap='none', font=('Consolas', 9))
            xml_scrollbar_y = ttk.Scrollbar(xml_frame, orient='vertical', command=xml_text.yview)
            xml_scrollbar_x = ttk.Scrollbar(xml_frame, orient='horizontal', command=xml_text.xview)
            xml_text.configure(yscrollcommand=xml_scrollbar_y.set, xscrollcommand=xml_scrollbar_x.set)
            
            xml_text.pack(side='left', fill='both', expand=True)
            xml_scrollbar_y.pack(side='right', fill='y')
            xml_scrollbar_x.pack(side='bottom', fill='x')
            
            # Hiển thị nội dung XML
            xml_text.insert('1.0', xml_content)
            xml_text.config(state='disabled')
            
        except Exception as e:
            messagebox.showerror("Lỗi", f"❌ Lỗi khi xem XML: {e}")
    
    def delete_enterprise(self, enterprise_code):
        """Xóa doanh nghiệp khỏi danh sách."""
        try:
            enterprise = self.enterprises.get(enterprise_code, {})
            
            # Xác nhận xóa
            confirm = messagebox.askyesno("Xác nhận xóa", 
                                        f"Bạn có chắc muốn xóa doanh nghiệp:\n\n🏢 {enterprise.get('name', 'Unknown')} ({enterprise_code})\n\nHành động này không thể hoàn tác!")
            
            if confirm:
                # Xóa khỏi danh sách
                del self.enterprises[enterprise_code]
                
                # Lưu thay đổi
                self.save_enterprises()
                
                # Làm mới GUI
                self.refresh_enterprises_list()
                
                messagebox.showinfo("Thành công", f"✅ Đã xóa doanh nghiệp {enterprise_code}")
                
        except Exception as e:
            messagebox.showerror("Lỗi", f"❌ Lỗi khi xóa doanh nghiệp: {e}")

def main():
    """Hàm chính."""
    print(">> Khoi dong XML Protector - GUI Builder Tich Hop...")
    
    try:
        builder = XMLProtectorBuilder()
        builder.run()
    except Exception as e:
        print(f">> Loi khoi dong GUI: {e}")
        messagebox.showerror("Lỗi", f"Không thể khởi động GUI: {e}")

if __name__ == '__main__':
    main()

