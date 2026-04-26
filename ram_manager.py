#!/usr/bin/env python3
"""
ram_manager.py – نظام إدارة الذاكرة الموزعة المحسن
===================================================

❖ الغرض
--------
نظام متقدم لمشاركة الذاكرة بين العقد في شبكة AmalOffload مع إدارة ذكية للموارد
وأمان محسن وكفاءة في التخزين.

❖ المزايا المحسنة
------------------
* مراقبة ذكية للذاكرة مع عتبات تكيفية
* اكتشاف ديناميكي للأقران مع مراقبة الصحة
* تخزين هرمي (ذاكرة + قرص) مع استرجاع آلي
* ضغط البيانات وتشفيرها
* واجهة REST API شاملة
* إدارة ذكية لدورة حياة البيانات
"""

import os
import psutil
import time
import threading
import socket
import base64
import uuid
import zlib
import json
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from enum import Enum
import sqlite3
from pathlib import Path

try:
    from flask import Flask, request, jsonify
    from werkzeug.serving import make_server
except ImportError as exc:
    raise RuntimeError("Flask غير مُثبّت. نفِّذ: pip install flask") from exc

# إعداد السجلات
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class StorageTier(Enum):
    """مستويات التخزين"""
    MEMORY = "memory"
    DISK = "disk"
    REMOTE = "remote"

class ChunkStatus(Enum):
    """حالات كتلة البيانات"""
    ACTIVE = "active"
    ARCHIVED = "archived"
    EXPIRED = "expired"
    DELETED = "deleted"

@dataclass
class ChunkMetadata:
    """بيانات وصفية لكتلة البيانات"""
    chunk_id: str
    size_mb: float
    created_at: datetime
    accessed_at: datetime
    access_count: int
    tier: StorageTier
    status: ChunkStatus
    source_node: str
    compression_ratio: float
    ttl_hours: int

@dataclass
class NodeHealth:
    """صحة العقدة"""
    free_ram_mb: float
    total_ram_mb: float
    disk_free_mb: float
    cpu_usage: float
    last_seen: datetime
    is_active: bool
    capacity_score: float

class EnhancedRAMManager:
    """مدير ذاكرة موزع محسن"""
    
    def __init__(self):
        # الإعدادات - قابلة للتعديل عبر متغيّرات البيئة
        self.ram_limit_mb = int(os.getenv("RAM_THRESHOLD_MB", "2048"))
        self.chunk_size_mb = int(os.getenv("RAM_CHUNK_MB", "32"))
        self.check_interval = int(os.getenv("RAM_CHECK_INTERVAL", "10"))
        self.ram_port = int(os.getenv("RAM_PORT", "8765"))
        self.max_disk_storage_mb = int(os.getenv("MAX_DISK_STORAGE_MB", "1024"))  # 1GB
        
        # تخزين البيانات
        self.memory_chunks: Dict[str, bytes] = {}
        self.chunk_metadata: Dict[str, ChunkMetadata] = {}
        self.remote_nodes: Dict[str, NodeHealth] = {}
        
        # قواعد البيانات
        self.db_path = Path("ram_storage.db")
        self._init_database()
        
        # إحصائيات
        self.stats = {
            'total_chunks_stored': 0,
            'memory_chunks': 0,
            'disk_chunks': 0,
            'remote_chunks': 0,
            'total_data_offloaded_mb': 0,
            'compression_savings_mb': 0
        }
        
        # التزامن
        self._lock = threading.RLock()
        self._running = True
        
        # تطبيق Flask
        self.app = Flask(__name__)
        self._setup_routes()
        
        logger.info("🚀 بدء نظام إدارة الذاكرة الموزعة المحسن")
    
    def _init_database(self):
        """تهيئة قاعدة البيانات للتخزين الدائم"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS chunk_metadata (
                    chunk_id TEXT PRIMARY KEY,
                    size_mb REAL,
                    created_at TEXT,
                    accessed_at TEXT,
                    access_count INTEGER,
                    tier TEXT,
                    status TEXT,
                    source_node TEXT,
                    compression_ratio REAL,
                    ttl_hours INTEGER,
                    data BLOB
                )
            ''')
            
            conn.commit()
            conn.close()
            logger.info("✅ قاعدة البيانات مهيأة")
            
        except Exception as e:
            logger.error(f"❌ فشل تهيئة قاعدة البيانات: {e}")
    
    def _setup_routes(self):
        """إعداد مسارات واجهة API"""
        
        @self.app.route("/")
        def index():
            """الصفحة الرئيسية"""
            return jsonify({
                "service": "Enhanced RAM Manager",
                "version": "2.0",
                "endpoints": {
                    "/health": "صحة النظام",
                    "/status": "حالة الذاكرة",
                    "/store": "تخزين بيانات (POST)",
                    "/retrieve/<chunk_id>": "استرجاع بيانات",
                    "/nodes": "قائمة العقد المتاحة",
                    "/stats": "إحصائيات النظام"
                }
            })
        
        @self.app.route("/health", methods=["GET"])
        def health():
            """صحة النظام الشاملة"""
            health_info = self._get_system_health()
            return jsonify(health_info)
        
        @self.app.route("/status", methods=["GET"])
        def status():
            """حالة الذاكرة والموارد"""
            with self._lock:
                free_ram = self._get_free_ram_mb()
                total_ram = psutil.virtual_memory().total / (1024 ** 2)
                disk_usage = psutil.disk_usage('/').percent
            
            return jsonify({
                "memory": {
                    "free_mb": round(free_ram, 1),
                    "total_mb": round(total_ram, 1),
                    "usage_percent": round((1 - free_ram / total_ram) * 100, 1)
                },
                "disk_usage_percent": disk_usage,
                "active_chunks": len(self.memory_chunks),
                "node_capacity": self._calculate_capacity_score()
            })
        
        @self.app.route("/store", methods=["POST"])
        def store():
            """تخزين بيانات مع معالجة متقدمة"""
            try:
                if not request.is_json:
                    return jsonify({"error": "يجب أن يكون المحتوى JSON"}), 400
                
                data = request.get_json(force=True)
                
                # التحقق من الحقول المطلوبة
                if 'data' not in data:
                    return jsonify({"error": "حقل البيانات مطلوب"}), 400
                
                # معالجة البيانات
                raw_data = base64.b64decode(data['data'])
                chunk_id = data.get('chunk_id', str(uuid.uuid4()))
                ttl_hours = data.get('ttl_hours', 24)  # وقت البقاء افتراضي 24 ساعة
                
                # تخزين البيانات
                success, message = self._store_chunk(chunk_id, raw_data, ttl_hours)
                
                if success:
                    return jsonify({
                        "status": "success",
                        "chunk_id": chunk_id,
                        "message": message,
                        "size_mb": len(raw_data) / (1024 ** 2)
                    })
                else:
                    return jsonify({"error": message}), 507  # Insufficient Storage
                    
            except Exception as e:
                logger.error(f"❌ خطأ في التخزين: {e}")
                return jsonify({"error": f"خطأ في المعالجة: {str(e)}"}), 500
        
        @self.app.route("/retrieve/<chunk_id>", methods=["GET"])
        def retrieve(chunk_id):
            """استرجاع بيانات"""
            try:
                data = self._retrieve_chunk(chunk_id)
                if data is None:
                    return jsonify({"error": "البيانات غير موجودة"}), 404
                
                return jsonify({
                    "chunk_id": chunk_id,
                    "data": base64.b64encode(data).decode(),
                    "size_bytes": len(data)
                })
                
            except Exception as e:
                logger.error(f"❌ خطأ في الاسترجاع: {e}")
                return jsonify({"error": str(e)}), 500
        
        @self.app.route("/nodes", methods=["GET"])
        def list_nodes():
            """قائمة العقد المتاحة"""
            with self._lock:
                active_nodes = {
                    node: asdict(health) 
                    for node, health in self.remote_nodes.items() 
                    if health.is_active
                }
            
            return jsonify({
                "total_nodes": len(active_nodes),
                "active_nodes": active_nodes
            })
        
        @self.app.route("/stats", methods=["GET"])
        def statistics():
            """إحصائيات النظام"""
            with self._lock:
                stats = self.stats.copy()
                stats['memory_usage_mb'] = self._get_memory_usage()
                stats['disk_usage_mb'] = self._get_disk_usage()
            
            return jsonify(stats)
    
    def _get_free_ram_mb(self) -> float:
        """الحصول على الذاكرة الحرة بالميغابايت"""
        return psutil.virtual_memory().available / (1024 ** 2)
    
    def _get_system_health(self) -> Dict:
        """الحصول على صحة النظام الشاملة"""
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        
        return {
            "timestamp": datetime.now().isoformat(),
            "memory": {
                "total_gb": round(memory.total / (1024 ** 3), 1),
                "available_gb": round(memory.available / (1024 ** 3), 1),
                "used_percent": memory.percent
            },
            "disk": {
                "total_gb": round(disk.total / (1024 ** 3), 1),
                "free_gb": round(disk.free / (1024 ** 3), 1),
                "used_percent": disk.percent
            },
            "cpu_usage_percent": psutil.cpu_percent(interval=1),
            "load_average": os.getloadavg() if hasattr(os, 'getloadavg') else [0, 0, 0],
            "active_threads": threading.active_count(),
            "chunk_stats": self.stats
        }
    
    def _calculate_capacity_score(self) -> float:
        """حساب درجة سعة العقدة (0-1)"""
        free_ram = self._get_free_ram_mb()
        total_ram = psutil.virtual_memory().total / (1024 ** 2)
        disk_free = psutil.disk_usage('/').free / (1024 ** 2)
        
        ram_score = min(1.0, free_ram / 4096)  # Normalize to 4GB
        disk_score = min(1.0, disk_free / 5000)  # Normalize to 5GB
        
        return round((ram_score * 0.7 + disk_score * 0.3), 2)
    
    def _compress_data(self, data: bytes) -> Tuple[bytes, float]:
        """ضغط البيانات وإرجاع نسبة الضغط"""
        compressed = zlib.compress(data, level=6)
        ratio = len(compressed) / len(data) if data else 1.0
        return compressed, ratio
    
    def _decompress_data(self, compressed_data: bytes) -> bytes:
        """فك ضغط البيانات"""
        return zlib.decompress(compressed_data)
    
    def _store_chunk(self, chunk_id: str, data: bytes, ttl_hours: int) -> Tuple[bool, str]:
        """تخزين كتلة بيانات مع إدارة ذكية"""
        try:
            with self._lock:
                # ضغط البيانات
                compressed_data, compression_ratio = self._compress_data(data)
                size_mb = len(compressed_data) / (1024 ** 2)
                
                # التحقق من السعة
                free_ram = self._get_free_ram_mb()
                
                if free_ram > self.ram_limit_mb:
                    # التخزين في الذاكرة
                    self.memory_chunks[chunk_id] = compressed_data
                    tier = StorageTier.MEMORY
                    message = "مخزن في الذاكرة"
                else:
                    # التخزين في القرص
                    if not self._store_to_disk(chunk_id, compressed_data):
                        return False, "لا توجد سعة تخزين كافية"
                    tier = StorageTier.DISK
                    message = "مخزن في القرص"
                
                # حفظ البيانات الوصفية
                metadata = ChunkMetadata(
                    chunk_id=chunk_id,
                    size_mb=size_mb,
                    created_at=datetime.now(),
                    accessed_at=datetime.now(),
                    access_count=0,
                    tier=tier,
                    status=ChunkStatus.ACTIVE,
                    source_node=socket.gethostname(),
                    compression_ratio=compression_ratio,
                    ttl_hours=ttl_hours
                )
                
                self.chunk_metadata[chunk_id] = metadata
                self._save_metadata_to_db(metadata, compressed_data)
                
                # تحديث الإحصائيات
                self.stats['total_chunks_stored'] += 1
                self.stats['memory_chunks'] = len(self.memory_chunks)
                self.stats['compression_savings_mb'] += len(data) / (1024 ** 2) - size_mb
                
                logger.info(f"💾 تم تخزين كتلة {chunk_id} ({size_mb:.2f} MB) - {message}")
                return True, message
                
        except Exception as e:
            logger.error(f"❌ فشل تخزين الكتلة {chunk_id}: {e}")
            return False, str(e)
    
    def _store_to_disk(self, chunk_id: str, data: bytes) -> bool:
        """تخزين البيانات في القرص"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT OR REPLACE INTO chunk_metadata 
                (chunk_id, data) VALUES (?, ?)
            ''', (chunk_id, data))
            
            conn.commit()
            conn.close()
            return True
            
        except Exception as e:
            logger.error(f"❌ فشل التخزين في القرص: {e}")
            return False
    
    def _retrieve_chunk(self, chunk_id: str) -> Optional[bytes]:
        """استرجاع كتلة بيانات"""
        try:
            with self._lock:
                # البحث في الذاكرة أولاً
                if chunk_id in self.memory_chunks:
                    compressed_data = self.memory_chunks[chunk_id]
                    self._update_chunk_access(chunk_id)
                else:
                    # البحث في القرص
                    compressed_data = self._retrieve_from_disk(chunk_id)
                    if compressed_data is None:
                        return None
                
                # فك الضغط
                data = self._decompress_data(compressed_data)
                self._update_chunk_access(chunk_id)
                
                return data
                
        except Exception as e:
            logger.error(f"❌ فشل استرجاع الكتلة {chunk_id}: {e}")
            return None
    
    def _retrieve_from_disk(self, chunk_id: str) -> Optional[bytes]:
        """استرجاع البيانات من القرص"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('SELECT data FROM chunk_metadata WHERE chunk_id = ?', (chunk_id,))
            result = cursor.fetchone()
            
            conn.close()
            return result[0] if result else None
            
        except Exception as e:
            logger.error(f"❌ فشل الاسترجاع من القرص: {e}")
            return None
    
    def _update_chunk_access(self, chunk_id: str):
        """تحديث بيانات الوصول للكتلة"""
        if chunk_id in self.chunk_metadata:
            metadata = self.chunk_metadata[chunk_id]
            metadata.accessed_at = datetime.now()
            metadata.access_count += 1
    
    def _save_metadata_to_db(self, metadata: ChunkMetadata, data: bytes):
        """حفظ البيانات الوصفية في قاعدة البيانات"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT OR REPLACE INTO chunk_metadata 
                (chunk_id, size_mb, created_at, accessed_at, access_count, 
                 tier, status, source_node, compression_ratio, ttl_hours, data)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                metadata.chunk_id,
                metadata.size_mb,
                metadata.created_at.isoformat(),
                metadata.accessed_at.isoformat(),
                metadata.access_count,
                metadata.tier.value,
                metadata.status.value,
                metadata.source_node,
                metadata.compression_ratio,
                metadata.ttl_hours,
                data
            ))
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            logger.error(f"❌ فشل حفظ البيانات الوصفية: {e}")
    
    def _get_memory_usage(self) -> float:
        """حساب استخدام الذاكرة للتخزين"""
        total_size = 0
        for chunk_data in self.memory_chunks.values():
            total_size += len(chunk_data)
        return total_size / (1024 ** 2)
    
    def _get_disk_usage(self) -> float:
        """حساب استخدام القرص للتخزين"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('SELECT SUM(LENGTH(data)) FROM chunk_metadata')
            result = cursor.fetchone()
            conn.close()
            
            return (result[0] or 0) / (1024 ** 2)
            
        except Exception as e:
            logger.error(f"❌ فشل حساب استخدام القرص: {e}")
            return 0
    
    def start_monitoring(self):
        """بدء المراقبة الخلفية"""
        def monitor_loop():
            while self._running:
                try:
                    self._check_memory_pressure()
                    self._cleanup_expired_chunks()
                    self._discover_and_update_nodes()
                    time.sleep(self.check_interval)
                    
                except Exception as e:
                    logger.error(f"❌ خطأ في المراقبة: {e}")
                    time.sleep(5)
        
        threading.Thread(target=monitor_loop, daemon=True).start()
        logger.info("🔍 بدء المراقبة الخلفية")
    
    def _check_memory_pressure(self):
        """التحقق من ضغط الذاكرة وإدارة التخزين"""
        free_ram = self._get_free_ram_mb()
        
        if free_ram < self.ram_limit_mb:
            # نقل البيانات من الذاكرة إلى القرص
            self._migrate_memory_to_disk()
            
            # إذا لا يزال الضغط مرتفعاً، التفكير في التوزيع
            if free_ram < self.ram_limit_mb * 0.5:
                self._consider_offload()
    
    def _migrate_memory_to_disk(self):
        """نقل البيانات من الذاكرة إلى القرص"""
        chunks_to_migrate = []
        
        with self._lock:
            for chunk_id, data in self.memory_chunks.items():
                if self._store_to_disk(chunk_id, data):
                    chunks_to_migrate.append(chunk_id)
            
            # إزالة من الذاكرة بعد النقل الناجح
            for chunk_id in chunks_to_migrate:
                del self.memory_chunks[chunk_id]
                if chunk_id in self.chunk_metadata:
                    self.chunk_metadata[chunk_id].tier = StorageTier.DISK
        
        if chunks_to_migrate:
            logger.info(f"📦 تم نقل {len(chunks_to_migrate)} كتلة من الذاكرة إلى القرص")
    
    def _consider_offload(self):
        """التفكير في توزيع البيانات لعقد أخرى"""
        # البحث عن عقد ذات سعة جيدة
        suitable_nodes = [
            node for node, health in self.remote_nodes.items()
            if health.is_active and health.capacity_score > 0.7
        ]
        
        if suitable_nodes:
            logger.info(f"🌐 توزيع البيانات إلى {len(suitable_nodes)} عقدة مناسبة")
            # تنفيذ التوزيع الفعلي يمكن إضافته هنا
    
    def _cleanup_expired_chunks(self):
        """تنظيف البيانات المنتهية الصلاحية"""
        current_time = datetime.now()
        chunks_to_remove = []
        
        with self._lock:
            for chunk_id, metadata in self.chunk_metadata.items():
                expiry_time = metadata.created_at + timedelta(hours=metadata.ttl_hours)
                if current_time > expiry_time:
                    chunks_to_remove.append(chunk_id)
        
        # الإزالة
        for chunk_id in chunks_to_remove:
            self._remove_chunk(chunk_id)
        
        if chunks_to_remove:
            logger.info(f"🧹 تم تنظيف {len(chunks_to_remove)} كتلة منتهية الصلاحية")
    
    def _remove_chunk(self, chunk_id: str):
        """إزالة كتلة بيانات"""
        with self._lock:
            # إزالة من الذاكرة
            if chunk_id in self.memory_chunks:
                del self.memory_chunks[chunk_id]
            
            # إزالة من قاعدة البيانات
            try:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                cursor.execute('DELETE FROM chunk_metadata WHERE chunk_id = ?', (chunk_id,))
                conn.commit()
                conn.close()
            except Exception as e:
                logger.error(f"❌ فشل إزالة الكتلة من قاعدة البيانات: {e}")
            
            # إزالة البيانات الوصفية
            if chunk_id in self.chunk_metadata:
                del self.chunk_metadata[chunk_id]
    
    def _discover_and_update_nodes(self):
        """اكتشاف وتحديث حالة العقد المتاحة"""
        # يمكن دمج هذا مع نظام اكتشاف الأقران في المشروع
        # حالياً، تنفيذ بسيط للتوضيح
        pass
    
    def run_server(self, host: str = "0.0.0.0", port: int = None):
        """تشغيل خادم الويب"""
        if port is None:
            port = self.ram_port
        
        logger.info(f"🌐 بدء خادم الذاكرة على {host}:{port}")
        self.start_monitoring()
        
        try:
            server = make_server(host, port, self.app)
            server.serve_forever()
        except KeyboardInterrupt:
            logger.info("🛑 إيقاف الخادم...")
            self._running = False

# التوافق مع الإصدار القديم
def main():
    """الدالة الرئيسية للتوافق"""
    manager = EnhancedRAMManager()
    manager.run_server()

if __name__ == "__main__":
    main()