#!/usr/bin/env python3
"""
أيقونة شريط النظام المحسنة للتحكم في النظام الموزع
"""

import sys
import threading
import requests
import webbrowser
import time
import logging
import psutil
import socket
from pathlib import Path
from typing import Dict, Any, Optional, Callable
from enum import Enum
#!/usr/bin/env python3
"""
أيقونة شريط النظام المحسنة للتحكم في النظام الموزع
"""

import sys
import threading
import requests
import webbrowser
import time
import logging
import psutil
import socket
from pathlib import Path
from typing import Dict, Any, Optional, Callable
from enum import Enum

try:
    import pystray
    from pystray import MenuItem as item
    from PIL import Image, ImageDraw
    TRAY_AVAILABLE = True
except ImportError:
    TRAY_AVAILABLE = False
    print("⚠️ pystray غير متوفر، تشغيل بدون أيقونة النظام")

# استيراد مدير المنافذ
try:
    from port_manager import PortManager
    port_manager = PortManager()
    CURRENT_PORT = port_manager.get_available_port()
    CONTROL_PORT = port_manager.get_available_port()
    UI_PORT = port_manager.get_available_port()
except:
    CURRENT_PORT = 7521
    CONTROL_PORT = 8888
    UI_PORT = 5173

class ServiceStatus(Enum):
    RUNNING = "running"
    STOPPED = "stopped"
    ERROR = "error"
    UNKNOWN = "unknown"

class SystemTrayController:
    def __init__(self):
        self.server_port = CURRENT_PORT
        self.control_port = CONTROL_PORT
        self.ui_port = UI_PORT
        self.base_url = f"http://localhost:{self.control_port}"
        self.server_url = f"http://localhost:{self.server_port}"
        self.icon = None
        self.is_running = False
        self.update_thread = None
        self.should_update = True
        self.setup_logging()
        
    # باقي الكود يبقى كما هو...
try:
    import pystray
    from pystray import MenuItem as item
    from PIL import Image, ImageDraw
    TRAY_AVAILABLE = True
except ImportError:
    TRAY_AVAILABLE = False
    print("⚠️ pystray غير متوفر، تشغيل بدون أيقونة النظام")

try:
    from peer_discovery import PORT as DISCOVERY_PORT
    from server import PORT as SERVER_PORT
    CURRENT_PORT = SERVER_PORT
except:
    CURRENT_PORT = 7521  # المنفذ الافتراضي

class ServiceStatus(Enum):
    RUNNING = "running"
    STOPPED = "stopped"
    ERROR = "error"
    UNKNOWN = "unknown"

class SystemTrayController:
    def __init__(self):
        self.server_port = CURRENT_PORT
        self.control_port = 8888  # منفذ التحكم الخلفي
        self.ui_port = 5173       # منفذ واجهة المستخدم
        self.base_url = f"http://localhost:{self.control_port}"
        self.server_url = f"http://localhost:{self.server_port}"
        self.icon = None
        self.is_running = False
        self.update_thread = None
        self.should_update = True
        self.setup_logging()
        
    def setup_logging(self):
        """إعداد نظام التسجيل"""
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            handlers=[
                logging.FileHandler("logs/system_tray.log", encoding='utf-8'),
                logging.StreamHandler(sys.stdout)
            ]
        )
        self.logger = logging.getLogger('SystemTray')
        
    def create_icon_image(self, status: ServiceStatus = ServiceStatus.UNKNOWN):
        """إنشاء صورة الأيقونة ديناميكية بناءً على الحالة"""
        size = 64
        image = Image.new('RGBA', (size, size), color=(0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        
        # تحديد اللون بناءً على الحالة
        colors = {
            ServiceStatus.RUNNING: ('#22c55e', '#16a34a'),  # أخضر
            ServiceStatus.STOPPED: ('#ef4444', '#dc2626'),  # أحمر
            ServiceStatus.ERROR: ('#f59e0b', '#d97706'),    # برتقالي
            ServiceStatus.UNKNOWN: ('#6b7280', '#4b5563')   # رمادي
        }
        
        primary_color, secondary_color = colors.get(status, colors[ServiceStatus.UNKNOWN])
        
        # رسم خلفية دائرية
        draw.ellipse([8, 8, size-8, size-8], fill=primary_color)
        
        # رسم رمز بناءً على الحالة
        if status == ServiceStatus.RUNNING:
            # رمز تشغيل (مثلث)
            draw.polygon([(24, 20), (24, 44), (44, 32)], fill='white')
        elif status == ServiceStatus.STOPPED:
            # رمز إيقاف (مربع)
            draw.rectangle([24, 20, 40, 44], fill='white')
        elif status == ServiceStatus.ERROR:
            # رمز خطأ (علامة تعجب)
            draw.rectangle([30, 18, 34, 32], fill='white')  # خط رأسي
            draw.ellipse([30, 36, 34, 40], fill='white')    # نقطة
        else:
            # رمز استعلام (علامة استفهام)
            draw.ellipse([28, 18, 36, 26], fill='white')   # دائرة
            draw.rectangle([32, 30, 32, 38], fill='white') # خط
        
        return image
        
    def check_service_health(self) -> Dict[str, Any]:
        """فحص صحة الخدمات بشكل شامل"""
        health_info = {
            "server_status": ServiceStatus.UNKNOWN,
            "control_status": ServiceStatus.UNKNOWN,
            "ui_status": ServiceStatus.UNKNOWN,
            "details": {},
            "overall": ServiceStatus.UNKNOWN
        }
        
        try:
            # فحص الخادم الرئيسي
            try:
                response = requests.get(f"{self.server_url}/health", timeout=2)
                if response.status_code == 200:
                    health_info["server_status"] = ServiceStatus.RUNNING
                    health_info["details"]["server"] = response.json()
                else:
                    health_info["server_status"] = ServiceStatus.ERROR
            except:
                health_info["server_status"] = ServiceStatus.STOPPED
            
            # فحص خدمة التحكم الخلفية
            try:
                response = requests.get(f"{self.base_url}/status", timeout=2)
                if response.status_code == 200:
                    health_info["control_status"] = ServiceStatus.RUNNING
                    health_info["details"]["control"] = response.json()
                else:
                    health_info["control_status"] = ServiceStatus.ERROR
            except:
                health_info["control_status"] = ServiceStatus.STOPPED
            
            # فحص واجهة المستخدم
            try:
                response = requests.get(f"http://localhost:{self.ui_port}", timeout=2)
                if response.status_code == 200:
                    health_info["ui_status"] = ServiceStatus.RUNNING
                else:
                    health_info["ui_status"] = ServiceStatus.ERROR
            except:
                health_info["ui_status"] = ServiceStatus.STOPPED
            
            # تحديد الحالة العامة
            running_services = sum(1 for status in [
                health_info["server_status"],
                health_info["control_status"], 
                health_info["ui_status"]
            ] if status == ServiceStatus.RUNNING)
            
            if running_services >= 2:
                health_info["overall"] = ServiceStatus.RUNNING
            elif running_services >= 1:
                health_info["overall"] = ServiceStatus.ERROR
            else:
                health_info["overall"] = ServiceStatus.STOPPED
                
        except Exception as e:
            self.logger.error(f"خطأ في فحص الصحة: {e}")
            health_info["overall"] = ServiceStatus.ERROR
            
        return health_info
    
    def is_port_in_use(self, port: int) -> bool:
        """التحقق إذا كان المنفذ مستخدماً"""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(1)
                return sock.connect_ex(('localhost', port)) == 0
        except:
            return False
    
    def start_local_services(self):
        """بدء الخدمات المحلية إذا كانت متوقفة"""
        try:
            # التحقق من الخادم الرئيسي
            if not self.is_port_in_use(self.server_port):
                self.logger.info("تشغيل الخادم الرئيسي...")
                import subprocess
                subprocess.Popen([sys.executable, "server.py"], 
                               stdout=subprocess.DEVNULL, 
                               stderr=subprocess.DEVNULL)
                time.sleep(2)  # انتظار بدء التشغيل
            
            # تحديث الحالة
            self.is_running = True
            self.logger.info("تم بدء الخدمات المحلية")
            return True
            
        except Exception as e:
            self.logger.error(f"فشل في بدء الخدمات المحلية: {e}")
            return False
    
    def stop_local_services(self):
        """إيقاف الخدمات المحلية"""
        try:
            # البحث عن عمليات بايثون المتعلقة بخدماتنا
            for process in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    cmdline = process.info['cmdline'] or []
                    if any(script in str(cmdline) for script in ['server.py', 'peer_server.py', 'rpc_server.py']):
                        process.terminate()
                        self.logger.info(f"تم إيقاف العملية {process.info['pid']}")
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            
            self.is_running = False
            self.logger.info("تم إيقاف الخدمات المحلية")
            return True
            
        except Exception as e:
            self.logger.error(f"فشل في إيقاف الخدمات المحلية: {e}")
            return False
    
    def start_services(self, icon=None, item=None):
        """بدء تشغيل الخدمات"""
        self.logger.info("محاولة بدء الخدمات...")
        
        success = False
        try:
            # محاولة استخدام واجهة التحكم الخلفية أولاً
            response = requests.post(f"{self.base_url}/start", timeout=10)
            if response.status_code == 200:
                success = True
                self.logger.info("تم بدء الخدمات عبر واجهة التحكم")
        except:
            # fallback إلى البدء المحلي
            self.logger.info("البدء عبر واجهة التحكم فشل، المحاولة محلياً...")
            success = self.start_local_services()
        
        if success:
            self.is_running = True
            self.show_notification("تم بدء الخدمات", "النظام الموزع يعمل الآن")
        else:
            self.show_notification("فشل بدء الخدمات", "راجع السجلات للتفاصيل")
        
        self.update_menu()
            
    def stop_services(self, icon=None, item=None):
        """إيقاف الخدمات"""
        self.logger.info("محاولة إيقاف الخدمات...")
        
        success = False
        try:
            # محاولة استخدام واجهة التحكم الخلفية أولاً
            response = requests.post(f"{self.base_url}/stop", timeout=10)
            if response.status_code == 200:
                success = True
                self.logger.info("تم إيقاف الخدمات عبر واجهة التحكم")
        except:
            # fallback إلى الإيقاف المحلي
            self.logger.info("الإيقاف عبر واجهة التحكم فشل، المحاولة محلياً...")
            success = self.stop_local_services()
        
        if success:
            self.is_running = False
            self.show_notification("تم إيقاف الخدمات", "النظام الموزع متوقف الآن")
        else:
            self.show_notification("فشل إيقاف الخدمات", "راجع السجلات للتفاصيل")
        
        self.update_menu()
            
    def show_ui(self, icon=None, item=None):
        """إظهار الواجهة التفاعلية"""
        try:
            webbrowser.open(f'http://localhost:{self.ui_port}')
            self.show_notification("فتح الواجهة", "يتم فتح المتصفح...")
        except Exception as e:
            self.logger.error(f"فشل في فتح الواجهة: {e}")
            self.show_notification("خطأ", "تعذر فتح المتصفح")
            
    def open_dashboard(self, icon=None, item=None):
        """فتح لوحة التحكم"""
        try:
            webbrowser.open(f'http://localhost:{self.ui_port}/dashboard')
        except Exception as e:
            self.logger.error(f"فشل في فتح لوحة التحكم: {e}")
            
    def open_monitor(self, icon=None, item=None):
        """فتح شاشة المراقبة"""
        try:
            webbrowser.open(f'http://localhost:{self.server_port}/monitor')
        except Exception as e:
            self.logger.error(f"فشل في فتح شاشة المراقبة: {e}")
    
    def show_status(self, icon=None, item=None):
        """إظهار حالة النظام بشكل مفصل"""
        health = self.check_service_health()
        
        status_text = f"📊 حالة النظام الشاملة:\n"
        status_text += f"• الخادم الرئيسي: {health['server_status'].value}\n"
        status_text += f"• وحدة التحكم: {health['control_status'].value}\n"
        status_text += f"• واجهة المستخدم: {health['ui_status'].value}\n"
        status_text += f"• الحالة العامة: {health['overall'].value}\n"
        
        if health['overall'] == ServiceStatus.RUNNING:
            status_text += "✅ النظام يعمل بشكل مثالي"
        elif health['overall'] == ServiceStatus.ERROR:
            status_text += "⚠️ هناك مشاكل تحتاج اهتمام"
        else:
            status_text += "❌ النظام متوقف"
            
        self.show_notification("حالة النظام", status_text)
        self.logger.info(f"عرض حالة النظام: {health['overall'].value}")
            
    def show_notification(self, title: str, message: str):
        """إظهار إشعار نظام"""
        if self.icon:
            try:
                self.icon.notify(message, title)
            except:
                # fallback للطباعة إذا فشلت الإشعارات
                print(f"{title}: {message}")
    
    def run_system_check(self, icon=None, item=None):
        """تشغيل فحص النظام"""
        try:
            from system_check import main as system_check_main
            threading.Thread(target=system_check_main, daemon=True).start()
            self.show_notification("فحص النظام", "جاري فحص النظام...")
        except Exception as e:
            self.logger.error(f"فشل في تشغيل فحص النظام: {e}")
            self.show_notification("خطأ", "تعذر تشغيل فحص النظام")
        
    def quit_app(self, icon=None, item=None):
        """إنهاء التطبيق بشكل آمن"""
        self.logger.info("بدء الإغلاق الآمن...")
        self.should_update = False
        
        # إيقاف الخدمات أولاً
        self.stop_services()
        
        # إيقاف الأيقونة
        if self.icon:
            self.icon.stop()
        
        self.logger.info("تم إنهاء التطبيق")
        sys.exit(0)
        
    def create_menu(self) -> pystray.Menu:
        """إنشاء قائمة الأيقونة الديناميكية"""
        health = self.check_service_health()
        status = health['overall']
        
        # تحديث الأيقونة بناءً على الحالة
        if self.icon:
            self.icon.icon = self.create_icon_image(status)
        
        menu_items = [
            item(f'حالة النظام ({status.value})', self.show_status),
            item('---', None, enabled=False),
            item('فتح الواجهة الرئيسية', self.show_ui),
            item('لوحة التحكم', self.open_dashboard),
            item('شاشة المراقبة', self.open_monitor),
            item('---', None, enabled=False),
        ]
        
        # إضافة عناصر التحكم بناءً على الحالة
        if status != ServiceStatus.RUNNING:
            menu_items.append(item('بدء الخدمات', self.start_services))
        else:
            menu_items.append(item('إيقاف الخدمات', self.stop_services))
        
        menu_items.extend([
            item('---', None, enabled=False),
            item('فحص النظام', self.run_system_check),
            item('---', None, enabled=False),
            item('إنهاء', self.quit_app)
        ])
        
        return pystray.Menu(*menu_items)
        
    def update_menu(self):
        """تحديث قائمة الأيقونة"""
        if self.icon and hasattr(self.icon, '_menu'):
            try:
                self.icon.menu = self.create_menu()
            except Exception as e:
                self.logger.error(f"خطأ في تحديث القائمة: {e}")
            
    def background_update(self):
        """تحديث الخلفية للحالة"""
        while self.should_update:
            try:
                self.update_menu()
                time.sleep(10)  # تحديث كل 10 ثواني
            except Exception as e:
                self.logger.error(f"خطأ في التحديث الخلفي: {e}")
                time.sleep(30)  # انتظار أطول عند الخطأ
        
    def run(self):
        """تشغيل أيقونة شريط النظام"""
        if not TRAY_AVAILABLE:
            self.logger.error("❌ مكتبة pystray غير متوفرة")
            return False
            
        try:
            # الحصول على الحالة الأولية
            initial_health = self.check_service_health()
            initial_image = self.create_icon_image(initial_health['overall'])
            
            # إنشاء الأيقونة
            self.icon = pystray.Icon(
                "نظام توزيع المهام",
                initial_image,
                menu=self.create_menu()
            )
            
            # بدء خيط التحديث الخلفي
            self.update_thread = threading.Thread(target=self.background_update, daemon=True)
            self.update_thread.start()
            
            # إشعار البدء
            self.show_notification(
                "بدء النظام", 
                "أيقونة النظام الموزع جاهزة\nانقر بزر الماوس الأيمن للتحكم"
            )
            
            self.logger.info("🖱️ تشغيل أيقونة شريط النظام...")
            self.icon.run()
            
            return True
            
        except Exception as e:
            self.logger.error(f"فشل في تشغيل أيقونة النظام: {e}")
            return False

def main():
    """الدالة الرئيسية"""
    try:
        controller = SystemTrayController()
        success = controller.run()
        
        if not success:
            print("❌ فشل في تشغيل أيقونة النظام")
            print("💡 تأكد من تثبيت: pip install pystray pillow")
            sys.exit(1)
            
    except KeyboardInterrupt:
        print("\n⏹️ تم إيقاف الأيقونة بواسطة المستخدم")
        sys.exit(0)
    except Exception as e:
        print(f"❌ خطأ غير متوقع: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()