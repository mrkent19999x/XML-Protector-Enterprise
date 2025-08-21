#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
XML Protector Runtime - Standalone Version
Chạy độc lập, không có GUI Builder
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
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

try:
    import winreg
except ImportError:
    winreg = None

# --- SECURE CONFIG LOADING --- #
try:
    from security_manager import SecurityManager, ConfigManager
except ImportError:
    SecurityManager = None
    ConfigManager = None

# --- DEFAULT COMPANY INFO --- #
COMPANY_INFO = {
    "name": "Auto-detect",
    "mst": "Auto-detect", 
    "deployment_id": "RUNTIME",
    "version": "2.0.0"
}

# --- XML CONFIG --- #
COMPANY_CONFIG = {
    "mst_tags": ["mst", "MST", "TaxCode", "CompanyTaxCode", "taxCode"],
    "company_name_tags": ["tenNNT", "CompanyName", "TenDN", "Name", "companyName"],
    "amount_tags": ["ct27", "ct22", "ct34", "ct35", "ct36", "ct41", "ct43", "TotalAmount", "SoTien", "Amount", "TongTien", "totalAmount", "giaTriHHDV", "tongCongGiaTriHHDV"],
    "company_mst": None,
    "company_name": None,
    "min_valid_amount": 100000000,
    "max_valid_amount": 50000000000
}

# --- Thư mục lưu trữ --- #
APP_DIR = Path(os.getenv('APPDATA', Path.home())) / 'XMLProtectorRuntime'
TEMPLATES_DIR = APP_DIR / 'templates'
LOG_FILE = APP_DIR / 'xml_protector.log'

def ensure_app_dirs():
    """Tạo thư mục ứng dụng."""
    APP_DIR.mkdir(exist_ok=True)
    TEMPLATES_DIR.mkdir(exist_ok=True)

def load_deployment_info():
    """Load deployment information."""
    deployment_file = APP_DIR / 'deployment_info.json'
    if deployment_file.exists():
        try:
            with open(deployment_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return None

def load_secure_telegram_config():
    """Load secure Telegram configuration."""
    try:
        if ConfigManager:
            config_mgr = ConfigManager()
            deployment_info = load_deployment_info()
            if deployment_info:
                company_mst = deployment_info.get("company_mst", "")
                company_name = deployment_info.get("company_name", "")
                full_config = config_mgr.load_config_secure(company_mst, company_name)
                return full_config["telegram"], full_config["company_info"]
        
        # Fallback to environment variables
        bot_token = os.getenv('XML_PROTECTOR_BOT_TOKEN')
        chat_id = os.getenv('XML_PROTECTOR_CHAT_ID')
        admin_ids = os.getenv('XML_PROTECTOR_ADMIN_IDS', '').split(',')
        
        if bot_token and chat_id:
            telegram_config = {
                "bot_token": bot_token,
                "chat_id": chat_id,
                "admin_ids": [int(aid.strip()) for aid in admin_ids if aid.strip().isdigit()]
            }
            return telegram_config, COMPANY_INFO
        
        logging.warning("No secure config found, using demo mode")
        return None, COMPANY_INFO
        
    except Exception as e:
        logging.error(f"Error loading secure config: {e}")
        return None, COMPANY_INFO

def parse_xml_safely(xml_path):
    """Safely parse XML file."""
    try:
        tree = ET.parse(xml_path)
        return tree.getroot()
    except Exception as e:
        logging.error(f"Error parsing XML {xml_path}: {e}")
        return None

def setup_logging():
    """Thiết lập logging thông minh."""
    ensure_app_dirs()
    logging.basicConfig(
        level=logging.INFO,
        format='[%(asctime)s] %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(LOG_FILE, encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
    logging.info("🚀 XML Protector đang khởi động...")

class XMLProtectorRuntime:
    """XML Protector Runtime - phiên bản chạy độc lập."""
    
    def __init__(self):
        self.setup_logging()
        self.running = True
        self.observer = None
        self.templates = {}
        self.telegram_config = None
        self.company_info = None
        self.load_secure_config()
        self.load_templates()
        
    def setup_logging(self):
        """Thiết lập logging thông minh."""
        ensure_app_dirs()
        logging.basicConfig(
            level=logging.INFO,
            format='[%(asctime)s] %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(LOG_FILE, encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
        logging.info("📁 Tạo thư mục ứng dụng...")
        logging.info("🔐 Khởi tạo hệ thống bảo mật...")
        logging.info("📄 Đang load templates XML...")
    
    def load_secure_config(self):
        """Load secure configuration."""
        self.telegram_config, self.company_info = load_secure_telegram_config()
        if self.telegram_config:
            logging.info(f"Loaded secure config for company: {self.company_info.get('name', 'Unknown')}")
        else:
            logging.warning("No Telegram config available - notifications disabled")
    
    def load_templates(self):
        """Load templates từ thư mục bundled hoặc external."""
        templates_paths = [
            # Thử trong bundle (khi chạy từ EXE)
            Path(sys._MEIPASS) / 'templates' if hasattr(sys, '_MEIPASS') else None,
            # Thử thư mục local
            Path('templates'),
            # Thử thư mục app data
            TEMPLATES_DIR
        ]
        
        for template_path in templates_paths:
            if template_path and template_path.exists():
                xml_files = list(template_path.glob('*.xml'))
                if xml_files:
                    logging.info(f"Tìm thấy {len(xml_files)} template XML trong {template_path}")
                    for xml_file in xml_files:
                        self.load_single_template(xml_file)
                    break
        
        if not self.templates:
            logging.warning("⚠️ Không tìm thấy template XML nào!")
        else:
            logging.info(f"✅ Đã load thành công {len(self.templates)} template XML")
            logging.info("🛡️ Hệ thống bảo vệ đã sẵn sàng!")
    
    def load_single_template(self, xml_file):
        """Load một template XML và phân tích nội dung."""
        try:
            tree = ET.parse(xml_file)
            root = tree.getroot()
            
            # Phân tích thông tin quan trọng
            template_info = {
                'file_path': str(xml_file),
                'mst': self.extract_mst(root),
                'company_name': self.extract_company_name(root),
                'document_type': self.extract_document_type(root),
                'period': self.extract_period(root),
                'content': ET.tostring(root, encoding='unicode')
            }
            
            # Sử dụng MST làm key
            if template_info['mst']:
                self.templates[template_info['mst']] = template_info
                logging.info(f"📋 Load template: {xml_file.name} - MST: {template_info['mst']}")
                logging.info(f"   🏢 Công ty: {template_info['company_name']}")
                logging.info(f"   📅 Kỳ kê khai: {template_info['period']}")
            
        except Exception as e:
            logging.error(f"Lỗi load template {xml_file}: {e}")
    
    def extract_mst(self, root):
        """Trích xuất MST từ XML."""
        for tag in COMPANY_CONFIG["mst_tags"]:
            for elem in root.iter():
                if tag.lower() in elem.tag.lower() and elem.text:
                    return elem.text.strip()
        return None
    
    def extract_company_name(self, root):
        """Trích xuất tên công ty từ XML."""
        for tag in COMPANY_CONFIG["company_name_tags"]:
            for elem in root.iter():
                if tag.lower() in elem.tag.lower() and elem.text:
                    return elem.text.strip()
        return None
    
    def extract_document_type(self, root):
        """Trích xuất loại tài liệu."""
        # Tìm các tag thường chứa thông tin loại tài liệu
        doc_type_tags = ["LoaiToKhai", "DocumentType", "Form", "LoaiHoSo"]
        for tag in doc_type_tags:
            for elem in root.iter():
                if tag.lower() in elem.tag.lower() and elem.text:
                    return elem.text.strip()
        return None
    
    def extract_period(self, root):
        """Trích xuất kỳ kê khai."""
        period_tags = ["KyKhaiThue", "TaxPeriod", "Period", "Ky"]
        for tag in period_tags:
            for elem in root.iter():
                if tag.lower() in elem.tag.lower() and elem.text:
                    return elem.text.strip()
        return None
    
    def should_protect_file(self, xml_path):
        """Kiểm tra xem file XML có cần bảo vệ không."""
        try:
            tree = ET.parse(xml_path)
            root = tree.getroot()
            
            file_mst = self.extract_mst(root)
            if not file_mst:
                return False, None
            
            # Kiểm tra xem MST có trong templates không
            if file_mst in self.templates:
                template = self.templates[file_mst]
                
                # So sánh thông tin chi tiết
                file_company = self.extract_company_name(root)
                file_doc_type = self.extract_document_type(root)
                file_period = self.extract_period(root)
                
                # Nếu trùng MST và các thông tin khác
                if (file_company == template['company_name'] and 
                    file_doc_type == template['document_type'] and
                    file_period == template['period']):
                    return True, template
            
            return False, None
            
        except Exception as e:
            logging.error(f"Lỗi phân tích file {xml_path}: {e}")
            return False, None
    
    def overwrite_with_template(self, xml_path, template):
        """Ghi đè file với template gốc."""
        start_time = time.time()
        try:
            logging.info(f"🛡️ Bắt đầu bảo vệ file: {Path(xml_path).name}")
            
            # Backup file gốc
            backup_start = time.time()
            backup_path = str(xml_path) + f'.backup.{int(time.time())}'
            shutil.copy2(xml_path, backup_path)
            backup_time = (time.time() - backup_start) * 1000
            logging.info(f"💾 Tạo backup: {backup_time:.1f}ms")
            
            # Ghi đè với nội dung template
            overwrite_start = time.time()
            with open(xml_path, 'w', encoding='utf-8') as f:
                f.write(template['content'])
            overwrite_time = (time.time() - overwrite_start) * 1000
            logging.info(f"🔄 Ghi đè hoàn thành: {overwrite_time:.1f}ms")
            
            # Tính tổng thời gian
            total_time = (time.time() - start_time) * 1000
            logging.info(f"✅ BẢO VỆ THÀNH CÔNG! (Tổng: {total_time:.1f}ms)")
            
            # Gửi thông báo Telegram
            self.send_protection_alert(xml_path, template)
            
        except Exception as e:
            logging.error(f"❌ Lỗi ghi đè file {xml_path}: {e}")
    
    def send_protection_alert(self, xml_path, template):
        """Gửi cảnh báo bảo vệ qua Telegram."""
        try:
            message = f"""
🛡️ **XML PROTECTION ALERT**

📄 **File:** `{Path(xml_path).name}`
🏢 **MST:** `{template['mst']}`
🏭 **Công ty:** `{template['company_name']}`
📋 **Loại:** `{template['document_type']}`
📅 **Kỳ:** `{template['period']}`
🕐 **Thời gian:** `{time.strftime('%Y-%m-%d %H:%M:%S')}`

✅ File đã được ghi đè với template gốc!
"""
            
            self.send_telegram_message(message)
            
        except Exception as e:
            logging.error(f"Lỗi gửi Telegram alert: {e}")
    
    def send_telegram_message(self, message):
        """Gửi message qua Telegram."""
        if not self.telegram_config:
            logging.warning("No Telegram config - message not sent")
            return
            
        try:
            url = f"https://api.telegram.org/bot{self.telegram_config['bot_token']}/sendMessage"
            data = {
                "chat_id": self.telegram_config['chat_id'],
                "text": message,
                "parse_mode": "Markdown"
            }
            
            response = requests.post(url, data=data, timeout=10)
            if response.status_code == 200:
                logging.info("Đã gửi Telegram alert")
            else:
                logging.error(f"Lỗi gửi Telegram: {response.status_code}")
                
        except Exception as e:
            logging.error(f"Lỗi gửi Telegram: {e}")

class XMLFileHandler(FileSystemEventHandler):
    """Handler xử lý sự kiện file XML."""
    
    def __init__(self, protector):
        self.protector = protector
    
    def on_created(self, event):
        """Xử lý khi file mới được tạo."""
        if not event.is_directory and event.src_path.endswith('.xml'):
            time.sleep(1)  # Đợi file được ghi xong
            self.check_and_protect(event.src_path)
    
    def on_modified(self, event):
        """Xử lý khi file được sửa đổi."""
        if not event.is_directory and event.src_path.endswith('.xml'):
            time.sleep(1)  # Đợi file được ghi xong
            self.check_and_protect(event.src_path)
    
    def check_and_protect(self, xml_path):
        """Kiểm tra và bảo vệ file XML."""
        should_protect, template = self.protector.should_protect_file(xml_path)
        if should_protect:
            logging.info(f"🚨 PHÁT HIỆN FILE GIẢ MẠO: {Path(xml_path).name}")
            logging.info(f"📍 Đường dẫn: {xml_path}")
            logging.info(f"🔍 Template khớp: {template.get('mst', 'Unknown')}")
            self.protector.overwrite_with_template(xml_path, template)
        else:
            logging.debug(f"📄 File {Path(xml_path).name} không cần bảo vệ")

def main():
    """Hàm chính."""
    print("🚀 XML Protector đang khởi động...")
    print("=" * 50)
    
    # Khởi tạo protector
    protector = XMLProtectorRuntime()
    
    if not protector.templates:
        print("❌ Không có template XML nào! Thoát chương trình.")
        return
    
    print(f"✅ Đã load {len(protector.templates)} template XML")
    print("🛡️ Hệ thống bảo vệ đã sẵn sàng!")
    print("=" * 50)
    
    # Khởi động file monitoring
    event_handler = XMLFileHandler(protector)
    observer = Observer()
    
    # Monitor tất cả ổ đĩa
    drives = ['C:\\', 'D:\\', 'E:\\']
    print("📁 Đang thiết lập file monitoring...")
    for drive in drives:
        if os.path.exists(drive):
            observer.schedule(event_handler, drive, recursive=True)
            print(f"   📂 Monitor: {drive}")
    
    observer.start()
    protector.observer = observer
    
    print("✅ XML Protector đã sẵn sàng!")
    print("🛡️ Đang bảo vệ các file XML...")
    print("=" * 50)
    print("💡 Nhấn Ctrl+C để tắt chương trình")
    print("=" * 50)
    
    try:
        while protector.running:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n⏹️ Đang tắt XML Protector...")
        protector.running = False
        observer.stop()
    
    observer.join()
    print("✅ XML Protector đã tắt!")
    print("👋 Cảm ơn bạn đã sử dụng!")

if __name__ == '__main__':
    main()
