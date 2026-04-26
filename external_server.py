#!/usr/bin/env python3
"""
الخادم الخارجي المحسن - نظام مركزي متقدم لتوزيع المهام ولوحة تحكم تفاعلية
إصدار محسن مع إدارة ذكية للنظير وأمان متقدم
"""

import logging
import asyncio
import aiohttp
import time
import json
import secrets
import queue  # إضافة استيراد queue
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from datetime import datetime, timedelta
import threading

from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_httpauth import HTTPTokenAuth

# استيراد مدير المنافذ
try:
    from port_manager import PortManager
    port_manager = PortManager()
    DEFAULT_PORT = port_manager.get_available_port()
except:
    DEFAULT_PORT = 7531

# إعداد اللوجر
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("ExternalServer")

# ---- نماذج البيانات --------------------------------------------------------

class NodeStatus(Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    OVERLOADED = "overloaded"
    MAINTENANCE = "maintenance"

class TaskPriority(Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"

@dataclass
class NodeInfo:
    """معلومات شاملة عن العقدة"""
    node_id: str
    url: str
    ip_address: str
    status: NodeStatus
    capabilities: List[str]
    cpu_load: float
    memory_load: float
    gpu_load: float
    last_seen: datetime
    response_time: float = 0.0
    success_rate: float = 1.0
    total_tasks_processed: int = 0
    active_tasks: int = 0
    max_concurrent_tasks: int = 10
    
    @property
    def overall_load(self) -> float:
        """الحمل الكلي للعقدة"""
        return max(self.cpu_load, self.memory_load, self.gpu_load)
    
    @property
    def is_available(self) -> bool:
        """التحقق من توفر العقدة"""
        return (self.status == NodeStatus.ONLINE and 
                self.overall_load < 85 and
                self.active_tasks < self.max_concurrent_tasks)
    
    @property
    def score(self) -> float:
        """حساب درجة العقدة لاختيار الأفضل"""
        load_factor = (1 - self.overall_load / 100) * 0.4
        performance_factor = self.success_rate * 0.3
        response_factor = max(0, 1 - (self.response_time / 10)) * 0.2
        capacity_factor = (1 - self.active_tasks / self.max_concurrent_tasks) * 0.1
        
        return load_factor + performance_factor + response_factor + capacity_factor

@dataclass
class TaskInfo:
    """معلومات المهمة"""
    task_id: str
    function_name: str
    args: List[Any]
    kwargs: Dict[str, Any]
    priority: TaskPriority
    submitted_at: datetime
    status: str = "pending"
    assigned_node: Optional[str] = None
    result: Optional[Any] = None
    error: Optional[str] = None
    execution_time: Optional[float] = None

@dataclass
class SystemMetrics:
    """مقاييس أداء النظام"""
    total_nodes: int = 0
    online_nodes: int = 0
    total_tasks_processed: int = 0
    successful_tasks: int = 0
    failed_tasks: int = 0
    average_response_time: float = 0.0
    system_uptime: float = 0.0

# ---- فئة مدير الخادم المركزي ----------------------------------------------

class CentralServerManager:
    """مدير الخادم المركزي المتقدم"""
    
    def __init__(self, config_file: str = "server_config.json"):
        self.nodes: Dict[str, NodeInfo] = {}
        self.tasks: Dict[str, TaskInfo] = {}
        self.task_queue = queue.Queue()
        self._lock = threading.RLock()
        self._is_running = False
        self._task_dispatcher_thread: Optional[threading.Thread] = None
        self._health_check_thread: Optional[threading.Thread] = None
        
        # التكوين
        self.config_file = Path(config_file)
        self.load_config()
        
        # الإحصائيات
        self.metrics = SystemMetrics()
        self.start_time = time.time()
        
        # جلسة HTTP غير متزامنة
        self.session: Optional[aiohttp.ClientSession] = None
    
    def load_config(self):
        """تحميل تكوين الخادم"""
        default_config = {
            "server_port": DEFAULT_PORT,
            "health_check_interval": 30,
            "task_timeout": 30,
            "max_retries": 3,
            "enable_auth": True,
            "allowed_origins": ["http://localhost:3000", "http://127.0.0.1:3000"],
            "rate_limits": {
                "submit_task": "100/hour",
                "update_status": "500/hour",
                "dashboard": "1000/hour"
            }
        }
        
        try:
            if self.config_file.exists():
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    self.config = json.load(f)
            else:
                self.config = default_config
                self.save_config()
        except Exception as e:
            logger.error(f"فشل في تحميل التكوين: {e}")
            self.config = default_config
    
    def save_config(self):
        """حفظ التكوين"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"فشل في حفظ التكوين: {e}")
    
    async def initialize(self):
        """تهيئة المدير"""
        self.session = aiohttp.ClientSession()
        self.start_services()
        logger.info("🚀 بدء تشغيل الخادم المركزي")
    
    def start_services(self):
        """بدء الخدمات الخلفية"""
        self._is_running = True
        
        # بدء موزع المهام
        self._task_dispatcher_thread = threading.Thread(
            target=self._task_dispatch_loop,
            daemon=True
        )
        self._task_dispatcher_thread.start()
        
        # بدء فحص صحة العقد
        self._health_check_thread = threading.Thread(
            target=self._health_check_loop,
            daemon=True
        )
        self._health_check_thread.start()
    
    def stop_services(self):
        """إيقاف الخدمات"""
        self._is_running = False
        
        if self.session:
            # استخدام حلقة منفصلة لإغلاق الجلسة
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(self.session.close())
                loop.close()
            except Exception as e:
                logger.error(f"خطأ في إغلاق الجلسة: {e}")
        
        logger.info("🛑 إيقاف الخادم المركزي")
    
    def register_node(self, node_id: str, url: str, ip_address: str, 
                     capabilities: List[str], initial_load: Dict[str, float]) -> NodeInfo:
        """تسجيل عقدة جديدة"""
        with self._lock:
            node_info = NodeInfo(
                node_id=node_id,
                url=url,
                ip_address=ip_address,
                status=NodeStatus.ONLINE,
                capabilities=capabilities,
                cpu_load=initial_load.get('cpu', 0),
                memory_load=initial_load.get('memory', 0),
                gpu_load=initial_load.get('gpu', 0),
                last_seen=datetime.now()
            )
            
            self.nodes[node_id] = node_info
            self.metrics.total_nodes += 1
            self.metrics.online_nodes += 1
            
            logger.info(f"عقدة مسجلة: {node_id} من {ip_address}")
            return node_info
    
    def update_node_status(self, node_id: str, load_metrics: Dict[str, float], 
                          active_tasks: int = 0):
        """تحديث حالة العقدة"""
        with self._lock:
            if node_id in self.nodes:
                node = self.nodes[node_id]
                node.cpu_load = load_metrics.get('cpu', node.cpu_load)
                node.memory_load = load_metrics.get('memory', node.memory_load)
                node.gpu_load = load_metrics.get('gpu', node.gpu_load)
                node.active_tasks = active_tasks
                node.last_seen = datetime.now()
                node.status = NodeStatus.ONLINE
    
    def get_best_node(self, required_capabilities: List[str] = None) -> Optional[NodeInfo]:
        """الحصول على أفضل عقدة للمهمة"""
        with self._lock:
            available_nodes = [
                node for node in self.nodes.values() 
                if node.is_available
            ]
            
            if required_capabilities:
                available_nodes = [
                    node for node in available_nodes
                    if all(cap in node.capabilities for cap in required_capabilities)
                ]
            
            if not available_nodes:
                return None
            
            # اختيار العقدة بأعلى درجة
            return max(available_nodes, key=lambda x: x.score)
    
    async def submit_task(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """إرسال مهمة للتنفيذ"""
        task_id = task_data.get('task_id')
        if not task_id:
            return {"error": "معرف المهمة مطلوب"}, 400
        
        # إنشاء سجل المهمة
        task_info = TaskInfo(
            task_id=task_id,
            function_name=task_data.get('function', 'unknown'),
            args=task_data.get('args', []),
            kwargs=task_data.get('kwargs', {}),
            priority=TaskPriority(task_data.get('priority', 'normal')),
            submitted_at=datetime.now()
        )
        
        with self._lock:
            self.tasks[task_id] = task_info
        
        # إضافة إلى قائمة الانتظار
        priority_value = {
            TaskPriority.LOW: 4,
            TaskPriority.NORMAL: 3,
            TaskPriority.HIGH: 2,
            TaskPriority.CRITICAL: 1
        }.get(task_info.priority, 3)
        
        self.task_queue.put((priority_value, task_id))
        
        return {"status": "accepted", "task_id": task_id}
    
    def _task_dispatch_loop(self):
        """حلقة توزيع المهام"""
        while self._is_running:
            try:
                # انتظار مهمة
                priority, task_id = self.task_queue.get(timeout=1.0)
                
                task_info = self.tasks.get(task_id)
                if not task_info:
                    continue
                
                # العثور على أفضل عقدة
                best_node = self.get_best_node(task_info.kwargs.get('required_capabilities', []))
                
                if best_node:
                    # تشغيل الدالة غير المتزامنة في حلقة منفصلة
                    asyncio.run(self._assign_task_to_node(task_info, best_node))
                else:
                    # لا توجد عقد متاحة - إعادة المحاولة لاحقاً
                    logger.warning(f"لا توجد عقد متاحة للمهمة {task_id}")
                    time.sleep(5)
                    self.task_queue.put((priority, task_id))
                    
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"خطأ في توزيع المهام: {e}")
                time.sleep(5)
    
    async def _assign_task_to_node(self, task_info: TaskInfo, node: NodeInfo):
        """تعيين مهمة لعقدة محددة"""
        try:
            task_data = {
                "task_id": task_info.task_id,
                "function": task_info.function_name,
                "args": task_info.args,
                "kwargs": task_info.kwargs,
                "priority": task_info.priority.value
            }
            
            start_time = time.time()
            
            async with self.session.post(
                f"{node.url}/execute",
                json=task_data,
                timeout=self.config.get("task_timeout", 30)
            ) as response:
                
                response_time = time.time() - start_time
                
                if response.status == 200:
                    result = await response.json()
                    
                    # تحديث إحصائيات العقدة
                    with self._lock:
                        node.response_time = response_time
                        node.success_rate = min(1.0, node.success_rate + 0.01)
                        node.total_tasks_processed += 1
                        self.metrics.successful_tasks += 1
                    
                    # تحديث حالة المهمة
                    task_info.status = "completed"
                    task_info.assigned_node = node.node_id
                    task_info.result = result.get('result')
                    task_info.execution_time = response_time
                    
                    logger.info(f"تم تنفيذ المهمة {task_info.task_id} على {node.node_id}")
                    
                else:
                    raise Exception(f"كود الحالة: {response.status}")
                    
        except Exception as e:
            logger.error(f"فشل تعيين المهمة {task_info.task_id} إلى {node.node_id}: {e}")
            
            # تحديث إحصائيات الفشل
            with self._lock:
                node.success_rate = max(0.0, node.success_rate - 0.05)
                self.metrics.failed_tasks += 1
            
            task_info.status = "failed"
            task_info.error = str(e)
            
            # إعادة المحاولة لاحقاً
            time.sleep(2)
            self.task_queue.put((3, task_info.task_id))  # أولوية عادية
    
    def _health_check_loop(self):
        """حلقة فحص صحة العقد"""
        while self._is_running:
            try:
                current_time = datetime.now()
                offline_nodes = []
                
                with self._lock:
                    for node_id, node in self.nodes.items():
                        if (current_time - node.last_seen).total_seconds() > 60:  # 60 ثانية
                            node.status = NodeStatus.OFFLINE
                            offline_nodes.append(node_id)
                    
                    self.metrics.online_nodes = len([
                        node for node in self.nodes.values() 
                        if node.status == NodeStatus.ONLINE
                    ])
                
                if offline_nodes:
                    logger.warning(f"العقد المتوقفة: {offline_nodes}")
                
                time.sleep(self.config.get("health_check_interval", 30))
                
            except Exception as e:
                logger.error(f"خطأ في فحص الصحة: {e}")
                time.sleep(60)
    
    def get_system_overview(self) -> Dict[str, Any]:
        """الحصول على نظرة عامة على النظام"""
        with self._lock:
            self.metrics.system_uptime = time.time() - self.start_time
            self.metrics.total_tasks_processed = self.metrics.successful_tasks + self.metrics.failed_tasks
            
            # حساب متوسط وقت الاستجابة
            response_times = [
                node.response_time for node in self.nodes.values() 
                if node.response_time > 0
            ]
            self.metrics.average_response_time = (
                sum(response_times) / len(response_times) if response_times else 0
            )
            
            overview = {
                "metrics": self.metrics.__dict__,
                "nodes": [
                    {
                        "node_id": node.node_id,
                        "status": node.status.value,
                        "overall_load": node.overall_load,
                        "active_tasks": node.active_tasks,
                        "capabilities": node.capabilities,
                        "success_rate": node.success_rate,
                        "last_seen": node.last_seen.isoformat()
                    }
                    for node in self.nodes.values()
                ],
                "pending_tasks": self.task_queue.qsize(),
                "recent_tasks": [
                    {
                        "task_id": task.task_id,
                        "status": task.status,
                        "assigned_node": task.assigned_node,
                        "submitted_at": task.submitted_at.isoformat()
                    }
                    for task in list(self.tasks.values())[-10:]  # آخر 10 مهام
                ]
            }
        
        return overview

# ---- إعداد تطبيق Flask ----------------------------------------------------

app = Flask(__name__)
app.config['SECRET_KEY'] = secrets.token_urlsafe(32)

# إعداد CORS آمن
CORS(app, origins=["http://localhost:3000", "http://127.0.0.1:3000"])

# إعداد معدل الطلبات
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://"
)

# إعداد SocketIO
socketio = SocketIO(
    app,
    cors_allowed_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    async_mode='threading'
)

# إعداد المصادقة
auth = HTTPTokenAuth(scheme='Bearer')
tokens = {
    "admin": "your-secure-admin-token",
    "node": "your-secure-node-token"
}

@auth.verify_token
def verify_token(token):
    return tokens.get(token)

# إنشاء مدير الخادم
server_manager = CentralServerManager()

# ---- مسارات API -----------------------------------------------------------

@app.route('/')
@limiter.exempt
def index():
    """الصفحة الرئيسية للوحة التحكم"""
    return jsonify({
        "message": "🚀 خادم توزيع المهام الخارجي يعمل",
        "endpoints": {
            "/api/overview": "نظرة عامة على النظام",
            "/api/nodes": "قائمة العقد",
            "/api/tasks": "قائمة المهام",
            "/api/nodes/register": "تسجيل عقدة جديدة (POST)",
            "/api/tasks/submit": "إرسال مهمة جديدة (POST)"
        },
        "version": "2.0.0"
    })

@app.route('/api/overview')
@limiter.limit("10 per minute")
def get_overview():
    """الحصول على نظرة عامة على النظام"""
    return jsonify(server_manager.get_system_overview())

@app.route('/api/nodes')
@limiter.limit("20 per minute")
def get_nodes():
    """الحصول على قائمة العقد"""
    with server_manager._lock:
        nodes_data = [
            {
                "node_id": node.node_id,
                "url": node.url,
                "status": node.status.value,
                "cpu_load": node.cpu_load,
                "memory_load": node.memory_load,
                "gpu_load": node.gpu_load,
                "active_tasks": node.active_tasks,
                "success_rate": node.success_rate,
                "last_seen": node.last_seen.isoformat()
            }
            for node in server_manager.nodes.values()
        ]
    return jsonify(nodes_data)

@app.route('/api/tasks/submit', methods=['POST'])
@limiter.limit("100 per hour")
def submit_task():
    """إرسال مهمة جديدة"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "بيانات JSON مطلوبة"}), 400
        
        # استخدام حلقة منفصلة للدالة غير المتزامنة
        async def submit_async():
            return await server_manager.submit_task(data)
        
        result = asyncio.run(submit_async())
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"خطأ في إرسال المهمة: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/nodes/register', methods=['POST'])
@auth.login_required
def register_node():
    """تسجيل عقدة جديدة"""
    try:
        data = request.get_json()
        node_id = data.get('node_id')
        url = data.get('url')
        ip_address = request.remote_addr
        capabilities = data.get('capabilities', [])
        initial_load = data.get('load', {})
        
        if not node_id or not url:
            return jsonify({"error": "معرف العقدة والرابط مطلوبان"}), 400
        
        node_info = server_manager.register_node(
            node_id, url, ip_address, capabilities, initial_load
        )
        
        # إرسال تحديث للوحة التحكم
        socketio.emit('node_registered', {
            'node_id': node_id,
            'ip_address': ip_address,
            'capabilities': capabilities
        })
        
        return jsonify({
            "status": "success",
            "node_id": node_id,
            "message": "تم تسجيل العقدة بنجاح"
        })
        
    except Exception as e:
        logger.error(f"خطأ في تسجيل العقدة: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/nodes/<node_id>/status', methods=['POST'])
@auth.login_required
def update_node_status(node_id):
    """تحديث حالة العقدة"""
    try:
        data = request.get_json()
        load_metrics = data.get('load', {})
        active_tasks = data.get('active_tasks', 0)
        
        server_manager.update_node_status(node_id, load_metrics, active_tasks)
        
        # إرسال تحديث للوحة التحكم
        socketio.emit('node_updated', {
            'node_id': node_id,
            'load': load_metrics,
            'active_tasks': active_tasks
        })
        
        return jsonify({"status": "success"})
        
    except Exception as e:
        logger.error(f"خطأ في تحديث حالة العقدة: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/tasks')
@limiter.limit("30 per minute")
def get_tasks():
    """الحصول على قائمة المهام"""
    with server_manager._lock:
        tasks_data = [
            {
                "task_id": task.task_id,
                "function": task.function_name,
                "status": task.status,
                "assigned_node": task.assigned_node,
                "submitted_at": task.submitted_at.isoformat(),
                "execution_time": task.execution_time
            }
            for task in server_manager.tasks.values()
        ]
    return jsonify(tasks_data)

# ---- معالجات WebSocket ----------------------------------------------------

@socketio.on('connect')
def handle_connect():
    """معالجة اتصال عميل جديد"""
    join_room('dashboard')
    emit('connection_established', {
        'message': 'تم الاتصال بلوحة التحكم',
        'system_overview': server_manager.get_system_overview()
    })
    logger.info(f"عميل متصل من {request.remote_addr}")

@socketio.on('disconnect')
def handle_disconnect():
    """معالجة انفصال العميل"""
    leave_room('dashboard')
    logger.info(f"عميل منفصل من {request.remote_addr}")

@socketio.on('request_system_update')
def handle_system_update():
    """طلب تحديث حالة النظام"""
    overview = server_manager.get_system_overview()
    emit('system_update', overview)

@socketio.on('send_message')
def handle_chat_message(data):
    """معالجة رسائل الدردشة"""
    message = {
        'id': secrets.token_urlsafe(8),
        'timestamp': datetime.now().isoformat(),
        'message': data.get('message', ''),
        'type': data.get('type', 'chat')
    }
    emit('receive_message', message, room='dashboard')

# ---- تشغيل التطبيق ---------------------------------------------------------

def main():
    """الدالة الرئيسية"""
    try:
        # تهيئة الخادم
        asyncio.run(server_manager.initialize())
        
        # تشغيل تطبيق Flask
        logger.info(f"🚀 تشغيل الخادم الخارجي على المنفذ {DEFAULT_PORT}")
        socketio.run(
            app,
            host="0.0.0.0",
            port=DEFAULT_PORT,
            debug=False,
            allow_unsafe_werkzeug=True
        )
        
    except KeyboardInterrupt:
        logger.info("إيقاف الخادم...")
    except Exception as e:
        logger.error(f"خطأ غير متوقع: {e}")
    finally:
        server_manager.stop_services()

if __name__ == "__main__":
    main()
