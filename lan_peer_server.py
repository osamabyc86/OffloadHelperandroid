#!/usr/bin/env python3
"""
خادم النظير المحلي المحسن - نظام تنفيذ مهام متقدم للشبكة المحلية
إصدار محسن مع ديناميكية كاملة وإدارة موارد متقدمة
"""

import logging
import time
import json
import hashlib
import hmac
import secrets
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from datetime import datetime
import threading
import concurrent.futures
import psutil
import GPUtil

from flask import Flask, request, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_cors import CORS
from zeroconf import Zeroconf, ServiceInfo
#!/usr/bin/env python3
"""
خادم النظير المحلي المحسن
"""

import logging
import time
import json
import hashlib
import hmac
import secrets
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from datetime import datetime
import threading
import concurrent.futures
import psutil
import GPUtil

from flask import Flask, request, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_cors import CORS
from zeroconf import Zeroconf, ServiceInfo

# استيراد مدير المنافذ
try:
    from port_manager import PortManager
    port_manager = PortManager()
    DEFAULT_PORT = port_manager.get_available_port()
except:
    DEFAULT_PORT = 7520

class LanPeerServer:
    def __init__(self, port: int = None, shared_secret: str = None):
        self.port = port or DEFAULT_PORT
        # باقي الكود يبقى كما هو...
# إعداد اللوجر
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("LanPeerServer")

class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

class NodeStatus(Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    OVERLOADED = "overloaded"
    MAINTENANCE = "maintenance"

@dataclass
class TaskInfo:
    """معلومات المهمة الشاملة"""
    task_id: str
    function_name: str
    args: List[Any]
    kwargs: Dict[str, Any]
    priority: int
    submitted_at: float
    status: TaskStatus = TaskStatus.PENDING
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    result: Optional[Any] = None
    error: Optional[str] = None
    client_ip: Optional[str] = None
    
    @property
    def execution_time(self) -> Optional[float]:
        """زمن التنفيذ"""
        if self.started_at and self.completed_at:
            return self.completed_at - self.started_at
        return None

@dataclass
class SystemMetrics:
    """مقاييس أداء النظام"""
    cpu_percent: float
    memory_percent: float
    memory_used: int
    memory_total: int
    gpu_percent: float = 0.0
    gpu_memory_used: int = 0
    gpu_memory_total: int = 0
    disk_usage: float = 0.0
    active_tasks: int = 0
    total_tasks_processed: int = 0
    timestamp: float = field(default_factory=time.time)

class LanPeerServer:
    """
    خادم نظير محلي محسن مع إدارة موارد ذكية
    وتسجيل ديناميكي في الشبكة
    """
    
    def __init__(self, port: int = 7520, shared_secret: str = None):
        self.port = port
        self.shared_secret = shared_secret or secrets.token_urlsafe(32)
        self.node_id = self._generate_node_id()
        
        # إعداد Flask
        self.app = Flask(__name__)
        self.setup_flask()
        
        # إدارة المهام والموارد
        self.tasks: Dict[str, TaskInfo] = {}
        self.registered_functions: Dict[str, Callable] = {}
        self.system_metrics = SystemMetrics(0, 0, 0, 0)
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=10)
        
        # اكتشاف الخدمة
        self.zeroconf = Zeroconf()
        self.service_info: Optional[ServiceInfo] = None
        
        # الإحصائيات
        self.stats = {
            "tasks_received": 0,
            "tasks_completed": 0,
            "tasks_failed": 0,
            "uptime": time.time()
        }
        
        self._lock = threading.RLock()
        self._is_running = False
        self._metrics_thread: Optional[threading.Thread] = None
        
        # التسجيل التلقائي للدوال
        self._register_builtin_functions()
    
    def _generate_node_id(self) -> str:
        """توليد معرف فريد للعقدة"""
        hostname = psutil.users()[0].name if psutil.users() else "unknown"
        return f"{hostname}-{secrets.token_urlsafe(4)}"
    
    def setup_flask(self):
        """إعداد تطبيق Flask"""
        # إعداد CORS آمن
        CORS(self.app, origins=[
            "http://localhost:3000", 
            "http://127.0.0.1:3000",
            "http://localhost:5000",
            "http://127.0.0.1:5000"
        ])
        
        # إعداد معدل الطلبات
        self.limiter = Limiter(
            app=self.app,
            key_func=get_remote_address,
            default_limits=["200 per day", "50 per hour"]
        )
        
        # تسجيل مسارات API
        self.setup_routes()
    
    def setup_routes(self):
        """إعداد مسارات API"""
        
        @self.app.route('/execute', methods=['POST'])
        @self.limiter.limit("30 per minute")
        def execute_task():
            """تنفيذ مهمة مع التحقق من الصحة"""
            return self._handle_task_execution()
        
        @self.app.route('/health', methods=['GET'])
        @self.limiter.exempt
        def health_check():
            """فحص صحة الخادم"""
            return self._handle_health_check()
        
        @self.app.route('/status', methods=['GET'])
        @self.limiter.limit("10 per minute")
        def get_status():
            """الحصول على حالة الخادم"""
            return self._handle_status_request()
        
        @self.app.route('/metrics', methods=['GET'])
        @self.limiter.limit("20 per minute")
        def get_metrics():
            """الحصول على مقاييس النظام"""
            return self._handle_metrics_request()
        
        @self.app.route('/functions', methods=['GET'])
        @self.limiter.limit("10 per minute")
        def list_functions():
            """قائمة الدوال المسجلة"""
            return jsonify({
                "functions": list(self.registered_functions.keys()),
                "total_functions": len(self.registered_functions)
            })
        
        @self.app.route('/tasks/<task_id>', methods=['GET'])
        @self.limiter.limit("30 per minute")
        def get_task_status(task_id):
            """الحصول على حالة مهمة محددة"""
            return self._handle_task_status(task_id)
        
        @self.app.route('/system/info', methods=['GET'])
        @self.limiter.limit("10 per minute")
        def system_info():
            """معلومات النظام"""
            return jsonify(self._get_system_info())
    
    def _register_builtin_functions(self):
        """تسجيل الدوال المضمنة"""
        self.register_function("add", self._function_add)
        self.register_function("multiply", self._function_multiply)
        self.register_function("process_data", self._function_process_data)
        self.register_function("analyze_text", self._function_analyze_text)
        self.register_function("simulate_work", self._function_simulate_work)
    
    def register_function(self, name: str, func: Callable):
        """تسجيل دالة جديدة للتنفيذ"""
        self.registered_functions[name] = func
        logger.info(f"تم تسجيل الدالة: {name}")
    
    def _function_add(self, a: float, b: float) -> float:
        """دالة الجمع"""
        return a + b
    
    def _function_multiply(self, a: float, b: float) -> float:
        """دالة الضرب"""
        return a * b
    
    def _function_process_data(self, data: List[Any], operation: str = "sort") -> List[Any]:
        """معالجة البيانات"""
        if operation == "sort":
            return sorted(data)
        elif operation == "reverse":
            return list(reversed(data))
        elif operation == "unique":
            return list(set(data))
        else:
            raise ValueError(f"عملية غير معروفة: {operation}")
    
    def _function_analyze_text(self, text: str) -> Dict[str, Any]:
        """تحليل النص"""
        words = text.split()
        return {
            "word_count": len(words),
            "character_count": len(text),
            "average_word_length": sum(len(word) for word in words) / len(words) if words else 0,
            "unique_words": len(set(words))
        }
    
    def _function_simulate_work(self, duration: float = 1.0, complexity: int = 1) -> Dict[str, Any]:
        """محاكاة عمل معقد"""
        start_time = time.time()
        
        # محاكاة عمل حسابي
        result = 0
        for i in range(complexity * 1000000):
            result += i * 0.000001
        
        execution_time = time.time() - start_time
        
        # التأكد من المدة المطلوبة
        if execution_time < duration:
            time.sleep(duration - execution_time)
        
        return {
            "result": result,
            "requested_duration": duration,
            "actual_duration": max(execution_time, duration),
            "complexity": complexity
        }
    
    def _validate_task_request(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """التحقق من صحة طلب المهمة"""
        if not data:
            return {"error": "بيانات JSON مطلوبة"}, 400
        
        required_fields = ["task_id", "function"]
        for field in required_fields:
            if field not in data:
                return {"error": f"الحقل {field} مطلوب"}, 400
        
        function_name = data["function"]
        if function_name not in self.registered_functions:
            return {"error": f"الدالة {function_name} غير مسجلة"}, 404
        
        # التحقق من الحمل الحالي
        if self.system_metrics.cpu_percent > 90 or self.system_metrics.memory_percent > 90:
            return {"error": "الخادم مشغول حاليًا، يرجى المحاولة لاحقًا"}, 503
        
        return None
    
    def _handle_task_execution(self):
        """معالجة تنفيذ المهمة"""
        try:
            data = request.get_json()
            
            # التحقق من الصحة
            validation_error = self._validate_task_request(data)
            if validation_error:
                return jsonify(validation_error[0]), validation_error[1]
            
            task_id = data["task_id"]
            function_name = data["function"]
            args = data.get("args", [])
            kwargs = data.get("kwargs", {})
            priority = data.get("priority", 1)
            
            # إنشاء سجل المهمة
            task_info = TaskInfo(
                task_id=task_id,
                function_name=function_name,
                args=args,
                kwargs=kwargs,
                priority=priority,
                submitted_at=time.time(),
                client_ip=request.remote_addr
            )
            
            with self._lock:
                self.tasks[task_id] = task_info
                self.stats["tasks_received"] += 1
            
            # تنفيذ المهمة في الخلفية
            self.executor.submit(self._execute_task, task_info)
            
            return jsonify({
                "status": "accepted",
                "task_id": task_id,
                "message": "تم قبول المهمة للتنفيذ"
            })
            
        except Exception as e:
            logger.error(f"خطأ في معالجة المهمة: {e}")
            return jsonify({"error": str(e)}), 500
    
    def _execute_task(self, task_info: TaskInfo):
        """تنفيذ المهمة الفعلي"""
        try:
            task_info.status = TaskStatus.RUNNING
            task_info.started_at = time.time()
            
            logger.info(f"بدء تنفيذ المهمة: {task_info.function_name} - {task_info.task_id}")
            
            # تنفيذ الدالة
            function = self.registered_functions[task_info.function_name]
            result = function(*task_info.args, **task_info.kwargs)
            
            task_info.status = TaskStatus.COMPLETED
            task_info.completed_at = time.time()
            task_info.result = result
            
            with self._lock:
                self.stats["tasks_completed"] += 1
            
            logger.info(f"تم تنفيذ المهمة: {task_info.function_name} - {task_info.task_id} في {task_info.execution_time:.2f} ثانية")
            
        except Exception as e:
            task_info.status = TaskStatus.FAILED
            task_info.error = str(e)
            task_info.completed_at = time.time()
            
            with self._lock:
                self.stats["tasks_failed"] += 1
            
            logger.error(f"فشل تنفيذ المهمة {task_info.task_id}: {e}")
    
    def _handle_health_check(self):
        """معالجة فحص الصحة"""
        metrics = self._collect_system_metrics()
        return jsonify({
            "status": "healthy",
            "node_id": self.node_id,
            "timestamp": datetime.now().isoformat(),
            "load": {
                "cpu": metrics.cpu_percent,
                "memory": metrics.memory_percent,
                "active_tasks": metrics.active_tasks
            }
        })
    
    def _handle_status_request(self):
        """معالجة طلب الحالة"""
        with self._lock:
            pending_tasks = len([t for t in self.tasks.values() if t.status == TaskStatus.PENDING])
            running_tasks = len([t for t in self.tasks.values() if t.status == TaskStatus.RUNNING])
            
            status_info = {
                "node_id": self.node_id,
                "status": "online",
                "uptime": time.time() - self.stats["uptime"],
                "tasks": {
                    "pending": pending_tasks,
                    "running": running_tasks,
                    "completed": self.stats["tasks_completed"],
                    "failed": self.stats["tasks_failed"],
                    "total_received": self.stats["tasks_received"]
                },
                "resources": {
                    "cpu": self.system_metrics.cpu_percent,
                    "memory": self.system_metrics.memory_percent,
                    "active_tasks": self.system_metrics.active_tasks
                },
                "registered_functions": len(self.registered_functions)
            }
        
        return jsonify(status_info)
    
    def _handle_metrics_request(self):
        """معالجة طلب المقاييس"""
        return jsonify(self.system_metrics.__dict__)
    
    def _handle_task_status(self, task_id: str):
        """معالجة طلب حالة المهمة"""
        task_info = self.tasks.get(task_id)
        if not task_info:
            return jsonify({"error": "المهمة غير موجودة"}), 404
        
        task_data = {
            "task_id": task_info.task_id,
            "function": task_info.function_name,
            "status": task_info.status.value,
            "submitted_at": task_info.submitted_at,
            "started_at": task_info.started_at,
            "completed_at": task_info.completed_at,
            "execution_time": task_info.execution_time,
            "client_ip": task_info.client_ip
        }
        
        if task_info.status == TaskStatus.COMPLETED:
            task_data["result"] = task_info.result
        elif task_info.status == TaskStatus.FAILED:
            task_data["error"] = task_info.error
        
        return jsonify(task_data)
    
    def _collect_system_metrics(self) -> SystemMetrics:
        """جمع مقاييس أداء النظام"""
        try:
            # CPU و Memory
            cpu_percent = psutil.cpu_percent(interval=0.1)
            memory = psutil.virtual_memory()
            
            # GPU
            gpu_percent = 0.0
            gpu_memory_used = 0
            gpu_memory_total = 0
            try:
                gpus = GPUtil.getGPUs()
                if gpus:
                    gpu = gpus[0]
                    gpu_percent = gpu.load * 100
                    gpu_memory_used = gpu.memoryUsed
                    gpu_memory_total = gpu.memoryTotal
            except Exception:
                pass
            
            # Disk
            disk_usage = psutil.disk_usage('/').percent
            
            # المهام النشطة
            active_tasks = len([t for t in self.tasks.values() if t.status == TaskStatus.RUNNING])
            
            metrics = SystemMetrics(
                cpu_percent=cpu_percent,
                memory_percent=memory.percent,
                memory_used=memory.used,
                memory_total=memory.total,
                gpu_percent=gpu_percent,
                gpu_memory_used=gpu_memory_used,
                gpu_memory_total=gpu_memory_total,
                disk_usage=disk_usage,
                active_tasks=active_tasks,
                total_tasks_processed=self.stats["tasks_completed"] + self.stats["tasks_failed"]
            )
            
            self.system_metrics = metrics
            return metrics
            
        except Exception as e:
            logger.error(f"خطأ في جمع مقاييس النظام: {e}")
            return SystemMetrics(0, 0, 0, 0)
    
    def _get_system_info(self) -> Dict[str, Any]:
        """الحصول على معلومات النظام"""
        import platform
        return {
            "node_id": self.node_id,
            "hostname": platform.node(),
            "os": f"{platform.system()} {platform.release()}",
            "processor": platform.processor(),
            "python_version": platform.python_version(),
            "server_uptime": time.time() - self.stats["uptime"],
            "registered_functions": list(self.registered_functions.keys())
        }
    
    def _start_metrics_collection(self):
        """بدء جمع المقاييس بشكل دوري"""
        while self._is_running:
            try:
                self._collect_system_metrics()
                time.sleep(5)  # كل 5 ثواني
            except Exception as e:
                logger.error(f"خطأ في جمع المقاييس: {e}")
                time.sleep(10)
    
    def register_service(self):
        """تسجيل الخدمة في الشبكة المحلية"""
        try:
            local_ip = self._get_local_ip()
            capabilities = list(self.registered_functions.keys())
            
            self.service_info = ServiceInfo(
                "_lanpeer._tcp.local.",
                f"{self.node_id}._lanpeer._tcp.local.",
                addresses=[socket.inet_aton(local_ip)],
                port=self.port,
                properties={
                    b'node_id': self.node_id.encode(),
                    b'capabilities': json.dumps(capabilities).encode(),
                    b'load': str(self.system_metrics.cpu_percent).encode(),
                    b'version': b'2.0.0'
                },
                server=f"{self.node_id}.local."
            )
            
            self.zeroconf.register_service(self.service_info)
            logger.info(f"✅ الخدمة مسجلة: {self.node_id} @ {local_ip}:{self.port}")
            
        except Exception as e:
            logger.error(f"❌ فشل في تسجيل الخدمة: {e}")
    
    def _get_local_ip(self) -> str:
        """الحصول على عنوان IP المحلي"""
        try:
            import socket
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(('8.8.8.8', 80))
                return s.getsockname()[0]
        except Exception:
            return '127.0.0.1'
    
    def start(self):
        """بدء تشغيل الخادم"""
        self._is_running = True
        
        # بدء جمع المقاييس
        self._metrics_thread = threading.Thread(target=self._start_metrics_collection, daemon=True)
        self._metrics_thread.start()
        
        # تسجيل الخدمة
        self.register_service()
        
        logger.info(f"🚀 بدء تشغيل خادم النظير المحلي على المنفذ {self.port}")
        self.app.run(host='0.0.0.0', port=self.port, debug=False)
    
    def stop(self):
        """إيقاف الخادم"""
        self._is_running = False
        
        if self.service_info:
            self.zeroconf.unregister_service(self.service_info)
        
        self.zeroconf.close()
        self.executor.shutdown(wait=True)
        
        logger.info("🛑 إيقاف خادم النظير المحلي")

# تشغيل الخادم
if __name__ == '__main__':
    server = LanPeerServer(port=7520)
    
    try:
        server.start()
    except KeyboardInterrupt:
        logger.info("إيقاف الخادم...")
    finally:
        server.stop()