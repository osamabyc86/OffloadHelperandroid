#!/usr/bin/env python3
"""
rpc_server.py - خادم RPC آمن ومحسن
====================================

خادم RPC متقدم مع أمان محسن، مراقبة شاملة، وإدارة ذكية للمهام
"""

from flask import Flask, request, jsonify
import logging
import json
import time
import threading
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict
from functools import wraps
import hashlib
import hmac
import secrets
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
import psutil
#!/usr/bin/env python3
"""
rpc_server.py - خادم RPC آمن ومحسن
"""

from flask import Flask, request, jsonify
import logging
import json
import time
import threading
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict
from functools import wraps
import hashlib
import hmac
import secrets
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
import psutil

# استيراد مدير المنافذ
try:
    from port_manager import PortManager
    port_manager = PortManager()
    DEFAULT_PORT = port_manager.get_available_port()
except:
    DEFAULT_PORT = 7520

class EnhancedRPCServer:
    def __init__(self, port: int = None, enable_security: bool = True):
        self.port = port or DEFAULT_PORT
        # باقي الكود يبقى كما هو...
# محاولة استيراد الوحدات
try:
    import smart_tasks
    TASKS_AVAILABLE = True
except ImportError:
    smart_tasks = None
    TASKS_AVAILABLE = False

try:
    from security_layer import SecurityManager
    SECURITY_AVAILABLE = True
except ImportError:
    SECURITY_AVAILABLE = False

# إعداد السجلات
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("rpc_server.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

@dataclass
class TaskMetrics:
    """مقاييس أداء المهمة"""
    task_id: str
    function_name: str
    start_time: datetime
    end_time: Optional[datetime] = None
    execution_time: float = 0.0
    success: bool = False
    error: Optional[str] = None
    client_ip: str = ""
    payload_size: int = 0

@dataclass
class SystemHealth:
    """صحة النظام"""
    cpu_usage: float
    memory_usage: float
    active_tasks: int
    total_requests: int
    error_rate: float
    uptime: float

class EnhancedSecurityManager:
    """مدير أمان محسن مع مفاتيح ديناميكية"""
    
    def __init__(self, secret_key: Optional[str] = None):
        self.secret_key = secret_key or self._generate_dynamic_key()
        self.key_rotation_interval = 3600  # تدوير المفاتيح كل ساعة
        self.last_key_rotation = time.time()
        self.rate_limits: Dict[str, List[float]] = {}
        
        logger.info("🔒 مدير الأمان المحسن مُهيأ")
    
    def _generate_dynamic_key(self) -> str:
        """توليد مفتاح ديناميكي آمن"""
        return secrets.token_urlsafe(32)
    
    def should_rotate_key(self) -> bool:
        """التحقق من الحاجة لتدوير المفتاح"""
        return (time.time() - self.last_key_rotation) > self.key_rotation_interval
    
    def rotate_key(self):
        """تدوير المفتاح السري"""
        self.secret_key = self._generate_dynamic_key()
        self.last_key_rotation = time.time()
        logger.info("🔄 تم تدوير المفتاح السري")
    
    def verify_signature(self, data: dict, signature: str) -> bool:
        """التحقق من توقيع البيانات"""
        try:
            # إنشاء توقيع متوقع
            payload_str = json.dumps(data, sort_keys=True, separators=(',', ':'))
            expected_signature = hmac.new(
                self.secret_key.encode(),
                payload_str.encode(),
                hashlib.sha256
            ).hexdigest()
            
            return hmac.compare_digest(expected_signature, signature)
            
        except Exception as e:
            logger.error(f"❌ خطأ في التحقق من التوقيع: {e}")
            return False
    
    def check_rate_limit(self, client_id: str, max_requests: int = 100, window_seconds: int = 60) -> bool:
        """التحقق من حد معدل الطلبات"""
        now = time.time()
        window_start = now - window_seconds
        
        if client_id not in self.rate_limits:
            self.rate_limits[client_id] = []
        
        # تنظيف الطلبات القديمة
        self.rate_limits[client_id] = [
            req_time for req_time in self.rate_limits[client_id]
            if req_time > window_start
        ]
        
        # التحقق من الحد
        if len(self.rate_limits[client_id]) >= max_requests:
            return False
        
        self.rate_limits[client_id].append(now)
        return True

class TaskManager:
    """مدير مهام متقدم مع تتبع ومراقبة"""
    
    def __init__(self, max_workers: int = 10, task_timeout: int = 300):
        self.max_workers = max_workers
        self.task_timeout = task_timeout
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.active_tasks: Dict[str, threading.Thread] = {}
        self.task_history: List[TaskMetrics] = []
        self.task_history_max_size = 1000
        
        # الإحصائيات
        self.stats = {
            'total_tasks': 0,
            'successful_tasks': 0,
            'failed_tasks': 0,
            'total_execution_time': 0.0
        }
        
        self._lock = threading.RLock()
        logger.info(f"🔧 مدير المهام مُهيأ ({max_workers} عامل)")
    
    def execute_task(self, func, args: list, kwargs: dict, task_id: str, client_ip: str) -> Any:
        """تنفيذ مهمة مع التتبع والمراقبة"""
        metrics = TaskMetrics(
            task_id=task_id,
            function_name=func.__name__,
            start_time=datetime.now(),
            client_ip=client_ip,
            payload_size=len(str(args)) + len(str(kwargs))
        )
        
        try:
            # تنفيذ المهمة مع حد زمني
            future = self.executor.submit(func, *args, **kwargs)
            result = future.result(timeout=self.task_timeout)
            
            # تسجيل النجاح
            metrics.end_time = datetime.now()
            metrics.execution_time = (metrics.end_time - metrics.start_time).total_seconds()
            metrics.success = True
            
            self._record_task(metrics)
            logger.info(f"✅ تم تنفيذ المهمة {task_id} في {metrics.execution_time:.3f} ثانية")
            
            return result
            
        except FutureTimeoutError:
            error_msg = f"انتهت مهلة المهمة بعد {self.task_timeout} ثانية"
            metrics.error = error_msg
            self._record_task(metrics)
            logger.warning(f"⏰ انتهت مهلة المهمة {task_id}")
            raise TimeoutError(error_msg)
            
        except Exception as e:
            error_msg = str(e)
            metrics.error = error_msg
            metrics.end_time = datetime.now()
            metrics.execution_time = (metrics.end_time - metrics.start_time).total_seconds()
            self._record_task(metrics)
            logger.error(f"❌ فشلت المهمة {task_id}: {error_msg}")
            raise
    
    def _record_task(self, metrics: TaskMetrics):
        """تسجيل مقاييس المهمة"""
        with self._lock:
            self.task_history.append(metrics)
            self.stats['total_tasks'] += 1
            
            if metrics.success:
                self.stats['successful_tasks'] += 1
                self.stats['total_execution_time'] += metrics.execution_time
            else:
                self.stats['failed_tasks'] += 1
            
            # الحفاظ على حجم السجل
            if len(self.task_history) > self.task_history_max_size:
                self.task_history = self.task_history[-self.task_history_max_size:]
    
    def get_system_health(self) -> SystemHealth:
        """الحصول على صحة النظام"""
        with self._lock:
            total_requests = self.stats['total_tasks']
            failed_requests = self.stats['failed_tasks']
            error_rate = failed_requests / max(total_requests, 1)
            
            return SystemHealth(
                cpu_usage=psutil.cpu_percent(interval=1),
                memory_usage=psutil.virtual_memory().percent,
                active_tasks=len(self.active_tasks),
                total_requests=total_requests,
                error_rate=error_rate,
                uptime=time.time() - self.start_time if hasattr(self, 'start_time') else 0
            )
    
    def start(self):
        """بدء مدير المهام"""
        self.start_time = time.time()
    
    def stop(self):
        """إيقاف مدير المهام"""
        self.executor.shutdown(wait=False)

class EnhancedRPCServer:
    """خادم RPC محسن مع إدارة شاملة"""
    
    def __init__(self, port: int = 7520, enable_security: bool = True):
        self.port = port
        self.app = Flask(__name__)
        self.security_manager = EnhancedSecurityManager() if enable_security else None
        self.task_manager = TaskManager()
        self.start_time = time.time()
        
        # اكتشاف الوظائف المتاحة
        self.available_functions = self._discover_functions()
        
        # إعداد التطبيق
        self._setup_app()
        self.task_manager.start()
        
        logger.info(f"🚀 خادم RPC المحسن مُهيأ على المنفذ {port}")
        logger.info(f"📋 الوظائف المتاحة: {list(self.available_functions.keys())}")
    
    def _discover_functions(self) -> Dict[str, Any]:
        """اكتشاف الوظائف المتاحة ديناميكياً"""
        functions = {}
        
        # اكتشاف من smart_tasks
        if TASKS_AVAILABLE:
            for attr_name in dir(smart_tasks):
                attr = getattr(smart_tasks, attr_name)
                if callable(attr) and not attr_name.startswith('_'):
                    functions[attr_name] = attr
        
        # إضافة وظائف النظام
        functions['system_info'] = self._system_info_function
        functions['list_functions'] = self._list_functions
        
        return functions
    
    def _system_info_function(self):
        """وظيفة معلومات النظام"""
        return {
            "hostname": socket.gethostname(),
            "uptime": time.time() - self.start_time,
            "python_version": "3.8+",
            "available_functions": len(self.available_functions)
        }
    
    def _list_functions(self):
        """وظيفة سرد الوظائف المتاحة"""
        return list(self.available_functions.keys())
    
    def _setup_app(self):
        """إعداد تطبيق Flask مع المسارات"""
        
        @self.app.before_request
        def before_request():
            """معالجة قبل الطلب"""
            request.start_time = time.time()
            
            # التحقق من حد حجم الطلب
            if request.content_length and request.content_length > 10 * 1024 * 1024:  # 10MB
                return jsonify(error="حجم الطلب كبير جداً"), 413
        
        @self.app.after_request
        def after_request(response):
            """معالجة بعد الطلب"""
            # إضافة رؤوس أمان
            response.headers['X-Content-Type-Options'] = 'nosniff'
            response.headers['X-Frame-Options'] = 'DENY'
            response.headers['X-XSS-Protection'] = '1; mode=block'
            
            # حساب وقت المعالجة
            if hasattr(request, 'start_time'):
                processing_time = time.time() - request.start_time
                response.headers['X-Processing-Time'] = str(processing_time)
            
            return response
        
        @self.app.route('/')
        def index():
            """الصفحة الرئيسية"""
            return jsonify({
                "service": "Enhanced RPC Server",
                "version": "2.0",
                "endpoints": {
                    "/health": "صحة النظام",
                    "/run": "تنفيذ المهام (POST)",
                    "/metrics": "مقاييس الأداء",
                    "/functions": "الوظائف المتاحة"
                }
            })
        
        @self.app.route('/health', methods=['GET'])
        def health():
            """فحص صحة النظام"""
            system_health = self.task_manager.get_system_health()
            
            return jsonify({
                "status": "healthy",
                "timestamp": datetime.now().isoformat(),
                "system_health": asdict(system_health),
                "security_enabled": self.security_manager is not None,
                "available_functions": len(self.available_functions)
            })
        
        @self.app.route('/run', methods=['POST'])
        def run():
            """تنفيذ المهمة مع معالجة محسنة"""
            client_ip = request.remote_addr or "unknown"
            task_id = f"task_{int(time.time()*1000)}_{secrets.token_hex(4)}"
            
            # التحقق من حد المعدل
            if self.security_manager and not self.security_manager.check_rate_limit(client_ip):
                logger.warning(f"🚫 تجاوز حد المعدل للعميل {client_ip}")
                return jsonify(error="تجاوز حد المعدل"), 429
            
            try:
                # معالجة البيانات المدخلة
                if request.is_json:
                    data = request.get_json(force=True, cache=True)
                else:
                    raw_data = request.get_data()
                    
                    if self.security_manager and SECURITY_AVAILABLE:
                        # فك التشفير إذا كان مدعوماً
                        try:
                            decrypted = SecurityManager.decrypt_data(raw_data)
                            data = json.loads(decrypted.decode())
                        except Exception as e:
                            logger.error(f"❌ فشل فك التشفير: {e}")
                            return jsonify(error="فشل فك التشفير"), 400
                    else:
                        # محاولة تحليل كـ JSON مباشرة
                        try:
                            data = json.loads(raw_data.decode())
                        except json.JSONDecodeError:
                            return jsonify(error="بيانات غير صالحة"), 400
                
                # التحقق من التوقيع إذا كان الأمان مفعلاً
                if self.security_manager and "_signature" in data:
                    if not self.security_manager.verify_signature(
                        {k: v for k, v in data.items() if k != "_signature"},
                        data["_signature"]
                    ):
                        logger.warning(f"❌ توقيع غير صالح من {client_ip}")
                        return jsonify(error="توقيع غير صالح"), 403
                
                # استخراج بيانات المهمة
                func_name = data.get("func")
                args = data.get("args", [])
                kwargs = data.get("kwargs", {})
                
                # التحقق من وجود الوظيفة
                if func_name not in self.available_functions:
                    logger.warning(f"❌ وظيفة غير موجودة: {func_name} من {client_ip}")
                    return jsonify(error=f"الوظيفة '{func_name}' غير موجودة"), 404
                
                # التحقق من صحة المعاملات
                if not self._validate_arguments(func_name, args, kwargs):
                    return jsonify(error="معاملات غير صالحة"), 400
                
                # تنفيذ المهمة
                func = self.available_functions[func_name]
                result = self.task_manager.execute_task(func, args, kwargs, task_id, client_ip)
                
                logger.info(f"✅ تم معالجة المهمة {task_id} من {client_ip}")
                return jsonify({
                    "result": result,
                    "task_id": task_id,
                    "status": "success"
                })
                
            except TimeoutError as e:
                return jsonify(error=str(e)), 408
            except Exception as e:
                logger.error(f"❌ خطأ في معالجة المهمة {task_id}: {e}")
                return jsonify(error=str(e)), 500
        
        @self.app.route('/metrics', methods=['GET'])
        def metrics():
            """مقاييس أداء النظام"""
            health_data = self.task_manager.get_system_health()
            recent_tasks = self.task_manager.task_history[-10:]  # آخر 10 مهام
            
            return jsonify({
                "system_health": asdict(health_data),
                "task_statistics": self.task_manager.stats,
                "recent_tasks": [
                    {
                        "task_id": task.task_id,
                        "function": task.function_name,
                        "execution_time": task.execution_time,
                        "success": task.success,
                        "client_ip": task.client_ip
                    }
                    for task in recent_tasks
                ]
            })
        
        @self.app.route('/functions', methods=['GET'])
        def list_functions():
            """سرد الوظائف المتاحة"""
            functions_info = {}
            
            for name, func in self.available_functions.items():
                functions_info[name] = {
                    "description": func.__doc__ or "لا يوجد وصف",
                    "module": func.__module__
                }
            
            return jsonify(functions_info)
    
    def _validate_arguments(self, func_name: str, args: list, kwargs: dict) -> bool:
        """التحقق من صحة معاملات الوظيفة"""
        try:
            func = self.available_functions[func_name]
            
            # تحقق بسيط من عدد المعاملات
            import inspect
            sig = inspect.signature(func)
            params = list(sig.parameters.values())
            
            # التحقق من المعاملات الإلزامية
            required_params = [p for p in params if p.default == inspect.Parameter.empty]
            if len(args) < len(required_params):
                return False
                
            return True
            
        except Exception as e:
            logger.error(f"❌ خطأ في التحقق من المعاملات: {e}")
            return False
    
    def run(self, host: str = "0.0.0.0", debug: bool = False):
        """تشغيل الخادم"""
        logger.info(f"🌐 بدء خادم RPC على {host}:{self.port}")
        
        try:
            self.app.run(
                host=host,
                port=self.port,
                debug=debug,
                threaded=True
            )
        except KeyboardInterrupt:
            logger.info("🛑 إيقاف الخادم...")
            self.task_manager.stop()
        except Exception as e:
            logger.error(f"❌ خطأ في تشغيل الخادم: {e}")
            raise

# التوافق مع الإصدار القديم
def create_legacy_server(port: int = 7520):
    """إنشاء خادم متوافق مع الإصدار القديم"""
    server = EnhancedRPCServer(port=port)
    return server.app

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="خادم RPC المحسن")
    parser.add_argument("--port", type=int, default=7520, help="منفذ الخادم")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="واجهة الخادم")
    parser.add_argument("--no-security", action="store_true", help="تعطيل الأمان")
    
    args = parser.parse_args()
    
    server = EnhancedRPCServer(
        port=args.port,
        enable_security=not args.no_security
    )
    server.run(host=args.host)