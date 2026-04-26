#!/usr/bin/env python3
# dependency_checker.py - فحص وتثبيت الاعتماديات المفقودة

import subprocess
import sys
import importlib
import logging
import argparse

class DependencyChecker:
    def __init__(self):
        self.setup_logging()
        self.required_packages = {
            'flask': 'flask',
            'requests': 'requests',
            'psutil': 'psutil',
            'flask_socketio': 'flask-socketio',
            'flask_limiter': 'flask-limiter',
            'flask_cors': 'flask-cors',
            'aiohttp': 'aiohttp',
            'fastapi': 'fastapi',
            'uvicorn': 'uvicorn',
            'pydantic': 'pydantic',
            'redis': 'redis',
            'GPUtil': 'gputil'
        }
        
        self.optional_packages = {
            'opencv': 'opencv-python',
            'zeroconf': 'zeroconf',
            'torch': 'torch'
        }
    
    def setup_logging(self):
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger('DependencyChecker')
    
    def is_package_installed(self, package_name: str) -> bool:
        """التحقق إذا كانت الحزمة مثبتة"""
        try:
            importlib.import_module(package_name)
            return True
        except ImportError:
            return False
    
    def install_package(self, package_name: str, pip_name: str = None):
        """تثبيت حزمة"""
        if pip_name is None:
            pip_name = package_name
        
        try:
            self.logger.info(f"📦 جاري تثبيت {package_name}...")
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', pip_name])
            self.logger.info(f"✅ تم تثبيت {package_name} بنجاح")
            return True
        except subprocess.CalledProcessError as e:
            self.logger.error(f"❌ فشل تثبيت {package_name}: {e}")
            return False
    
    def check_and_install_dependencies(self):
        """فحص وتثبيت الاعتماديات المفقودة"""
        self.logger.info("🔍 فحص الاعتماديات...")
        
        missing_required = []
        missing_optional = []
        
        # فحص الاعتماديات الأساسية
        for package, pip_name in self.required_packages.items():
            if not self.is_package_installed(package):
                missing_required.append((package, pip_name))
        
        # فحص الاعتماديات الاختيارية
        for package, pip_name in self.optional_packages.items():
            if not self.is_package_installed(package):
                missing_optional.append((package, pip_name))
        
        # عرض النتائج
        if not missing_required and not missing_optional:
            self.logger.info("✅ جميع الاعتماديات مثبتة!")
            return True
        
        # تثبيت الاعتماديات الأساسية المفقودة
        if missing_required:
            self.logger.warning(f"⚠️ الاعتماديات الأساسية المفقودة: {[p[0] for p in missing_required]}")
            
            for package, pip_name in missing_required:
                if not self.install_package(package, pip_name):
                    self.logger.error(f"❌ لا يمكن المتابعة بدون {package}")
                    return False
        
        # الإبلاغ عن الاعتماديات الاختيارية المفقودة
        if missing_optional:
            self.logger.info(f"💡 الاعتماديات الاختيارية المفقودة: {[p[0] for p in missing_optional]}")
            install_optional = input("هل تريد تثبيت الاعتماديات الاختيارية؟ (y/n): ").lower().strip()
            if install_optional == 'y':
                for package, pip_name in missing_optional:
                    self.install_package(package, pip_name)
        
        self.logger.info("✅ جميع الاعتماديات الأساسية جاهزة")
        return True
    
    def create_requirements_file(self):
        """إنشاء ملف متطلبات"""
        requirements = list(self.required_packages.values()) + list(self.optional_packages.values())
        with open('requirements.txt', 'w', encoding='utf-8') as f:
            for req in requirements:
                f.write(f"{req}\n")
        self.logger.info("✅ تم إنشاء ملف requirements.txt")
    
    def create_fallback_module(self):
        """إنشاء وحدات بديلة للاعتماديات المفقودة"""
        fallback_code = '''
# fallback_modules.py - وحدات بديلة للاعتماديات المفقودة
import time
import math
import random

class FakeNumpy:
    """محاكاة numpy الأساسية"""
    @staticmethod
    def random.rand(size):
        if isinstance(size, int):
            return [random.random() for _ in range(size)]
        elif isinstance(size, tuple):
            return [[random.random() for _ in range(size[1])] for _ in range(size[0])]
    
    @staticmethod
    def dot(a, b):
        if isinstance(a[0], list) and isinstance(b[0], list):
            # ضرب مصفوفات
            result = []
            for i in range(len(a)):
                row = []
                for j in range(len(b[0])):
                    sum_val = 0
                    for k in range(len(b)):
                        sum_val += a[i][k] * b[k][j]
                    row.append(sum_val)
                result.append(row)
            return result
        else:
            return sum(x * y for x, y in zip(a, b))
    
    @staticmethod
    def mean(data):
        return sum(data) / len(data)
    
    @staticmethod
    def std(data):
        mean_val = sum(data) / len(data)
        variance = sum((x - mean_val) ** 2 for x in data) / len(data)
        return math.sqrt(variance)

# استبدال الوحدات المفقودة
try:
    import numpy as np
except ImportError:
    np = FakeNumpy()

try:
    import psutil
except ImportError:
    class FakePsutil:
        @staticmethod
        def cpu_percent():
            return 0.0
        @staticmethod
        def virtual_memory():
            class Memory: percent = 0.0
            return Memory()
        @staticmethod
        def disk_usage(path):
            class Disk: percent = 0.0
            return Disk()
    psutil = FakePsutil()
'''
        
        with open('fallback_modules.py', 'w', encoding='utf-8') as f:
            f.write(fallback_code)
        self.logger.info("✅ تم إنشاء وحدات بديلة")

def main():
    parser = argparse.ArgumentParser(description='فحص وتثبيت اعتماديات النظام الموزع')
    parser.add_argument('--check', action='store_true', help='فحص الاعتماديات فقط بدون تثبيت')
    parser.add_argument('--install', action='store_true', help='تثبيت الاعتماديات المفقودة')
    parser.add_argument('--create-requirements', action='store_true', help='إنشاء ملف المتطلبات')
    
    args = parser.parse_args()
    
    checker = DependencyChecker()
    
    if args.create_requirements:
        checker.create_requirements_file()
        return
    
    if args.check:
        # فحص فقط
        checker.check_and_install_dependencies()
    elif args.install:
        # تثبيت تلقائي
        success = checker.check_and_install_dependencies()
        if success:
            checker.create_fallback_module()
            checker.create_requirements_file()
    else:
        # الوضع التفاعلي
        print("🚀 مدقق اعتماديات النظام الموزع")
        print("=" * 40)
        
        success = checker.check_and_install_dependencies()
        
        if success:
            print("\n✅ تم فحص الاعتماديات بنجاح!")
            print("📋 يمكنك الآن تشغيل التطبيقات الأخرى:")
            print("   python central_manager.py")
            print("   python dashboard.py")
            print("   python peer_node.py")
            
            create_fallback = input("\nهل تريد إنشاء وحدات بديلة؟ (y/n): ").lower().strip()
            if create_fallback == 'y':
                checker.create_fallback_module()
            
            create_req = input("هل تريد إنشاء ملف المتطلبات؟ (y/n): ").lower().strip()
            if create_req == 'y':
                checker.create_requirements_file()
        else:
            print("\n❌ فشل في تثبيت بعض الاعتماديات الأساسية")
            print("💡 حاول تشغيل الأمر: pip install -r requirements.txt")

if __name__ == "__main__":
    main()
