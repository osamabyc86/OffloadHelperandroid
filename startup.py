import os
import sys
import subprocess
import time
import logging
import signal
import atexit
import psutil
from typing import List, Tuple, Dict, Optional
from pathlib import Path
from autostart_config import AutoStartManager
from distributed_executor import DistributedExecutor

# التهيئة العامة
PY = sys.executable
SERVICES = [
    ("peer_server.py", "Peer-Server"),
    ("rpc_server.py", "RPC-Server"),
    ("server.py", "REST-Server"),
    ("load_balancer.py", "Load-Balancer"),
]

# محاولة استيراد psutil
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

class ServiceManager:
    """مدير خدمة محسن لإدارة دورة حياة الخدمات"""
    
    def __init__(self):
        self.processes: Dict[str, subprocess.Popen] = {}
        self.service_info: Dict[str, dict] = {}
        self.shutting_down = False
        self.start_time = time.time()
        self.setup_signal_handlers()
        self.setup_logging()
    
    def setup_logging(self):
        """إعداد نظام التسجيل"""
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            handlers=[
                logging.FileHandler("logs/startup.log", encoding='utf-8'),
                logging.StreamHandler(sys.stdout)
            ]
        )
        self.logger = logging.getLogger('ServiceManager')
    
    def setup_signal_handlers(self):
        """إعداد معالجات الإشارات للإغلاق الآمن"""
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        atexit.register(self.cleanup)
    
    def signal_handler(self, signum, frame):
        """معالج الإشارات للإغلاق النظيف"""
        self.logger.info(f"📴 استقبال إشارة {signum}، إيقاف الخدمات...")
        self.shutting_down = True
        self.cleanup()
        sys.exit(0)
    
    def check_dependencies(self) -> bool:
        """التحقق من توفر جميع الاعتماديات المطلوبة"""
        missing_deps = []
        
        for script, name in SERVICES:
            if not os.path.exists(script):
                missing_deps.append(script)
        
        if missing_deps:
            self.logger.error(f"❌ الملفات الناقصة: {missing_deps}")
            return False
        
        # التحقق من الواردات الضرورية
        try:
            from autostart_config import AutoStartManager
            from distributed_executor import DistributedExecutor
        except ImportError as e:
            self.logger.error(f"❌ خطأ في استيراد الوحدات: {e}")
            return False
        
        return True
    
    def launch_service(self, script: str, name: str) -> Optional[subprocess.Popen]:
        """تشغيل خدمة فردية مع معالجة الأخطاء"""
        try:
            # التحقق من وجود الملف
            if not os.path.exists(script):
                self.logger.error(f"❌ ملف {script} غير موجود")
                return None
            
            # تشغيل العملية
            process = subprocess.Popen(
                [PY, script],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            # انتظار قصير للتحقق من نجاح التشغيل
            time.sleep(1)
            
            if process.poll() is not None:
                # العملية فشلت في البدء
                stderr_output = process.stderr.read() if process.stderr else "Unknown error"
                self.logger.error(f"❌ فشل تشغيل {name}: {stderr_output}")
                return None
            
            self.logger.info(f"✅ {name} قيد التشغيل (PID={process.pid})")
            
            # تخزين معلومات إضافية
            self.service_info[name] = {
                "script": script,
                "start_time": time.time(),
                "restart_count": 0
            }
            
            return process
            
        except Exception as e:
            self.logger.error(f"❌ استثناء أثناء تشغيل {name}: {e}")
            return None
    
    def launch_all_services(self) -> bool:
        """تشغيل جميع الخدمات"""
        self.logger.info("🚀 بدء تشغيل جميع الخدمات...")
        
        success_count = 0
        for script, name in SERVICES:
            process = self.launch_service(script, name)
            if process:
                self.processes[name] = process
                success_count += 1
            else:
                self.logger.warning(f"⚠️ فشل تشغيل {name}")
        
        self.logger.info(f"📊 نجح تشغيل {success_count}/{len(SERVICES)} خدمة")
        return success_count > 0
    
    def monitor_services_health(self) -> Dict[str, Dict]:
        """مراقبة صحة الخدمات بشكل تفصيلي"""
        health_status = {}
        
        for name, process in self.processes.items():
            status = {
                "pid": process.pid,
                "alive": process.poll() is None,
                "return_code": process.poll(),
                "name": name
            }
            
            # جمع إحصائيات إضافية إذا كانت متاحة
            if HAS_PSUTIL:
                try:
                    ps_process = psutil.Process(process.pid)
                    status.update({
                        "memory_mb": round(ps_process.memory_info().rss / 1024 / 1024, 2),
                        "cpu_percent": ps_process.cpu_percent(),
                        "create_time": ps_process.create_time(),
                        "status": ps_process.status()
                    })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    status["psutil_error"] = "لا يمكن الوصول إلى معلومات العملية"
            
            health_status[name] = status
        
        return health_status
    
    def restart_failed_services(self) -> int:
        """إعادة تشغيل الخدمات الفاشلة وإعادة الإحصاء"""
        restarted_count = 0
        health_status = self.monitor_services_health()
        
        for name, status in health_status.items():
            if not status["alive"]:
                self.logger.warning(f"⚠️ الخدمة {name} توقفت (كود الخروج: {status['return_code']})")
                
                # إعادة التشغيل
                script = self.service_info[name]["script"]
                new_process = self.launch_service(script, name)
                
                if new_process:
                    self.processes[name] = new_process
                    self.service_info[name]["restart_count"] += 1
                    self.service_info[name]["last_restart"] = time.time()
                    restarted_count += 1
                    self.logger.info(f"✅ أعيد تشغيل {name} (المحاولة: {self.service_info[name]['restart_count']})")
                else:
                    self.logger.error(f"❌ فشل إعادة تشغيل {name}")
        
        return restarted_count
    
    def initialize_distributed_system(self) -> bool:
        """تهيئة نظام التنفيذ الموزع"""
        try:
            executor = DistributedExecutor("my_shared_secret_123")
            executor.peer_registry.register_service("auto_node", 7520)
            self.logger.info("🚀 العقدة auto_node مُسجّلة في الـRegistry على 7520")
            return True
        except Exception as e:
            self.logger.error(f"❌ فشل تهيئة النظام الموزع: {e}")
            return False
    
    def try_enhanced_background_service(self) -> bool:
        """محاولة تشغيل الخدمة الخلفية المحسنة"""
        if not os.path.exists("background_service.py"):
            self.logger.info("ℹ️ الخدمة الخلفية المحسنة غير متوفرة")
            return False
        
        try:
            self.logger.info("🔄 تشغيل الخدمة الخلفية المحسّنة...")
            process = subprocess.Popen([PY, "background_service.py", "start"])
            
            # التحقق من نجاح التشغيل
            time.sleep(2)
            if process.poll() is None:
                self.logger.info("✅ تم بدء تشغيل الخدمة الخلفية المحسّنة")
                return True
            else:
                self.logger.warning("⚠️ فشل تشغيل الخدمة الخلفية المحسنة")
                return False
                
        except Exception as e:
            self.logger.warning(f"⚠️ فشل في تشغيل الخدمة الخلفية المحسّنة: {e}")
            return False
    
    def cleanup(self):
        """تنظيف الموارد وإيقاف جميع العمليات"""
        if self.shutting_down:
            return
            
        self.shutting_down = True
        self.logger.info("🧹 تنظيف الموارد وإيقاف الخدمات...")
        
        # إيقاف جميع العمليات
        for name, process in self.processes.items():
            try:
                self.logger.info(f"⏹️ إيقاف {name} (PID: {process.pid})")
                process.terminate()
                
                try:
                    process.wait(timeout=10)
                    self.logger.info(f"✅ تم إيقاف {name}")
                except subprocess.TimeoutExpired:
                    self.logger.warning(f"⚠️ إجبار إيقاف {name}")
                    process.kill()
                    process.wait()
                    
            except Exception as e:
                self.logger.error(f"❌ خطأ أثناء إيقاف {name}: {e}")
        
        self.logger.info("📴 تم إيقاف جميع الخدمات")
    
    def run(self):
        """الدورة الرئيسية لتشغيل المدير"""
        # التحقق من الاعتماديات
        if not self.check_dependencies():
            self.logger.error("❌ فشل التحقق من الاعتماديات، إيقاف التشغيل")
            return
        
        # التحقق من إعدادات التشغيل التلقائي
        try:
            cfg = AutoStartManager().config
            if not cfg.get("enabled", True):
                self.logger.info("⏸️ التشغيل التلقائي مُعطل في الإعدادات")
                return
        except Exception as e:
            self.logger.warning(f"⚠️ خطأ في قراءة الإعدادات: {e}")
        
        # محاولة تشغيل الخدمة الخلفية المحسنة
        if self.try_enhanced_background_service():
            self.logger.info("🎯 التشغيل عبر الخدمة الخلفية المحسنة")
            return
        
        self.logger.info("🔄 العودة إلى الطريقة التقليدية...")
        
        # تشغيل الخدمات التقليدية
        if not self.launch_all_services():
            self.logger.error("❌ فشل تشغيل الخدمات الأساسية")
            return
        
        # تهيئة النظام الموزع
        if not self.initialize_distributed_system():
            self.logger.warning("⚠️ فشل تهيئة النظام الموزع، المتابعة بدونها")
        
        # الحلقة الرئيسية للمراقبة
        self.logger.info("🔍 بدء المراقبة المستمرة للخدمات...")
        monitor_cycle = 0
        
        try:
            while not self.shutting_down:
                time.sleep(30)  # فحص كل 30 ثانية
                monitor_cycle += 1
                
                # فحص صحة الخدمات بشكل دوري
                if monitor_cycle % 2 == 0:  # كل دقيقة
                    health_status = self.monitor_services_health()
                    self.logger.debug(f"📊 صحة الخدمات: {health_status}")
                
                # إعادة تشغيل الخدمات الفاشلة
                restarted = self.restart_failed_services()
                if restarted > 0:
                    self.logger.info(f"🔄 أعيد تشغيل {restarted} خدمة")
                
                # تسجيل إحصائية دورية
                if monitor_cycle % 10 == 0:  # كل 5 دقائق
                    uptime = time.time() - self.start_time
                    self.logger.info(f"⏱️  وقت التشغيل: {uptime:.0f} ثانية، {len(self.processes)} خدمة نشطة")
                    
        except KeyboardInterrupt:
            self.logger.info("📴 إيقاف الخدمات يدويًا")
        except Exception as e:
            self.logger.error(f"❌ خطأ غير متوقع في حلقة المراقبة: {e}")
        finally:
            self.cleanup()


def main():
    """الدالة الرئيسية"""
    manager = ServiceManager()
    manager.run()


if __name__ == "__main__":
    main()