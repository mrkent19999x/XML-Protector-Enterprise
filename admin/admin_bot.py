#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
XML Protector Admin Bot - Telegram Bot tích hợp
Quản lý tất cả EXE clients từ xa
"""

import os
import sys
import time
import json
import sqlite3
import logging
import requests
import threading
from datetime import datetime
from pathlib import Path

# --- SECURE CONFIG LOADING --- #
def load_admin_bot_config():
    """Load config an toàn cho Admin Bot."""
    import os
    bot_token = os.getenv("XML_PROTECTOR_BOT_TOKEN", "")
    admin_ids_str = os.getenv("XML_PROTECTOR_ADMIN_IDS", "")
    
    if admin_ids_str:
        admin_ids = [int(x.strip()) for x in admin_ids_str.split(",") if x.strip()]
    else:
        admin_ids = []
    
    if not bot_token:
        raise Exception("❌ Bot token không được cấu hình! Set XML_PROTECTOR_BOT_TOKEN environment variable")
    
    return bot_token, admin_ids

# Load config
try:
    BOT_TOKEN, ADMIN_IDS = load_admin_bot_config()
except Exception as e:
    print(f"❌ ADMIN BOT CONFIG ERROR: {e}")
    BOT_TOKEN = ""
    ADMIN_IDS = []

# --- DATABASE --- #
DB_FILE = "xml_protector_admin.db"

# --- LOGGING --- #
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('admin_bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

class AdminBot:
    def __init__(self):
        self.bot_token = BOT_TOKEN
        self.admin_ids = ADMIN_IDS
        self.clients = {}  # Lưu trữ thông tin clients
        self.init_database()
        
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
            logging.info("✅ Database đã được khởi tạo")
            
        except Exception as e:
            logging.error(f"❌ Lỗi khởi tạo database: {e}")
    
    def send_telegram_message(self, chat_id, message, reply_markup=None):
        """Gửi message qua Telegram Bot."""
        try:
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
                logging.warning(f"❌ Lỗi gửi Telegram: {response.status_code}")
                return False
        except Exception as e:
            logging.error(f"❌ Gửi Telegram thất bại: {e}")
            return False
    
    def create_main_menu(self):
        """Tạo menu chính cho admin - Enhanced với Enterprise Management."""
        return {
            "inline_keyboard": [
                [
                    {"text": "📊 Master Dashboard", "callback_data": "master_dashboard"},
                    {"text": "🏢 Doanh Nghiệp", "callback_data": "companies_list"}
                ],
                [
                    {"text": "🖥️ Clients Online", "callback_data": "clients_online"},
                    {"text": "🔴 Clients Offline", "callback_data": "clients_offline"}
                ],
                [
                    {"text": "🏗️ Build & Deploy", "callback_data": "build_deploy_menu"},
                    {"text": "📤 Mass Deploy", "callback_data": "mass_deploy"}
                ],
                [
                    {"text": "🚨 Security Alerts", "callback_data": "security_alerts"},
                    {"text": "📋 Audit Logs", "callback_data": "audit_logs"}
                ],
                [
                    {"text": "🔄 Mass Commands", "callback_data": "mass_commands"},
                    {"text": "📊 Analytics", "callback_data": "analytics"}
                ],
                [
                    {"text": "⚙️ System Settings", "callback_data": "system_settings"},
                    {"text": "🆘 Emergency", "callback_data": "emergency_menu"}
                ]
            ]
        }
    
    def create_client_menu(self, client_id):
        """Tạo menu quản lý client cụ thể."""
        return {
            "inline_keyboard": [
                [
                    {"text": "📊 Trạng thái", "callback_data": f"client_status_{client_id}"},
                    {"text": "⏸️ Tạm dừng", "callback_data": f"client_pause_{client_id}"}
                ],
                [
                    {"text": "▶️ Tiếp tục", "callback_data": f"client_resume_{client_id}"},
                    {"text": "🔄 Restart", "callback_data": f"client_restart_{client_id}"}
                ],
                [
                    {"text": "📁 Templates", "callback_data": f"client_templates_{client_id}"},
                    {"text": "📋 Logs", "callback_data": f"client_logs_{client_id}"}
                ],
                [
                    {"text": "🗑️ Xóa Client", "callback_data": f"client_delete_{client_id}"},
                    {"text": "🔙 Quay lại", "callback_data": "manage_clients"}
                ]
            ]
        }
    
    def handle_callback(self, callback_data, user_id, chat_id):
        """Xử lý callback từ menu."""
        if user_id not in self.admin_ids:
            self.send_telegram_message(chat_id, "❌ **Bạn không có quyền truy cập!**")
            return
        
        try:
            # Master Dashboard và Enterprise Management
            if callback_data == "master_dashboard":
                self.show_master_dashboard(chat_id)
            elif callback_data == "companies_list":
                self.show_companies_list(chat_id)
            elif callback_data == "clients_online":
                self.show_clients_by_status(chat_id, "online")
            elif callback_data == "clients_offline":
                self.show_clients_by_status(chat_id, "offline")
            
            # Build & Deploy
            elif callback_data == "build_deploy_menu":
                self.show_build_deploy_menu(chat_id)
            elif callback_data == "mass_deploy":
                self.show_mass_deploy_menu(chat_id)
            
            # Security & Monitoring
            elif callback_data == "security_alerts":
                self.show_security_alerts(chat_id)
            elif callback_data == "audit_logs":
                self.show_audit_logs(chat_id)
            elif callback_data == "analytics":
                self.show_analytics(chat_id)
            
            # Mass Commands
            elif callback_data == "mass_commands":
                self.show_mass_commands_menu(chat_id)
            
            # System Settings
            elif callback_data == "system_settings":
                self.show_system_settings(chat_id)
            elif callback_data == "emergency_menu":
                self.show_emergency_menu(chat_id)
            
            # Legacy callbacks (backward compatibility)
            elif callback_data == "dashboard":
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
            elif callback_data.startswith("client_"):
                self.handle_client_action(callback_data, chat_id)
            else:
                self.send_telegram_message(chat_id, f"❌ **Lệnh không hợp lệ:** `{callback_data}`")
                
        except Exception as e:
            logging.error(f"❌ Lỗi xử lý callback: {e}")
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
            logging.error(f"❌ Lỗi hiển thị dashboard: {e}")
            self.send_telegram_message(chat_id, f"❌ **Lỗi:** `{str(e)}`")
    
    def show_clients_list(self, chat_id):
        """Hiển thị danh sách clients."""
        try:
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT client_name, client_id, status, last_seen, templates_count 
                FROM clients 
                ORDER BY last_seen DESC
            """)
            clients = cursor.fetchall()
            conn.close()
            
            if not clients:
                self.send_telegram_message(chat_id, "📭 **Chưa có client nào được đăng ký**", self.create_main_menu())
                return
            
            clients_text = "🖥️ **DANH SÁCH CLIENTS**\n\n"
            
            for i, (name, client_id, status, last_seen, templates) in enumerate(clients, 1):
                status_emoji = "🟢" if status == "online" else "🔴"
                last_seen_str = last_seen if last_seen else "Chưa kết nối"
                
                clients_text += f"{i}. **{name}**\n"
                clients_text += f"   ID: `{client_id}`\n"
                clients_text += f"   Trạng thái: {status_emoji} {status}\n"
                clients_text += f"   Templates: {templates} files\n"
                clients_text += f"   Cuối cùng: {last_seen_str}\n\n"
            
            # Tạo menu cho từng client
            keyboard = []
            for name, client_id, status, _, _ in clients:
                keyboard.append([{"text": f"{name} ({status})", "callback_data": f"client_menu_{client_id}"}])
            
            keyboard.append([{"text": "🔙 Quay lại", "callback_data": "main_menu"}])
            
            reply_markup = {"inline_keyboard": keyboard}
            self.send_telegram_message(chat_id, clients_text, reply_markup)
            
        except Exception as e:
            logging.error(f"❌ Lỗi hiển thị clients: {e}")
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
                    {"text": "🛡️ Runtime Client", "callback_data": "build_runtime"},
                    {"text": "🏗️ Builder Tool", "callback_data": "build_builder"}
                ],
                [
                    {"text": "🤖 Hybrid Bot", "callback_data": "build_hybrid"},
                    {"text": "📱 Mobile App", "callback_data": "build_mobile"}
                ],
                [
                    {"text": "🔙 Quay lại", "callback_data": "main_menu"}
                ]
            ]
        }
        
        self.send_telegram_message(chat_id, build_text, keyboard)
    
    def show_deploy_menu(self, chat_id):
        """Hiển thị menu deploy."""
        deploy_text = """
📤 **DEPLOY & PHÂN PHỐI**

Chọn cách deploy EXE:

1. **📤 Gửi qua Telegram** - Gửi file EXE
2. **🌐 Download Link** - Tạo link download
3. **📧 Email** - Gửi qua email
4. **🔄 Auto Update** - Cập nhật tự động
"""
        
        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "📤 Telegram", "callback_data": "deploy_telegram"},
                    {"text": "🌐 Download", "callback_data": "deploy_download"}
                ],
                [
                    {"text": "📧 Email", "callback_data": "deploy_email"},
                    {"text": "🔄 Auto Update", "callback_data": "deploy_auto"}
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
            
            cursor.execute("""
                SELECT a.alert_type, a.message, a.severity, a.timestamp, c.client_name
                FROM alerts a
                LEFT JOIN clients c ON a.client_id = c.client_id
                ORDER BY a.timestamp DESC
                LIMIT 10
            """)
            alerts = cursor.fetchall()
            conn.close()
            
            if not alerts:
                self.send_telegram_message(chat_id, "✅ **Không có alert nào**", self.create_main_menu())
                return
            
            alerts_text = "🚨 **ALERTS GẦN ĐÂY**\n\n"
            
            for alert_type, message, severity, timestamp, client_name in alerts:
                severity_emoji = {
                    "high": "🔴",
                    "medium": "🟡", 
                    "low": "🟢",
                    "info": "ℹ️"
                }.get(severity, "ℹ️")
                
                alerts_text += f"{severity_emoji} **{alert_type}**\n"
                alerts_text += f"   Client: {client_name or 'System'}\n"
                alerts_text += f"   Message: {message}\n"
                alerts_text += f"   Time: {timestamp}\n\n"
            
            keyboard = {
                "inline_keyboard": [
                    [{"text": "🔙 Quay lại", "callback_data": "main_menu"}]
                ]
            }
            
            self.send_telegram_message(chat_id, alerts_text, keyboard)
            
        except Exception as e:
            logging.error(f"❌ Lỗi hiển thị alerts: {e}")
            self.send_telegram_message(chat_id, f"❌ **Lỗi:** `{str(e)}`")
    
    def show_reports(self, chat_id):
        """Hiển thị reports."""
        reports_text = """
📋 **BÁO CÁO & THỐNG KÊ**

Chọn loại báo cáo:

1. **📊 Performance** - Hiệu suất hệ thống
2. **🚨 Security** - Báo cáo bảo mật
3. **💰 Business** - Báo cáo kinh doanh
4. **📈 Analytics** - Phân tích dữ liệu
"""
        
        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "📊 Performance", "callback_data": "report_performance"},
                    {"text": "🚨 Security", "callback_data": "report_security"}
                ],
                [
                    {"text": "💰 Business", "callback_data": "report_business"},
                    {"text": "📈 Analytics", "callback_data": "report_analytics"}
                ],
                [
                    {"text": "🔙 Quay lại", "callback_data": "main_menu"}
                ]
            ]
        }
        
        self.send_telegram_message(chat_id, reports_text, keyboard)
    
    def show_settings(self, chat_id):
        """Hiển thị settings."""
        settings_text = """
⚙️ **CÀI ĐẶT HỆ THỐNG**

1. **🔑 Bot Token** - Cấu hình bot
2. **👥 Admin Users** - Quản lý quyền admin
3. **📧 Notifications** - Cài đặt thông báo
4. **🔄 Auto Update** - Cập nhật tự động
"""
        
        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "🔑 Bot Token", "callback_data": "setting_token"},
                    {"text": "👥 Admin Users", "callback_data": "setting_admins"}
                ],
                [
                    {"text": "📧 Notifications", "callback_data": "setting_notifications"},
                    {"text": "🔄 Auto Update", "callback_data": "setting_auto_update"}
                ],
                [
                    {"text": "🔙 Quay lại", "callback_data": "main_menu"}
                ]
            ]
        }
        
        self.send_telegram_message(chat_id, settings_text, keyboard)
    
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

**Liên hệ hỗ trợ:**
• Admin: @admin_username
• Email: support@xmlprotector.com
"""
        
        keyboard = {
            "inline_keyboard": [
                [{"text": "🔙 Quay lại", "callback_data": "main_menu"}]
            ]
        }
        
        self.send_telegram_message(chat_id, help_text, keyboard)
    
    def handle_client_action(self, callback_data, chat_id):
        """Xử lý action với client cụ thể."""
        try:
            parts = callback_data.split("_")
            action = parts[1]
            client_id = parts[2] if len(parts) > 2 else None
            
            if action == "menu":
                self.show_client_menu(chat_id, client_id)
            elif action == "status":
                self.show_client_status(chat_id, client_id)
            elif action == "pause":
                self.pause_client(chat_id, client_id)
            elif action == "resume":
                self.resume_client(chat_id, client_id)
            elif action == "restart":
                self.restart_client(chat_id, client_id)
            elif action == "templates":
                self.show_client_templates(chat_id, client_id)
            elif action == "logs":
                self.show_client_logs(chat_id, client_id)
            elif action == "delete":
                self.delete_client(chat_id, client_id)
            else:
                self.send_telegram_message(chat_id, "❌ Action không hợp lệ!")
                
        except Exception as e:
            logging.error(f"❌ Lỗi xử lý client action: {e}")
            self.send_telegram_message(chat_id, f"❌ **Lỗi:** `{str(e)}`")
    
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
                                
                                elif text == '/help':
                                    self.show_help(chat_id)
                                
                                elif text == '/status':
                                    self.show_dashboard(chat_id)
                                
                                else:
                                    # Xử lý tin nhắn thông thường
                                    self.handle_text_message(text, user_id, chat_id)
                
                except Exception as e:
                    logging.error(f"❌ Lỗi Telegram webhook: {e}")
                    time.sleep(5)
                
                time.sleep(1)
        
        telegram_thread = threading.Thread(target=check_telegram_updates, daemon=True)
        telegram_thread.start()
        logging.info("✅ Telegram webhook đã khởi động")
    
    def handle_text_message(self, text, user_id, chat_id):
        """Xử lý tin nhắn text thông thường."""
        if user_id not in self.admin_ids:
            self.send_telegram_message(chat_id, "❌ **Bạn không có quyền truy cập!**")
            return
        
        # Xử lý các lệnh text
        if text.lower().startswith("build "):
            self.handle_build_command(text, chat_id)
        elif text.lower().startswith("deploy "):
            self.handle_deploy_command(text, chat_id)
        elif text.lower().startswith("client "):
            self.handle_client_command(text, chat_id)
        else:
            self.send_telegram_message(chat_id, "💡 Gửi /menu để xem các tùy chọn", self.create_main_menu())
    
    # === ENHANCED ENTERPRISE METHODS === #
    
    def show_master_dashboard(self, chat_id):
        """Hiển thị master dashboard tổng quan toàn hệ thống."""
        try:
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            
            # Enterprise-level statistics
            cursor.execute("SELECT COUNT(*) FROM clients")
            total_clients = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM clients WHERE status = 'online'")
            online_clients = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM alerts WHERE severity = 'high' AND timestamp > datetime('now', '-24 hours')")
            high_alerts_24h = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM activities WHERE timestamp > datetime('now', '-1 hours')")
            recent_activities = cursor.fetchone()[0]
            
            # Top active clients
            cursor.execute("""
                SELECT client_name, COUNT(*) as activity_count 
                FROM activities a
                JOIN clients c ON a.client_id = c.client_id
                WHERE a.timestamp > datetime('now', '-24 hours')
                GROUP BY a.client_id
                ORDER BY activity_count DESC
                LIMIT 3
            """)
            top_clients = cursor.fetchall()
            
            conn.close()
            
            # Create dashboard text
            dashboard_text = f"""
🎯 **XML PROTECTOR - MASTER CONTROL DASHBOARD**

📊 **TỔNG QUAN HỆ THỐNG:**
🏢 **Total Enterprises:** `{total_clients}`
🟢 **Online Now:** `{online_clients}`
🔴 **Offline:** `{total_clients - online_clients}`
⚡ **Uptime Ratio:** `{(online_clients/total_clients*100) if total_clients > 0 else 0:.1f}%`

🚨 **BẢO MẬT 24H:**
🔥 **High Alerts:** `{high_alerts_24h}`
🔄 **Recent Activities:** `{recent_activities}`

📈 **TOP ACTIVE CLIENTS (24H):**
"""
            
            for i, (client_name, activity_count) in enumerate(top_clients, 1):
                dashboard_text += f"   {i}. **{client_name}:** `{activity_count} activities`\n"
            
            if not top_clients:
                dashboard_text += "   _Chưa có hoạt động nào_\n"
            
            dashboard_text += f"\n⏰ **Last Update:** `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`"
            
            self.send_telegram_message(chat_id, dashboard_text, self.create_main_menu())
            
        except Exception as e:
            logging.error(f"❌ Lỗi hiển thị master dashboard: {e}")
            self.send_telegram_message(chat_id, f"❌ **Lỗi Master Dashboard:** `{str(e)}`")
    
    def show_mass_commands_menu(self, chat_id):
        """Hiển thị menu lệnh hàng loạt."""
        mass_text = """
🔄 **MASS COMMANDS - ĐIỀU KHIỂN HÀNG LOẠT**

Thực hiện lệnh cho nhiều client cùng lúc:

🔴 **Mass Pause** - Tạm dừng tất cả client
▶️ **Mass Resume** - Khởi động lại tất cả client  
🔄 **Mass Restart** - Restart tất cả client
📋 **Mass Status** - Lấy trạng thái tất cả client
🗑️ **Mass Cleanup** - Dọn dẹp log files
📤 **Mass Update** - Cập nhật templates mới

⚠️ **Cảnh báo:** Các lệnh này sẽ ảnh hưởng đến TẤT CẢ client đang hoạt động!
"""
        
        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "🔴 Mass Pause", "callback_data": "mass_pause_all"},
                    {"text": "▶️ Mass Resume", "callback_data": "mass_resume_all"}
                ],
                [
                    {"text": "🔄 Mass Restart", "callback_data": "mass_restart_all"},
                    {"text": "📋 Mass Status", "callback_data": "mass_status_all"}
                ],
                [
                    {"text": "🗑️ Mass Cleanup", "callback_data": "mass_cleanup_all"},
                    {"text": "📤 Mass Update", "callback_data": "mass_update_all"}
                ],
                [
                    {"text": "🔙 Quay lại", "callback_data": "master_dashboard"}
                ]
            ]
        }
        
        self.send_telegram_message(chat_id, mass_text, keyboard)
    
    def run(self):
        """Chạy bot."""
        logging.info("🚀 XML Protector Admin Bot đang khởi động...")
        
        # Khởi động Telegram webhook
        self.start_telegram_webhook()
        
        # Gửi thông báo khởi động cho admin
        startup_msg = f"""
🚀 **XML PROTECTOR ADMIN BOT ĐÃ KHỞI ĐỘNG!**

⏰ **Thời gian:** `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`
🤖 **Bot Token:** `{self.bot_token[:20]}...`
👥 **Admin IDs:** `{self.admin_ids}`

Gửi /start để bắt đầu sử dụng!
"""
        
        for admin_id in self.admin_ids:
            self.send_telegram_message(admin_id, startup_msg)
        
        logging.info("✅ Admin Bot đã sẵn sàng!")
        
        # Giữ bot chạy
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logging.info("⏹️ Admin Bot đã tắt (KeyboardInterrupt)")
        except Exception as e:
            logging.error(f"❌ Admin Bot gặp lỗi: {e}")

if __name__ == '__main__':
    bot = AdminBot()
    bot.run()
