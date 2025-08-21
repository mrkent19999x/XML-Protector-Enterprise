#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
XML Protector Simple Test Script
Basic functionality testing
"""

import os
import sys
from pathlib import Path

def main():
    print("=" * 60)
    print("XML PROTECTOR ENTERPRISE - SIMPLE TEST")
    print("=" * 60)
    
    # Add src to path
    project_root = Path(__file__).parent.parent
    src_dir = project_root / "src"
    admin_dir = project_root / "admin"
    
    sys.path.insert(0, str(src_dir))
    sys.path.insert(0, str(admin_dir))
    
    tests_passed = 0
    total_tests = 0
    
    # Test 1: Security Manager
    print("\n[TEST 1] Security Manager...")
    total_tests += 1
    try:
        from security_manager import SecurityManager, ConfigManager
        security = SecurityManager()
        print(f"[OK] Machine ID: {security.machine_id}")
        tests_passed += 1
    except Exception as e:
        print(f"[FAIL] {e}")
    
    # Test 2: Monitoring System  
    print("\n[TEST 2] Monitoring System...")
    total_tests += 1
    try:
        from monitoring_system import AdvancedMonitoringSystem
        monitoring = AdvancedMonitoringSystem()
        monitoring.record_security_event("test", "info", "test_client", "Test event")
        print("[OK] Monitoring system functional")
        tests_passed += 1
    except Exception as e:
        print(f"[FAIL] {e}")
    
    # Test 3: Runtime Components
    print("\n[TEST 3] Runtime Components...")
    total_tests += 1
    try:
        # Set demo environment for testing
        os.environ['XML_PROTECTOR_BOT_TOKEN'] = 'demo_token'
        os.environ['XML_PROTECTOR_CHAT_ID'] = '-1234567890'
        os.environ['XML_PROTECTOR_ADMIN_IDS'] = '123456789'
        
        from xml_protector_runtime import COMPANY_INFO
        print(f"[OK] Runtime loaded - Company: {COMPANY_INFO.get('name', 'Unknown')}")
        tests_passed += 1
    except Exception as e:
        print(f"[FAIL] {e}")
    
    # Test 4: Builder Components
    print("\n[TEST 4] Builder Components...")
    total_tests += 1
    try:
        # Only test import, not GUI
        import xml_protector_builder
        print("[OK] Builder components available")
        tests_passed += 1
    except Exception as e:
        print(f"[FAIL] {e}")
    
    # Test 5: Admin Bot
    print("\n[TEST 5] Admin Bot Components...")
    total_tests += 1
    try:
        from admin_bot import AdminBot
        # Create instance without starting
        bot = AdminBot()
        menu = bot.create_main_menu()
        print(f"[OK] Admin bot ready with {len(menu['inline_keyboard'])} menu sections")
        tests_passed += 1
    except Exception as e:
        print(f"[FAIL] {e}")
    
    # Test 6: XML Processing
    print("\n[TEST 6] XML Processing...")
    total_tests += 1
    try:
        from xml_protector_runtime import parse_xml_safely
        templates_dir = project_root / "templates"
        xml_files = list(templates_dir.glob("*.xml"))
        
        if xml_files:
            sample_xml = xml_files[0]
            root = parse_xml_safely(str(sample_xml))
            if root is not None:
                print(f"[OK] XML parsing works - tested {sample_xml.name}")
                tests_passed += 1
            else:
                print(f"[FAIL] Could not parse {sample_xml.name}")
        else:
            print("[FAIL] No XML templates found")
    except Exception as e:
        print(f"[FAIL] {e}")
    
    # Results
    print("\n" + "=" * 60)
    print("TEST RESULTS")
    print("=" * 60)
    print(f"Passed: {tests_passed}/{total_tests}")
    print(f"Success Rate: {(tests_passed/total_tests)*100:.1f}%")
    
    if tests_passed == total_tests:
        print("\n[SUCCESS] All tests passed! System ready for use.")
        print("\nNext steps:")
        print("1. Set real Telegram credentials:")
        print("   set XML_PROTECTOR_BOT_TOKEN=your_real_token")
        print("   set XML_PROTECTOR_CHAT_ID=your_real_chat_id")
        print("   set XML_PROTECTOR_ADMIN_IDS=your_admin_id")
        print("2. Run GUI Builder: python src/xml_protector_builder.py")
        print("3. Run Admin Bot: python admin/admin_bot.py")
        return True
    else:
        print(f"\n[WARNING] {total_tests - tests_passed} tests failed.")
        print("Please check the failed components before proceeding.")
        return False

if __name__ == '__main__':
    try:
        success = main()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\nFATAL ERROR: {e}")
        sys.exit(1)