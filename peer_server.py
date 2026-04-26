#!/usr/bin/env python3
"""
خادم الأقران المحسن - الإصدار 2.0
خادم Flask معزز لإدارة المهام الموزعة مع مراقبة متقدمة
"""

from flask import Flask, request, jsonify
from functools import wraps
import psutil
import time
import socket
import logging
import threading
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Callable
import json
import inspect
from dataclasses import dataclass
import os
#!/usr/bin/env python3
"""
خادم الأقران المحسن - الإصدار 2.0
"""

from flask import Flask, request, jsonify
from functools import wraps
import psutil
import time
import socket
import logging
import threading
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Callable
import json
import inspect
from dataclasses import dataclass
import os

# استيراد مدير المنافذ
try:
    from port_manager import PortManager
    port_manager = PortManager()
    DEFAULT_PORT = port_manager.get_available_port()
except:
    DEFAULT_PORT = 7520

# باقي الكود يبقى كما هو...

class EnhancedPeerServer:
    def __init__(self, port: int = None):
        self.port = port or DEFAULT_PORT
        # باقي الكود يبقى كما هو...
# إعداد السجلات
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# إعدادات التطبيق
MAX_REQUEST_SIZE = 10 * 1024 * 1024  # 10MB حد أقصى لحجم الطلب
DEFAULT_TIMEOUT = 300  # 5 دقائق حد أقصى لتنفيذ المهمة
TASK_HISTORY_SIZE = 100  # عدد المهام المحفوظة في السجل

@dataclass
class TaskResult:
    """نتيجة تنفيذ المهمة"""
    task_id: str
    function_name: str
    success: bool
    result: Any
    error: Optional[str]
    execution_time: float
    timestamp: datetime
    hostname: str

@dataclass
class SystemMetrics:
    """مقاييس نظام شاملة"""
    cpu_usage: float
    memory_available: float
    memory_total: float
    disk_usage: float
    load_average: tuple
    active_tasks: int
    total_tasks: int
    uptime: float

class EnhancedPeerServer:
    """خادم أقران محسن مع إدارة متقدمة للمهام"""
    
    def __init__(self, port: int = 7520):
        self.app = Flask(__name__)
        self.port = port
        self.hostname = socket.gethostname()
        self.start_time = time.time()
        
        # إدارة المهام
        self.task_history: List[TaskResult] = []
        self.active_tasks: Dict[str, threading.Thread] = {}
        self.available_functions: Dict[str, Callable] = {}
        
        # الإحصائيات
        self.stats = {
            'total_requests': 0,
            'successful_tasks': 0,
            'failed_tasks': 0,
            'total_execution_time': 0.0
        }
        
        # قفل للتزامن
        self._lock = threading.RLock()
        
        # إعداد التطبيق
        self._setup_app()
        self._discover_functions()
    
    def _setup_app(self):
        """إعداد تطبيق Flask مع النقاط النهائية"""
        
        @self.app.before_request
        def limit_request_size():
            """التحقق من حجم الطلب"""
            if request.content_length and request.content_length > MAX_REQUEST_SIZE:
                return jsonify(error="Request too large"), 413
        
        @self.app.errorhandler(404)
        def not_found(error):
            return jsonify(error="Endpoint not found"), 404
        
        @self.app.errorhandler(500)
        def internal_error(error):
            logger.error(f"Internal server error: {error}")
            return jsonify(error="Internal server error"), 500
        
        # النقاط النهائية
        @self.app.route("/")
        def index():
            """الصفحة الرئيسية"""
            return jsonify({
                "service": "Enhanced Peer Server",
                "version": "2.0",
                "hostname": self.hostname,
                "uptime": round(time.time() - self.start_time, 2),
                "endpoints": {
                    "/health": "System health metrics",
                    "/info": "System information",
                    "/run": "Execute tasks (POST)",
                    "/tasks": "Task history and statistics",
                    "/functions": "Available functions"
                }
            })
        
        @self.app.route("/health")
        def health():
            """مقاييس صحة النظام"""
            metrics = self._get_system_metrics()
            return jsonify({
                "status": "healthy",
                "hostname": self.hostname,
                "timestamp": datetime.now().isoformat(),
                "metrics": {
                    "cpu_usage": metrics.cpu_usage,
                    "memory_available_gb": round(metrics.memory_available / (1024**3), 2),
                    "memory_usage_percent": round((1 - metrics.memory_available / metrics.memory_total) * 100, 1),
                    "disk_usage_percent": metrics.disk_usage,
                    "load_average": metrics.load_average,
                    "active_tasks": metrics.active_tasks,
                    "total_tasks_processed": metrics.total_tasks,
                    "uptime_hours": round(metrics.uptime / 3600, 2)
                }
            })
        
        @self.app.route("/info")
        def info():
            """معلومات النظام والوظائف"""
            return jsonify({
                "hostname": self.hostname,
                "ip_address": self._get_local_ip(),
                "port": self.port,
                "available_functions": list(self.available_functions.keys()),
                "task_capabilities": self._get_function_capabilities(),
                "system_info": {
                    "python_version": os.sys.version,
                    "platform": os.sys.platform,
                    "cpu_count": psutil.cpu_count(),
                    "total_memory_gb": round(psutil.virtual_memory().total / (1024**3), 1)
                }
            })
        
        @self.app.route("/run", methods=["POST"])
        def run_task():
            """تنفيذ مهمة مع التحقق المتقدم"""
            self.stats['total_requests'] += 1
            
            # التحقق من نوع المحتوى
            if not request.is_json:
                return jsonify(error="Content-Type must be application/json"), 400
            
            try:
                data = request.get_json(force=True, cache=True)
            except Exception as e:
                return jsonify(error=f"Invalid JSON: {str(e)}"), 400
            
            # التحقق من الحقول المطلوبة
            required_fields = ['func', 'args']
            for field in required_fields:
                if field not in data:
                    return jsonify(error=f"Missing required field: {field}"), 400
            
            function_name = data['func']
            task_id = f"task_{int(time.time()*1000)}_{hash(str(data)) % 10000:04d}"
            
            # التحقق من وجود الوظيفة
            if function_name not in self.available_functions:
                return jsonify(error=f"Function '{function_name}' not found"), 404
            
            # الحصول على وقت البدء
            start_time = time.time()
            
            try:
                # تنفيذ المهمة مع حدود الوقت
                result = self._execute_task_with_timeout(
                    function_name, 
                    data.get('args', []), 
                    data.get('kwargs', {}),
                    timeout=data.get('timeout', DEFAULT_TIMEOUT)
                )
                
                execution_time = time.time() - start_time
                
                # حفظ النتيجة
                task_result = TaskResult(
                    task_id=task_id,
                    function_name=function_name,
                    success=True,
                    result=result,
                    error=None,
                    execution_time=execution_time,
                    timestamp=datetime.now(),
                    hostname=self.hostname
                )
                
                self._add_to_history(task_result)
                self.stats['successful_tasks'] += 1
                self.stats['total_execution_time'] += execution_time
                
                logger.info(f"✅ مهمة ناجحة: {function_name} - {execution_time:.3f} ثانية")
                
                return jsonify({
                    "result": result,
                    "host": self.hostname,
                    "task_id": task_id,
                    "execution_time": round(execution_time, 3),
                    "timestamp": task_result.timestamp.isoformat()
                })
                
            except TimeoutError:
                execution_time = time.time() - start_time
                error_msg = f"Task timed out after {execution_time:.1f} seconds"
                
                task_result = TaskResult(
                    task_id=task_id,
                    function_name=function_name,
                    success=False,
                    result=None,
                    error=error_msg,
                    execution_time=execution_time,
                    timestamp=datetime.now(),
                    hostname=self.hostname
                )
                
                self._add_to_history(task_result)
                self.stats['failed_tasks'] += 1
                
                logger.warning(f"⏰ مهلة المهمة: {function_name}")
                return jsonify(error=error_msg), 408
                
            except Exception as e:
                execution_time = time.time() - start_time
                error_msg = str(e)
                
                task_result = TaskResult(
                    task_id=task_id,
                    function_name=function_name,
                    success=False,
                    result=None,
                    error=error_msg,
                    execution_time=execution_time,
                    timestamp=datetime.now(),
                    hostname=self.hostname
                )
                
                self._add_to_history(task_result)
                self.stats['failed_tasks'] += 1
                
                logger.error(f"❌ فشل المهمة: {function_name} - {error_msg}")
                return jsonify(error=error_msg), 500
        
        @self.app.route("/tasks", methods=["GET"])
        def get_tasks():
            """الحصول على سجل المهام والإحصائيات"""
            recent_tasks = self.task_history[-10:]  # آخر 10 مهام
            
            return jsonify({
                "statistics": {
                    "total_requests": self.stats['total_requests'],
                    "successful_tasks": self.stats['successful_tasks'],
                    "failed_tasks": self.stats['failed_tasks'],
                    "success_rate": round(
                        self.stats['successful_tasks'] / max(self.stats['total_requests'], 1) * 100, 1
                    ),
                    "average_execution_time": round(
                        self.stats['total_execution_time'] / max(self.stats['successful_tasks'], 1), 3
                    ),
                    "currently_active_tasks": len(self.active_tasks)
                },
                "recent_tasks": [
                    {
                        "task_id": task.task_id,
                        "function": task.function_name,
                        "success": task.success,
                        "execution_time": task.execution_time,
                        "timestamp": task.timestamp.isoformat(),
                        "error": task.error
                    }
                    for task in recent_tasks
                ]
            })
        
        @self.app.route("/functions", methods=["GET"])
        def get_functions():
            """الحصول على قائمة الوظائف المتاحة"""
            functions_info = {}
            
            for name, func in self.available_functions.items():
                sig = inspect.signature(func)
                functions_info[name] = {
                    "description": func.__doc__ or "No description available",
                    "parameters": {
                        param.name: {
                            "type": str(param.annotation) if param.annotation != inspect.Parameter.empty else "any",
                            "default": param.default if param.default != inspect.Parameter.empty else None,
                            "required": param.default == inspect.Parameter.empty
                        }
                        for param in sig.parameters.values()
                    },
                    "return_type": str(sig.return_annotation) if sig.return_annotation != inspect.Parameter.empty else "any"
                }
            
            return jsonify(functions_info)
    
    def _discover_functions(self):
        """اكتشاف الوظائف المتاحة تلقائياً"""
        modules_to_check = ['smart_tasks', 'offload_lib']
        
        for module_name in modules_to_check:
            try:
                module = __import__(module_name)
                for name in dir(module):
                    obj = getattr(module, name)
                    if callable(obj) and not name.startswith('_'):
                        self.available_functions[name] = obj
                        logger.info(f"🔍 اكتشاف وظيفة: {name} من {module_name}")
            except ImportError as e:
                logger.warning(f"⚠️ لم يتم العثور على الوحدة {module_name}: {e}")
        
        logger.info(f"✅ تم تحميل {len(self.available_functions)} وظيفة")
    
    def _get_system_metrics(self) -> SystemMetrics:
        """الحصول على مقاييس النظام"""
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        
        return SystemMetrics(
            cpu_usage=psutil.cpu_percent(interval=0.5),
            memory_available=memory.available,
            memory_total=memory.total,
            disk_usage=disk.percent,
            load_average=os.getloadavg() if hasattr(os, 'getloadavg') else (0, 0, 0),
            active_tasks=len(self.active_tasks),
            total_tasks=self.stats['total_requests'],
            uptime=time.time() - self.start_time
        )
    
    def _get_local_ip(self) -> str:
        """الحصول على IP المحلي"""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                return s.getsockname()[0]
        except Exception:
            return "127.0.0.1"
    
    def _get_function_capabilities(self) -> List[str]:
        """الحصول على إمكانيات الوظائف"""
        capabilities = set()
        function_names = list(self.available_functions.keys())
        
        # تحليل أسماء الوظائف لاكتشاف الإمكانيات
        for name in function_names:
            name_lower = name.lower()
            if 'matrix' in name_lower:
                capabilities.add('linear_algebra')
            if 'prime' in name_lower or 'calculation' in name_lower:
                capabilities.add('mathematics')
            if 'image' in name_lower or 'processing' in name_lower:
                capabilities.add('image_processing')
            if 'data' in name_lower:
                capabilities.add('data_processing')
        
        return list(capabilities)
    
    def _execute_task_with_timeout(self, func_name: str, args: list, kwargs: dict, timeout: int = DEFAULT_TIMEOUT):
        """تنفيذ مهمة مع حد زمني"""
        func = self.available_functions[func_name]
        
        # للمهام البسيطة، التنفيذ المباشر
        if timeout >= DEFAULT_TIMEOUT:  # لا حاجة للخيوط للوقت الطويل
            return func(*args, **kwargs)
        
        # للمهام ذات الوقت المحدود، استخدام الخيوط
        result = [None]
        exception = [None]
        
        def worker():
            try:
                result[0] = func(*args, **kwargs)
            except Exception as e:
                exception[0] = e
        
        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        thread.join(timeout=timeout)
        
        if thread.is_alive():
            raise TimeoutError(f"Task exceeded timeout of {timeout} seconds")
        
        if exception[0] is not None:
            raise exception[0]
        
        return result[0]
    
    def _add_to_history(self, task_result: TaskResult):
        """إضافة مهمة إلى السجل"""
        with self._lock:
            self.task_history.append(task_result)
            # الحفاظ على حجم السجل
            if len(self.task_history) > TASK_HISTORY_SIZE:
                self.task_history = self.task_history[-TASK_HISTORY_SIZE:]
    
    def run(self, host: str = "0.0.0.0", port: int = None, debug: bool = False):
        """تشغيل الخادم"""
        if port is None:
            port = self.port
        
        logger.info(f"🚀 بدء خادم الأقران على {host}:{port}")
        logger.info(f"📊 الوظائف المتاحة: {list(self.available_functions.keys())}")
        
        self.app.run(
            host=host,
            port=port,
            debug=debug,
            threaded=True  # تمكين الخيوط لمعالجة متعددة
        )

# التوافق مع الإصدار القديم
def create_legacy_server(port: int = 7520):
    """إنشاء خادم متوافق مع الإصدار القديم"""
    server = EnhancedPeerServer(port)
    return server.app

# التشغيل المباشر
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Enhanced Peer Server")
    parser.add_argument("--port", type=int, default=7520, help="Port to run the server on")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host to bind the server to")
    parser.add_argument("--debug", action="store_true", help="Run in debug mode")
    
    args = parser.parse_args()
    
    server = EnhancedPeerServer(port=args.port)
    server.run(host=args.host, port=args.port, debug=args.debug)