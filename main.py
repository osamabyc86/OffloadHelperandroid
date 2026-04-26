#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
main.py — نظام توزيع المهام الذكي المحسن
الإصدار 2.1.0 - مع التعديلات الأخيرة
"""
import torch
import torch
import pickle
import base64
import os
import sys
import time
import threading
import subprocess
import logging
import argparse
import socket
import random
import requests
import importlib.util
import psutil
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from flask_cors import CORS
from dataclasses import dataclass, asdict

import external_server
# استيراد مدير المنافذ
try:
    from port_manager import PortManager
    port_manager = PortManager()
    CPU_PORT = port_manager.get_available_port()
except:
    CPU_PORT = 5297

# تحديث الثوابت
SHARED_SECRET = os.getenv("SHARED_SECRET", "my_shared_secret_123")
PYTHON_EXE = sys.executable
NODE_ID = os.getenv("NODE_ID", socket.gethostname())
MAX_TASK_TIMEOUT = int(os.getenv("MAX_TASK_TIMEOUT", "300"))

# ─────────────── إعدادات المسارات ───────────────
FILE = Path(__file__).resolve()
BASE_DIR = FILE.parent
sys.path.insert(0, str(BASE_DIR))

# ─────────────── إعداد السجلات المتقدم ───────────────
os.makedirs("logs", exist_ok=True)

# إنشاء logger مخصص
logger = logging.getLogger("main")
logger.setLevel(logging.INFO)

# إنشاء formatter
formatter = logging.Formatter(
    "%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s"
)

# معالج لل stdout
stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setFormatter(formatter)

# معالج للسجلات العامة
file_handler = logging.FileHandler("logs/main.log", mode="a", encoding="utf-8")
file_handler.setFormatter(formatter)

# معالج لأخطاء فقط
error_handler = logging.FileHandler("logs/errors.log", mode="a", encoding="utf-8")
error_handler.setLevel(logging.ERROR)
error_handler.setFormatter(formatter)

# إضافة المعالجات
logger.addHandler(stream_handler)
logger.addHandler(file_handler)
logger.addHandler(error_handler)

# ─────────────── تحميل متغيرات البيئة ───────────────
try:
    from dotenv import load_dotenv
    load_dotenv()
    logger.info("✅ تم تحميل متغيرات البيئة من .env")
except ImportError:
    logger.warning("⚠️ python-dotenv غير مثبَّت؛ تَخطّي .env")

# ─────────────── ثوابت التهيئة ───────────────
CPU_PORT = int(os.getenv("CPU_PORT", "5297"))
SHARED_SECRET = os.getenv("SHARED_SECRET", "my_shared_secret_123")
PYTHON_EXE = sys.executable
NODE_ID = os.getenv("NODE_ID", socket.gethostname())
MAX_TASK_TIMEOUT = int(os.getenv("MAX_TASK_TIMEOUT", "300"))  # 5 دقائق افتراضياً

# ─────────────── خيارات سطر الأوامر ───────────────
parser = argparse.ArgumentParser(description="نظام توزيع المهام الذكي المحسن")
parser.add_argument(
    "--stats-interval", "-s",
    type=int,
    default=10,
    help="ثواني بين كل طباعة لإحصائية الأقران (0 = تعطيل)"
)
parser.add_argument(
    "--no-cli",
    action="store_true",
    help="تعطيل القائمة التفاعلية حتى عند وجود TTY"
)
parser.add_argument(
    "--port",
    type=int,
    default=CPU_PORT,
    help="منفذ تشغيل الخادم"
)
parser.add_argument(
    "--discovery-interval",
    type=int,
    default=15,
    help="فاصل اكتشاف الأقران بالثواني"
)
parser.add_argument(
    "--health-check-interval",
    type=int,
    default=30,
    help="فاصل فحص الصحة بالثواني"
)
parser.add_argument(
    "--max-peers",
    type=int,
    default=50,
    help="الحد الأقصى لعدد الأقران المسجلين"
)
parser.add_argument(
    "--task-timeout",
    type=int,
    default=MAX_TASK_TIMEOUT,
    help="الحد الزمني الأقصى لتنفيذ المهمة بالثواني"
)
args = parser.parse_args()

# تحديث القيم بناء على الوسائط
CPU_PORT = args.port
MAX_TASK_TIMEOUT = args.task_timeout

# ─────────────── هياكل البيانات ───────────────
@dataclass
class PeerInfo:
    """معلومات شاملة عن القرين"""
    node_id: str
    ip: str
    port: int
    url: str
    last_seen: datetime
    capabilities: List[str]
    cpu_usage: float = 0.0
    memory_usage: float = 0.0
    status: str = "unknown"
    success_rate: float = 0.0
    response_time: float = 0.0
    weight: float = 1.0  # وزن القرين للتوزيع
    failed_attempts: int = 0  # عدد المحاولات الفاشلة

@dataclass
class TaskResult:
    """نتيجة تنفيذ المهمة"""
    task_id: str
    status: str  # completed, failed, timeout
    result: Any
    execution_time: float
    memory_used: float
    node_id: str
    timestamp: datetime

class SystemHealthMonitor:
    """مراقب صحة النظام"""
    
    def __init__(self):
        self.metrics_history = []
        self.health_status = "healthy"
        self.last_check = datetime.now()
        self.health_thresholds = {
            "cpu_usage": 90,
            "memory_usage": 85,
            "disk_usage": 90,
            "system_load": 5.0
        }
    
    def collect_metrics(self) -> Dict[str, Any]:
        """جمع مقاييس النظام مع معالجة الأخطاء"""
        try:
            metrics = {
                "timestamp": datetime.now(),
                "cpu_usage": 0.0,
                "memory_usage": 0.0,
                "disk_usage": 0.0,
                "network_io": {},
                "active_tasks": 0,
                "peer_count": len(PEERS_INFO),
                "system_load": 0.0,
                "thread_count": threading.active_count(),
                "uptime": time.time() - START_TIME
            }
            
            # جمع استخدام الذاكرة (عادة ما يعمل في معظم البيئات)
            try:
                memory_usage = psutil.virtual_memory().percent
                metrics["memory_usage"] = memory_usage
            except Exception as e:
                logger.warning(f"⚠️ لا يمكن قراءة استخدام الذاكرة: {e}")
            
            # جمع استخدام CPU مع معالجة الأخطاء
            try:
                cpu_usage = psutil.cpu_percent(interval=1)
                metrics["cpu_usage"] = cpu_usage
            except (PermissionError, FileNotFoundError) as e:
                logger.warning(f"⚠️ لا يمكن قراءة استخدام CPU: {e}")
                # استخدام قيمة افتراضية أو تقديرية
                metrics["cpu_usage"] = random.uniform(5.0, 20.0)  # قيمة تقديرية
            
            # جمع استخدام القرص - الإصدار المصحح
            try:
                disk_usage = psutil.disk_usage('/').percent
                metrics["disk_usage"] = disk_usage
                # إذا كان استخدام التخزين مرتفعاً جداً، سجل تحذيراً
                if disk_usage > 95:
                    logger.warning(f"⚠️ استخدام التخزين مرتفع: {disk_usage}%")
            except Exception as e:
                logger.warning(f"⚠️ لا يمكن قراءة استخدام القرص: {e}")
                # استخدام قيمة افتراضية معقولة
                metrics["disk_usage"] = 75.0
            
            # جمع إحصائيات الشبكة
            try:
                net_io = psutil.net_io_counters()
                metrics["network_io"] = {
                    "bytes_sent": net_io.bytes_sent,
                    "bytes_recv": net_io.bytes_recv,
                    "packets_sent": net_io.packets_sent,
                    "packets_recv": net_io.packets_recv
                }
            except Exception as e:
                logger.warning(f"⚠️ لا يمكن قراءة إحصائيات الشبكة: {e}")
            
            # جمع حمل النظام (لأنظمة Unix فقط)
            try:
                if hasattr(os, 'getloadavg') and os.name != 'nt':
                    metrics["system_load"] = os.getloadavg()[0]
            except Exception as e:
                logger.warning(f"⚠️ لا يمكن قراءة حمل النظام: {e}")
            
            # حساب المهام النشطة
            active_tasks = len([t for t in threading.enumerate() if t.name and t.name.startswith("task_")])
            metrics["active_tasks"] = active_tasks
            
            self.metrics_history.append(metrics)
            # الحفاظ على أحدث 100 تسجيل
            if len(self.metrics_history) > 100:
                self.metrics_history.pop(0)
            
            # تحديث حالة الصحة
            self.update_health_status(metrics)
            
            return metrics
            
        except Exception as e:
            logger.error(f"❌ خطأ في جمع مقاييس النظام: {e}")
            # إرجاع بيانات أساسية في حالة الخطأ
            return {
                "timestamp": datetime.now(),
                "cpu_usage": 0.0,
                "memory_usage": 0.0,
                "disk_usage": 0.0,
                "network_io": {},
                "active_tasks": 0,
                "peer_count": len(PEERS_INFO),
                "system_load": 0.0,
                "thread_count": threading.active_count(),
                "uptime": time.time() - START_TIME,
                "error": str(e)
            }
    
    def update_health_status(self, metrics: Dict):
        """تحديث حالة صحة النظام"""
        issues = []
        
        if metrics.get("cpu_usage", 0) > self.health_thresholds["cpu_usage"]:
            issues.append("استخدام CPU مرتفع")
        if metrics.get("memory_usage", 0) > self.health_thresholds["memory_usage"]:
            issues.append("استخدام الذاكرة مرتفع")
        if metrics.get("disk_usage", 0) > self.health_thresholds["disk_usage"]:
            issues.append("مساحة التخزين منخفضة")
        if metrics.get("system_load", 0) > self.health_thresholds["system_load"]:
            issues.append("حمل النظام مرتفع")
        
        if issues:
            self.health_status = "degraded"
            logger.warning(f"⚠️ مشاكل في الصحة: {', '.join(issues)}")
        else:
            self.health_status = "healthy"
    
    def get_health_report(self) -> Dict[str, Any]:
        """تقرير صحة النظام"""
        metrics = self.collect_metrics()
        
        return {
            "status": self.health_status,
            "timestamp": datetime.now(),
            "metrics": metrics,
            "node_id": NODE_ID,
            "uptime": time.time() - START_TIME,
            "thresholds": self.health_thresholds
        }

class TaskManager:
    """مدير المهام المحسن"""
    
    def __init__(self):
        self.active_tasks: Dict[str, threading.Thread] = {}
        self.task_results: Dict[str, TaskResult] = {}
        self.task_queue = []
        
    def submit_task(self, task_id: str, function, args: tuple, kwargs: dict = None) -> str:
        """إرسال مهمة للتنفيذ مع معالجة الأخطاء المحسنة"""
        if kwargs is None:
            kwargs = {}
            
        def task_wrapper():
            start_time = time.time()
            start_memory = 0
            end_memory = 0
            
            try:
                # قياس الذاكرة الأولية (بمعالجة الخطأ)
                try:
                    start_memory = psutil.Process().memory_info().rss / 1024 / 1024
                except:
                    start_memory = 0
                
                # تنفيذ المهمة
                result = function(*args, **kwargs)
                
                execution_time = time.time() - start_time
                
                # قياس الذاكرة النهائية (بمعالجة الخطأ)
                try:
                    end_memory = psutil.Process().memory_info().rss / 1024 / 1024
                except:
                    end_memory = 0
                    
                memory_used = end_memory - start_memory
                
                task_result = TaskResult(
                    task_id=task_id,
                    status="completed",
                    result=result,
                    execution_time=execution_time,
                    memory_used=memory_used,
                    node_id=NODE_ID,
                    timestamp=datetime.now()
                )
                
                self.task_results[task_id] = task_result
                logger.info(f"✅ تم إنهاء المهمة {task_id} في {execution_time:.3f} ثانية")
                
            except Exception as e:
                logger.error(f"❌ فشل المهمة {task_id}: {e}")
                execution_time = time.time() - start_time
                
                task_result = TaskResult(
                    task_id=task_id,
                    status="failed",
                    result=str(e),
                    execution_time=execution_time,
                    memory_used=0,
                    node_id=NODE_ID,
                    timestamp=datetime.now()
                )
                self.task_results[task_id] = task_result
            finally:
                if task_id in self.active_tasks:
                    del self.active_tasks[task_id]
        
        task_thread = threading.Thread(target=task_wrapper, name=f"task_{task_id}")
        task_thread.daemon = True
        self.active_tasks[task_id] = task_thread
        task_thread.start()
        
        return task_id
    
    def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """الحصول على حالة المهمة"""
        if task_id in self.active_tasks:
            return {"status": "running", "task_id": task_id}
        elif task_id in self.task_results:
            result = self.task_results[task_id]
            return {
                "status": result.status,
                "task_id": task_id,
                "result": result.result,
                "execution_time": result.execution_time,
                "memory_used": result.memory_used,
                "timestamp": result.timestamp.isoformat()
            }
        else:
            return None

# ─────────────── متغيرات النظام ───────────────
START_TIME = time.time()
PEERS_INFO: Dict[str, PeerInfo] = {}  # معلومات الأقران الكاملة
current_server_index = 0
health_monitor = SystemHealthMonitor()
task_manager = TaskManager()

# ─────────────── دوال اكتشاف الأقران المحسنة ───────────────
def scan_local_network() -> List[Dict[str, Any]]:
    """مسح الشبكة المحلية لاكتشاف الأقران مع معالجة الأخطاء"""
    discovered_peers = []
    
    try:
        local_ip = get_local_ip()
        if not local_ip or local_ip == "127.0.0.1":
            logger.warning("⚠️ لا يمكن الحصول على IP محلي صالح")
            return discovered_peers
            
        network_parts = local_ip.split('.')
        if len(network_parts) != 4:
            logger.warning(f"⚠️ تنسيق IP غير صالح: {local_ip}")
            return discovered_peers
            
        network_prefix = '.'.join(network_parts[:3])
        
        logger.info(f"🔍 مسح الشبكة المحلية: {network_prefix}.x")
        
        # فحص المنافذ الشائعة في الشبكة المحلية
        common_ports = [CPU_PORT, 5297, 5298, 5299, 5300, 5000, 8000, 8080]
        
        def check_host(host_ip, port):
            try:
                url = f"http://{host_ip}:{port}/health"
                response = requests.get(url, timeout=3)
                if response.status_code == 200:
                    peer_info = response.json()
                    discovered_peers.append({
                        "ip": host_ip,
                        "port": port,
                        "node_id": peer_info.get("node_id", f"node_{host_ip}"),
                        "capabilities": peer_info.get("capabilities", []),
                        "status": "active",
                        "last_seen": datetime.now().isoformat()
                    })
                    logger.info(f"✅ تم اكتشاف قرين: {host_ip}:{port} - {peer_info.get('node_id', 'unknown')}")
            except requests.exceptions.Timeout:
                pass
            except requests.exceptions.ConnectionError:
                pass
            except Exception as e:
                pass  # تجاهل الأخطاء في المسح
        
        # مسح مجموعة محدودة من العناوين لتجنب الحمل الزائد
        threads = []
        for i in range(1, 50):  # زيادة النطاق
            host_ip = f"{network_prefix}.{i}"
            if host_ip == local_ip:
                continue
                
            for port in common_ports:
                thread = threading.Thread(target=check_host, args=(host_ip, port))
                thread.daemon = True
                thread.start()
                threads.append(thread)
        
        # انتظار انتهاء جميع الخيوط (بحد زمني)
        for thread in threads:
            thread.join(timeout=0.3)
        
        logger.info(f"🎯 تم اكتشاف {len(discovered_peers)} أقران محليين")
        
    except Exception as e:
        logger.error(f"❌ خطأ في مسح الشبكة المحلية: {e}")
    
    return discovered_peers

def register_service_lan():
    """تسجيل الخدمة على الشبكة المحلية بشكل فعال"""
    logger.info("🚀 بدء خدمة التسجيل المحلي...")
    
    while True:
        try:
            # تحديث حالة الخدمة المحلية
            local_ip = get_local_ip()
            service_info = {
                "node_id": NODE_ID,
                "ip": local_ip,
                "port": CPU_PORT,
                "status": "active",
                "capabilities": ["cpu", "memory", "basic_tasks", "advanced_tasks"],
                "last_update": datetime.now().isoformat(),
                "health": health_monitor.get_health_report()
            }
            
            # هنا يمكن إضافة بث الخدمة على الشبكة المحلية
            # باستخدام UDP broadcast أو بروتوكولات الاكتشاف
            
            logger.debug("🔄 تحديث حالة الخدمة المحلية")
            time.sleep(30)  # تحديث كل 30 ثانية
            
        except Exception as e:
            logger.error(f"❌ خطأ في تسجيل الخدمة: {e}")
            time.sleep(60)  # انتظار أطول عند الخطأ

def discover_lan_loop():
    """اكتشاف الأقران على الشبكة المحلية بشكل دوري"""
    logger.info("🔍 بدء اكتشاف الأقران المحليين...")
    
    while True:
        try:
            discovered = scan_local_network()
            for peer_data in discovered:
                add_peer(peer_data)
            
            # تنظيف الأقران المتوقفين
            cleanup_inactive_peers()
            
            logger.info(f"📊 الإحصائية: {len(PEERS_INFO)} أقران معروفين")
            time.sleep(args.discovery_interval)
            
        except Exception as e:
            logger.error(f"❌ خطأ في اكتشاف الأقران: {e}")
            time.sleep(60)

def fetch_central_loop():
    """جلب تحديثات من السيرفر المركزي بشكل فعال"""
    logger.info("🌐 بدء الاتصال بالسيرفرات المركزية...")
    
    while True:
        try:
            peer_module = load_and_run_peer_discovery()
            if peer_module and hasattr(peer_module, 'CENTRAL_REGISTRY_SERVERS'):
                servers = peer_module.CENTRAL_REGISTRY_SERVERS
                
                for server in servers:
                    try:
                        # تحديث حالة العقدة - إصلاح تسلسل JSON
                        node_info = {
                            "node_id": NODE_ID,
                            "ip": get_local_ip(),
                            "port": CPU_PORT,
                            "status": "active",
                            "capabilities": ["cpu", "memory", "web_api", "advanced_tasks"],
                            "last_seen": datetime.now().isoformat(),  # استخدام isoformat بدلاً من datetime مباشرة
                            "health": {
                                "status": health_monitor.health_status,
                                "timestamp": datetime.now().isoformat(),
                                "node_id": NODE_ID,
                                "uptime": time.time() - START_TIME
                            }
                        }
                        
                        response = requests.post(
                            f"{server}/register", 
                            json=node_info, 
                            timeout=10
                        )
                        
                        if response.status_code == 200:
                            # معالجة قائمة الأقران المستلمة
                            peers_data = response.json()
                            for peer_data in peers_data:
                                add_peer(peer_data)
                            
                            logger.info(f"✅ تم التحديث من {server} - {len(peers_data)} أقران")
                            break  # الخروج عند النجاح مع أول سيرفر
                            
                    except Exception as e:
                        logger.warning(f"⚠️ فشل الاتصال بـ {server}: {e}")
                        continue
            
            time.sleep(60)  # تحديث كل دقيقة
            
        except Exception as e:
            logger.error(f"❌ خطأ في جلب التحديثات: {e}")
            time.sleep(120)  # انتظار أطول عند الخطأ

def cleanup_inactive_peers():
    """تنظيف الأقران غير النشطين"""
    current_time = datetime.now()
    inactive_peers = []
    
    for peer_url, peer_info in PEERS_INFO.items():
        time_diff = (current_time - peer_info.last_seen).total_seconds()
        if time_diff > 300:  # 5 دقائق
            inactive_peers.append(peer_url)
    
    for peer_url in inactive_peers:
        logger.info(f"🗑️ إزالة قرين غير نشط: {PEERS_INFO[peer_url].node_id}")
        del PEERS_INFO[peer_url]

# ─────────────── دوال مساعدة محسنة ───────────────
def get_local_ip() -> str:
    """الحصول على عنوان IP المحلي بدقة"""
    try:
        # محاولة متعددة للحصول على IP الحقيقي
        methods = [
            # الطريقة مع الاتصال (الأكثر موثوقية)
            lambda: [(s.connect(('8.8.8.8', 53)), s.getsockname()[0], s.close()) for s in [socket.socket(socket.AF_INET, socket.SOCK_DGRAM)]][0][1],
            # من البيئة
            lambda: os.getenv("HOST_IP", "127.0.0.1"),
            # الطريقة الأساسية
            lambda: socket.gethostbyname(socket.gethostname())
        ]
        
        for method in methods:
            try:
                ip = method()
                if ip and ip != "127.0.0.1" and not ip.startswith("127."):
                    return ip
            except:
                continue
                
        return "127.0.0.1"
    except Exception as e:
        logger.error(f"❌ خطأ في الحصول على IP المحلي: {e}")
        return "127.0.0.1"

def add_peer(peer_data: Dict[str, Any]) -> str:
    """إضافة قرين جديد إلى النظام مع معلومات كاملة"""
    try:
        peer_url = f"http://{peer_data['ip']}:{peer_data['port']}"
        
        if peer_url not in PEERS_INFO:
            # التحقق من الحد الأقصى للأقران
            if len(PEERS_INFO) >= args.max_peers:
                # إزالة أقدم قرين
                oldest_peer = min(PEERS_INFO.values(), key=lambda x: x.last_seen)
                del PEERS_INFO[oldest_peer.url]
                logger.info(f"🗑️ تم إزالة أقدم قرين: {oldest_peer.node_id}")
            
            peer_info = PeerInfo(
                node_id=peer_data.get('node_id', f"node_{peer_data['ip']}"),
                ip=peer_data['ip'],
                port=peer_data['port'],
                url=peer_url,
                last_seen=datetime.now(),
                capabilities=peer_data.get('capabilities', []),
                status=peer_data.get('status', 'active')
            )
            PEERS_INFO[peer_url] = peer_info
            logger.info(f"✅ تمت إضافة قرين جديد: {peer_info.node_id} ({peer_url})")
        else:
            # تحديث المعلومات الموجودة
            PEERS_INFO[peer_url].last_seen = datetime.now()
            PEERS_INFO[peer_url].capabilities = peer_data.get('capabilities', [])
            PEERS_INFO[peer_url].status = peer_data.get('status', 'active')
        
        return peer_url
    except Exception as e:
        logger.error(f"❌ خطأ في إضافة القرين: {e}")
        return ""

def benchmark(fn, *args) -> tuple:
    """قياس زمن تنفيذ الدالة مع تحسينات"""
    start_time = time.time()
    start_memory = psutil.Process().memory_info().rss / 1024 / 1024  # MB
    
    try:
        result = fn(*args)
        execution_time = time.time() - start_time
        end_memory = psutil.Process().memory_info().rss / 1024 / 1024
        memory_used = end_memory - start_memory
        
        logger.info(f"⏱️  أداء الدالة {fn.__name__}: {execution_time:.3f}s, ذاكرة: {memory_used:.2f}MB")
        
        return execution_time, result, memory_used
    except Exception as e:
        logger.error(f"❌ خطأ في تنفيذ الدالة {fn.__name__}: {e}")
        return -1, None, 0

def load_and_run_peer_discovery():
    """تحميل وتشغيل ملف peer_discovery.py مع تحسينات"""
    try:
        peer_discovery_path = Path(__file__).parent / "peer_discovery.py"
        if not peer_discovery_path.exists():
            logger.warning("📄 ملف peer_discovery.py غير موجود")
            return None
        
        spec = importlib.util.spec_from_file_location("peer_discovery_module", peer_discovery_path)
        peer_module = importlib.util.module_from_spec(spec)
        
        # تحميل المتغيرات البيئية في الوحدة
        peer_module.CPU_PORT = CPU_PORT
        peer_module.NODE_ID = NODE_ID
        
        spec.loader.exec_module(peer_module)
        
        logger.info("✅ تم تحميل peer_discovery.py بنجاح")
        return peer_module
    except Exception as e:
        logger.error(f"❌ خطأ في تحميل peer_discovery.py: {e}")
        return None

# ─────────────── دوال المهام المحسنة ───────────────
def example_task(x: int) -> int:
    """دالة مثال محسنة"""
    return x * x + 2*x + 1

def matrix_multiply(size: int) -> List[List[int]]:
    """ضرب المصفوفات مع تحسينات الأداء"""
    logger.info(f"🧮 بدء ضرب مصفوفة بحجم {size}x{size}")
    
    # إنشاء مصفوفات عشوائية
    matrix_a = [[random.randint(1, 100) for _ in range(size)] for _ in range(size)]
    matrix_b = [[random.randint(1, 100) for _ in range(size)] for _ in range(size)]
    
    # الضرب
    result = [[0 for _ in range(size)] for _ in range(size)]
    for i in range(size):
        for j in range(size):
            for k in range(size):
                result[i][j] += matrix_a[i][k] * matrix_b[k][j]
    
    logger.info(f"✅ انتهاء ضرب المصفوفة")
    return result

def prime_calculation(limit: int) -> List[int]:
    """حساب الأعداد الأولية مع تحسينات الخوارزمية"""
    logger.info(f"🔢 حساب الأعداد الأولية حتى {limit}")
    
    if limit < 2:
        return []
    
    primes = []
    is_prime = [True] * (limit + 1)
    is_prime[0] = is_prime[1] = False
    
    for i in range(2, int(limit**0.5) + 1):
        if is_prime[i]:
            for j in range(i*i, limit + 1, i):
                is_prime[j] = False
    
    primes = [i for i in range(2, limit + 1) if is_prime[i]]
    logger.info(f"✅ تم إيجاد {len(primes)} عدد أولي")
    return primes

def data_processing(size: int) -> Dict[str, Any]:
    """معالجة البيانات مع تحليلات"""
    logger.info(f"📊 معالجة بيانات بحجم {size}")
    
    # إنشاء بيانات نموذجية
    data = {
        f"item_{i}": {
            "value": random.randint(1, 1000),
            "timestamp": datetime.now().isoformat(),
            "category": random.choice(["A", "B", "C", "D"])
        } for i in range(size)
    }
    
    # تحليلات أساسية
    values = [item["value"] for item in data.values()]
    analytics = {
        "total_items": size,
        "average_value": sum(values) / len(values),
        "max_value": max(values),
        "min_value": min(values),
        "processing_time": time.time()
    }
    
    logger.info(f"✅ انتهاء معالجة البيانات - متوسط القيم: {analytics['average_value']:.2f}")
    return {"data": data, "analytics": analytics}

def fibonacci_calculation(n: int) -> int:
    """حساب متسلسلة فيبوناتشي (لمهام CPU مكثفة)"""
    if n <= 1:
        return n
    a, b = 0, 1
    for _ in range(2, n + 1):
        a, b = b, a + b
    return b

def image_processing_simulation(size: int) -> Dict[str, Any]:
    """محاكاة معالجة الصور"""
    logger.info(f"🖼️ محاكاة معالجة صورة بحجم {size}")
    
    # محاكاة معالجة الصورة
    time.sleep(size * 0.01)  # محاكاة وقت المعالجة
    
    result = {
        "original_size": size,
        "processed_size": size // 2,
        "format": "JPEG",
        "compression_ratio": 0.5,
        "processing_time": size * 0.01
    }
    
    logger.info(f"✅ انتهاء محاكاة معالجة الصورة")
    return result

# ─────────────── خادم Flask المحسن ───────────────
flask_app = Flask(__name__)
CORS(flask_app, resources={r"/*": {"origins": "*"}})

@flask_app.route("/", methods=["GET"])
def home():
    """الصفحة الرئيسية"""
    return jsonify({
        "message": "مرحباً في نظام توزيع المهام الذكي المحسن",
        "node_id": NODE_ID,
        "status": "active",
        "timestamp": datetime.now().isoformat(),
        "version": "2.1.0",
        "endpoints": {
            "health": "/health",
            "peers": "/peers", 
            "system_info": "/system_info",
            "run_task": "/run_task",
            "task_status": "/task_status/<task_id>",
            "distribute_task": "/distribute_task"
        }
    })

@flask_app.route("/health", methods=["GET"])
def health_check():
    """فحص صحة النظام"""
    health_report = health_monitor.get_health_report()
    return jsonify(health_report)

@flask_app.route("/run_task", methods=["POST"])
def run_task():
    """تشغيل مهمة مع تحسينات"""
    try:
        data = request.get_json() if request.is_json else request.form
        task_id = data.get("task_id")
        task_params = data.get("params", {})
        
        if not task_id:
            return jsonify({"error": "يجب تحديد task_id"}), 400
        
        logger.info(f"🎯 طلب تشغيل مهمة: {task_id}")
        
        # قاموس المهام الموسع
        tasks = {
            "1": {"name": "ضرب المصفوفات", "function": matrix_multiply, "params": ["size"]},
            "2": {"name": "حساب الأعداد الأولية", "function": prime_calculation, "params": ["limit"]},
            "3": {"name": "معالجة البيانات", "function": data_processing, "params": ["size"]},
            "4": {"name": "مثال بسيط", "function": example_task, "params": ["x"]},
            "5": {"name": "متسلسلة فيبوناتشي", "function": fibonacci_calculation, "params": ["n"]},
            "6": {"name": "محاكاة معالجة الصور", "function": image_processing_simulation, "params": ["size"]}
        }
        
        if task_id not in tasks:
            return jsonify({"error": "معرف المهمة غير صحيح"}), 400
        
        task_info = tasks[task_id]
        function = task_info["function"]
        
        # تحضير المعاملات
        fn_args = []
        for param in task_info["params"]:
            if param in task_params:
                fn_args.append(task_params[param])
            else:
                # قيم افتراضية
                defaults = {"size": 100, "limit": 1000, "x": 10, "n": 30}
                fn_args.append(defaults.get(param, 1))
        
        # إنشاء معرف فريد للمهمة
        unique_task_id = f"{task_id}_{int(time.time())}_{random.randint(1000, 9999)}"
        
        # إرسال المهمة للمدير
        task_manager.submit_task(unique_task_id, function, tuple(fn_args))
        
        response_data = {
            "task_id": unique_task_id,
            "original_task_id": task_id,
            "task_name": task_info["name"],
            "status": "submitted",
            "submitted_at": datetime.now().isoformat(),
            "estimated_timeout": MAX_TASK_TIMEOUT
        }
        
        logger.info(f"✅ تم إرسال المهمة {unique_task_id} للتنفيذ")
        return jsonify(response_data)
        
    except Exception as e:
        logger.error(f"❌ خطأ في معالجة المهمة: {e}", exc_info=True)
        return jsonify({"error": "حدث خطأ داخلي في الخادم", "details": str(e)}), 500

@flask_app.route("/task_status/<task_id>", methods=["GET"])
def get_task_status(task_id: str):
    """الحصول على حالة المهمة"""
    try:
        status = task_manager.get_task_status(task_id)
        if status:
            return jsonify(status)
        else:
            return jsonify({"error": "المهمة غير موجودة"}), 404
    except Exception as e:
        logger.error(f"❌ خطأ في الحصول على حالة المهمة: {e}")
        return jsonify({"error": str(e)}), 500

@flask_app.route("/distribute_task", methods=["POST"])
def distribute_task():
    """توزيع المهمة على الأقران المتاحين"""
    try:
        data = request.get_json()
        task_id = data.get("task_id")
        task_params = data.get("params", {})
        
        if not task_id:
            return jsonify({"error": "يجب تحديد task_id"}), 400
        
        # اختيار أفضل قرين
        best_peer = select_best_peer()
        if not best_peer:
            return jsonify({"error": "لا توجد أقران متاحة"}), 503
        
        # إرسال المهمة للقرين
        try:
            response = requests.post(
                f"{best_peer.url}/run_task",
                json={"task_id": task_id, "params": task_params},
                timeout=10
            )
            
            if response.status_code == 200:
                result = response.json()
                logger.info(f"✅ تم توزيع المهمة {task_id} على {best_peer.node_id}")
                return jsonify({
                    "distributed_to": best_peer.node_id,
                    "peer_url": best_peer.url,
                    "task_info": result
                })
            else:
                logger.error(f"❌ فشل القرين في معالجة المهمة: {response.status_code}")
                return jsonify({"error": "فشل القرين في معالجة المهمة"}), 502
                
        except Exception as e:
            logger.error(f"❌ خطأ في الاتصال بالقرين {best_peer.node_id}: {e}")
            # تحديث حالة القرين
            best_peer.failed_attempts += 1
            return jsonify({"error": "فشل الاتصال بالقرين"}), 503
            
    except Exception as e:
        logger.error(f"❌ خطأ في توزيع المهمة: {e}")
        return jsonify({"error": str(e)}), 500

@flask_app.route("/peers", methods=["GET"])
def get_peers():
    """الحصول على قائمة الأقران"""
    peers_list = []
    for peer_info in PEERS_INFO.values():
        peer_dict = asdict(peer_info)
        peer_dict["last_seen"] = peer_info.last_seen.isoformat()
        peers_list.append(peer_dict)
    
    return jsonify({
        "node_id": NODE_ID,
        "total_peers": len(peers_list),
        "peers": peers_list
    })

@flask_app.route("/system_info", methods=["GET"])
def system_info():
    """معلومات النظام الشاملة"""
    health_report = health_monitor.get_health_report()
    
    system_info = {
        "node_id": NODE_ID,
        "status": "active",
        "version": "2.1.0",
        "start_time": datetime.fromtimestamp(START_TIME).isoformat(),
        "uptime": time.time() - START_TIME,
        "python_version": sys.version,
        "platform": sys.platform,
        "active_tasks": len(task_manager.active_tasks),
        "completed_tasks": len(task_manager.task_results),
        "known_peers": len(PEERS_INFO),
        "health": health_report,
        "endpoints": [
            "/", "/health", "/peers", "/system_info", 
            "/run_task", "/task_status", "/distribute_task"
        ]
    }
    
    return jsonify(system_info)

# ─────────────── دوال التوزيع الذكي ───────────────
def select_best_peer() -> Optional[PeerInfo]:
    """اختيار أفضل قرين بناءً على عدة عوامل"""
    if not PEERS_INFO:
        return None
    
    # تصفية الأقران النشطين فقط
    active_peers = []
    for peer_info in PEERS_INFO.values():
        time_diff = (datetime.now() - peer_info.last_seen).total_seconds()
        if time_diff < 180:  # 3 دقائق كحد أقصى
            active_peers.append(peer_info)
    
    if not active_peers:
        return None
    
    # حساب النقاط لكل قرين
    scored_peers = []
    for peer in active_peers:
        score = 0
        
        # عامل الصحة (40%)
        health_factor = (100 - peer.cpu_usage) * 0.4
        
        # عامل الأداء (30%)
        performance_factor = (1.0 / (peer.response_time + 0.1)) * 30
        
        # عامل الموثوقية (20%)
        reliability_factor = peer.success_rate * 20
        
        # عامل التوازن (10%)
        balance_factor = (1.0 - peer.weight) * 10
        
        total_score = health_factor + performance_factor + reliability_factor + balance_factor
        scored_peers.append((peer, total_score))
    
    # اختيار القرين بأعلى نقاط
    best_peer = max(scored_peers, key=lambda x: x[1])[0]
    logger.info(f"🎯 تم اختيار القرين {best_peer.node_id} (نقاط: {max(scored_peers, key=lambda x: x[1])[1]:.2f})")
    
    return best_peer

def update_peer_metrics(peer_url: str, success: bool, response_time: float):
    """تحديث مقاييس الأداء للقرين"""
    if peer_url in PEERS_INFO:
        peer_info = PEERS_INFO[peer_url]
        
        # تحديث وقت الاستجابة (متوسط متحرك)
        if peer_info.response_time == 0:
            peer_info.response_time = response_time
        else:
            peer_info.response_time = 0.7 * peer_info.response_time + 0.3 * response_time
        
        # تحديث معدل النجاح
        if success:
            peer_info.success_rate = min(1.0, peer_info.success_rate + 0.05)
            peer_info.failed_attempts = max(0, peer_info.failed_attempts - 1)
        else:
            peer_info.success_rate = max(0.0, peer_info.success_rate - 0.1)
            peer_info.failed_attempts += 1
        
        # تحديث الوزن بناءً على الأداء
        if peer_info.success_rate < 0.5 or peer_info.failed_attempts > 3:
            peer_info.weight = max(0.1, peer_info.weight - 0.1)
        elif peer_info.success_rate > 0.8 and peer_info.failed_attempts == 0:
            peer_info.weight = min(1.0, peer_info.weight + 0.05)

# ─────────────── دوال المراقبة والإحصاءات ───────────────
def print_peer_stats():
    """طباعة إحصاءات الأقران"""
    if not PEERS_INFO:
        logger.info("📊 لا توجد أقران نشطين")
        return
    
    logger.info("📊 إحصاءات الأقران:")
    for peer_info in PEERS_INFO.values():
        time_diff = (datetime.now() - peer_info.last_seen).total_seconds()
        status = "🟢" if time_diff < 60 else "🟡" if time_diff < 180 else "🔴"
        
        logger.info(f"  {status} {peer_info.node_id} ({peer_info.ip}:{peer_info.port})")
        logger.info(f"     الحالة: {peer_info.status}, القدرات: {', '.join(peer_info.capabilities)}")
        logger.info(f"     آخر ظهور: {time_diff:.0f} ثانية مضت")
        logger.info(f"     معدل النجاح: {peer_info.success_rate:.1%}, وقت الاستجابة: {peer_info.response_time:.2f}s")
        logger.info(f"     الوزن: {peer_info.weight:.2f}, محاولات فاشلة: {peer_info.failed_attempts}")

def stats_loop():
    """حلقة طباعة الإحصاءات"""
    if args.stats_interval <= 0:
        return
    
    logger.info(f"📈 بدء مراقبة الإحصاءات (كل {args.stats_interval} ثانية)")
    
    while True:
        try:
            print_peer_stats()
            
            # إحصاءات النظام
            health_report = health_monitor.get_health_report()
            logger.info(f"💻 إحصاءات النظام - CPU: {health_report['metrics'].get('cpu_usage', 0):.1f}%, ذاكرة: {health_report['metrics'].get('memory_usage', 0):.1f}%")
            logger.info(f"🔄 المهام النشطة: {len(task_manager.active_tasks)}, المهام المنتهية: {len(task_manager.task_results)}")
            
            time.sleep(args.stats_interval)
        except Exception as e:
            logger.error(f"❌ خطأ في مراقبة الإحصاءات: {e}")
            time.sleep(60)
def load_layer_from_remote(layer_name: str) -> torch.Tensor:
    """جلب طبقة من جهاز بعيد"""
    # استخدام discovery_manager.PEERS للعثور على جهاز يدعم tensor_storage
    for peer_url in discovery_manager.PEERS:
        try:
            resp = requests.get(f"{peer_url}/fetch_tensor", params={'name': layer_name})
            if resp.status_code == 200:
                return pickle.loads(bytes(resp.json()['data']))
        except:
            continue
    raise Exception(f"لا يمكن جلب الطبقة {layer_name}")
# ─────────────── الدالة الرئيسية المحسنة ───────────────
def main():
    """الدالة الرئيسية مع تحسينات"""
    logger.info("🚀 بدء تشغيل نظام توزيع المهام الذكي المحسن")
    logger.info(f"🆔 معرف العقدة: {NODE_ID}")
    logger.info(f"🌐 المنفذ: {CPU_PORT}")
    logger.info(f"🔑 المفتاح المشترك: {SHARED_SECRET[:10]}...")
    
    # عرض معلومات النظام
    local_ip = get_local_ip()
    logger.info(f"📍 IP المحلي: {local_ip}")
    logger.info(f"🐍 إصدار Python: {sys.version.split()[0]}")
    logger.info(f"💻 النظام: {sys.platform}")
    
    # بدء الخيوط الخلفية
    threading.Thread(target=discover_lan_loop, daemon=True, name="discovery").start()
    threading.Thread(target=fetch_central_loop, daemon=True, name="central_fetch").start()
    threading.Thread(target=register_service_lan, daemon=True, name="service_register").start()
    threading.Thread(target=stats_loop, daemon=True, name="stats").start()
    
    logger.info("✅ تم بدء جميع الخدمات الخلفية")
    
    # بدء خادم Flask
    try:
        logger.info(f"🌐 بدء خادم الويب على المنفذ {CPU_PORT}")
        flask_app.run(
            host="0.0.0.0",
            port=CPU_PORT,
            debug=False,
            threaded=True,
            use_reloader=False
        )
    except Exception as e:
        logger.error(f"❌ خطأ في تشغيل الخادم: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
