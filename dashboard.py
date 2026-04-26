#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
لوحة التحكم المتقدمة للنظام الموزع
إصدار محسن مع مراقبة في الوقت الحقيقي وإدارة متقدمة
"""

import logging
import socket
import threading
import asyncio
import time
import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import secrets

import psutil
try:
    import GPUtil
    HAS_GPU = True
except ImportError:
    HAS_GPU = False
    logging.warning("⚠️ GPUtil غير متوفر - سيتم تعطيل مراقبة GPU")

from flask import Flask, render_template, request, jsonify, session
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_cors import CORS

# استيراد مدير المنافذ
try:
    from port_manager import PortManager
    port_manager = PortManager()
    DASHBOARD_PORT = port_manager.get_available_port()
except:
    DASHBOARD_PORT = 7000

# إعداد اللوجر مع دعم Unicode
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('dashboard.log', encoding='utf-8', errors='replace')
    ]
)
logger = logging.getLogger("Dashboard")

# تكوين التطبيق
app = Flask(__name__)
app.config['SECRET_KEY'] = secrets.token_urlsafe(32)
app.config['SESSION_TYPE'] = 'filesystem'

# إعداد CORS آمن
CORS(app, origins=["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:5173"], supports_credentials=True)

# إعداد معدل الطلبات
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://"
)

# إعداد SocketIO مع تحسينات
socketio = SocketIO(
    app,
    cors_allowed_origins=["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:5173"],
    async_mode='threading',
    logger=False,  # تقليل السجلات
    engineio_logger=False,
    max_http_buffer_size=1e8,
    ping_timeout=60,
    ping_interval=25
)

# ---- نماذج البيانات --------------------------------------------------------

class NodeStatus(Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    WARNING = "warning"
    ERROR = "error"

class ResourceType(Enum):
    CPU = "cpu"
    MEMORY = "memory"
    GPU = "gpu"
    NETWORK = "network"
    DISK = "disk"

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
    network_sent: int = 0
    network_recv: int = 0
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cpu_percent": round(self.cpu_percent, 2),
            "memory_percent": round(self.memory_percent, 2),
            "memory_used": self.memory_used,
            "memory_total": self.memory_total,
            "gpu_percent": round(self.gpu_percent, 2),
            "gpu_memory_used": self.gpu_memory_used,
            "gpu_memory_total": self.gpu_memory_total,
            "disk_usage": round(self.disk_usage, 2),
            "network_sent": self.network_sent,
            "network_recv": self.network_recv,
            "timestamp": self.timestamp.isoformat()
        }

@dataclass
class NodeInfo:
    """معلومات العقدة المتصلة"""
    node_id: str
    hostname: str
    ip_address: str
    status: NodeStatus
    metrics: SystemMetrics
    last_seen: datetime
    capabilities: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    connection_id: Optional[str] = None

    def is_online(self) -> bool:
        return (datetime.now() - self.last_seen).total_seconds() < 30

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "hostname": self.hostname,
            "ip_address": self.ip_address,
            "status": self.status.value,
            "metrics": self.metrics.to_dict(),
            "last_seen": self.last_seen.isoformat(),
            "capabilities": self.capabilities,
            "tags": self.tags,
            "online": self.is_online()
        }

# ---- فئة مدير اللوحة الرئيسية ----------------------------------------------

class DashboardManager:
    """مدير لوحة التحكم المتقدمة"""
    
    def __init__(self):
        self.nodes: Dict[str, NodeInfo] = {}
        self.metrics_history: Dict[str, List[SystemMetrics]] = {}
        self.rooms: Dict[str, List[str]] = {}
        self._lock = threading.RLock()
        self._broadcast_task: Optional[threading.Thread] = None
        self._cleanup_task: Optional[threading.Thread] = None
        self._is_running = False
        self._connected_clients = set()
        
        # إحصائيات النظام
        self.system_stats = {
            "total_nodes": 0,
            "online_nodes": 0,
            "total_messages": 0,
            "uptime": time.time()
        }
        
        # تكوين اللوحة
        self.config = {
            "update_interval": 5,  # ثواني - زيادة الفاصل لتقليل الحمل
            "max_history": 50,     # عدد القراءات المسجلة - تقليل للذاكرة
            "cleanup_interval": 60 # ثواني
        }

    def start(self):
        """بدء مدير اللوحة"""
        self._is_running = True
        self._broadcast_task = threading.Thread(target=self._broadcast_loop, daemon=True)
        self._cleanup_task = threading.Thread(target=self._cleanup_loop, daemon=True)
        self._broadcast_task.start()
        self._cleanup_task.start()
        logger.info("🚀 بدء تشغيل مدير لوحة التحكم")

    def stop(self):
        """إيقاف مدير اللوحة"""
        self._is_running = False
        if self._broadcast_task:
            self._broadcast_task.join(timeout=5)
        if self._cleanup_task:
            self._cleanup_task.join(timeout=5)
        logger.info("🛑 إيقاف مدير لوحة التحكم")

    def add_client(self, client_id: str):
        """إضافة عميل متصل"""
        self._connected_clients.add(client_id)
        logger.debug(f"➕ عميل متصل: {client_id} (إجمالي: {len(self._connected_clients)})")

    def remove_client(self, client_id: str):
        """إزالة عميل منفصل"""
        if client_id in self._connected_clients:
            self._connected_clients.remove(client_id)
        logger.debug(f"➖ عميل منفصل: {client_id} (إجمالي: {len(self._connected_clients)})")

    def has_connected_clients(self) -> bool:
        """التحقق من وجود عملاء متصلين"""
        return len(self._connected_clients) > 0

    def register_node(self, node_id: str, hostname: str, ip_address: str, 
                     connection_id: str, capabilities: List[str] = None) -> NodeInfo:
        """تسجيل عقدة جديدة"""
        with self._lock:
            metrics = self._collect_system_metrics()
            node_info = NodeInfo(
                node_id=node_id,
                hostname=hostname,
                ip_address=ip_address,
                status=NodeStatus.ONLINE,
                metrics=metrics,
                last_seen=datetime.now(),
                capabilities=capabilities or [],
                connection_id=connection_id
            )
            
            self.nodes[node_id] = node_info
            self.metrics_history[node_id] = [metrics]
            self.system_stats["total_nodes"] += 1
            self.system_stats["online_nodes"] += 1
            
            logger.info(f"✅ عقدة جديدة مسجلة: {node_id} ({hostname})")
            return node_info

    def update_node_metrics(self, node_id: str, metrics: SystemMetrics):
        """تحديث مقاييس العقدة"""
        with self._lock:
            if node_id in self.nodes:
                self.nodes[node_id].metrics = metrics
                self.nodes[node_id].last_seen = datetime.now()
                
                # تحديث السجل التاريخي
                history = self.metrics_history.get(node_id, [])
                history.append(metrics)
                if len(history) > self.config["max_history"]:
                    history.pop(0)
                self.metrics_history[node_id] = history

    def remove_node(self, node_id: str):
        """إزالة عقدة"""
        with self._lock:
            if node_id in self.nodes:
                del self.nodes[node_id]
                if node_id in self.metrics_history:
                    del self.metrics_history[node_id]
                self.system_stats["online_nodes"] = max(0, self.system_stats["online_nodes"] - 1)
                logger.info(f"🗑️ إزالة العقدة: {node_id}")

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
            
            if HAS_GPU:
                try:
                    gpus = GPUtil.getGPUs()
                    if gpus:
                        gpu = gpus[0]  # أول GPU
                        gpu_percent = gpu.load * 100
                        gpu_memory_used = gpu.memoryUsed
                        gpu_memory_total = gpu.memoryTotal
                except Exception as e:
                    logger.debug(f"فشل في جمع بيانات GPU: {e}")

            # Disk
            disk_usage = psutil.disk_usage('/').percent
            
            # Network
            net_io = psutil.net_io_counters()
            
            return SystemMetrics(
                cpu_percent=cpu_percent,
                memory_percent=memory.percent,
                memory_used=memory.used,
                memory_total=memory.total,
                gpu_percent=gpu_percent,
                gpu_memory_used=gpu_memory_used,
                gpu_memory_total=gpu_memory_total,
                disk_usage=disk_usage,
                network_sent=net_io.bytes_sent,
                network_recv=net_io.bytes_recv
            )
            
        except Exception as e:
            logger.error(f"❌ خطأ في جمع مقاييس النظام: {e}")
            return SystemMetrics(0, 0, 0, 0)

    def get_system_overview(self) -> Dict[str, Any]:
        """الحصول على نظرة عامة على النظام"""
        with self._lock:
            online_nodes = [node for node in self.nodes.values() if node.is_online()]
            
            if online_nodes:
                total_cpu = sum(node.metrics.cpu_percent for node in online_nodes) / len(online_nodes)
                total_memory = sum(node.metrics.memory_percent for node in online_nodes) / len(online_nodes)
            else:
                total_cpu = 0
                total_memory = 0
            
            return {
                "total_nodes": self.system_stats["total_nodes"],
                "online_nodes": len(online_nodes),
                "offline_nodes": self.system_stats["total_nodes"] - len(online_nodes),
                "avg_cpu_usage": round(total_cpu, 2),
                "avg_memory_usage": round(total_memory, 2),
                "system_uptime": int(time.time() - self.system_stats["uptime"]),
                "total_messages": self.system_stats["total_messages"],
                "connected_clients": len(self._connected_clients)
            }

    def _broadcast_loop(self):
        """حلقة بث تحديثات الحالة"""
        while self._is_running:
            try:
                with self._lock:
                    # تحديث مقاييس العقدة المحلية فقط إذا كان هناك عملاء متصلين
                    if self.has_connected_clients():
                        local_node_id = socket.gethostname()
                        if local_node_id in self.nodes:
                            metrics = self._collect_system_metrics()
                            self.update_node_metrics(local_node_id, metrics)
                
                # بث تحديثات الحالة فقط إذا كان هناك عملاء متصلين
                if self.has_connected_clients():
                    self._broadcast_status_update()
                
                time.sleep(self.config["update_interval"])
                
            except Exception as e:
                logger.error(f"🔧 خطأ في حلقة البث: {e}")
                time.sleep(5)

    def _broadcast_status_update(self):
        """بث تحديث الحالة لجميع العملاء المتصلين"""
        try:
            overview = self.get_system_overview()
            nodes_data = {
                node_id: node.to_dict() 
                for node_id, node in self.nodes.items() 
                if node.is_online()
            }
            
            # البث فقط إذا كان هناك عملاء متصلين
            if self.has_connected_clients():
                socketio.emit("system_overview", overview, room='dashboard')
                socketio.emit("nodes_update", nodes_data, room='dashboard')
                self.system_stats["total_messages"] += 1
                
                # تسجيل التحديث بشكل دوري فقط
                if self.system_stats["total_messages"] % 10 == 0:
                    logger.debug(f"📤 بث تحديث النظام (العملاء: {len(self._connected_clients)})")
            
        except Exception as e:
            logger.error(f"❌ خطأ في بث تحديث الحالة: {e}")

    def _cleanup_loop(self):
        """حلقة تنظيف العقد المتوقفة"""
        while self._is_running:
            try:
                current_time = datetime.now()
                with self._lock:
                    offline_nodes = [
                        node_id for node_id, node in self.nodes.items()
                        if (current_time - node.last_seen).total_seconds() > 120  # زيادة المهلة
                    ]
                    
                    for node_id in offline_nodes:
                        self.nodes[node_id].status = NodeStatus.OFFLINE
                        logger.info(f"🔴 تم وضع العقدة {node_id} في وضع غير متصل")
                
                time.sleep(self.config["cleanup_interval"])
                
            except Exception as e:
                logger.error(f"🧹 خطأ في حلقة التنظيف: {e}")
                time.sleep(30)

    def get_node_history(self, node_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """الحصول على السجل التاريخي للعقدة"""
        history = self.metrics_history.get(node_id, [])
        recent_history = history[-limit:] if limit > 0 else history
        return [metrics.to_dict() for metrics in recent_history]

# ---- إنشاء مدير اللوحة -----------------------------------------------------

dashboard_manager = DashboardManager()

# ---- قالب HTML بسيط مدمج ---------------------------------------------------

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>لوحة تحكم النظام الموزع</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        }
        
        body {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: #333;
            min-height: 100vh;
            padding: 20px;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
        }
        
        .header {
            background: rgba(255, 255, 255, 0.95);
            padding: 20px;
            border-radius: 15px;
            margin-bottom: 20px;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.1);
            backdrop-filter: blur(10px);
        }
        
        .header h1 {
            color: #2c3e50;
            margin-bottom: 10px;
            text-align: center;
        }
        
        .status-bar {
            display: flex;
            justify-content: space-around;
            flex-wrap: wrap;
            gap: 15px;
            margin-top: 15px;
        }
        
        .status-item {
            background: linear-gradient(135deg, #74b9ff, #0984e3);
            color: white;
            padding: 15px;
            border-radius: 10px;
            text-align: center;
            min-width: 150px;
            box-shadow: 0 4px 15px rgba(0, 0, 0, 0.2);
        }
        
        .status-item h3 {
            font-size: 0.9em;
            margin-bottom: 5px;
            opacity: 0.9;
        }
        
        .status-item .value {
            font-size: 1.8em;
            font-weight: bold;
        }
        
        .nodes-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
            gap: 20px;
            margin-top: 20px;
        }
        
        .node-card {
            background: rgba(255, 255, 255, 0.95);
            border-radius: 15px;
            padding: 20px;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.1);
            backdrop-filter: blur(10px);
            transition: transform 0.3s ease, box-shadow 0.3s ease;
        }
        
        .node-card:hover {
            transform: translateY(-5px);
            box-shadow: 0 12px 40px rgba(0, 0, 0, 0.15);
        }
        
        .node-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
            padding-bottom: 10px;
            border-bottom: 2px solid #f8f9fa;
        }
        
        .node-name {
            font-weight: bold;
            color: #2c3e50;
        }
        
        .node-status {
            padding: 5px 12px;
            border-radius: 20px;
            font-size: 0.8em;
            font-weight: bold;
        }
        
        .status-online {
            background: #00b894;
            color: white;
        }
        
        .status-offline {
            background: #dfe6e9;
            color: #636e72;
        }
        
        .metrics {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 10px;
        }
        
        .metric {
            text-align: center;
            padding: 10px;
            background: #f8f9fa;
            border-radius: 8px;
        }
        
        .metric-label {
            font-size: 0.8em;
            color: #636e72;
            margin-bottom: 5px;
        }
        
        .metric-value {
            font-weight: bold;
            font-size: 1.1em;
            color: #2d3436;
        }
        
        .connection-status {
            position: fixed;
            top: 20px;
            left: 20px;
            padding: 10px 15px;
            border-radius: 20px;
            font-weight: bold;
            z-index: 1000;
        }
        
        .connected {
            background: #00b894;
            color: white;
        }
        
        .disconnected {
            background: #e17055;
            color: white;
        }
        
        .last-update {
            text-align: center;
            margin-top: 10px;
            font-size: 0.8em;
            color: rgba(255, 255, 255, 0.8);
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🚀 لوحة تحكم النظام الموزع</h1>
            <div class="status-bar" id="statusBar">
                <!-- سيتم ملؤها بالبيانات من JavaScript -->
            </div>
        </div>
        
        <div class="connection-status" id="connectionStatus">جاري الاتصال...</div>
        
        <div class="nodes-grid" id="nodesGrid">
            <!-- سيتم ملؤها بالبيانات من JavaScript -->
        </div>
        
        <div class="last-update" id="lastUpdate">
            آخر تحديث: جاري التحميل...
        </div>
    </div>

    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.7.2/socket.io.min.js"></script>
    <script>
        class Dashboard {
            constructor() {
                this.socket = null;
                this.isConnected = false;
                this.nodes = {};
                this.overview = {};
                this.init();
            }
            
            init() {
                this.connectSocket();
                this.setupEventListeners();
            }
            
            connectSocket() {
                this.socket = io({
                    transports: ['websocket', 'polling'],
                    timeout: 10000
                });
                
                this.socket.on('connect', () => {
                    this.isConnected = true;
                    this.updateConnectionStatus('متصل', 'connected');
                    this.socket.emit('join_room', { room: 'dashboard' });
                    console.log('✅ تم الاتصال بالخادم');
                });
                
                this.socket.on('disconnect', () => {
                    this.isConnected = false;
                    this.updateConnectionStatus('غير متصل', 'disconnected');
                    console.log('❌ تم قطع الاتصال بالخادم');
                });
                
                this.socket.on('system_overview', (data) => {
                    this.overview = data;
                    this.updateStatusBar();
                });
                
                this.socket.on('nodes_update', (data) => {
                    this.nodes = data;
                    this.updateNodesGrid();
                    this.updateLastUpdate();
                });
                
                this.socket.on('error', (data) => {
                    console.error('❌ خطأ:', data.message);
                });
            }
            
            updateConnectionStatus(text, className) {
                const statusElement = document.getElementById('connectionStatus');
                statusElement.textContent = text;
                statusElement.className = `connection-status ${className}`;
            }
            
            updateStatusBar() {
                const statusBar = document.getElementById('statusBar');
                if (!statusBar) return;
                
                statusBar.innerHTML = `
                    <div class="status-item">
                        <h3>إجمالي العقد</h3>
                        <div class="value">${this.overview.total_nodes || 0}</div>
                    </div>
                    <div class="status-item">
                        <h3>العقد النشطة</h3>
                        <div class="value">${this.overview.online_nodes || 0}</div>
                    </div>
                    <div class="status-item">
                        <h3>متوسط CPU</h3>
                        <div class="value">${this.overview.avg_cpu_usage || 0}%</div>
                    </div>
                    <div class="status-item">
                        <h3>متوسط الذاكرة</h3>
                        <div class="value">${this.overview.avg_memory_usage || 0}%</div>
                    </div>
                    <div class="status-item">
                        <h3>وقت التشغيل</h3>
                        <div class="value">${Math.round((this.overview.system_uptime || 0) / 60)} د</div>
                    </div>
                `;
            }
            
            updateNodesGrid() {
                const nodesGrid = document.getElementById('nodesGrid');
                if (!nodesGrid) return;
                
                if (Object.keys(this.nodes).length === 0) {
                    nodesGrid.innerHTML = '<div style="grid-column: 1/-1; text-align: center; padding: 40px; color: white; font-size: 1.2em;">لا توجد عقد متصلة حالياً</div>';
                    return;
                }
                
                nodesGrid.innerHTML = Object.values(this.nodes).map(node => `
                    <div class="node-card">
                        <div class="node-header">
                            <div class="node-name">${node.hostname}</div>
                            <div class="node-status ${node.online ? 'status-online' : 'status-offline'}">
                                ${node.online ? '🟢 نشط' : '🔴 غير متصل'}
                            </div>
                        </div>
                        <div class="metrics">
                            <div class="metric">
                                <div class="metric-label">💻 CPU</div>
                                <div class="metric-value">${node.metrics.cpu_percent}%</div>
                            </div>
                            <div class="metric">
                                <div class="metric-label">🧠 ذاكرة</div>
                                <div class="metric-value">${node.metrics.memory_percent}%</div>
                            </div>
                            <div class="metric">
                                <div class="metric-label">🖥️ GPU</div>
                                <div class="metric-value">${node.metrics.gpu_percent}%</div>
                            </div>
                            <div class="metric">
                                <div class="metric-label">💾 قرص</div>
                                <div class="metric-value">${node.metrics.disk_usage}%</div>
                            </div>
                        </div>
                        <div style="margin-top: 15px; font-size: 0.8em; color: #666;">
                            <strong>IP:</strong> ${node.ip_address}<br>
                            <strong>آخر تحديث:</strong> ${new Date(node.last_seen).toLocaleTimeString('ar-EG')}
                        </div>
                    </div>
                `).join('');
            }
            
            updateLastUpdate() {
                const lastUpdate = document.getElementById('lastUpdate');
                if (lastUpdate) {
                    lastUpdate.textContent = `آخر تحديث: ${new Date().toLocaleTimeString('ar-EG')}`;
                }
            }
            
            setupEventListeners() {
                // إعادة الاتصال عند فقدان الاتصال
                setInterval(() => {
                    if (!this.isConnected && this.socket) {
                        console.log('🔄 محاولة إعادة الاتصال...');
                        this.socket.connect();
                    }
                }, 5000);
            }
        }
        
        // بدء التطبيق عند تحميل الصفحة
        document.addEventListener('DOMContentLoaded', () => {
            window.dashboard = new Dashboard();
        });
    </script>
</body>
</html>
"""

# ---- مسارات HTTP -----------------------------------------------------------

@app.route('/')
@limiter.exempt
def index():
    """الصفحة الرئيسية للوحة التحكم"""
    return HTML_TEMPLATE

@app.route('/api/overview')
@limiter.limit("10 per minute")
def get_overview():
    """الحصول على نظرة عامة على النظام"""
    return jsonify(dashboard_manager.get_system_overview())

@app.route('/api/nodes')
@limiter.limit("20 per minute")
def get_nodes():
    """الحصول على قائمة العقد"""
    with dashboard_manager._lock:
        nodes_data = {
            node_id: node.to_dict() 
            for node_id, node in dashboard_manager.nodes.items()
        }
    return jsonify(nodes_data)

@app.route('/api/nodes/<node_id>')
@limiter.limit("30 per minute")
def get_node_details(node_id):
    """الحصول على تفاصيل عقدة محددة"""
    with dashboard_manager._lock:
        if node_id not in dashboard_manager.nodes:
            return jsonify({"error": "العقدة غير موجودة"}), 404
        
        node_info = dashboard_manager.nodes[node_id].to_dict()
        node_info["history"] = dashboard_manager.get_node_history(node_id, 20)
        
    return jsonify(node_info)

@app.route('/api/nodes/<node_id>/history')
@limiter.limit("20 per minute")
def get_node_history(node_id):
    """الحصول على السجل التاريخي للعقدة"""
    limit = request.args.get('limit', 50, type=int)
    history = dashboard_manager.get_node_history(node_id, limit)
    return jsonify(history)

@app.route('/api/health')
@limiter.exempt
def health_check():
    """فحص صحة النظام"""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "version": "2.0.0",
        "connected_clients": len(dashboard_manager._connected_clients)
    })

# ---- معالجات WebSocket -----------------------------------------------------

@socketio.on('connect')
def handle_connect():
    """معالجة اتصال عميل جديد"""
    try:
        client_id = request.sid
        node_id = socket.gethostname()
        hostname = socket.gethostname()
        ip_address = request.remote_addr
        
        # إضافة العميل إلى القائمة
        dashboard_manager.add_client(client_id)
        
        # تسجيل العقدة
        node_info = dashboard_manager.register_node(
            node_id=node_id,
            hostname=hostname,
            ip_address=ip_address,
            connection_id=client_id,
            capabilities=['dashboard', 'monitoring']
        )
        
        join_room('dashboard')
        emit('connection_established', {
            'node_id': node_id,
            'message': 'تم الاتصال بلوحة التحكم بنجاح'
        })
        
        logger.info(f"✅ عميل متصل: {node_id} من {ip_address}")
        
    except Exception as e:
        logger.error(f"❌ خطأ في اتصال العميل: {e}")
        emit('error', {'message': 'فشل في الاتصال'})

@socketio.on('disconnect')
def handle_disconnect():
    """معالجة انفصال العميل"""
    try:
        client_id = request.sid
        node_id = socket.gethostname()
        
        # إزالة العميل من القائمة
        dashboard_manager.remove_client(client_id)
        dashboard_manager.remove_node(node_id)
        leave_room('dashboard')
        
        logger.info(f"➖ عميل منفصل: {node_id}")
        
    except Exception as e:
        logger.error(f"❌ خطأ في انفصال العميل: {e}")

@socketio.on('join_room')
def handle_join_room(data):
    """انضمام إلى غرفة محددة"""
    room = data.get('room', 'default')
    join_room(room)
    emit('room_joined', {'room': room})

@socketio.on('leave_room')
def handle_leave_room(data):
    """مغادرة غرفة محددة"""
    room = data.get('room', 'default')
    leave_room(room)
    emit('room_left', {'room': room})

# ---- تشغيل التطبيق ---------------------------------------------------------

def main():
    """الدالة الرئيسية"""
    try:
        # بدء مدير اللوحة
        dashboard_manager.start()
        
        # تشغيل الخادم
        logger.info(f"🚀 تشغيل لوحة التحكم على http://0.0.0.0:{DASHBOARD_PORT}")
        logger.info(f"📊 يمكن الوصول للوحة من: http://localhost:{DASHBOARD_PORT}")
        
        socketio.run(
            app,
            host="0.0.0.0",
            port=DASHBOARD_PORT,
            debug=False,
            allow_unsafe_werkzeug=True,
            log_output=False  # تقليل السجلات
        )
        
    except KeyboardInterrupt:
        logger.info("🛑 إيقاف لوحة التحكم...")
        dashboard_manager.stop()
    except Exception as e:
        logger.error(f"❌ خطأ غير متوقع: {e}")
        dashboard_manager.stop()

if __name__ == "__main__":
    main()
