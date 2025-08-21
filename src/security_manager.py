#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
XML Protector Security Manager
Quản lý mã hóa, xác thực và bảo mật
"""

import os
import sys
import json
import uuid
import hashlib
import platform
import base64
from datetime import datetime, timedelta
from pathlib import Path
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

class SecurityManager:
    """Quản lý bảo mật tổng thể."""
    
    def __init__(self):
        self.app_dir = Path(os.getenv('APPDATA', Path.home())) / 'XMLProtectorRuntime'
        self.app_dir.mkdir(parents=True, exist_ok=True)
        self.config_file = self.app_dir / 'secure_config.enc'
        self.machine_id = self.get_machine_id()
    
    def get_machine_id(self):
        """Tạo Machine ID unique cho từng máy."""
        try:
            # Kết hợp nhiều thông tin để tạo ID unique
            machine_info = f"{platform.node()}-{platform.system()}-{platform.release()}"
            
            # Thêm MAC address nếu có
            try:
                import uuid
                mac = ':'.join(['{:02x}'.format((uuid.getnode() >> ele) & 0xff) 
                               for ele in range(0,8*6,8)][::-1])
                machine_info += f"-{mac}"
            except:
                pass
                
            # Hash để tạo ID ngắn gọn
            machine_hash = hashlib.sha256(machine_info.encode()).hexdigest()[:16]
            return machine_hash.upper()
        except:
            # Fallback: Random UUID
            return str(uuid.uuid4())[:16].upper()
    
    def generate_company_key(self, company_mst, company_name=""):
        """Tạo encryption key riêng cho từng công ty."""
        # Kết hợp MST + tên DN + machine ID
        key_material = f"{company_mst}-{company_name}-{self.machine_id}"
        
        # Derive key từ PBKDF2
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b'xml_protector_salt_2025',
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(key_material.encode()))
        return key
    
    def encrypt_config(self, config_data, company_mst, company_name=""):
        """Mã hóa config với company-specific key."""
        try:
            key = self.generate_company_key(company_mst, company_name)
            f = Fernet(key)
            
            # Thêm metadata
            secure_config = {
                "encrypted_data": config_data,
                "company_mst": company_mst,
                "company_name": company_name,
                "machine_id": self.machine_id,
                "created_at": datetime.now().isoformat(),
                "expires_at": (datetime.now() + timedelta(days=365)).isoformat()
            }
            
            # Mã hóa toàn bộ
            config_json = json.dumps(secure_config, ensure_ascii=False)
            encrypted = f.encrypt(config_json.encode())
            
            return base64.urlsafe_b64encode(encrypted).decode()
            
        except Exception as e:
            raise Exception(f"❌ Lỗi mã hóa config: {e}")
    
    def decrypt_config(self, encrypted_config, company_mst, company_name=""):
        """Giải mã config."""
        try:
            key = self.generate_company_key(company_mst, company_name)
            f = Fernet(key)
            
            # Decode và decrypt
            encrypted_bytes = base64.urlsafe_b64decode(encrypted_config.encode())
            decrypted = f.decrypt(encrypted_bytes)
            
            secure_config = json.loads(decrypted.decode())
            
            # Kiểm tra expires
            expires_at = datetime.fromisoformat(secure_config["expires_at"])
            if datetime.now() > expires_at:
                raise Exception("⏰ Config đã hết hạn!")
            
            # Kiểm tra machine ID
            if secure_config.get("machine_id") != self.machine_id:
                raise Exception("🚫 Config không phù hợp với máy này!")
            
            return secure_config["encrypted_data"]
            
        except Exception as e:
            raise Exception(f"❌ Lỗi giải mã config: {e}")
    
    def save_secure_config(self, config_data, company_mst, company_name=""):
        """Lưu config mã hóa vào file."""
        try:
            encrypted_config = self.encrypt_config(config_data, company_mst, company_name)
            
            with open(self.config_file, 'w', encoding='utf-8') as f:
                f.write(encrypted_config)
                
            return True
        except Exception as e:
            print(f"❌ Lỗi lưu config: {e}")
            return False
    
    def load_secure_config(self, company_mst, company_name=""):
        """Load config mã hóa từ file."""
        try:
            if not self.config_file.exists():
                raise Exception("📄 Không tìm thấy config file!")
            
            with open(self.config_file, 'r', encoding='utf-8') as f:
                encrypted_config = f.read().strip()
            
            return self.decrypt_config(encrypted_config, company_mst, company_name)
            
        except Exception as e:
            raise Exception(f"❌ Lỗi load config: {e}")
    
    def generate_bot_token_hash(self, bot_token):
        """Tạo hash để verify bot token mà không lưu plaintext."""
        return hashlib.sha256(f"{bot_token}-{self.machine_id}".encode()).hexdigest()
    
    def validate_admin_access(self, user_id, admin_ids_list):
        """Validate admin access với time-based restrictions."""
        try:
            if user_id not in admin_ids_list:
                return False, "❌ User ID không có quyền admin!"
            
            # Thêm time-based validation nếu cần
            current_hour = datetime.now().hour
            if current_hour < 6 or current_hour > 22:
                return False, "⏰ Ngoài giờ làm việc (6:00-22:00)!"
                
            return True, "✅ Admin access hợp lệ"
            
        except Exception as e:
            return False, f"❌ Lỗi validate admin: {e}"
    
    def create_deployment_package(self, company_config):
        """Tạo package deployment an toàn cho từng công ty."""
        try:
            # Tạo unique deployment ID
            deployment_id = str(uuid.uuid4())[:8].upper()
            
            # Encrypt config
            encrypted_config = self.encrypt_config(
                company_config["telegram_config"],
                company_config["company_mst"],
                company_config["company_name"]
            )
            
            # Package info
            deployment_package = {
                "deployment_id": deployment_id,
                "company_mst": company_config["company_mst"],
                "company_name": company_config["company_name"],
                "encrypted_config": encrypted_config,
                "templates_count": len(company_config.get("templates", [])),
                "created_at": datetime.now().isoformat(),
                "expires_at": (datetime.now() + timedelta(days=30)).isoformat(),
                "version": "2.0.0-secure"
            }
            
            return deployment_package
            
        except Exception as e:
            raise Exception(f"❌ Lỗi tạo deployment package: {e}")
    
    def verify_deployment_package(self, deployment_package):
        """Verify deployment package trước khi sử dụng."""
        try:
            # Kiểm tra expiry
            expires_at = datetime.fromisoformat(deployment_package["expires_at"])
            if datetime.now() > expires_at:
                return False, "⏰ Package đã hết hạn!"
            
            # Kiểm tra required fields
            required_fields = ["deployment_id", "company_mst", "encrypted_config"]
            for field in required_fields:
                if field not in deployment_package:
                    return False, f"❌ Thiếu field: {field}"
            
            return True, "✅ Package hợp lệ"
            
        except Exception as e:
            return False, f"❌ Lỗi verify package: {e}"

class ConfigManager:
    """Quản lý config an toàn."""
    
    def __init__(self):
        self.security = SecurityManager()
        self.default_config_template = {
            "telegram": {
                "bot_token": "",
                "chat_id": "",
                "admin_ids": []
            },
            "company_info": {
                "mst": "",
                "name": "",
                "deployment_id": ""
            },
            "xml_protection": {
                "min_valid_amount": 100000000,
                "max_valid_amount": 50000000000,
                "monitor_all_drives": True,
                "auto_backup": True
            },
            "security_settings": {
                "auto_update": True,
                "remote_control_enabled": True,
                "audit_logging": True,
                "working_hours_only": False
            }
        }
    
    def create_company_config(self, bot_token, chat_id, admin_ids, company_mst, company_name):
        """Tạo config mới cho công ty."""
        try:
            config = self.default_config_template.copy()
            
            # Fill telegram info
            config["telegram"]["bot_token"] = bot_token
            config["telegram"]["chat_id"] = chat_id
            config["telegram"]["admin_ids"] = admin_ids
            
            # Fill company info
            config["company_info"]["mst"] = company_mst
            config["company_info"]["name"] = company_name
            config["company_info"]["deployment_id"] = str(uuid.uuid4())[:8].upper()
            
            return config
            
        except Exception as e:
            raise Exception(f"❌ Lỗi tạo config: {e}")
    
    def save_config_secure(self, config):
        """Lưu config với mã hóa."""
        try:
            company_mst = config["company_info"]["mst"]
            company_name = config["company_info"]["name"]
            
            return self.security.save_secure_config(config, company_mst, company_name)
            
        except Exception as e:
            print(f"❌ Lỗi lưu config: {e}")
            return False
    
    def load_config_secure(self, company_mst, company_name):
        """Load config với giải mã."""
        try:
            return self.security.load_secure_config(company_mst, company_name)
        except Exception as e:
            # Fallback to environment variables
            return self.load_from_environment()
    
    def load_from_environment(self):
        """Load từ environment variables như fallback."""
        try:
            config = self.default_config_template.copy()
            
            # Load từ env vars
            config["telegram"]["bot_token"] = os.getenv("XML_PROTECTOR_BOT_TOKEN", "")
            config["telegram"]["chat_id"] = os.getenv("XML_PROTECTOR_CHAT_ID", "")
            
            admin_ids_str = os.getenv("XML_PROTECTOR_ADMIN_IDS", "")
            if admin_ids_str:
                config["telegram"]["admin_ids"] = [int(x.strip()) for x in admin_ids_str.split(",")]
            
            config["company_info"]["mst"] = os.getenv("XML_PROTECTOR_COMPANY_MST", "")
            config["company_info"]["name"] = os.getenv("XML_PROTECTOR_COMPANY_NAME", "")
            
            if not config["telegram"]["bot_token"]:
                raise Exception("❌ Không tìm thấy bot token trong environment variables!")
            
            return config
            
        except Exception as e:
            raise Exception(f"❌ Lỗi load từ environment: {e}")

# Test security system
if __name__ == '__main__':
    print("🔒 Testing XML Protector Security Manager...")
    
    security = SecurityManager()
    config_mgr = ConfigManager()
    
    # Test tạo config mã hóa
    test_config = config_mgr.create_company_config(
        bot_token="TEST_TOKEN_123",
        chat_id="-1234567890",
        admin_ids=[123456789],
        company_mst="0123456789",
        company_name="Công ty Test TNHH"
    )
    
    print(f"✅ Machine ID: {security.machine_id}")
    print(f"✅ Test config tạo thành công")
    
    # Test save/load
    if config_mgr.save_config_secure(test_config):
        print("✅ Save config mã hóa thành công")
        
        # Test load
        loaded_config = config_mgr.load_config_secure("0123456789", "Công ty Test TNHH")
        print("✅ Load config mã hóa thành công")
        print(f"✅ Bot Token: {loaded_config['telegram']['bot_token'][:10]}...")
    else:
        print("❌ Save config thất bại")