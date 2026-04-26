#!/usr/bin/env python3
"""
موازن حمل ذكي - يوزع المهام على الأقران المتاحين
"""
import sys
import os
import json
import time
import socket
import threading
import random
import logging  # <-- هذا هو السطر المهم!
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta

# إعداد التسجيل (logging) - يجب أن يكون بعد import مباشرة
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('load_balancer.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

logger.info("🔧 تهيئة PEERS افتراضية")

@dataclass
class PeerInfo:
    """معلومات عن نظير (peer)"""
    ip: str
    port: int
    last_seen: datetime
    cpu_usage: float = 0.0
    memory_usage: float = 0.0
    disk_usage: float = 0.0
    status: str = "offline"
    tasks_running: int = 0
    max_tasks: int = 10
    
    @property
    def is_online(self) -> bool:
        """التحقق من أن النظير متصل"""
        return (datetime.now() - self.last_seen) < timedelta(minutes=5) and self.status == "online"
    
    @property
    def has_capacity(self) -> bool:
        """التحقق من أن النظير لديه قدرة على تنفيذ مهام"""
        return self.tasks_running < self.max_tasks and self.cpu_usage < 80 and self.memory_usage < 80

class LoadBalancer:
    """موزع حمل ذكي"""
    
    def __init__(self, config_file: str = "config.json"):
        self.config = self.load_config(config_file)
        self.peers: Dict[str, PeerInfo] = {}
        self.task_queue: List[Dict] = []
        self.lock = threading.Lock()
        self.running = True
        
        # تهيئة أقران افتراضية للاختبار
        self.init_default_peers()
    
    def load_config(self, config_file: str) -> Dict:
        """تحميل الإعدادات من ملف"""
        default_config = {
            "http_port": 8888,
            "heartbeat_interval": 30,
            "max_retries": 3,
            "task_timeout": 300,
            "log_level": "INFO"
        }
        
        try:
            if os.path.exists(config_file):
                with open(config_file, 'r', encoding='utf-8') as f:
                    loaded_config = json.load(f)
                    default_config.update(loaded_config)
                    logger.info(f"✅ تم تحميل الإعدادات من {config_file}")
            else:
                logger.warning(f"⚠️  ملف الإعدادات {config_file} غير موجود، استخدام الإعدادات الافتراضية")
        except Exception as e:
            logger.error(f"❌ خطأ في تحميل الإعدادات: {e}")
        
        return default_config
    
    def init_default_peers(self):
        """تهيئة أقران افتراضية للاختبار"""
        default_peers = [
            {"ip": "127.0.0.1", "port": 5000, "name": "Local Peer 1"},
            {"ip": "127.0.0.1", "port": 5001, "name": "Local Peer 2"},
            {"ip": "192.168.1.100", "port": 5000, "name": "Remote Peer 1"},
            {"ip": "192.168.1.101", "port": 5000, "name": "Remote Peer 2"},
        ]
        
        for peer in default_peers:
            peer_id = f"{peer['ip']}:{peer['port']}"
            self.peers[peer_id] = PeerInfo(
                ip=peer['ip'],
                port=peer['port'],
                last_seen=datetime.now() - timedelta(seconds=random.randint(0, 60)),
                cpu_usage=random.uniform(10, 70),
                memory_usage=random.uniform(20, 80),
                disk_usage=random.uniform(10, 90),
                status="online" if random.random() > 0.3 else "offline",
                tasks_running=random.randint(0, 5),
                max_tasks=10
            )
        
        logger.info(f"✅ تم تهيئة {len(self.peers)} أقران افتراضية")
    
    def find_best_peer(self, task_requirements: Dict = None) -> Optional[PeerInfo]:
        """إيجاد أفضل نظير للمهمة الحالية"""
        with self.lock:
            available_peers = [
                peer for peer in self.peers.values() 
                if peer.is_online and peer.has_capacity
            ]
            
            if not available_peers:
                logger.warning("⚠️  لا توجد أقران متاحة حالياً")
                return None
            
            # خوارزمية اختيار بسيطة تعتمد على الحمل
            def calculate_score(peer: PeerInfo) -> float:
                # كلما قل الحمل، كلما زادت النتيجة
                cpu_score = 100 - peer.cpu_usage
                memory_score = 100 - peer.memory_usage
                task_score = (peer.max_tasks - peer.tasks_running) * 10
                
                return (cpu_score * 0.4 + memory_score * 0.4 + task_score * 0.2) / 100
            
            # اختيار النظير بأعلى نتيجة
            best_peer = max(available_peers, key=calculate_score)
            logger.info(f"✅ تم اختيار النظير {best_peer.ip}:{best_peer.port} للمهمة")
            
            return best_peer
    
    def distribute_task(self, task: Dict) -> Dict:
        """توزيع مهمة على النظير المناسب"""
        logger.info(f"📦 توزيع مهمة: {task.get('id', 'unknown')}")
        
        peer = self.find_best_peer(task.get('requirements', {}))
        
        if not peer:
            # وضع المهمة في قائمة الانتظار
            with self.lock:
                self.task_queue.append(task)
                logger.info(f"⏳ تم إضافة المهمة إلى قائمة الانتظار (الطول: {len(self.task_queue)})")
            
            return {
                "success": False,
                "message": "لا توجد أقران متاحة حالياً",
                "queued": True,
                "queue_position": len(self.task_queue)
            }
        
        # محاولة إرسال المهمة للنظير
        try:
            result = self.send_task_to_peer(peer, task)
            
            if result.get("success"):
                peer.tasks_running += 1
                logger.info(f"✅ تم إرسال المهمة بنجاح إلى {peer.ip}:{peer.port}")
            else:
                logger.error(f"❌ فشل إرسال المهمة: {result.get('message')}")
            
            return result
            
        except Exception as e:
            logger.error(f"❌ خطأ في توزيع المهمة: {e}")
            return {
                "success": False,
                "message": f"خطأ في التوزيع: {str(e)}"
            }
    
    def send_task_to_peer(self, peer: PeerInfo, task: Dict) -> Dict:
        """إرسال مهمة إلى نظير معين"""
        # هذه دالة محاكاة - في التطبيق الفعلي ستكون هناك اتصال شبكي
        time.sleep(0.5)  # محاكاة وقت الإرسال
        
        success_rate = 0.9  # 90% نسبة نجاح
        
        if random.random() < success_rate:
            return {
                "success": True,
                "message": "تم قبول المهمة",
                "peer": f"{peer.ip}:{peer.port}",
                "estimated_time": random.randint(10, 60),
                "task_id": task.get('id')
            }
        else:
            return {
                "success": False,
                "message": "فشل في معالجة المهمة",
                "peer": f"{peer.ip}:{peer.port}"
            }
    
    def process_queued_tasks(self):
        """معالجة المهام في قائمة الانتظار"""
        while self.running:
            time.sleep(10)  # فحص كل 10 ثواني
            
            with self.lock:
                if not self.task_queue:
                    continue
                
                logger.info(f"🔍 فحص المهام في قائمة الانتظار: {len(self.task_queue)} مهمة")
                
                # محاولة توزيع المهام في قائمة الانتظار
                processed_tasks = []
                
                for i, task in enumerate(self.task_queue):
                    peer = self.find_best_peer(task.get('requirements', {}))
                    
                    if peer:
                        result = self.send_task_to_peer(peer, task)
                        
                        if result.get("success"):
                            peer.tasks_running += 1
                            processed_tasks.append(i)
                            logger.info(f"✅ تم توزيع مهمة من قائمة الانتظار إلى {peer.ip}:{peer.port}")
                
                # إزالة المهام التي تم توزيعها
                for i in reversed(processed_tasks):
                    self.task_queue.pop(i)
    
    def start_http_server(self):
        """بدء خادم HTTP للتحكم"""
        from http.server import HTTPServer, BaseHTTPRequestHandler
        import urllib.parse
        
        class RequestHandler(BaseHTTPRequestHandler):
            lb = self
            
            def do_GET(self):
                parsed_path = urllib.parse.urlparse(self.path)
                
                if parsed_path.path == '/status':
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    
                    status = {
                        "peers": len(self.lb.peers),
                        "online_peers": len([p for p in self.lb.peers.values() if p.is_online]),
                        "queued_tasks": len(self.lb.task_queue),
                        "running_tasks": sum(p.tasks_running for p in self.lb.peers.values() if p.is_online),
                        "timestamp": datetime.now().isoformat()
                    }
                    
                    self.wfile.write(json.dumps(status, indent=2).encode())
                    
                elif parsed_path.path == '/peers':
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    
                    peers_list = []
                    for peer_id, peer in self.lb.peers.items():
                        peers_list.append({
                            "id": peer_id,
                            "ip": peer.ip,
                            "port": peer.port,
                            "status": peer.status,
                            "cpu_usage": peer.cpu_usage,
                            "memory_usage": peer.memory_usage,
                            "tasks_running": peer.tasks_running,
                            "max_tasks": peer.max_tasks,
                            "last_seen": peer.last_seen.isoformat(),
                            "is_online": peer.is_online,
                            "has_capacity": peer.has_capacity
                        })
                    
                    self.wfile.write(json.dumps(peers_list, indent=2).encode())
                    
                else:
                    self.send_response(404)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": "Endpoint not found"}).encode())
            
            def do_POST(self):
                content_length = int(self.headers['Content-Length'])
                post_data = self.rfile.read(content_length)
                
                try:
                    data = json.loads(post_data.decode('utf-8'))
                except:
                    data = {}
                
                if self.path == '/distribute':
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    
                    result = self.lb.distribute_task(data)
                    self.wfile.write(json.dumps(result, indent=2).encode())
                    
                elif self.path == '/add_peer':
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    
                    peer_id = f"{data.get('ip')}:{data.get('port', 5000)}"
                    
                    with self.lb.lock:
                        self.lb.peers[peer_id] = PeerInfo(
                            ip=data.get('ip'),
                            port=data.get('port', 5000),
                            last_seen=datetime.now(),
                            status="online"
                        )
                    
                    result = {"success": True, "message": f"تمت إضافة النظير {peer_id}"}
                    self.wfile.write(json.dumps(result, indent=2).encode())
                    
                else:
                    self.send_response(404)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": "Endpoint not found"}).encode())
            
            def log_message(self, format, *args):
                logger.info(f"HTTP {self.address_string()} - {format % args}")
        
        RequestHandler.lb = self
        
        try:
            server = HTTPServer(('0.0.0.0', self.config['http_port']), RequestHandler)
            logger.info(f"🌐 خادم HTTP يعمل على المنفذ {self.config['http_port']}")
            server.serve_forever()
        except Exception as e:
            logger.error(f"❌ خطأ في خادم HTTP: {e}")
    
    def start_heartbeat_monitor(self):
        """مراقبة نبضات القلب للأقران"""
        logger.info("❤️  بدء مراقبة نبضات القلب للأقران...")
        
        while self.running:
            time.sleep(self.config['heartbeat_interval'])
            
            with self.lock:
                offline_count = 0
                
                for peer_id, peer in list(self.peers.items()):
                    # محاكاة تغيير حالة الأقران
                    if random.random() < 0.1:  # 10% فرصة لتغيير الحالة
                        if peer.status == "online":
                            peer.status = "offline"
                            offline_count += 1
                            logger.warning(f"⚠️  النظير {peer_id} أصبح غير متصل")
                        else:
                            peer.status = "online"
                            peer.last_seen = datetime.now()
                            logger.info(f"✅ النظير {peer_id} عاد للاتصال")
                    
                    # تحديث مقاييس الأداء بشكل عشوائي
                    if peer.status == "online":
                        peer.cpu_usage = max(0, min(100, peer.cpu_usage + random.uniform(-5, 5)))
                        peer.memory_usage = max(0, min(100, peer.memory_usage + random.uniform(-3, 3)))
                        peer.disk_usage = max(0, min(100, peer.disk_usage + random.uniform(-2, 2)))
                        
                        # تقليل عدد المهام الجارية مع الوقت
                        if peer.tasks_running > 0 and random.random() < 0.3:
                            peer.tasks_running -= 1
                
                if offline_count > 0:
                    logger.info(f"📊 إحصائيات: {offline_count} أقران غير متصلين")
    
    def stop(self):
        """إيقاف موازن الحمل"""
        logger.info("🛑 إيقاف موازن الحمل...")
        self.running = False

def check_dependencies():
    """فحص الاعتماديات المطلوبة"""
    try:
        import http.server
        import urllib.parse
        logger.info("✅ جميع الاعتماديات متاحة")
        return True
    except ImportError as e:
        logger.error(f"❌ اعتماديات مفقودة: {e}")
        return False

def main():
    """الدالة الرئيسية"""
    logger.info("🚀 بدء تشغيل موازن الحمل...")
    
    try:
        # فحص الاعتماديات
        check_dependencies()
        
        # تهيئة موازن الحمل
        lb = LoadBalancer()
        
        # بدء الخوادم في خيوط منفصلة
        http_thread = threading.Thread(target=lb.start_http_server, daemon=True)
        heartbeat_thread = threading.Thread(target=lb.start_heartbeat_monitor, daemon=True)
        queue_thread = threading.Thread(target=lb.process_queued_tasks, daemon=True)
        
        http_thread.start()
        heartbeat_thread.start()
        queue_thread.start()
        
        logger.info(f"✅ موازن الحمل يعمل على المنفذ {lb.config['http_port']}")
        logger.info("📡 في انتظار الاتصالات من الأقران...")
        logger.info("🌐 يمكنك الوصول لواجهة التحكم عبر: http://localhost:8888/status")
        
        # الاحتفاظ بالبرنامج قيد التشغيل
        while lb.running:
            try:
                time.sleep(1)
            except KeyboardInterrupt:
                logger.info("\n🛑 تلقي إشارة الإيقاف...")
                lb.stop()
                break
                
    except KeyboardInterrupt:
        logger.info("\n🛑 إيقاف موازن الحمل...")
    except Exception as e:
        logger.error(f"❌ خطأ: {e}", exc_info=True)
        return 1
    
    logger.info("👋 إنهاء موازن الحمل")
    return 0

if __name__ == "__main__":
    sys.exit(main())
