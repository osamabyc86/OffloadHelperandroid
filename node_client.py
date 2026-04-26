#!/usr/bin/env python3
# ================================================================
# node_client.py – عميل تسجيل العُقدة المحسن في نظام AmalOffload
# ---------------------------------------------------------------
# • نظام تسجيل متقدم مع اكتشاف ذاتي ومراقبة صحة
# • دعم متعدد البروتوكولات وموازنة حمل ذكية
# • تحديثات حية ونسخ احتياطية تلقائية
# ================================================================

import os
import socket
import time
import logging
import random
import requests
import asyncio
import aiohttp
import threading
import psutil
from typing import Iterable, Tuple, List, Dict, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

# ⬇️ منافذ مقترحة مع تصنيف حسب الأولوية
DEFAULT_PORTS = {
    7520, 7384, 9021, 6998, 5810, 9274,
    8645, 7329, 7734, 8456, 6173, 7860,
    5297, 5298, 5299, 5300  # منافذ إضافية متوافقة
}

# ⬇️ خوادم السجل الاحتياطية مع أوزان الأداء
DEFAULT_REGISTRY_SERVERS = [
    {"url": "https://cv4790811.regru.cloud", "priority": 1, "type": "primary"},
    {"url": "https://amaloffload.onrender.com", "priority": 2, "type": "primary"},
    {"url": "https://osamabyc86-offload.hf.space", "priority": 3, "type": "secondary"},
    {"url": "http://10.229.36.125", "priority": 4, "type": "local"},
    {"url": "http://10.229.228.178", "priority": 5, "type": "local"},
]

# ⬇️ إعدادات السجلات المتقدمة
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("NodeClient")

@dataclass
class NodeMetrics:
    """مقاييس أداء العقدة"""
    cpu_usage: float = 0.0
    memory_usage: float = 0.0
    disk_usage: float = 0.0
    network_latency: float = 0.0
    active_tasks: int = 0
    success_rate: float = 1.0
    last_update: datetime = None
    health_score: float = 100.0

    def __post_init__(self):
        if self.last_update is None:
            self.last_update = datetime.now()

    def to_dict(self) -> Dict:
        """تحويل إلى قاموس للتسجيل"""
        return {
            "cpu_usage": round(self.cpu_usage, 2),
            "memory_usage": round(self.memory_usage, 2),
            "disk_usage": round(self.disk_usage, 2),
            "network_latency": round(self.network_latency, 4),
            "active_tasks": self.active_tasks,
            "success_rate": round(self.success_rate, 3),
            "health_score": round(self.health_score, 1),
            "last_update": self.last_update.isoformat()
        }

class AdvancedNodeClient:
    """
    عميل متقدم للتسجيل والاكتشاف في نظام AmalOffload
    مع مراقبة الصحة والتحديثات التلقائية
    """

    def __init__(
        self,
        ports: Iterable[int] | None = None,
        registry_servers: List[Dict] | None = None,
        node_id: str | None = None,
        capabilities: List[str] | None = None,
        heartbeat_interval: int = 30,
        discovery_interval: int = 60,
        max_retries: int = 3
    ):
        self.ports = set(ports) if ports else DEFAULT_PORTS
        self.registry_servers = registry_servers or DEFAULT_REGISTRY_SERVERS
        self.node_id = node_id or os.getenv("NODE_ID", socket.gethostname())
        self.capabilities = capabilities or ["compute", "storage", "network", "web_api"]
        self.heartbeat_interval = heartbeat_interval
        self.discovery_interval = discovery_interval
        self.max_retries = max_retries
        
        # حالة العقدة
        self.port: int = int(os.getenv("CPU_PORT", random.choice(list(self.ports))))
        self.current_server: Optional[Dict] = None
        self.registered_peers: List[Dict] = []
        self.node_metrics = NodeMetrics()
        self.is_running = False
        self.session = None
        
        # إحصائيات
        self.registration_attempts = 0
        self.successful_registrations = 0
        self.failed_registrations = 0
        self.last_successful_registration = None
        self.total_uptime = 0.0
        self.start_time = datetime.now()
        
        # تخزين مؤقت
        self.peer_cache: Dict[str, Dict] = {}
        self.server_performance: Dict[str, float] = {}
        self.connection_history: List[Dict] = []

    # -------------------------------------------------------------------------
    async def init_session(self):
        """تهيئة جلسة HTTP غير متزامنة"""
        if not self.session:
            timeout = aiohttp.ClientTimeout(total=10)
            self.session = aiohttp.ClientSession(timeout=timeout)

    @staticmethod
    def get_local_ip() -> str:
        """يحاول معرفة أفضل عنوان IP محلي لاستخدامه في الشبكة."""
        methods = [
            # الطريقة المباشرة
            lambda: socket.gethostbyname(socket.gethostname()),
            # الطريقة مع الاتصال
            lambda: socket.socket(socket.AF_INET, socket.SOCK_DGRAM).connect(("8.8.8.8", 80)).getsockname()[0],
            # من المتغيرات البيئية
            lambda: os.getenv("HOST_IP", "127.0.0.1"),
            # الطريقة الأصلية
            lambda: socket.socket(socket.AF_INET, socket.SOCK_DGRAM).connect(("10.255.255.255", 1)).getsockname()[0]
        ]
        
        for method in methods:
            try:
                ip = method()
                if ip and ip != "127.0.0.1" and not ip.startswith("127."):
                    logger.info(f"🌐 تم اكتشاف IP المحلي: {ip}")
                    return ip
            except Exception:
                continue
                
        logger.warning("⚠️ استخدام العنوان المحلي الافتراضي: 127.0.0.1")
        return "127.0.0.1"

    def collect_system_metrics(self) -> Dict:
        """جمع مقاييس أداء النظام الحقيقية"""
        try:
            # مقاييس حقيقية من النظام
            cpu_usage = psutil.cpu_percent(interval=0.1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            
            # تحديث مقاييس العقدة
            self.node_metrics.cpu_usage = cpu_usage
            self.node_metrics.memory_usage = memory.percent
            self.node_metrics.disk_usage = disk.percent
            self.node_metrics.active_tasks = len(psutil.Process().threads())
            self.node_metrics.last_update = datetime.now()
            
            # حساب درجة الصحة
            health_score = 100.0
            if cpu_usage > 90:
                health_score -= 20
            elif cpu_usage > 70:
                health_score -= 10
                
            if memory.percent > 90:
                health_score -= 20
            elif memory.percent > 70:
                health_score -= 10
                
            if disk.percent > 90:
                health_score -= 10
                
            self.node_metrics.health_score = max(0, health_score)
            
            return self.node_metrics.to_dict()
            
        except Exception as e:
            logger.error(f"❌ خطأ في جمع مقاييس النظام: {e}")
            # استخدام قيم افتراضية كنسخة احتياطية
            return {
                "cpu_usage": 25.0,
                "memory_usage": 45.0,
                "disk_usage": 60.0,
                "network_latency": 0.1,
                "active_tasks": 5,
                "success_rate": 0.95,
                "health_score": 85.0,
                "last_update": datetime.now().isoformat()
            }

    def get_node_info(self, port: int) -> Dict:
        """الحصول على معلومات العقدة للتسجيل"""
        return {
            "node_id": self.node_id,
            "ip": self.get_local_ip(),
            "port": port,
            "capabilities": self.capabilities,
            "metrics": self.collect_system_metrics(),
            "status": "active",
            "last_seen": datetime.now().isoformat(),
            "version": "2.0.0",
            "hostname": socket.gethostname()
        }

    async def _register_async(self, server: Dict, port: int) -> Tuple[bool, List[Dict]]:
        """محاولة تسجيل غير متزامنة مع تقييم الأداء"""
        try:
            start_time = time.time()
            
            async with self.session.post(
                f"{server['url']}/register",
                json=self.get_node_info(port),
                timeout=10
            ) as response:
                
                if response.status == 200:
                    peers_data = await response.json()
                    response_time = time.time() - start_time
                    
                    # تحديث أداء السيرفر
                    self.server_performance[server['url']] = response_time
                    
                    logger.info(f"✅ تسجيل ناجح: {server['url']}:{port} ({response_time:.2f}s)")
                    return True, peers_data
                else:
                    logger.warning(f"⚠️ استجابة غير ناجحة من {server['url']}: {response.status}")
                    return False, []
                    
        except asyncio.TimeoutError:
            logger.warning(f"⏰ انتهت المهلة مع {server['url']}")
            return False, []
        except Exception as e:
            logger.error(f"❌ خطأ في التسجيل مع {server['url']}: {e}")
            return False, []

    def _get_optimal_server_order(self) -> List[Dict]:
        """ترتيب الخوادم حسب الأولوية والأداء"""
        servers = self.registry_servers.copy()
        
        # ترتيب حسب الأولوية ثم الأداء
        servers.sort(key=lambda s: (
            s.get('priority', 999),
            self.server_performance.get(s['url'], float('inf'))
        ))
        
        return servers

    # -------------------------------------------------------------------------
    async def connect_until_success_async(self, retry_delay: int = 5) -> Tuple[Dict, List[Dict]]:
        """
        نسخة غير متزامنة من التسجيل المستمر
        """
        await self.init_session()
        logger.info(f"🚀 بدء محاولات التسجيل للعقدة '{self.node_id}'...")
        
        self.registration_attempts = 0
        self.is_running = True
        
        while self.is_running:
            self.registration_attempts += 1
            
            # الحصول على ترتيب الخوادم الأمثل
            optimal_servers = self._get_optimal_server_order()
            
            for port in self.ports:
                for server in optimal_servers:
                    if not self.is_running:
                        break
                        
                    success, peers_data = await self._register_async(server, port)
                    
                    if success:
                        self.current_server = server
                        self.port = port
                        self.registered_peers = peers_data
                        self.successful_registrations += 1
                        self.last_successful_registration = datetime.now()
                        
                        # تسجيل في السجل التاريخي
                        self.connection_history.append({
                            "server": server['url'],
                            "port": port,
                            "timestamp": datetime.now().isoformat(),
                            "peers_count": len(peers_data),
                            "success": True
                        })
                        
                        logger.info(f"🎯 متصل بـ {server['url']} على المنفذ {port}")
                        logger.info(f"👥 تم استلام {len(peers_data)} قرين")
                        return server, peers_data
                    else:
                        self.failed_registrations += 1
            
            # انتظار قبل إعادة المحاولة مع زيادة ذكية
            actual_delay = retry_delay + (self.registration_attempts // 3)
            logger.info(f"🔄 إعادة المحاولة خلال {actual_delay} ثواني (المحاولة: {self.registration_attempts})...")
            await asyncio.sleep(actual_delay)

    async def start_heartbeat(self):
        """بدء إرسال نبضات حية للحفاظ على التسجيل"""
        logger.info("❤️ بدء إرسال النبضات للحفاظ على التسجيل...")
        
        consecutive_failures = 0
        max_consecutive_failures = 3
        
        while self.is_running and self.current_server:
            try:
                # تحديث معلومات العقدة
                node_info = self.get_node_info(self.port)
                
                async with self.session.post(
                    f"{self.current_server['url']}/heartbeat",
                    json=node_info,
                    timeout=5
                ) as response:
                    
                    if response.status == 200:
                        logger.debug("✅ تم إرسال النبضة بنجاح")
                        consecutive_failures = 0
                        
                        # تحديث قائمة الأقران من الاستجابة إذا كانت متوفرة
                        try:
                            heartbeat_data = await response.json()
                            if 'peers' in heartbeat_data:
                                self.registered_peers = heartbeat_data['peers']
                                logger.debug(f"🔄 تم تحديث الأقران: {len(self.registered_peers)}")
                        except:
                            pass
                            
                    else:
                        logger.warning(f"⚠️ فشل في إرسال النبضة: {response.status}")
                        consecutive_failures += 1
                        
            except Exception as e:
                logger.error(f"❌ خطأ في إرسال النبضة: {e}")
                consecutive_failures += 1
            
            # إعادة التسجيل عند فشل النبضات المتكرر
            if consecutive_failures >= max_consecutive_failures:
                logger.warning("🔄 فشل متكرر في النبضات، محاولة إعادة التسجيل...")
                await self.connect_until_success_async()
                consecutive_failures = 0
            
            await asyncio.sleep(self.heartbeat_interval)

    async def start_peer_discovery(self):
        """بدء اكتشاف الأقران بشكل دوري"""
        logger.info("🔍 بدء اكتشاف الأقران التلقائي...")
        
        while self.is_running:
            if self.current_server:
                try:
                    async with self.session.get(
                        f"{self.current_server['url']}/peers",
                        timeout=10
                    ) as response:
                        
                        if response.status == 200:
                            peers_data = await response.json()
                            old_count = len(self.registered_peers)
                            self.registered_peers = peers_data
                            new_count = len(peers_data)
                            
                            if new_count != old_count:
                                logger.info(f"🔄 تم تحديث قائمة الأقران: {old_count} → {new_count}")
                            else:
                                logger.debug(f"📊 قائمة الأقران مستقرة: {new_count} قرين")
                        else:
                            logger.warning("⚠️ فشل في تحديث قائمة الأقران")
                            
                except Exception as e:
                    logger.error(f"❌ خطأ في اكتشاف الأقران: {e}")
            
            await asyncio.sleep(self.discovery_interval)

    async def start_metrics_collector(self):
        """بدء جمع المقاييس بشكل دوري"""
        logger.info("📊 بدء جمع مقاييس النظام...")
        
        while self.is_running:
            try:
                # تحديث وقت التشغيل
                self.total_uptime = (datetime.now() - self.start_time).total_seconds()
                
                # جمع المقاييس (سيتم استخدامها في التسجيل التالي)
                self.collect_system_metrics()
                
                await asyncio.sleep(30)  # جمع كل 30 ثانية
                
            except Exception as e:
                logger.error(f"❌ خطأ في جمع المقاييس: {e}")
                await asyncio.sleep(60)

    # -------------------------------------------------------------------------
    async def start_background_services(self):
        """بدء جميع الخدمات الخلفية"""
        await self.init_session()
        
        try:
            # التسجيل الأولي
            server, peers = await self.connect_until_success_async()
            
            # المهام الخلفية بعد التسجيل الناجح
            tasks = [
                asyncio.create_task(self.start_heartbeat()),
                asyncio.create_task(self.start_peer_discovery()),
                asyncio.create_task(self.start_metrics_collector()),
            ]
            
            await asyncio.gather(*tasks)
            
        except Exception as e:
            logger.error(f"💥 خطأ في الخدمات الخلفية: {e}")
        finally:
            await self.cleanup()

    def run_background(self):
        """تشغيل الخدمات في الخلفية"""
        def run_async():
            asyncio.run(self.start_background_services())
        
        thread = threading.Thread(target=run_async, daemon=True)
        thread.start()
        logger.info("🔄 تم بدء الخدمات الخلفية")
        return thread

    async def cleanup(self):
        """تنظيف الموارد"""
        self.is_running = False
        if self.session:
            await self.session.close()
        logger.info("🧹 تم تنظيف موارد العميل")

    def get_stats(self) -> Dict:
        """الحصول على إحصائيات العميل"""
        uptime = (datetime.now() - self.start_time).total_seconds()
        
        return {
            "node_id": self.node_id,
            "current_server": self.current_server['url'] if self.current_server else None,
            "port": self.port,
            "local_ip": self.get_local_ip(),
            "registration_attempts": self.registration_attempts,
            "successful_registrations": self.successful_registrations,
            "failed_registrations": self.failed_registrations,
            "success_rate": round(self.successful_registrations / max(self.registration_attempts, 1), 3),
            "last_success": self.last_successful_registration.isoformat() if self.last_successful_registration else None,
            "active_peers": len(self.registered_peers),
            "uptime_seconds": round(uptime, 2),
            "server_performance": {k: round(v, 3) for k, v in self.server_performance.items()},
            "node_metrics": self.node_metrics.to_dict(),
            "capabilities": self.capabilities,
            "status": "running" if self.is_running else "stopped"
        }

    def print_stats(self):
        """طباعة إحصائيات العميل"""
        stats = self.get_stats()
        
        print("\n" + "="*60)
        print("📊 إحصائيات عميل العقدة المتقدم")
        print("="*60)
        print(f"🆔 معرف العقدة: {stats['node_id']}")
        print(f"🌐 العنوان: {stats['local_ip']}:{stats['port']}")
        print(f"🎯 السيرفر الحالي: {stats['current_server'] or 'غير متصل'}")
        print(f"📈 المحاولات: {stats['registration_attempts']}")
        print(f"✅ الناجحة: {stats['successful_registrations']}")
        print(f"❌ الفاشلة: {stats['failed_registrations']}")
        print(f"📊 معدل النجاح: {stats['success_rate'] * 100}%")
        print(f"👥 الأقران النشطين: {stats['active_peers']}")
        print(f"⏱️  وقت التشغيل: {stats['uptime_seconds']}s")
        print(f"❤️  درجة الصحة: {stats['node_metrics']['health_score']}")
        print(f"⚡ استخدام CPU: {stats['node_metrics']['cpu_usage']}%")
        print(f"💾 استخدام الذاكرة: {stats['node_metrics']['memory_usage']}%")
        print("="*60)

    # -------------------------------------------------------------------------
    # دوال متوافقة مع الإصدار القديم
    def connect_until_success(self, retry_delay: int = 5) -> Tuple[str, List[str]]:
        """
        نسخة متوافقة مع الإصدار القديم
        """
        async def run():
            server, peers = await self.connect_until_success_async(retry_delay)
            return server['url'], [str(peer) for peer in peers]  # تحويل لتناسق الإصدار القديم
        
        return asyncio.run(run())

# -----------------------------------------------------------------------------
class NodeClient:
    """
    نسخة مبسطة متوافقة مع الإصدار القديم
    """
    
    def __init__(
        self,
        PORTs: Iterable[int] | None = None,
        registry_servers: List[str] | None = None,
        node_id: str | None = None,
    ):
        self.advanced_client = AdvancedNodeClient(
            ports=PORTs,
            registry_servers=[{"url": s, "priority": i, "type": "legacy"} 
                            for i, s in enumerate(registry_servers or [])],
            node_id=node_id
        )

    def get_local_ip(self) -> str:
        return self.advanced_client.get_local_ip()

    def _register_once(self, server: str, port: int) -> List[str]:
        """نسخة متزامنة للتسجيل"""
        node_info = self.advanced_client.get_node_info(port)
        resp = requests.post(f"{server}/register", json=node_info, timeout=5)
        resp.raise_for_status()
        return resp.json()

    def connect_until_success(self, retry_delay: int = 5) -> Tuple[str, List[str]]:
        return self.advanced_client.connect_until_success(retry_delay)

    def run_background(self) -> None:
        self.advanced_client.run_background()

# -----------------------------------------------------------------------------  
if __name__ == "__main__":
    """
    للتجربة المباشرة مع واجهة متقدمة
    """
    
    async def main():
        client = AdvancedNodeClient(
            capabilities=["compute", "storage", "gpu", "web_api", "advanced_tasks"],
            heartbeat_interval=25,
            discovery_interval=45
        )
        
        print("🚀 بدء عميل العقدة المتقدم...")
        print(f"🆔 معرف العقدة: {client.node_id}")
        print(f"🌐 العنوان المحلي: {client.get_local_ip()}")
        print(f"🎯 الإمكانيات: {client.capabilities}")
        
        try:
            # بدء الخدمات الخلفية
            background_thread = client.run_background()
            
            # عرض الإحصائيات بشكل دوري
            import time as sync_time
            while client.is_running:
                client.print_stats()
                sync_time.sleep(15)  # انتظار متزامن
                
        except KeyboardInterrupt:
            print("\n🛑 إيقاف العميل...")
            asyncio.run(client.cleanup())
    
    # التشغيل
    asyncio.run(main())