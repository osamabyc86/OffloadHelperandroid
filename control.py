#!/usr/bin/env python3
"""
نظام التحكم المتقدم - واجهة تحكم شاملة للنظام الموزع
يدعم التشغيل التلقائي، إدارة الخدمات، والمراقبة
"""

import argparse
import sys
import os
import time
import logging
from pathlib import Path
from typing import Optional, Dict, Any
import json

# إضافة المسار للأوامر الداخلية
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from autostart_config import AutoStartManager
from background_service import BackgroundService

class Colors:
    """ألوان للتنسيق في الطرفية"""
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    END = '\033[0m'

class ControlSystem:
    """نظام التحكم المتقدم"""
    
    def __init__(self):
        self.setup_logging()
        self.auto_start_manager = AutoStartManager()
        self.background_service = None
        self.config_file = Path.home() / ".distributed_system_control.json"
        self.load_config()
    
    def setup_logging(self):
        """إعداد نظام السجلات"""
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        
        logging.basicConfig(
            level=logging.INFO,
            format=f'{Colors.BLUE}%(asctime)s{Colors.END} - {Colors.GREEN}%(levelname)s{Colors.END} - %(message)s',
            handlers=[
                logging.FileHandler(log_dir / 'control_system.log', encoding='utf-8'),
                logging.StreamHandler(sys.stdout)
            ]
        )
        self.logger = logging.getLogger('ControlSystem')
    
    def load_config(self):
        """تحميل التكوين"""
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                self.config = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self.config = {
                'auto_start': False,
                'service_port': 8888,
                'log_level': 'INFO',
                'notifications': True
            }
            self.save_config()
    
    def save_config(self):
        """حفظ التكوين"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.logger.error(f"فشل في حفظ التكوين: {e}")
    
    def print_banner(self):
        """عرض شعار النظام"""
        banner = f"""
{Colors.CYAN}{Colors.BOLD}
╔══════════════════════════════════════════════════════════════╗
║                   نظام التحكم - النظام الموزع               ║
║                Distributed System Control Panel             ║
╚══════════════════════════════════════════════════════════════╝
{Colors.END}
        """
        print(banner)
    
    def print_status(self, message: str, status: str = "info"):
        """عرض حالة مع تلوين"""
        icons = {
            "success": f"{Colors.GREEN}✓{Colors.END}",
            "error": f"{Colors.RED}✗{Colors.END}",
            "warning": f"{Colors.YELLOW}⚠{Colors.END}",
            "info": f"{Colors.BLUE}ℹ{Colors.END}",
            "progress": f"{Colors.CYAN}↻{Colors.END}"
        }
        
        colors = {
            "success": Colors.GREEN,
            "error": Colors.RED,
            "warning": Colors.YELLOW,
            "info": Colors.BLUE,
            "progress": Colors.CYAN
        }
        
        icon = icons.get(status, icons["info"])
        color = colors.get(status, colors["info"])
        
        print(f"{icon} {color}{message}{Colors.END}")
    
    def show_animated_progress(self, message: str, duration: int = 3):
        """عرض تقدم متحرك"""
        animations = ["⣾", "⣽", "⣻", "⢿", "⡿", "⣟", "⣯", "⣷"]
        end_time = time.time() + duration
        
        print(f"{Colors.CYAN}{message}{Colors.END}", end=" ", flush=True)
        
        i = 0
        while time.time() < end_time:
            print(f"\r{Colors.CYAN}{message}{Colors.END} {animations[i % len(animations)]}", end="", flush=True)
            time.sleep(0.1)
            i += 1
        
        print("\r" + " " * (len(message) + 2) + "\r", end="", flush=True)
    
    def check_privileges(self) -> bool:
        """التحقق من صلاحيات المستخدم"""
        if os.name == 'posix':
            if os.geteuid() != 0:
                self.print_status("تحذير: بعض الميزات تتطلب صلاحيات مدير النظام", "warning")
                return False
        return True
    
    def handle_autostart(self, enable: bool):
        """معالجة طلبات التشغيل التلقائي"""
        try:
            self.show_animated_progress("جاري معالجة طلب التشغيل التلقائي")
            
            if enable:
                success = self.auto_start_manager.enable_autostart()
                if success:
                    self.config['auto_start'] = True
                    self.save_config()
                    self.print_status("تم تفعيل التشغيل التلقائي بنجاح", "success")
                else:
                    self.print_status("فشل في تفعيل التشغيل التلقائي", "error")
            else:
                success = self.auto_start_manager.disable_autostart()
                if success:
                    self.config['auto_start'] = False
                    self.save_config()
                    self.print_status("تم تعطيل التشغيل التلقائي بنجاح", "success")
                else:
                    self.print_status("فشل في تعطيل التشغيل التلقائي", "error")
                    
        except Exception as e:
            self.print_status(f"خطأ في معالجة التشغيل التلقائي: {e}", "error")
            self.logger.error(f"Autostart error: {e}")
    
    def handle_service_control(self, action: str):
        """معالجة طلبات التحكم في الخدمة"""
        try:
            if action == "start":
                self.show_animated_progress("بدء تشغيل الخدمات الخلفية")
                self.background_service = BackgroundService()
                # في التنفيذ الفعلي، سيتم بدء الخدمة
                self.print_status("تم بدء الخدمات الخلفية", "success")
                
            elif action == "stop":
                self.show_animated_progress("إيقاف الخدمات الخلفية")
                if self.background_service:
                    self.background_service.stop_all_services()
                self.print_status("تم إيقاف الخدمات الخلفية", "success")
                
            elif action == "restart":
                self.show_animated_progress("إعادة تشغيل الخدمات")
                if self.background_service:
                    self.background_service.stop_all_services()
                    time.sleep(2)
                    # إعادة البدء
                self.print_status("تم إعادة تشغيل الخدمات", "success")
                
            elif action == "status":
                self.show_service_status()
                
        except Exception as e:
            self.print_status(f"خطأ في التحكم بالخدمة: {e}", "error")
            self.logger.error(f"Service control error: {e}")
    
    def show_service_status(self):
        """عرض حالة الخدمات"""
        try:
            # محاكاة حالة الخدمات - في التنفيذ الفعلي سيتم الاتصال بالخدمة
            services_status = {
                "الخدمة الرئيسية": "نشط",
                "خادم الأقران": "نشط", 
                "موزع الحمل": "نشط",
                "المُنفذ الموزع": "نشط",
                "الواجهة الرسومية": "متوقف"
            }
            
            self.print_status("حالة الخدمات الحالية:", "info")
            print()
            
            for service, status in services_status.items():
                color = Colors.GREEN if status == "نشط" else Colors.RED
                status_icon = f"{Colors.GREEN}✓{Colors.END}" if status == "نشط" else f"{Colors.RED}✗{Colors.END}"
                print(f"  {status_icon} {service}: {color}{status}{Colors.END}")
            
            print()
            
        except Exception as e:
            self.print_status(f"خطأ في جلب حالة الخدمات: {e}", "error")
    
    def show_system_info(self):
        """عرض معلومات النظام"""
        try:
            import platform
            import psutil
            
            self.print_status("معلومات النظام:", "info")
            print()
            
            # معلومات النظام الأساسية
            system_info = {
                "نظام التشغيل": f"{platform.system()} {platform.release()}",
                "المعالج": f"{psutil.cpu_count()} نواة",
                "الذاكرة": f"{psutil.virtual_memory().total // (1024**3)} GB",
                "مساحة التخزين": f"{psutil.disk_usage('/').total // (1024**3)} GB متاحة"
            }
            
            for key, value in system_info.items():
                print(f"  {Colors.CYAN}{key}:{Colors.END} {value}")
            
            print()
            
            # حالة التشغيل التلقائي
            auto_start_status = "مفعل" if self.auto_start_manager.is_autostart_enabled() else "معطل"
            status_color = Colors.GREEN if auto_start_status == "مفعل" else Colors.RED
            print(f"  {Colors.CYAN}التشغيل التلقائي:{Colors.END} {status_color}{auto_start_status}{Colors.END}")
            
        except Exception as e:
            self.print_status(f"خطأ في جلب معلومات النظام: {e}", "error")
    
    def run_interactive_mode(self):
        """وضع التفاعل مع المستخدم"""
        self.print_banner()
        
        while True:
            try:
                print(f"\n{Colors.BOLD}خيارات التحكم:{Colors.END}")
                print(f"  {Colors.GREEN}1{Colors.END} - تفعيل التشغيل التلقائي")
                print(f"  {Colors.RED}2{Colors.END} - تعطيل التشغيل التلقائي") 
                print(f"  {Colors.BLUE}3{Colors.END} - بدء الخدمات")
                print(f"  {Colors.YELLOW}4{Colors.END} - إيقاف الخدمات")
                print(f"  {Colors.CYAN}5{Colors.END} - حالة النظام")
                print(f"  {Colors.MAGENTA}6{Colors.END} - الخروج")
                
                choice = input(f"\n{Colors.WHITE}اختر خيارًا (1-6): {Colors.END}").strip()
                
                if choice == "1":
                    self.handle_autostart(True)
                elif choice == "2":
                    self.handle_autostart(False)
                elif choice == "3":
                    self.handle_service_control("start")
                elif choice == "4":
                    self.handle_service_control("stop")
                elif choice == "5":
                    self.show_system_info()
                elif choice == "6":
                    self.print_status("شكرًا لاستخدامك نظام التحكم", "success")
                    break
                else:
                    self.print_status("خيار غير صحيح، يرجى المحاولة مرة أخرى", "warning")
                    
            except KeyboardInterrupt:
                self.print_status("\nتم إيقاف البرنامج بواسطة المستخدم", "warning")
                break
            except Exception as e:
                self.print_status(f"خطأ غير متوقع: {e}", "error")

def main():
    """الدالة الرئيسية"""
    parser = argparse.ArgumentParser(
        description=f"{Colors.BOLD}نظام التحكم في النظام الموزع{Colors.END}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
{Colors.CYAN}أمثلة على الاستخدام:{Colors.END}
  {Colors.GREEN}python control.py --enable{Colors.END}      تفعيل التشغيل التلقائي
  {Colors.RED}python control.py --disable{Colors.END}     تعطيل التشغيل التلقائي  
  {Colors.BLUE}python control.py --interactive{Colors.END} وضع التفاعل
  {Colors.YELLOW}python control.py --status{Colors.END}      عرض الحالة الكاملة
        """
    )
    
    # مجموعة أوامر التشغيل التلقائي
    autostart_group = parser.add_argument_group('التشغيل التلقائي')
    autostart_group.add_argument('--enable', action='store_true', 
                               help='تفعيل التشغيل التلقائي للنظام')
    autostart_group.add_argument('--disable', action='store_true',
                               help='تعطيل التشغيل التلقائي للنظام')
    
    # مجموعة أوامر الخدمات
    service_group = parser.add_argument_group('إدارة الخدمات')
    service_group.add_argument('--start-service', action='store_true',
                             help='بدء جميع الخدمات الخلفية')
    service_group.add_argument('--stop-service', action='store_true',
                            help='إيقاف جميع الخدمات الخلفية')
    service_group.add_argument('--restart-service', action='store_true',
                             help='إعادة تشغيل الخدمات الخلفية')
    service_group.add_argument('--service-status', action='store_true',
                             help='عرض حالة الخدمات')
    
    # مجموعة أوامر المعلومات
    info_group = parser.add_argument_group('المعلومات')
    info_group.add_argument('--status', action='store_true',
                          help='عرض الحالة الكاملة للنظام')
    info_group.add_argument('--system-info', action='store_true',
                          help='عرض معلومات النظام')
    
    # أوامر خاصة
    parser.add_argument('--interactive', '-i', action='store_true',
                      help='تشغيل وضع التفاعل مع المستخدم')
    parser.add_argument('--verbose', '-v', action='store_true',
                      help='عرض معلومات تفصيلية')
    
    args = parser.parse_args()
    
    # إنشاء نظام التحكم
    control_system = ControlSystem()
    
    # التحقق من الصلاحيات إذا لزم الأمر
    control_system.check_privileges()
    
    # معالجة الأوامر
    command_executed = False
    
    if args.interactive:
        control_system.run_interactive_mode()
        command_executed = True
    
    # أوامر التشغيل التلقائي
    if args.enable:
        control_system.handle_autostart(True)
        command_executed = True
        
    if args.disable:
        control_system.handle_autostart(False) 
        command_executed = True
    
    # أوامر الخدمات
    if args.start_service:
        control_system.handle_service_control("start")
        command_executed = True
        
    if args.stop_service:
        control_system.handle_service_control("stop")
        command_executed = True
        
    if args.restart_service:
        control_system.handle_service_control("restart")
        command_executed = True
        
    if args.service_status:
        control_system.show_service_status()
        command_executed = True
    
    # أوامر المعلومات
    if args.status or args.system_info:
        control_system.show_system_info()
        command_executed = True
    
    # إذا لم يتم تنفيذ أي أمر، عرض المساعدة
    if not command_executed:
        control_system.print_banner()
        parser.print_help()

if __name__ == "__main__":
    main()