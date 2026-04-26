#!/usr/bin/env python3
"""
منفذ موزع محسن - نظام تنفيذ مهام موزع متقدم
إصدار محسن مع موازنة حمل ذكية وإدارة موارد متقدمة
"""

import threading
import queue
import time
import hashlib
import hmac
from typing import Callable, Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
import socket
import logging
import json
from concurrent.futures import Future, ThreadPoolExecutor

import requests
from zeroconf import Zeroconf, ServiceBrowser, ServiceInfo

from device_manager import DeviceManager, DeviceType
from peer_discovery import PORT

# إعداد اللوجر
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("DistributedExecutor")

class TaskPriority(Enum):
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3

class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    OFFLOADED = "offloaded"

@dataclass
class Task:
    """معلومات المهمة الشاملة"""
    task_id: str
    function: Callable
    args: Tuple[Any, ...]
    kwargs: Dict[str, Any]
    task_type: str
    priority: TaskPriority
    timeout: int = 30
    retry_count: int = 3
    required_capabilities: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    status: TaskStatus = TaskStatus.PENDING
    result: Optional[Any] = None
    error: Optional[str] = None
    executed_by: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """تحويل المهمة إلى قاموس للتسلسل"""
        return {
            "task_id": self.task_id,
            "function_name": self.function.__name__,
            "args": self.args,
            "kwargs": self.kwargs,
            "task_type": self.task_type,
            "priority": self.priority.value,
            "timeout": self.timeout,
            "required_capabilities": self.required_capabilities,
            "created_at": self.created_at
        }

@dataclass
class PeerInfo:
    """معلومات شاملة عن النظير"""
    node_id: str
    ip: str
    port: int
    load: float
    capabilities: List[str]
    last_seen: float
    response_time: float = 0.0
    success_rate: float = 1.0
    is_local: bool = False
    
    @property
    def score(self) -> float:
        """حساب درجة النظير بناءً على معايير متعددة"""
        load_factor = (1 - self.load) * 0.4
        performance_factor = self.success_rate * 0.3
        location_factor = 0.2 if self.is_local else 0.1
        response_factor = max(0, 1 - (self.response_time / 5)) * 0.1
        
        return load_factor + performance_factor + location_factor + response_factor

class SecurePeerRegistry:
    """سجل النظير الآمن مع اكتشاف ديناميكي"""
    
    def __init__(self, shared_secret: str):
        self.shared_secret = shared_secret
        self._peers: Dict[str, PeerInfo] = {}
        self._zeroconf = Zeroconf()
        self.local_node_id = socket.gethostname()
        self._local_ip = self._get_local_ip()
        self._lock = threading.RLock()
        self._is_discovering = False
        
    def _get_local_ip(self) -> str:
        """الحصول على عنوان IP المحلي"""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(('8.8.8.8', 80))
                return s.getsockname()[0]
        except Exception:
            return '127.0.0.1'
    
    def _generate_token(self, data: str) -> str:
        """توليد توكن آمن"""
        return hmac.new(
            self.shared_secret.encode(),
            data.encode(),
            hashlib.sha256
        ).hexdigest()
    
    def register_service(self, name: str, port: int, capabilities: List[str], load: float = 0.0):
        """تسجيل الخدمة مع معلومات شاملة"""
        try:
            properties = {
                b'load': str(load).encode(),
                b'node_id': self.local_node_id.encode(),
                b'capabilities': json.dumps(capabilities).encode(),
                b'token': self._generate_token(f"{name}{port}").encode(),
                b'timestamp': str(time.time()).encode()
            }
            
            service_info = ServiceInfo(
                "_tasknode._tcp.local.",
                f"{name}._tasknode._tcp.local.",
                addresses=[socket.inet_aton(self._local_ip)],
                port=port,
                properties=properties,
                server=f"{name}.local."
            )
            
            self._zeroconf.register_service(service_info)
            logger.info(f"✅ خدمة مسجلة: {name} @ {self._local_ip}:{port}")
            
        except Exception as e:
            logger.error(f"❌ فشل في تسجيل الخدمة: {e}")
    
    def discover_peers(self, timeout: int = 5) -> List[PeerInfo]:
        """اكتشاف النظير مع التحقق من الصحة"""
        class PeerListener:
            def __init__(self, registry):
                self.registry = registry
                self.discovered_peers = []
            
            def add_service(self, zc, type_, name):
                try:
                    info = zc.get_service_info(type_, name, timeout=3000)
                    if info and info.addresses:
                        ip = socket.inet_ntoa(info.addresses[0])
                        
                        # التحقق من الصحة
                        if not self.registry._validate_peer(info):
                            return
                        
                        peer_info = PeerInfo(
                            node_id=info.properties.get(b'node_id', b'unknown').decode(),
                            ip=ip,
                            port=info.port,
                            load=float(info.properties.get(b'load', b'0')),
                            capabilities=json.loads(info.properties.get(b'capabilities', b'[]')),
                            last_seen=time.time(),
                            is_local=self.registry._is_local_network(ip)
                        )
                        
                        self.discovered_peers.append(peer_info)
                        logger.info(f"✅ تم اكتشاف نظير: {peer_info.node_id} @ {ip}")
                        
                except Exception as e:
                    logger.error(f"❌ خطأ في اكتشاف النظير {name}: {e}")
            
            def update_service(self, zc, type_, name):
                self.add_service(zc, type_, name)
            
            def remove_service(self, zc, type_, name):
                try:
                    # إزالة النظير من السجل
                    node_id = name.split('.')[0]
                    with self.registry._lock:
                        if node_id in self.registry._peers:
                            del self.registry._peers[node_id]
                            logger.info(f"🗑️ تم إزالة النظير: {node_id}")
                except Exception as e:
                    logger.error(f"❌ خطأ في إزالة النظير: {e}")
        
        listener = PeerListener(self)
        ServiceBrowser(self._zeroconf, "_tasknode._tcp.local.", listener)
        time.sleep(timeout)
        
        return listener.discovered_peers
    
    def _validate_peer(self, service_info: ServiceInfo) -> bool:
        """التحقق من صحة النظير"""
        try:
            # التحقق من التوكن
            token = service_info.properties.get(b'token')
            if not token:
                return False
            
            # يمكن إضافة المزيد من التحقق هنا
            return True
            
        except Exception:
            return False
    
    def _is_local_network(self, ip: str) -> bool:
        """التحقق إذا كان IP في الشبكة المحلية"""
        try:
            ip_parts = list(map(int, ip.split('.')))
            
            # 192.168.x.x
            if ip_parts[0] == 192 and ip_parts[1] == 168:
                return True
            # 10.x.x.x
            elif ip_parts[0] == 10:
                return True
            # 172.16.x.x - 172.31.x.x
            elif ip_parts[0] == 172 and 16 <= ip_parts[1] <= 31:
                return True
            # localhost
            elif ip == '127.0.0.1':
                return True
            
            return False
        except:
            return False
    
    def start_continuous_discovery(self, interval: int = 10):
        """بدء الاكتشاف المستمر للنظير"""
        if self._is_discovering:
            return
        
        self._is_discovering = True
        
        def discovery_loop():
            while self._is_discovering:
                try:
                    discovered_peers = self.discover_peers()
                    
                    with self._lock:
                        # تحديث النظير الموجودين
                        for peer in discovered_peers:
                            if peer.node_id in self._peers:
                                self._peers[peer.node_id].last_seen = peer.last_seen
                                self._peers[peer.node_id].load = peer.load
                            else:
                                self._peers[peer.node_id] = peer
                        
                        # إزالة النظير المتوقفين
                        current_time = time.time()
                        expired_peers = [
                            node_id for node_id, peer in self._peers.items()
                            if current_time - peer.last_seen > 60  # 60 ثانية
                        ]
                        for node_id in expired_peers:
                            del self._peers[node_id]
                    
                    logger.info(f"🔄 النظير المتاحون: {len(self._peers)}")
                    time.sleep(interval)
                    
                except Exception as e:
                    logger.error(f"❌ خطأ في الاكتشاف المستمر: {e}")
                    time.sleep(interval)
        
        threading.Thread(target=discovery_loop, daemon=True).start()
        logger.info("🚀 بدء الاكتشاف المستمر للنظير")
    
    def stop_continuous_discovery(self):
        """إيقاف الاكتشاف المستمر"""
        self._is_discovering = False
    
    def get_best_peer(self, required_capabilities: List[str] = None) -> Optional[PeerInfo]:
        """الحصول على أفضل نظير للمهمة"""
        with self._lock:
            available_peers = [
                peer for peer in self._peers.values()
                if peer.load < 0.8  # تجنب النظير المشبع
            ]
            
            if required_capabilities:
                available_peers = [
                    peer for peer in available_peers
                    if all(cap in peer.capabilities for cap in required_capabilities)
                ]
            
            if not available_peers:
                return None
            
            # اختيار النظير بأعلى درجة
            return max(available_peers, key=lambda x: x.score)
    
    def update_peer_performance(self, node_id: str, success: bool, response_time: float):
        """تحديث أداء النظير"""
        with self._lock:
            if node_id in self._peers:
                peer = self._peers[node_id]
                peer.response_time = response_time
                
                # تحديث معدل النجاح
                if success:
                    peer.success_rate = min(1.0, peer.success_rate + 0.01)
                else:
                    peer.success_rate = max(0.0, peer.success_rate - 0.05)

class DistributedExecutor:
    """
    منفذ موزع محسن مع موازنة حمل ذكية
    وإدارة موارد متقدمة
    """
    
    def __init__(self, shared_secret: str, max_local_workers: int = 4):
        self.shared_secret = shared_secret
        self.peer_registry = SecurePeerRegistry(shared_secret)
        self.device_manager = DeviceManager()
        
        # إدارة المهام
        self.task_queue = queue.PriorityQueue()
        self.tasks: Dict[str, Task] = {}
        self.task_futures: Dict[str, Future] = {}
        
        # تنفيذ محلي
        self.local_executor = ThreadPoolExecutor(max_workers=max_local_workers)
        
        # إحصائيات
        self.stats = {
            "tasks_submitted": 0,
            "tasks_completed": 0,
            "tasks_failed": 0,
            "tasks_offloaded": 0,
            "local_executions": 0,
            "remote_executions": 0
        }
        
        self._lock = threading.RLock()
        self._is_running = False
        self._task_processor_thread: Optional[threading.Thread] = None
        
        # بدء الخدمات
        self._start_services()
    
    def _start_services(self):
        """بدء الخدمات الخلفية"""
        # بدء الاكتشاف المستمر
        self.peer_registry.start_continuous_discovery()
        
        # بدء معالجة المهام
        self._is_running = True
        self._task_processor_thread = threading.Thread(
            target=self._task_processing_loop,
            daemon=True
        )
        self._task_processor_thread.start()
        
        # تسجيل الخدمة المحلية
        self._register_local_service()
        
        logger.info("🚀 نظام التنفيذ الموزع جاهز")
    
    def _register_local_service(self):
        """تسجيل الخدمة المحلية"""
        capabilities = ["computation", "storage", "general"]
        current_load = self._calculate_local_load()
        
        self.peer_registry.register_service(
            name=self.peer_registry.local_node_id,
            port=PORT,
            capabilities=capabilities,
            load=current_load
        )
    
    def _calculate_local_load(self) -> float:
        """حساب الحمل المحلي"""
        try:
            cpu_load = self.device_manager.get_device_load(DeviceType.CPU)
            memory_load = self.device_manager.get_device_load(DeviceType.MEMORY)
            return max(cpu_load, memory_load) / 100.0
        except:
            return 0.0
    
    def submit(self, func: Callable, *args, 
               task_type: str = "general",
               priority: TaskPriority = TaskPriority.NORMAL,
               timeout: int = 30,
               required_capabilities: List[str] = None,
               **kwargs) -> Future:
        """
        إرسال مهمة للتنفيذ مع خيارات متقدمة
        """
        task_id = f"{func.__name__}_{int(time.time() * 1000)}_{hashlib.md5(str(args).encode()).hexdigest()[:8]}"
        
        task = Task(
            task_id=task_id,
            function=func,
            args=args,
            kwargs=kwargs,
            task_type=task_type,
            priority=priority,
            timeout=timeout,
            required_capabilities=required_capabilities or []
        )
        
        # تخزين المهمة
        with self._lock:
            self.tasks[task_id] = task
            self.stats["tasks_submitted"] += 1
        
        # إضافة إلى قائمة الانتظار
        self.task_queue.put((priority.value, time.time(), task_id))
        
        # إنشاء Future للمهمة
        future = Future()
        self.task_futures[task_id] = future
        
        return future
    
    def _task_processing_loop(self):
        """حلقة معالجة المهام"""
        while self._is_running:
            try:
                # الحصول على مهمة من قائمة الانتظار
                priority, timestamp, task_id = self.task_queue.get(timeout=1.0)
                
                task = self.tasks.get(task_id)
                if not task:
                    continue
                
                # اتخاذ قرار التنفيذ
                execution_decision = self._make_execution_decision(task)
                
                if execution_decision == "local":
                    self._execute_local(task)
                elif execution_decision == "offload":
                    self._offload_task(task)
                else:
                    # إعادة المحاولة لاحقاً
                    self.task_queue.put((priority, timestamp, task_id))
                    time.sleep(0.1)
                    
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"❌ خطأ في معالجة المهمة: {e}")
    
    def _make_execution_decision(self, task: Task) -> str:
        """اتخاذ قرار تنفيذ المهمة"""
        # حساب الحمل المحلي
        local_load = self._calculate_local_load()
        
        # الحصول على أفضل نظير
        best_peer = self.peer_registry.get_best_peer(task.required_capabilities)
        
        # منطق اتخاذ القرار
        if local_load > 0.8:  # حمل مرتفع محلياً
            return "offload" if best_peer else "local"
        elif local_load < 0.4:  # حمل منخفض محلياً
            return "local"
        else:  # حمل متوسط
            if best_peer and best_peer.load < local_load - 0.1:  # النظير أفضل
                return "offload"
            else:
                return "local"
    
    def _execute_local(self, task: Task):
        """تنفيذ المهمة محلياً"""
        try:
            task.status = TaskStatus.RUNNING
            task.executed_by = self.peer_registry.local_node_id
            
            def execute():
                start_time = time.time()
                try:
                    result = task.function(*task.args, **task.kwargs)
                    execution_time = time.time() - start_time
                    
                    task.status = TaskStatus.COMPLETED
                    task.result = result
                    
                    # تحديث الإحصائيات
                    with self._lock:
                        self.stats["tasks_completed"] += 1
                        self.stats["local_executions"] += 1
                    
                    # إكمال Future
                    future = self.task_futures.get(task.task_id)
                    if future and not future.done():
                        future.set_result(result)
                    
                    logger.info(f"✅ تم تنفيذ المهمة محلياً: {task.task_id} في {execution_time:.2f} ثانية")
                    
                except Exception as e:
                    task.status = TaskStatus.FAILED
                    task.error = str(e)
                    
                    with self._lock:
                        self.stats["tasks_failed"] += 1
                    
                    future = self.task_futures.get(task.task_id)
                    if future and not future.done():
                        future.set_exception(e)
                    
                    logger.error(f"❌ فشل تنفيذ المهمة محلياً: {task.task_id} - {e}")
            
            # التنفيذ في خلفية
            self.local_executor.submit(execute)
            
        except Exception as e:
            logger.error(f"❌ خطأ في جدولة التنفيذ المحلي: {e}")
    
    def _offload_task(self, task: Task):
        """نقل المهمة إلى نظير"""
        try:
            best_peer = self.peer_registry.get_best_peer(task.required_capabilities)
            if not best_peer:
                logger.warning("⚠️ لا توجد نظير متاحة - التنفيذ محلياً")
                self._execute_local(task)
                return
            
            task.status = TaskStatus.OFFLOADED
            
            def send_task():
                start_time = time.time()
                try:
                    # إعداد بيانات المهمة
                    task_data = task.to_dict()
                    task_data['token'] = self._generate_task_token(task_data)
                    
                    # إرسال المهمة
                    url = f"http://{best_peer.ip}:{best_peer.port}/execute"
                    response = requests.post(
                        url,
                        json=task_data,
                        timeout=task.timeout
                    )
                    response.raise_for_status()
                    
                    response_time = time.time() - start_time
                    result = response.json()
                    
                    # تحديث أداء النظير
                    self.peer_registry.update_peer_performance(
                        best_peer.node_id, True, response_time
                    )
                    
                    # معالجة النتيجة
                    task.result = result.get('result')
                    task.executed_by = best_peer.node_id
                    
                    with self._lock:
                        self.stats["tasks_completed"] += 1
                        self.stats["tasks_offloaded"] += 1
                        self.stats["remote_executions"] += 1
                    
                    # إكمال Future
                    future = self.task_futures.get(task.task_id)
                    if future and not future.done():
                        future.set_result(task.result)
                    
                    logger.info(f"✅ تم نقل المهمة إلى {best_peer.node_id}: {task.task_id}")
                    
                except Exception as e:
                    response_time = time.time() - start_time
                    self.peer_registry.update_peer_performance(
                        best_peer.node_id, False, response_time
                    )
                    
                    logger.error(f"❌ فشل نقل المهمة إلى {best_peer.node_id}: {e}")
                    
                    # إعادة المحاولة محلياً
                    self._execute_local(task)
            
            # إرسال في خلفية
            threading.Thread(target=send_task, daemon=True).start()
            
        except Exception as e:
            logger.error(f"❌ خطأ في نقل المهمة: {e}")
            self._execute_local(task)
    
    def _generate_task_token(self, task_data: Dict[str, Any]) -> str:
        """توليد توكن آمن للمهمة"""
        data_str = json.dumps(task_data, sort_keys=True)
        return hmac.new(
            self.shared_secret.encode(),
            data_str.encode(),
            hashlib.sha256
        ).hexdigest()
    
    def get_stats(self) -> Dict[str, Any]:
        """الحصول على إحصائيات النظام"""
        with self._lock:
            stats = self.stats.copy()
            stats["pending_tasks"] = self.task_queue.qsize()
            stats["registered_tasks"] = len(self.tasks)
            stats["available_peers"] = len(self.peer_registry._peers)
            stats["local_load"] = self._calculate_local_load()
        
        return stats
    
    def shutdown(self):
        """إيقاف النظام بشكل آمن"""
        self._is_running = False
        self.peer_registry.stop_continuous_discovery()
        self.local_executor.shutdown(wait=True)
        logger.info("🛑 تم إيقاف نظام التنفيذ الموزع")

# مثال على الاستخدام
if __name__ == "__main__":
    def example_processing(data):
        """مثال على دالة معالجة"""
        time.sleep(1)  # محاكاة معالجة
        return f"تمت معالجة: {data}"
    
    # إنشاء المنفذ
    executor = DistributedExecutor("my_secure_secret_key")
    
    try:
        # إرسال مهام متنوعة
        futures = []
        for i in range(5):
            future = executor.submit(
                example_processing,
                f"بيانات {i}",
                task_type="computation",
                priority=TaskPriority.NORMAL,
                required_capabilities=["computation"]
            )
            futures.append(future)
        
        # انتظار النتائج
        for i, future in enumerate(futures):
            try:
                result = future.result(timeout=30)
                print(f"✅ نتيجة المهمة {i}: {result}")
            except Exception as e:
                print(f"❌ فشل المهمة {i}: {e}")
        
        # عرض الإحصائيات
        stats = executor.get_stats()
        print("\n📊 إحصائيات النظام:")
        for key, value in stats.items():
            print(f"  {key}: {value}")
            
    except KeyboardInterrupt:
        print("\nإيقاف النظام...")
    finally:
        executor.shutdown()