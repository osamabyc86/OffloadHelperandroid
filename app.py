initial_preferred_port = 7862
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
نظام توزيع المهام الذكي - الخادم المركزي على Hugging Face
يجمع بين واجهة Gradio وخادم التوزيع المركزي
"""

import os
import sys
import time
import json
import logging
import threading
import random
import queue
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict

import gradio as gr


# --- Gradio Aggressive Reset and Patching Logic ---
try:
    print("--- Attempting aggressive Gradio module reset and patching ---")

    # Function to check if a port is in use
    def is_port_in_use(port):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("localhost", port))
                return False
            except socket.error:
                return True

    # Function to find an available port
    def find_available_port(start_port, max_retries=10):
        current_port = start_port
        for _ in range(max_retries):
            if not is_port_in_use(current_port):
                return current_port
            print(f"Port {current_port} is in use, trying next port...")
            current_port += 1
        raise Exception(f"No available port found after {max_retries} retries starting from {start_port}")

    # Aggressively reset gradio module
    modules_to_delete = [
        m for m in sys.modules if m.startswith('gradio') or m.startswith('gradio.')
    ]
    for module_name in modules_to_delete:
        del sys.modules[module_name]
    print(f"Removed {len(modules_to_delete)} gradio related modules from sys.modules.")

    # Re-import gradio to ensure a clean state after removal
    import gradio as gr
    print("Gradio module re-imported successfully.")

    # Capture original launch methods if not already captured (ensures this happens once per kernel session)
    if not hasattr(sys, '_gradio_original_blocks_launch'):
        sys._gradio_original_blocks_launch = gr.Blocks.launch
        print("Captured original gr.Blocks.launch.")
    if not hasattr(sys, '_gradio_original_interface_launch'):
        sys._gradio_original_interface_launch = gr.Interface.launch
        print("Captured original gr.Interface.launch.")

    # Define the final patched launch function
    def _patched_launch_v_final(self, *args, launch_method, **kwargs):
        global initial_preferred_port # Access the global initial_preferred_port

        # Ensure server_name and server_port are not passed directly in kwargs to avoid conflicts
        kwargs.pop("server_name", None)
        kwargs.pop("server_port", None)

        # Find an available port and set environment variable
        try:
            available_port = find_available_port(initial_preferred_port)
            os.environ["GRADIO_SERVER_PORT"] = str(available_port)
            print(f"Using available port: {available_port}. GRADIO_SERVER_PORT set.")
        except Exception as e:
            print(f"Error finding available port: {e}. Falling back to default Gradio port selection.")
            # If port finding fails, let Gradio handle port selection
            if "GRADIO_SERVER_PORT" in os.environ:
                del os.environ["GRADIO_SERVER_PORT"]

        print(f"Calling original launch method for {self.__class__.__name__} on port {os.environ.get('GRADIO_SERVER_PORT', 'default Gradio port')}")
        # Call the stored original launch method with all arguments
        return launch_method(self, *args, **kwargs)

    # Apply patching to gr.Blocks.launch
    def blocks_launch_wrapper(self, *args, **kwargs):
        return _patched_launch_v_final(self, *args, launch_method=sys._gradio_original_blocks_launch, **kwargs)

    # Apply patching to gr.Interface.launch
    def interface_launch_wrapper(self, *args, **kwargs):
        return _patched_launch_v_final(self, *args, launch_method=sys._gradio_original_interface_launch, **kwargs)

    gr.Blocks.launch = blocks_launch_wrapper
    gr.Interface.launch = interface_launch_wrapper
    print("Gradio gr.Blocks.launch and gr.Interface.launch patched successfully.")

except Exception as e:
    print(f"Error during Gradio module reset or patching: {e}")
    print("Gradio patching might not be active. Proceeding with potentially unpatched Gradio.")
# --- End Gradio Aggressive Reset and Patching Logic ---




from flask import Flask, request, jsonify
from flask_cors import CORS
import requests

# ─────────────── إعداد السجلات ───────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("CentralServerHF")

# ─────────────── هياكل البيانات ───────────────
@dataclass
class NodeInfo:
    """معلومات العقدة المتصلة"""
    node_id: str
    ip: str
    port: int
    url: str
    capabilities: List[str]
    cpu_usage: float = 0.0
    memory_usage: float = 0.0
    status: str = "online"
    last_seen: datetime = field(default_factory=datetime.now)
    success_rate: float = 1.0
    response_time: float = 0.0
    tasks_completed: int = 0
    tasks_failed: int = 0
    current_tasks: int = 0
    weight: float = 1.0  # للأوزان الذكية
    
    @property
    def score(self) -> float:
        """حساب درجة العقدة"""
        health = 0.4 * (100 - (self.cpu_usage + self.memory_usage) / 2) / 100
        performance = 0.3 * self.success_rate
        availability = 0.2 * (1.0 - self.current_tasks / 5)
        speed = 0.1 * max(0, 1 - self.response_time / 10)
        
        return (health + performance + availability + speed) * self.weight

@dataclass
class TaskInfo:
    """معلومات المهمة"""
    task_id: str
    task_type: str
    params: Dict[str, Any]
    sender: str
    status: str = "pending"  # pending, processing, completed, failed
    assigned_to: Optional[str] = None
    result: Optional[Any] = None
    error: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    priority: int = 2  # 1=high, 2=medium, 3=low

# ─────────────── فئة الخادم المركزي ───────────────
class CentralServer:
    """الخادم المركزي الذكي لتوزيع المهام"""
    
    def __init__(self):
        self.nodes: Dict[str, NodeInfo] = {}
        self.tasks: Dict[str, TaskInfo] = {}
        self.task_queue = queue.PriorityQueue()
        self.lock = threading.RLock()
        self.is_running = True
        
        # إحصائيات النظام
        self.metrics = {
            "total_nodes": 0,
            "online_nodes": 0,
            "total_tasks": 0,
            "completed_tasks": 0,
            "failed_tasks": 0,
            "avg_response_time": 0.0,
            "system_uptime": time.time()
        }
        
        # بدء الخدمات الخلفية
        self._start_background_services()
        
        logger.info("🚀 بدء تشغيل الخادم المركزي على Hugging Face")
    
    def _start_background_services(self):
        """بدء الخدمات الخلفية"""
        # خيط توزيع المهام
        self.dispatcher = threading.Thread(target=self._dispatch_loop, daemon=True)
        self.dispatcher.start()
        
        # خيط فحص صحة العقد
        self.health_checker = threading.Thread(target=self._health_check_loop, daemon=True)
        self.health_checker.start()
        
        # خيط محاكاة العقد (للتجربة)
        self.simulator = threading.Thread(target=self._simulate_nodes, daemon=True)
        self.simulator.start()
    
    def register_node(self, node_data: Dict) -> Dict:
        """تسجيل عقدة جديدة"""
        with self.lock:
            node_id = node_data.get('node_id', f"node_{len(self.nodes)+1}")
            
            node = NodeInfo(
                node_id=node_id,
                ip=node_data.get('ip', '127.0.0.1'),
                port=node_data.get('port', 0),
                url=node_data.get('url', ''),
                capabilities=node_data.get('capabilities', ['general']),
                cpu_usage=node_data.get('cpu_usage', 0.0),
                memory_usage=node_data.get('memory_usage', 0.0),
                status='online'
            )
            
            self.nodes[node_id] = node
            self.metrics["total_nodes"] = len(self.nodes)
            self.metrics["online_nodes"] = len([n for n in self.nodes.values() if n.status == 'online'])
            
            logger.info(f"✅ عقدة مسجلة: {node_id}")
            
            return {
                "status": "success",
                "node_id": node_id,
                "message": "تم التسجيل بنجاح",
                "server_time": datetime.now().isoformat()
            }
    
    def update_node_status(self, node_id: str, metrics: Dict):
        """تحديث حالة العقدة"""
        with self.lock:
            if node_id in self.nodes:
                node = self.nodes[node_id]
                
                if 'cpu_usage' in metrics:
                    node.cpu_usage = metrics['cpu_usage']
                if 'memory_usage' in metrics:
                    node.memory_usage = metrics['memory_usage']
                if 'current_tasks' in metrics:
                    node.current_tasks = metrics['current_tasks']
                if 'status' in metrics:
                    node.status = metrics['status']
                
                node.last_seen = datetime.now()
                
                # تحديث معدل النجاح
                total = node.tasks_completed + node.tasks_failed
                if total > 0:
                    node.success_rate = node.tasks_completed / total
                
                return {"status": "updated"}
            
            return {"error": "العقدة غير موجودة"}
    
    def submit_task(self, task_data: Dict) -> Dict:
        """إرسال مهمة جديدة"""
        task_id = task_data.get('task_id', f"task_{int(time.time())}_{random.randint(1000,9999)}")
        
        task = TaskInfo(
            task_id=task_id,
            task_type=task_data.get('task_type', 'general'),
            params=task_data.get('params', {}),
            sender=task_data.get('sender', 'unknown'),
            priority=task_data.get('priority', 2)
        )
        
        with self.lock:
            self.tasks[task_id] = task
            self.metrics["total_tasks"] = len(self.tasks)
        
        # إضافة إلى قائمة الانتظار
        self.task_queue.put((task.priority, task_id))
        
        logger.info(f"📨 مهمة مستلمة: {task_id} ({task.task_type})")
        
        return {
            "status": "accepted",
            "task_id": task_id,
            "queue_position": self.task_queue.qsize(),
            "estimated_wait": self.task_queue.qsize() * 2  # ثانيتين لكل مهمة
        }
    
    def _dispatch_loop(self):
        """حلقة توزيع المهام"""
        while self.is_running:
            try:
                # انتظار مهمة
                priority, task_id = self.task_queue.get(timeout=1.0)
                
                with self.lock:
                    task = self.tasks.get(task_id)
                    if not task or task.status != "pending":
                        continue
                
                # إيجاد أفضل عقدة
                best_node = self._select_best_node(task.task_type)
                
                if best_node:
                    # تعيين المهمة
                    self._assign_task(task, best_node)
                else:
                    # إعادة المحاولة
                    time.sleep(3)
                    self.task_queue.put((priority, task_id))
                    
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"❌ خطأ في التوزيع: {e}")
                time.sleep(5)
    
    def _select_best_node(self, task_type: str) -> Optional[NodeInfo]:
        """اختيار أفضل عقدة للمهمة"""
        with self.lock:
            # فلترة العقد المتاحة
            available = []
            for node in self.nodes.values():
                if node.status != 'online':
                    continue
                if node.cpu_usage > 85 or node.memory_usage > 85:
                    continue
                if node.current_tasks >= 3:
                    continue
                
                # التحقق من القدرات
                capabilities_needed = []
                if task_type in ['matrix', 'fibonacci']:
                    capabilities_needed = ['cpu_intensive']
                elif task_type in ['data', 'processing']:
                    capabilities_needed = ['memory']
                
                if capabilities_needed:
                    if not any(cap in node.capabilities for cap in capabilities_needed):
                        continue
                
                available.append(node)
            
            if not available:
                return None
            
            # اختيار الأعلى درجة
            return max(available, key=lambda n: n.score)
    
    def _assign_task(self, task: TaskInfo, node: NodeInfo):
        """تعيين مهمة لعقدة"""
        try:
            # تحديث حالة المهمة
            with self.lock:
                task.status = "processing"
                task.assigned_to = node.node_id
                task.started_at = datetime.now()
                node.current_tasks += 1
            
            logger.info(f"🎯 تعيين {task.task_id} → {node.node_id}")
            
            # محاكاة التنفيذ
            execution_time = self._simulate_task_execution(task, node)
            
            # تحديث النتيجة
            with self.lock:
                task.status = "completed"
                task.completed_at = datetime.now()
                task.result = {
                    "executed_on": node.node_id,
                    "execution_time": execution_time,
                    "task_type": task.task_type,
                    "result": f"نتيجة محاكاة لـ {task.task_type}"
                }
                
                node.current_tasks -= 1
                node.tasks_completed += 1
                node.response_time = execution_time
                
                self.metrics["completed_tasks"] += 1
            
            logger.info(f"✅ مكتملة: {task.task_id} في {execution_time:.2f}s")
            
        except Exception as e:
            logger.error(f"❌ فشلت المهمة {task.task_id}: {e}")
            
            with self.lock:
                task.status = "failed"
                task.error = str(e)
                self.metrics["failed_tasks"] += 1
                
                if node.node_id in self.nodes:
                    self.nodes[node.node_id].tasks_failed += 1
                    self.nodes[node.node_id].current_tasks -= 1
    
    def _simulate_task_execution(self, task: TaskInfo, node: NodeInfo) -> float:
        """محاكاة تنفيذ المهمة"""
        # أوقات تنفيذ مختلفة حسب نوع المهمة
        base_times = {
            'matrix': 1.5,
            'fibonacci': 0.8,
            'primes': 1.2,
            'data': 0.5,
            'image': 2.0,
            'general': 0.3
        }
        
        base_time = base_times.get(task.task_type, 0.5)
        
        # تأثير حمل العقدة
        load_factor = 1 + (node.cpu_usage + node.memory_usage) / 200
        
        # تأثير حجم المهمة
        size = task.params.get('size', 10) if isinstance(task.params, dict) else 10
        size_factor = 1 + (size / 1000)
        
        # وقت تنفيذ محاكي
        execution_time = base_time * load_factor * size_factor
        
        # محاكاة الانتظار
        time.sleep(min(execution_time, 3.0))
        
        return execution_time
    
    def _health_check_loop(self):
        """فحص صحة العقد"""
        while self.is_running:
            try:
                with self.lock:
                    now = datetime.now()
                    for node in self.nodes.values():
                        # إذا مر أكثر من 2 دقيقة دون تحديث
                        if (now - node.last_seen).total_seconds() > 120:
                            node.status = "offline"
                    
                    # تحديث الإحصائيات
                    self.metrics["online_nodes"] = len(
                        [n for n in self.nodes.values() if n.status == 'online']
                    )
                
                time.sleep(30)
                
            except Exception as e:
                logger.error(f"❌ خطأ في فحص الصحة: {e}")
                time.sleep(60)
    
    def _simulate_nodes(self):
        """محاكاة عقد افتراضية (للتجربة)"""
        # إنشاء عقد افتراضية
        virtual_nodes = [
            {"id": "node_cpu1", "capabilities": ["cpu_intensive"], "cpu": 20, "memory": 40},
            {"id": "node_mem1", "capabilities": ["memory"], "cpu": 30, "memory": 25},
            {"id": "node_gpu1", "capabilities": ["gpu", "image"], "cpu": 25, "memory": 50},
            {"id": "node_gen1", "capabilities": ["general"], "cpu": 15, "memory": 35}
        ]
        
        for vnode in virtual_nodes:
            self.register_node({
                "node_id": vnode["id"],
                "ip": "192.168.1." + str(random.randint(100, 200)),
                "port": random.randint(5000, 6000),
                "url": f"http://192.168.1.{random.randint(100,200)}:{random.randint(5000,6000)}",
                "capabilities": vnode["capabilities"],
                "cpu_usage": vnode["cpu"],
                "memory_usage": vnode["memory"]
            })
        
        # محاكاة تحديثات دورية
        while self.is_running:
            try:
                with self.lock:
                    for node_id in list(self.nodes.keys())[:4]:  # أول 4 عقد (الافتراضية)
                        if node_id in self.nodes:
                            node = self.nodes[node_id]
                            node.cpu_usage = max(5, min(80, node.cpu_usage + random.uniform(-5, 5)))
                            node.memory_usage = max(10, min(70, node.memory_usage + random.uniform(-3, 3)))
                            node.current_tasks = random.randint(0, 2)
                            node.last_seen = datetime.now()
                
                time.sleep(10)
                
            except Exception as e:
                logger.error(f"❌ خطأ في محاكاة العقد: {e}")
                time.sleep(30)
    
    def get_system_overview(self) -> Dict:
        """نظرة عامة على النظام"""
        with self.lock:
            now = datetime.now()
            
            # حساب متوسط وقت الاستجابة
            response_times = [n.response_time for n in self.nodes.values() if n.response_time > 0]
            avg_response = sum(response_times) / len(response_times) if response_times else 0
            
            # المهام الأخيرة
            recent_tasks = list(self.tasks.values())[-10:]  # آخر 10 مهام
            
            return {
                "metrics": {
                    **self.metrics,
                    "uptime": time.time() - self.metrics["system_uptime"],
                    "avg_response_time": avg_response,
                    "queue_size": self.task_queue.qsize(),
                    "timestamp": now.isoformat()
                },
                "nodes": [
                    {
                        "id": n.node_id,
                        "status": n.status,
                        "score": round(n.score, 3),
                        "cpu": n.cpu_usage,
                        "memory": n.memory_usage,
                        "tasks": n.current_tasks,
                        "success_rate": round(n.success_rate, 2),
                        "last_seen": (now - n.last_seen).total_seconds()
                    }
                    for n in self.nodes.values()
                ],
                "recent_tasks": [
                    {
                        "id": t.task_id,
                        "type": t.task_type,
                        "status": t.status,
                        "assigned_to": t.assigned_to,
                        "created": t.created_at.strftime("%H:%M:%S")
                    }
                    for t in recent_tasks
                ]
            }

# ─────────────── إنشاء الخادم المركزي ───────────────
central_server = CentralServer()

# ─────────────── دوال Gradio ───────────────
def get_system_status():
    """الحصول على حالة النظام"""
    overview = central_server.get_system_overview()
    
    metrics = overview["metrics"]
    nodes = overview["nodes"]
    tasks = overview["recent_tasks"]
    
    # تنسيق النص
    status_text = f"""
# 🌐 الخادم المركزي لتوزيع المهام

## 📊 إحصائيات النظام
- **الوقت:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
- **مدة التشغيل:** {metrics['uptime']/3600:.1f} ساعة
- **العقد الإجمالية:** {metrics['total_nodes']}
- **العقد النشطة:** {metrics['online_nodes']}
- **المهام الإجمالية:** {metrics['total_tasks']}
- **المهام المكتملة:** {metrics['completed_tasks']}
- **المهام الفاشلة:** {metrics['failed_tasks']}
- **متوسط وقت الاستجابة:** {metrics['avg_response_time']:.2f} ثانية
- **المهام في الانتظار:** {metrics['queue_size']}

## 👥 العقد المتصلة ({len(nodes)})
"""
    
    for node in nodes:
        status_emoji = "🟢" if node['status'] == 'online' else "🔴" if node['status'] == 'offline' else "🟡"
        status_text += f"\n**{status_emoji} {node['id']}**"
        status_text += f"\n  - النقاط: {node['score']:.3f}"
        status_text += f"\n  - CPU: {node['cpu']:.1f}% | ذاكرة: {node['memory']:.1f}%"
        status_text += f"\n  - المهام النشطة: {node['tasks']}"
        status_text += f"\n  - معدل النجاح: {node['success_rate']*100:.1f}%"
        status_text += f"\n  - آخر ظهور: {node['last_seen']:.0f} ثانية مضت"
    
    if tasks:
        status_text += f"\n\n## 📋 آخر المهام ({len(tasks)})"
        for task in tasks[-5:]:  # آخر 5 مهام
            status_emoji = "🟢" if task['status'] == 'completed' else "🟡" if task['status'] == 'processing' else "🔴"
            status_text += f"\n{status_emoji} **{task['id']}** ({task['type']}) → {task['assigned_to'] or 'في الانتظار'}"
    
    return status_text

def submit_task_ui(task_type, params_json):
    """إرسال مهمة جديدة"""
    try:
        params = json.loads(params_json) if params_json else {}
    except:
        params = {"size": 10}
    
    task_data = {
        "task_type": task_type,
        "params": params,
        "sender": "gradio_ui",
        "priority": 2
    }
    
    result = central_server.submit_task(task_data)
    
    if "error" in result:
        return f"## ❌ خطأ\n{result['error']}"
    
    return f"""
## ✅ تم قبول المهمة

### 📝 معلومات المهمة
- **معرف المهمة:** {result['task_id']}
- **نوع المهمة:** {task_type}
- **الحالة:** في قائمة الانتظار
- **الموقع في الطابور:** {result['queue_position']}
- **الوقت المتوقع:** {result['estimated_wait']} ثانية
- **الوقت:** {datetime.now().strftime('%H:%M:%S')}

### 📊 تتبع المهمة
سيتم تعيين المهمة لأفضل عقدة متاحة تلقائياً.
"""

def get_node_details():
    """الحصول على تفاصيل العقد"""
    overview = central_server.get_system_overview()
    nodes = overview["nodes"]
    
    headers = ["العقدة", "الحالة", "النقاط", "CPU%", "الذاكرة%", "المهام", "معدل النجاح", "آخر ظهور"]
    data = []
    
    for node in nodes:
        status_emoji = "🟢" if node['status'] == 'online' else "🔴"
        data.append([
            node['id'],
            f"{status_emoji} {node['status']}",
            f"{node['score']:.3f}",
            f"{node['cpu']:.1f}",
            f"{node['memory']:.1f}",
            str(node['tasks']),
            f"{node['success_rate']*100:.1f}%",
            f"{node['last_seen']:.0f}s"
        ])
    
    return data

def simulate_new_node():
    """محاكاة عقدة جديدة"""
    node_id = f"node_{int(time.time())}"
    caps = random.choice([['cpu_intensive'], ['memory'], ['general'], ['gpu', 'image']])
    
    result = central_server.register_node({
        "node_id": node_id,
        "ip": f"10.0.0.{random.randint(1, 255)}",
        "port": random.randint(5000, 6000),
        "url": f"http://10.0.0.{random.randint(1,255)}:{random.randint(5000,6000)}",
        "capabilities": caps,
        "cpu_usage": random.uniform(10, 40),
        "memory_usage": random.uniform(20, 60)
    })
    
    return f"## 🆕 عقدة محاكاة\n**{node_id}** - {', '.join(caps)}\n\nتم التسجيل بنجاح!"

def simulate_task_load(count: int):
    """محاكاة حمل مهام"""
    task_types = ['matrix', 'fibonacci', 'primes', 'data', 'image', 'general']
    
    for i in range(min(count, 10)):  # حد أقصى 10 مهام
        task_type = random.choice(task_types)
        central_server.submit_task({
            "task_type": task_type,
            "params": {"size": random.randint(10, 1000)},
            "sender": "simulation",
            "priority": random.randint(1, 3)
        })
        time.sleep(0.1)
    
    return f"## 📨 محاكاة حمل\nتم إرسال {min(count, 10)} مهام عشوائية!"

# ─────────────── واجهة Gradio ───────────────
def create_interface():
    """إنشاء واجهة Gradio"""
    
    with gr.Blocks(
        title="الخادم المركزي لتوزيع المهام",
        theme=gr.themes.Soft(primary_hue="blue", secondary_hue="teal")
    ) as demo:
        gr.Markdown("# 🌐 الخادم المركزي الذكي لتوزيع المهام")
        gr.Markdown("### نسخة Hugging Face Spaces - خادم حقيقي")
        
        with gr.Tabs():
            # تبويب حالة النظام
            with gr.TabItem("📊 لوحة التحكم"):
                status_output = gr.Markdown()
                refresh_btn = gr.Button("🔄 تحديث الحالة", variant="primary")
                
                refresh_btn.click(get_system_status, outputs=status_output)
                demo.load(get_system_status, outputs=status_output)
            
            # تبويب إرسال المهام
            with gr.TabItem("🚀 إرسال المهام"):
                with gr.Row():
                    with gr.Column():
                        gr.Markdown("### إرسال مهمة جديدة")
                        
                        task_type = gr.Dropdown(
                            choices=[
                                ("ضرب المصفوفات (CPU)", "matrix"),
                                ("متسلسلة فيبوناتشي", "fibonacci"),
                                ("الأعداد الأولية", "primes"),
                                ("معالجة البيانات", "data"),
                                ("محاكاة معالجة الصور", "image"),
                                ("مهمة عامة", "general")
                            ],
                            label="نوع المهمة",
                            value="matrix"
                        )
                        
                        params_input = gr.Textbox(
                            label="معاملات المهمة (JSON)",
                            value='{"size": 100}',
                            placeholder='{"size": 100} أو {"limit": 1000}'
                        )
                        
                        submit_btn = gr.Button("📨 إرسال المهمة", variant="primary")
                    
                    with gr.Column():
                        gr.Markdown("### نتيجة الإرسال")
                        task_result = gr.Markdown()
                
                submit_btn.click(submit_task_ui, [task_type, params_input], task_result)
            
            # تبويب العقد
            with gr.TabItem("👥 إدارة العقد"):
                gr.Markdown("### العقد المتصلة")
                nodes_table = gr.Dataframe(
                    headers=["العقدة", "الحالة", "النقاط", "CPU%", "الذاكرة%", "المهام", "معدل النجاح", "آخر ظهور"],
                    interactive=False,
                    datatype=["str", "str", "str", "str", "str", "str", "str", "str"]
                )
                
                with gr.Row():
                    refresh_nodes = gr.Button("🔄 تحديث قائمة العقد")
                    sim_node = gr.Button("➕ محاكاة عقدة جديدة")
                    sim_tasks = gr.Button("📨 محاكاة حمل مهام")
                    task_count = gr.Slider(1, 10, value=3, label="عدد المهام")
                
                sim_result = gr.Markdown()
                
                refresh_nodes.click(get_node_details, outputs=nodes_table)
                sim_node.click(simulate_new_node, outputs=sim_result)
                sim_tasks.click(simulate_task_load, task_count, sim_result)
                demo.load(get_node_details, outputs=nodes_table)
            
            # تبويب المعلومات
            with gr.TabItem("ℹ️ معلومات النظام"):
                gr.Markdown("""
                ## 📖 عن الخادم المركزي
                
                هذا تطبيق **خادم مركزي حقيقي** يعمل على Hugging Face Spaces.
                
                ### ✨ المميزات:
                - **توزيع ذكي للمهام** على أفضل عقدة متاحة
                - **مراقبة في الوقت الفعلي** لجميع العقد
                - **محاكاة متقدمة** للعقد والمهام
                - **إحصائيات مفصلة** عن أداء النظام
                - **واجهة تحكم كاملة** عبر Gradio
                
                ### 🏗️ كيفية العمل:
                1. **العقد تتصل** بالخادم وتسجل نفسها
                2. **المهام ترسل** للخادم المركزي
                3. **الخادم يختار** أفضل عقدة بناءً على:
                   - استخدام CPU والذاكرة
                   - معدل النجاح السابق
                   - عدد المهام النشطة
                   - وقت الاستجابة
                4. **المهام تنفذ** على العقد المختارة
                5. **النتائج ترجع** للخادم
                
                ### 🌐 API المتاح:
                يمكن للعقد الحقيقية الاتصال عبر:
                - `POST /register` - تسجيل عقدة
                - `POST /task/submit` - إرسال مهمة
                - `POST /status/update` - تحديث حالة
                - `GET /nodes` - قائمة العقد
                - `GET /tasks` - قائمة المهام
                
                ### 🔧 التقنيات:
                - Python 3 مع معالجة متعددة الخيوط
                - Gradio للواجهة الأمامية
                - خوارزميات توزيع ذكية
                - نظام محاكاة متكامل
                """)
        
        gr.Markdown("---\n*الخادم المركزي لتوزيع المهام الذكي - الإصدار 3.0.0*")
    
    return demo

# ─────────────── API Flask (للعقد الحقيقية) ───────────────
flask_app = Flask(__name__)
CORS(flask_app)

@flask_app.route('/')
def api_home():
    return jsonify({
        "message": "الخادم المركزي لتوزيع المهام",
        "version": "3.0.0",
        "status": "running",
        "gradio_url": "https://huggingface.co/spaces/your-username/your-space"
    })

@flask_app.route('/register', methods=['POST'])
def api_register():
    try:
        data = request.get_json()
        result = central_server.register_node(data)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@flask_app.route('/task/submit', methods=['POST'])
def api_submit_task():
    try:
        data = request.get_json()
        result = central_server.submit_task(data)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@flask_app.route('/status/update', methods=['POST'])
def api_update_status():
    try:
        data = request.get_json()
        node_id = data.get('node_id')
        if not node_id:
            return jsonify({"error": "معرف العقدة مطلوب"}), 400
        
        result = central_server.update_node_status(node_id, data)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@flask_app.route('/nodes', methods=['GET'])
def api_get_nodes():
    try:
        overview = central_server.get_system_overview()
        return jsonify({
            "status": "success",
            "count": len(overview["nodes"]),
            "nodes": overview["nodes"]
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@flask_app.route('/tasks', methods=['GET'])
def api_get_tasks():
    try:
        with central_server.lock:
            tasks = list(central_server.tasks.values())[-50:]
            tasks_data = []
            for task in tasks:
                task_dict = asdict(task)
                for field in ["created_at", "started_at", "completed_at"]:
                    if task_dict[field]:
                        task_dict[field] = task_dict[field].isoformat()
                tasks_data.append(task_dict)
            
            return jsonify({
                "status": "success",
                "count": len(tasks_data),
                "tasks": tasks_data
            })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@flask_app.route('/stats', methods=['GET'])
def api_get_stats():
    try:
        overview = central_server.get_system_overview()
        return jsonify({
            "status": "success",
            "stats": overview["metrics"]
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ─────────────── بدء Flask في خيط منفصل ───────────────
def start_flask_server():
    """بدء خادم Flask للعقد الحقيقية"""
    port = 7861  # منفذ مختلف عن Gradio
    flask_app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        threaded=True,
        use_reloader=False
    )

# ─────────────── الدالة الرئيسية ───────────────
def main():
    """الدالة الرئيسية"""
    logger.info("🚀 بدء تشغيل تطبيق Hugging Face كخادم مركزي")
    
    # بدء خادم Flask للAPI في خيط منفصل
    flask_thread = threading.Thread(target=start_flask_server, daemon=True)
    flask_thread.start()
    logger.info("✅ بدء خادم Flask API على المنفذ 7861")
    
    # إنشاء واجهة Gradio
    demo = create_interface()
    
    # تشغيل Gradio
    demo.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False,
        debug=False
    )

if __name__ == "__main__":
    main()
