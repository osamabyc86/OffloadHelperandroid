#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
مدير مركزي محسن للمهام الموزعة
إصدار متقدم مع إدارة ذكية للعقد وتوازن حمل متطور
"""

import time
import threading
import asyncio
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

import aiohttp
import async_timeout
from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field, field_validator
import redis.asyncio as redis

# إعداد اللوجر مع دعم Unicode
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('central_manager.log', encoding='utf-8')
    ]
)
logger = logging.getLogger("CentralManager")

# ---- إدارة المنافذ المحسنة ----
try:
    from port_manager import PortManager
    port_manager = PortManager()
    DEFAULT_PORT = port_manager.get_available_port()
    logger.info(f"🚀 تم تحديد المنفذ الافتراضي: {DEFAULT_PORT}")
except ImportError:
    DEFAULT_PORT = 1500
    logger.warning("⚠️ استخدام المنفذ الافتراضي (1500) - port_manager غير متوفر")
except Exception as e:
    DEFAULT_PORT = 1500
    logger.warning(f"⚠️ استخدام المنفذ الافتراضي (1500) - خطأ: {e}")

# ---- نماذج البيانات المحسنة (Pydantic V2) ----

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

class RegisterRequest(BaseModel):
    """طلب تسجيل العقدة مع معلومات شاملة"""
    node_id: str = Field(..., description="معرف فريد للعقدة")
    url: str = Field(..., description="رابط الواجهة للعقدة")
    capabilities: List[str] = Field(default=["general"], description="القدرات المتاحة")
    max_concurrent_tasks: int = Field(default=10, description="أقصى مهام متزامنة")
    current_load: float = Field(default=0.0, ge=0.0, le=1.0, description="الحمل الحالي")
    metadata: Dict[str, Any] = Field(default={}, description="معلومات إضافية")

    @field_validator('url')
    @classmethod
    def validate_url(cls, v: str) -> str:
        """التحقق من صحة رابط العقدة"""
        if not v.startswith(('http://', 'https://')):
            raise ValueError('يجب أن يبدأ الرابط بـ http:// أو https://')
        return v

class TaskRequest(BaseModel):
    """طلب تنفيذ مهمة مع خيارات متقدمة"""
    task_id: str = Field(..., description="معرف فريد للمهمة")
    func: str = Field(..., description="اسم الدالة المنفذة")
    args: List[Any] = Field(default=[], description="معاملات الدالة")
    kwargs: Dict[str, Any] = Field(default={}, description="معاملات مفتاحية")
    priority: TaskPriority = Field(default=TaskPriority.NORMAL, description="أولوية المهمة")
    timeout: int = Field(default=30, ge=1, le=300, description="الحد الزمني بالثواني (1-300)")
    retry_count: int = Field(default=3, ge=0, le=10, description="عدد محاولات إعادة المحاولة")
    required_capabilities: List[str] = Field(default=[], description="القدرات المطلوبة")
    callback_url: Optional[str] = Field(None, description="رابط الاستدعاء عند الانتهاء")

    @field_validator('task_id')
    @classmethod
    def validate_task_id(cls, v: str) -> str:
        """التحقق من معرف المهمة"""
        if not v or len(v.strip()) == 0:
            raise ValueError('معرف المهمة لا يمكن أن يكون فارغاً')
        return v.strip()

class TaskResult(BaseModel):
    """نتيجة تنفيذ المهمة"""
    task_id: str
    success: bool
    result: Optional[Any] = None
    error: Optional[str] = None
    executed_by: str
    execution_time: float
    timestamp: datetime = Field(default_factory=datetime.now)

@dataclass
class NodeInfo:
    """معلومات شاملة عن العقدة"""
    node_id: str
    url: str
    capabilities: List[str]
    max_concurrent_tasks: int
    current_load: float
    status: NodeStatus
    last_heartbeat: datetime
    metadata: Dict[str, Any]
    active_tasks: int = 0
    total_tasks_processed: int = 0
    success_rate: float = 1.0
    response_time_avg: float = 0.0

    @property
    def available_slots(self) -> int:
        """عدد المهام المتاحة"""
        return max(0, self.max_concurrent_tasks - self.active_tasks)

    @property
    def effective_load(self) -> float:
        """الحمل الفعال للعقدة"""
        return max(self.current_load, self.active_tasks / max(1, self.max_concurrent_tasks))

    def is_available_for(self, task: TaskRequest) -> bool:
        """التحقق من قدرة العقدة على تنفيذ المهمة"""
        if self.status != NodeStatus.ONLINE:
            return False
        
        if self.available_slots <= 0:
            return False
        
        # التحقق من القدرات المطلوبة
        if task.required_capabilities:
            if not all(cap in self.capabilities for cap in task.required_capabilities):
                return False
        
        return self.effective_load < 0.9  # تجنب العقد المشبعة

# ---- فئة المدير المركزي المحسنة --------------------------------------------

class CentralTaskManager:
    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self.nodes: Dict[str, NodeInfo] = {}
        self.task_history: Dict[str, TaskResult] = {}
        self.redis_url = redis_url
        self.redis_client: Optional[redis.Redis] = None
        self._lock = threading.RLock()
        self._health_check_task: Optional[asyncio.Task] = None
        self._metrics_task: Optional[asyncio.Task] = None
        
        # إحصائيات
        self.metrics = {
            "tasks_dispatched": 0,
            "tasks_completed": 0,
            "tasks_failed": 0,
            "total_nodes_registered": 0,
            "current_active_nodes": 0,
            "startup_time": datetime.now()
        }

    async def initialize(self):
        """تهيئة المدير والاتصال بقاعدة البيانات"""
        try:
            self.redis_client = redis.from_url(
                self.redis_url, 
                encoding="utf-8", 
                decode_responses=True,
                socket_connect_timeout=5,
                retry_on_timeout=True
            )
            await self.redis_client.ping()
            logger.info("✅ تم الاتصال بـ Redis بنجاح")
        except Exception as e:
            logger.warning(f"⚠️ فشل الاتصال بـ Redis: {e}")
            self.redis_client = None
        
        await self._load_persistent_data()
        
        # بدء المهام الخلفية
        self._health_check_task = asyncio.create_task(self._health_check_loop())
        self._metrics_task = asyncio.create_task(self._metrics_collection_loop())
        
        logger.info("🚀 تم تهيئة Central Task Manager")

    async def _load_persistent_data(self):
        """تحميل البيانات المستمرة من Redis"""
        if not self.redis_client:
            return
            
        try:
            # تحميل العقد من Redis إذا كانت موجودة
            nodes_data = await self.redis_client.get("central_manager_nodes")
            if nodes_data:
                nodes_dict = json.loads(nodes_data)
                for node_id, node_data in nodes_dict.items():
                    # تحويل البيانات إلى NodeInfo
                    self.nodes[node_id] = NodeInfo(
                        node_id=node_data["node_id"],
                        url=node_data["url"],
                        capabilities=node_data["capabilities"],
                        max_concurrent_tasks=node_data["max_concurrent_tasks"],
                        current_load=node_data["current_load"],
                        status=NodeStatus(node_data["status"]),
                        last_heartbeat=datetime.fromisoformat(node_data["last_heartbeat"]),
                        metadata=node_data["metadata"],
                        active_tasks=node_data.get("active_tasks", 0),
                        total_tasks_processed=node_data.get("total_tasks_processed", 0),
                        success_rate=node_data.get("success_rate", 1.0)
                    )
                logger.info(f"📥 تم تحميل {len(self.nodes)} عقدة من التخزين المستمر")
        except Exception as e:
            logger.warning(f"⚠️ فشل في تحميل البيانات المستمرة: {e}")

    async def _save_persistent_data(self):
        """حفظ البيانات في Redis"""
        if not self.redis_client:
            return
            
        try:
            nodes_data = {}
            for node_id, node in self.nodes.items():
                nodes_data[node_id] = {
                    "node_id": node.node_id,
                    "url": node.url,
                    "capabilities": node.capabilities,
                    "max_concurrent_tasks": node.max_concurrent_tasks,
                    "current_load": node.current_load,
                    "status": node.status.value,
                    "last_heartbeat": node.last_heartbeat.isoformat(),
                    "metadata": node.metadata,
                    "active_tasks": node.active_tasks,
                    "total_tasks_processed": node.total_tasks_processed,
                    "success_rate": node.success_rate
                }
            
            await self.redis_client.set(
                "central_manager_nodes", 
                json.dumps(nodes_data, ensure_ascii=False),
                ex=3600  # انتهاء بعد ساعة
            )
        except Exception as e:
            logger.warning(f"⚠️ فشل في حفظ البيانات المستمرة: {e}")

    async def register_node(self, request: RegisterRequest) -> Dict[str, Any]:
        """تسجيل عقدة جديدة أو تحديث عقدة موجودة"""
        with self._lock:
            node_info = NodeInfo(
                node_id=request.node_id,
                url=request.url,
                capabilities=request.capabilities,
                max_concurrent_tasks=request.max_concurrent_tasks,
                current_load=request.current_load,
                status=NodeStatus.ONLINE,
                last_heartbeat=datetime.now(),
                metadata=request.metadata
            )
            
            is_new = request.node_id not in self.nodes
            self.nodes[request.node_id] = node_info
            
            if is_new:
                self.metrics["total_nodes_registered"] += 1
                logger.info(f"✅ عقدة جديدة مسجلة: {request.node_id} - {request.url}")
            else:
                logger.info(f"🔄 تحديث عقدة: {request.node_id}")
            
            # حفظ البيانات
            await self._save_persistent_data()
            
            return {
                "status": "success",
                "node_id": request.node_id,
                "is_new": is_new,
                "total_nodes": len(self.nodes)
            }

    async def unregister_node(self, node_id: str):
        """إلغاء تسجيل عقدة"""
        with self._lock:
            if node_id in self.nodes:
                del self.nodes[node_id]
                await self._save_persistent_data()
                logger.info(f"🗑️ تم إلغاء تسجيل العقدة: {node_id}")

    async def find_best_node(self, task: TaskRequest) -> Optional[NodeInfo]:
        """إيجاد أفضل عقدة للمهمة باستخدام خوارزمية متقدمة"""
        with self._lock:
            available_nodes = [
                node for node in self.nodes.values() 
                if node.is_available_for(task)
            ]
            
            if not available_nodes:
                logger.warning(f"⚠️ لا توجد عقد متاحة للمهمة {task.task_id}")
                return None

            # خوارزمية تسجيل متعددة العوامل
            scored_nodes = []
            for node in available_nodes:
                score = self._calculate_node_score(node, task)
                scored_nodes.append((score, node))
            
            # اختيار العقدة بأعلى درجة
            scored_nodes.sort(key=lambda x: x[0], reverse=True)
            best_node = scored_nodes[0][1] if scored_nodes else None
            
            if best_node:
                logger.debug(f"🎯 أفضل عقدة للمهمة {task.task_id}: {best_node.node_id} (درجة: {scored_nodes[0][0]:.2f})")
            
            return best_node

    def _calculate_node_score(self, node: NodeInfo, task: TaskRequest) -> float:
        """حساب درجة العقدة بناءً على معايير متعددة"""
        score = 0.0
        
        # عامل الحمل (40%)
        load_factor = (1 - node.effective_load) * 0.4
        
        # عامل القدرات (30%)
        capability_factor = 1.0
        if task.required_capabilities:
            matching_caps = len([cap for cap in task.required_capabilities if cap in node.capabilities])
            capability_factor = (matching_caps / len(task.required_capabilities)) * 0.3
        else:
            capability_factor = 0.3
        
        # عامل الأداء التاريخي (20%)
        performance_factor = node.success_rate * 0.2
        
        # عامل وقت الاستجابة (10%)
        response_factor = max(0, 1 - (node.response_time_avg / 10)) * 0.1
        
        score = load_factor + capability_factor + performance_factor + response_factor
        return min(1.0, score)  # التأكد من عدم تجاوز 1.0

    async def dispatch_task(self, task: TaskRequest) -> Dict[str, Any]:
        """توجيه المهمة إلى العقدة المناسبة"""
        # التحقق من صحة المهمة
        if not task.task_id:
            raise HTTPException(status_code=400, detail="معرف المهمة مطلوب")
        
        best_node = await self.find_best_node(task)
        if not best_node:
            raise HTTPException(
                status_code=503, 
                detail="لا توجد عقد متاحة حاليًا لتنفيذ هذه المهمة"
            )

        try:
            # تحديث إحصائيات العقدة
            best_node.active_tasks += 1
            
            # إرسال المهمة
            async with aiohttp.ClientSession() as session:
                async with async_timeout.timeout(task.timeout):
                    async with session.post(
                        f"{best_node.url}/execute",
                        json=task.model_dump(),
                        headers={"Content-Type": "application/json"}
                    ) as response:
                        result_data = await response.json()
                        
                        # تسجيل النتيجة
                        task_result = TaskResult(
                            task_id=task.task_id,
                            success=result_data.get("success", False),
                            result=result_data.get("result"),
                            error=result_data.get("error"),
                            executed_by=best_node.node_id,
                            execution_time=result_data.get("execution_time", 0)
                        )
                        
                        await self._record_task_result(task_result, best_node)
                        self.metrics["tasks_dispatched"] += 1
                        
                        logger.info(f"📤 تم توجيه المهمة {task.task_id} إلى {best_node.node_id}")
                        
                        return {
                            "success": True,
                            "node_id": best_node.node_id,
                            "result": result_data,
                            "dispatched_at": datetime.now().isoformat()
                        }
                        
        except asyncio.TimeoutError:
            logger.error(f"⏰ انتهى وقت المهمة {task.task_id}")
            raise HTTPException(status_code=504, detail="انتهى الوقت المخصص لتنفيذ المهمة")
        except Exception as e:
            logger.error(f"❌ فشل في توجيه المهمة {task.task_id} إلى {best_node.node_id}: {e}")
            raise HTTPException(status_code=502, detail=f"فشل في تنفيذ المهمة: {e}")
        finally:
            best_node.active_tasks -= 1

    async def _record_task_result(self, result: TaskResult, node: NodeInfo):
        """تسجيل نتيجة المهمة وتحديث إحصائيات العقدة"""
        with self._lock:
            self.task_history[result.task_id] = result
            
            # تحديث إحصائيات العقدة
            node.total_tasks_processed += 1
            if result.success:
                self.metrics["tasks_completed"] += 1
                logger.info(f"✅ تم إكمال المهمة {result.task_id} بنجاح")
            else:
                self.metrics["tasks_failed"] += 1
                logger.error(f"❌ فشل المهمة {result.task_id}: {result.error}")
            
            # تحديث معدل النجاح
            total_successful = node.total_tasks_processed * node.success_rate
            if result.success:
                total_successful += 1
            node.success_rate = total_successful / max(1, node.total_tasks_processed)

    async def get_system_status(self) -> Dict[str, Any]:
        """الحصول على حالة النظام الشاملة"""
        with self._lock:
            online_nodes = [node for node in self.nodes.values() if node.status == NodeStatus.ONLINE]
            total_tasks = self.metrics["tasks_completed"] + self.metrics["tasks_failed"]
            
            return {
                "total_nodes": len(self.nodes),
                "online_nodes": len(online_nodes),
                "total_tasks_processed": total_tasks,
                "success_rate": (
                    self.metrics["tasks_completed"] / total_tasks 
                    if total_tasks > 0 else 1.0
                ),
                "average_load": (
                    sum(node.effective_load for node in online_nodes) / len(online_nodes) 
                    if online_nodes else 0
                ),
                "uptime": (datetime.now() - self.metrics["startup_time"]).total_seconds(),
                "nodes": [
                    {
                        "node_id": node.node_id,
                        "status": node.status.value,
                        "load": round(node.effective_load, 3),
                        "active_tasks": node.active_tasks,
                        "available_slots": node.available_slots,
                        "capabilities": node.capabilities,
                        "success_rate": round(node.success_rate, 3)
                    }
                    for node in self.nodes.values()
                ]
            }

    async def _health_check_loop(self):
        """حلقة فحص صحة العقد بشكل دوري"""
        while True:
            try:
                await self._perform_health_checks()
                await asyncio.sleep(30)  # كل 30 ثانية
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"🔧 خطأ في فحص الصحة: {e}")
                await asyncio.sleep(60)

    async def _perform_health_checks(self):
        """إجراء فحوصات الصحة لجميع العقد"""
        tasks = []
        for node_id, node in list(self.nodes.items()):
            tasks.append(self._check_node_health(node_id, node))
        
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for node_id, result in zip(self.nodes.keys(), results):
                if isinstance(result, Exception):
                    logger.warning(f"⚠️ فشل فحص صحة العقدة {node_id}: {result}")

    async def _check_node_health(self, node_id: str, node: NodeInfo):
        """فحص صحة عقدة محددة"""
        try:
            async with aiohttp.ClientSession() as session:
                async with async_timeout.timeout(5):
                    async with session.get(f"{node.url}/health") as response:
                        if response.status == 200:
                            health_data = await response.json()
                            node.status = NodeStatus.ONLINE
                            node.current_load = health_data.get("load", 0.0)
                            node.last_heartbeat = datetime.now()
                        else:
                            node.status = NodeStatus.OFFLINE
                            logger.warning(f"🔴 العقدة {node_id} غير متاحة (HTTP {response.status})")
        except Exception as e:
            node.status = NodeStatus.OFFLINE
            logger.warning(f"🔴 فشل فحص صحة العقدة {node_id}: {e}")

    async def _metrics_collection_loop(self):
        """حلقة جمع المقاييس والإحصائيات"""
        while True:
            try:
                await self._update_metrics()
                await asyncio.sleep(60)  # كل دقيقة
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"📊 خطأ في جمع المقاييس: {e}")
                await asyncio.sleep(120)

    async def _update_metrics(self):
        """تحديث المقاييس والحفاظ عليها"""
        self.metrics["current_active_nodes"] = len([
            node for node in self.nodes.values() 
            if node.status == NodeStatus.ONLINE
        ])
        
        # حفظ المقاييس في Redis
        if self.redis_client:
            try:
                await self.redis_client.set(
                    "central_manager_metrics",
                    json.dumps(self.metrics, default=str, ensure_ascii=False),
                    ex=300  # انتهاء بعد 5 دقائق
                )
            except Exception as e:
                logger.warning(f"⚠️ فشل في حفظ المقاييس: {e}")

    async def shutdown(self):
        """إيقاف المدير بشكل آمن"""
        logger.info("🛑 إيقاف Central Task Manager...")
        
        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass
        
        if self._metrics_task:
            self._metrics_task.cancel()
            try:
                await self._metrics_task
            except asyncio.CancelledError:
                pass
        
        if self.redis_client:
            await self.redis_client.close()
        
        logger.info("✅ تم إيقاف Central Task Manager")

# ---- إعداد FastAPI والتوابع -------------------------------------------------

# اعتماديات الأمان
security = HTTPBearer()

async def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """التحقق من صحة التوكن"""
    # في البيئة الحقيقية، تحقق من التوكن ضد قاعدة بيانات أو خدمة
    expected_token = "your-secret-token"  # يجب أن يكون من تكوين آمن
    if credentials.credentials != expected_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="توكن غير صالح",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials

# إنشاء المدير
manager = CentralTaskManager()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """إدارة دورة حياة التطبيق"""
    # بدء التشغيل
    logger.info("🚀 بدء تشغيل Central Task Manager...")
    await manager.initialize()
    yield
    # الإيقاف
    await manager.shutdown()

app = FastAPI(
    title="Central Task Manager - Advanced",
    description="نظام إدارة مهام موزع متطور مع توازن حمل ذكي",
    version="2.0.0",
    lifespan=lifespan
)

# إعداد CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # في الإنتاج، حدد النطاقات المسموحة
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- مسارات API المحسنة ----------------------------------------------------

@app.post("/register", response_model=Dict[str, Any])
async def register_peer(request: RegisterRequest): #, token: str = Depends(verify_token)):
    """تسجيل عقدة جديدة في النظام"""
    return await manager.register_node(request)

@app.post("/unregister/{node_id}")
async def unregister_peer(node_id: str): #, token: str = Depends(verify_token)):
    """إلغاء تسجيل عقدة"""
    await manager.unregister_node(node_id)
    return {"status": "success", "message": f"تم إلغاء تسجيل العقدة {node_id}"}

@app.post("/dispatch", response_model=Dict[str, Any])
async def dispatch_task(task: TaskRequest): #, token: str = Depends(verify_token)):
    """توجيه مهمة إلى العقدة المناسبة"""
    return await manager.dispatch_task(task)

@app.get("/status", response_model=Dict[str, Any])
async def get_status(): #, token: str = Depends(verify_token)):
    """الحصول على حالة النظام الشاملة"""
    return await manager.get_system_status()

@app.get("/nodes", response_model=List[Dict[str, Any]])
async def list_nodes(): #, token: str = Depends(verify_token)):
    """قائمة بالعقد المتاحة مع معلومات مفصلة"""
    return [
        {
            "node_id": node.node_id,
            "url": node.url,
            "status": node.status.value,
            "load": round(node.effective_load, 3),
            "capabilities": node.capabilities,
            "active_tasks": node.active_tasks,
            "available_slots": node.available_slots,
            "success_rate": round(node.success_rate, 3),
            "last_heartbeat": node.last_heartbeat.isoformat()
        }
        for node in manager.nodes.values()
    ]

@app.get("/tasks/{task_id}", response_model=TaskResult)
async def get_task_result(task_id: str): #, token: str = Depends(verify_token)):
    """الحصول على نتيجة مهمة محددة"""
    if task_id not in manager.task_history:
        raise HTTPException(status_code=404, detail="المهمة غير موجودة")
    return manager.task_history[task_id]

@app.get("/health")
async def health_check():
    """فحص صحة الخدمة"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "version": "2.0.0"
    }

# ---- تشغيل التطبيق ---------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        app, 
        host="0.0.0.0", 
        port=DEFAULT_PORT,
        log_level="info",
        access_log=True,
        log_config=None  # استخدام إعدادات اللوجر المخصصة
    )
