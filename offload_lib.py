#!/usr/bin/env python3
# offload_lib.py - النسخة المحسنة

import time
import math
import random
import psutil
import requests
import socket
import json
from functools import wraps
from zeroconf import Zeroconf, ServiceBrowser
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import ipaddress
from dataclasses import dataclass, field  # أضف field هنا
from typing import List, Dict, Any, Optional

# استيراد مدير المنافذ للتوافق
try:
    from port_manager import PortManager
    port_manager = PortManager()
    DEFAULT_PEER_PORT = port_manager.get_available_port()
except:
    DEFAULT_PEER_PORT = 7520

# إعداد السجل
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# إعدادات التحميل
MAX_CPU = 0.6  # عتبة استخدام CPU فقط
CACHE_TIMEOUT = 30  # ثانية للتخزين المؤقت

@dataclass
class PeerInfo:
    """معلومات عن الجهاز الشريك"""
    url: str
    ip: str
    port: int = DEFAULT_PEER_PORT
    network_type: str = "lan"  # lan, wan, internet
    last_seen: float = field(default_factory=time.time)
    success_count: int = 0
    total_count: int = 0
    avg_response_time: float = 0.0
    cpu_usage: float = 0.0
    memory_available: float = 0.0

class PeerListener:
    def __init__(self):
        self.peers = []

    def add_service(self, zc, type, name):
        info = zc.get_service_info(type, name)
        if info:
            ip = socket.inet_ntoa(info.addresses[0])
            port = info.port
            self.peers.append(f"{ip}:{port}")
            logging.info(f"جهاز مكتشف: {ip}:{port}")

    def update_service(self, zc, type, name):
        logging.debug(f"تم تحديث الخدمة: {name}")

class OffloadManager:
    """مدير ذكي لتوزيع المهام"""
    
    def __init__(self):
        self.peer_cache: List[PeerInfo] = []
        self.last_discovery = 0
        self.performance_history: Dict[str, Dict] = {}
        self._lock = threading.RLock()
    
    def get_cached_peers(self) -> List[PeerInfo]:
        """الحصول على قائمة الأجهزة مع التخزين المؤقت"""
        with self._lock:
            current_time = time.time()
            if (current_time - self.last_discovery) > CACHE_TIMEOUT or not self.peer_cache:
                self.peer_cache = self.discover_peers_optimized()
                self.last_discovery = current_time
            return self.peer_cache.copy()
    
    def discover_peers_optimized(self, timeout=2.0) -> List[PeerInfo]:
        """اكتشاف متوازي للأجهزة"""
        zc = Zeroconf()
        listener = PeerListener()
        ServiceBrowser(zc, "_http._tcp.local.", listener)
        
        # اكتشاف متوازي للأقران المعروفين
        verified_peers = []
        
        try:
            # فحص الأقران من zeroconf
            with ThreadPoolExecutor(max_workers=10) as executor:
                future_to_peer = {}
                
                for peer in listener.peers:
                    ip = peer.split(':')[0]
                    port = int(peer.split(':')[1])
                    future = executor.submit(self.verify_and_classify_peer, ip, port)
                    future_to_peer[future] = (ip, port)
                
                # انتظار انتهاء timeout
                start_time = time.time()
                while time.time() - start_time < timeout:
                    time.sleep(0.1)
                
                # جمع النتائج
                for future in as_completed(future_to_peer):
                    if future.done() and not future.cancelled():
                        try:
                            peer_info = future.result(timeout=0.1)
                            if peer_info:
                                verified_peers.append(peer_info)
                        except:
                            pass
                
        finally:
            zc.close()
        
        # إضافة الأقران الثابتين من ملف الاكتشاف
        try:
            import peer_discovery
            from project_identifier import verify_project_compatibility
            
            for peer_url in peer_discovery.PEERS:
                try:
                    if peer_url.startswith('http://'):
                        ip_port = peer_url[7:].split(':')
                        if len(ip_port) == 2:
                            ip, port = ip_port[0], int(ip_port[1])
                            if self.verify_peer_project(ip, port):
                                network_type = "lan" if self.is_local_network(ip) else "internet"
                                peer_info = PeerInfo(
                                    url=peer_url,
                                    ip=ip,
                                    port=port,
                                    network_type=network_type,
                                    last_seen=time.time()
                                )
                                # تجنب التكرار
                                if not any(p.ip == ip for p in verified_peers):
                                    verified_peers.append(peer_info)
                except Exception as e:
                    logging.debug(f"خطأ في معالجة {peer_url}: {e}")
        except ImportError:
            pass
        
        logging.info(f"اكتُشف {len(verified_peers)} جهاز متوافق")
        return verified_peers
    
    def verify_and_classify_peer(self, ip: str, port: int) -> Optional[PeerInfo]:
        """فحص وتصنيف الجهاز"""
        try:
            if not self.verify_peer_project(ip, port):
                return None
            
            network_type = "lan" if self.is_local_network(ip) else "wan"
            
            # الحصول على معلومات الصحة
            health_info = self.get_peer_health(ip, port)
            
            peer_info = PeerInfo(
                url=f"{ip}:{port}",
                ip=ip,
                port=port,
                network_type=network_type,
                last_seen=time.time(),
                cpu_usage=health_info.get('cpu_usage', 1.0),
                memory_available=health_info.get('memory_available', 0)
            )
            
            return peer_info
            
        except Exception as e:
            logging.debug(f"فشل فحص الجهاز {ip}:{port}: {e}")
            return None
    
    def verify_peer_project(self, ip: str, port: int = 7520) -> bool:
        """فحص إذا كان الجهاز يحتوي على نفس المشروع"""
        try:
            from project_identifier import verify_project_compatibility

            project_url = f"http://{ip}:{port}/project_info"
            response = requests.get(project_url, timeout=2)

            if response.status_code == 200:
                remote_info = response.json()
                return verify_project_compatibility(remote_info)

        except:
            pass
        return False
    
    def get_peer_health(self, ip: str, port: int) -> Dict[str, Any]:
        """الحصول على معلومات صحة الجهاز"""
        try:
            health_url = f"http://{ip}:{port}/health"
            response = requests.get(health_url, timeout=2)
            
            if response.status_code == 200:
                return response.json()
        except:
            pass
        
        return {'cpu_usage': 1.0, 'memory_available': 0}
    
    def is_local_network(self, ip: str) -> bool:
        """فحص إذا كان IP في الشبكة المحلية"""
        try:
            addr = ipaddress.ip_address(ip)
            return addr.is_private
        except:
            return False
    
    def smart_peer_selection(self, peers: List[PeerInfo], complexity: float, func_name: str) -> Optional[PeerInfo]:
        """اختيار ذكي للجهاز المستهدف"""
        if not peers:
            return None
        
        scored_peers = []
        
        for peer in peers:
            score = self.calculate_peer_score(peer, complexity, func_name)
            if score > 0:  # استبعاد الأقران غير المناسبين
                scored_peers.append((peer, score))
        
        if not scored_peers:
            return None
        
        # ترتيب حسب الجودة واختيار الأفضل
        scored_peers.sort(key=lambda x: x[1], reverse=True)
        
        # اختيار عشوائي مرجح من أفضل 3 أقران
        top_peers = scored_peers[:3]
        total_score = sum(score for _, score in top_peers)
        
        if total_score == 0:
            return top_peers[0][0]
        
        rand_val = random.uniform(0, total_score)
        cumulative = 0
        
        for peer, score in top_peers:
            cumulative += score
            if rand_val <= cumulative:
                return peer
        
        return top_peers[0][0]
    
    def calculate_peer_score(self, peer: PeerInfo, complexity: float, func_name: str) -> float:
        """حساب درجة ملائمة الجهاز"""
        try:
            # عوامل الترجيح
            cpu_weight = 0.3
            memory_weight = 0.2
            network_weight = 0.2
            history_weight = 0.3
            
            # درجة استخدام CPU (أقل أفضل)
            cpu_score = 1.0 - min(peer.cpu_usage, 1.0)
            
            # درجة الذاكرة (أكثر أفضل)
            memory_score = min(peer.memory_available / 1000, 1.0)  # افتراض 1GB كحد أقصى
            
            # درجة الشبكة (LAN أفضل من WAN)
            network_score = 1.0 if peer.network_type == "lan" else 0.7
            
            # درجة السجل التاريخي
            history_key = f"{peer.ip}:{peer.port}"
            history = self.performance_history.get(history_key, {'success_rate': 0.5, 'avg_response_time': 1.0})
            success_rate = history.get('success_rate', 0.5)
            avg_response = history.get('avg_response_time', 1.0)
            
            history_score = success_rate * (1.0 / max(avg_response, 0.1))
            
            # حساب الدرجة النهائية
            total_score = (cpu_score * cpu_weight +
                         memory_score * memory_weight +
                         network_score * network_weight +
                         history_score * history_weight)
            
            return total_score
            
        except Exception as e:
            logging.debug(f"خطأ في حساب درجة {peer.ip}: {e}")
            return 0.5  # درجة افتراضية
    
    def update_performance_history(self, peer: PeerInfo, success: bool, response_time: float):
        """تحديث سجل أداء الأجهزة"""
        history_key = f"{peer.ip}:{peer.port}"
        
        with self._lock:
            if history_key not in self.performance_history:
                self.performance_history[history_key] = {
                    'success_count': 0,
                    'total_count': 0,
                    'avg_response_time': response_time
                }
            
            history = self.performance_history[history_key]
            history['total_count'] += 1
            
            if success:
                history['success_count'] += 1
            
            # تحديث متوسط وقت الاستجابة (المتوسط المتحرك)
            old_avg = history['avg_response_time']
            history['avg_response_time'] = (
                old_avg * (history['total_count'] - 1) + response_time
            ) / history['total_count']
            
            # حساب معدل النجاح
            history['success_rate'] = history['success_count'] / history['total_count']

# إنشاء المدير العالمي
offload_manager = OffloadManager()

# تعريفات تقدير التعقيد المحسنة
COMPLEXITY_PROFILES = {
    "matrix_multiply": lambda size: size ** 2.8,
    "prime_calculation": lambda n: n * math.log(n) if n > 1000 else n/100,
    "data_processing": lambda size: size * 15,
    "image_processing_emulation": lambda iterations: iterations * 60
}

def estimate_complexity_improved(func, args, kwargs):
    """تقدير تعقيد أكثر دقة"""
    profile = COMPLEXITY_PROFILES.get(func.__name__)
    if profile:
        return profile(args[0] if args else 1)
    return 1  # قيمة افتراضية

def try_offload_enhanced(peer_info: PeerInfo, payload: Dict, max_retries: int = 3) -> Any:
    """محاولة إرسال محسنة مع تتبع الأداء"""
    start_time = time.time()
    peer_url = peer_info.url
    
    for attempt in range(max_retries):
        try:
            delay = 0.5 * (2 ** attempt)  # exponential backoff
            if attempt > 0:
                time.sleep(delay)
            
            url = f"http://{peer_url}/run"
            response = requests.post(
                url, 
                json=payload, 
                timeout=10 + attempt * 5  # زيادة timeout تدريجياً
            )
            response.raise_for_status()
            
            response_time = time.time() - start_time
            offload_manager.update_performance_history(peer_info, True, response_time)
            
            return response.json()
            
        except requests.exceptions.Timeout:
            logging.warning(f"انتهت المهلة للمحاولة {attempt + 1} لـ {peer_url}")
        except Exception as e:
            logging.warning(f"فشل المحاولة {attempt + 1} لـ {peer_url}: {str(e)}")
    
    response_time = time.time() - start_time
    offload_manager.update_performance_history(peer_info, False, response_time)
    raise ConnectionError(f"فشل جميع المحاولات ({max_retries}) لـ {peer_url}")

def offload_enhanced(complexity_threshold=50, cpu_threshold=None, memory_threshold=500):
    """ديكوراتور محسن مع معاملات قابلة للتخصيص"""
    if cpu_threshold is None:
        cpu_threshold = MAX_CPU
    
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # قياس موارد النظام
            cpu = psutil.cpu_percent(interval=0.3) / 100.0
            mem_available = psutil.virtual_memory().available / (1024**2)  # MB
            
            complexity = estimate_complexity_improved(func, args, kwargs)
            
            logging.info(f"تحميل النظام - CPU: {cpu:.2f}, الذاكرة: {mem_available:.1f}MB, التعقيد: {complexity:.1f}")
            
            # قرار التوزيع الذكي
            should_offload = (
                complexity > complexity_threshold or 
                cpu > cpu_threshold or 
                mem_available < memory_threshold
            )
            
            if should_offload:
                try:
                    peers = offload_manager.get_cached_peers()
                    if peers:
                        selected_peer = offload_manager.smart_peer_selection(
                            peers, complexity, func.__name__
                        )
                        
                        if selected_peer:
                            payload = {
                                "func": func.__name__,
                                "args": args,
                                "kwargs": kwargs,
                                "complexity": complexity,
                                "timestamp": time.time()
                            }
                            
                            logging.info(f"إرسال {func.__name__} إلى {selected_peer.url} ({selected_peer.network_type.upper()})")
                            return try_offload_enhanced(selected_peer, payload)
                        else:
                            logging.warning("لا توجد أجهزة مناسبة للتوزيع")
                except Exception as e:
                    logging.error(f"فشل التوزيع: {str(e)}")
            
            logging.info("التنفيذ محلياً")
            return func(*args, **kwargs)
        return wrapper
    return decorator

# المهام القابلة للتوزيع (محدثة بالديكوراتور المحسن):

@offload_enhanced(complexity_threshold=50, memory_threshold=300)
def matrix_multiply(size):
    """ضرب مصفوفتين عشوائيتين بالحجم"""
    import numpy as np
    A = np.random.rand(size, size)
    B = np.random.rand(size, size)
    result = np.dot(A, B)
    return {
        "result": result.tolist(),
        "shape": result.shape,
        "computed_locally": True
    }

@offload_enhanced(complexity_threshold=1000, cpu_threshold=0.7)
def prime_calculation(n):
    """حساب الأعداد الأولية"""
    primes = []
    for num in range(2, n + 1):
        is_prime = True
        for i in range(2, int(math.sqrt(num)) + 1):
            if num % i == 0:
                is_prime = False
                break
        if is_prime:
            primes.append(num)
    return {
        "primes_count": len(primes), 
        "primes": primes if n <= 1000 else primes[:1000],  # تحديد للحجم الكبير
        "computed_locally": True
    }

@offload_enhanced(complexity_threshold=100, memory_threshold=200)
def data_processing(data_size):
    """معالجة بيانات كبيرة"""
    processed_data = []
    for i in range(data_size):
        result = sum(math.sin(x) * math.cos(x) for x in range(i, i + 100))
        processed_data.append(result)
    return {
        "processed_items": len(processed_data),
        "computed_locally": True
    }

@offload_enhanced(complexity_threshold=30, cpu_threshold=0.5)
def image_processing_emulation(iterations):
    """محاكاة معالجة الصور"""
    results = []
    for i in range(iterations):
        fake_processing = sum(math.sqrt(x) for x in range(i * 100, (i + 1) * 100))
        results.append(fake_processing)
        time.sleep(0.01)
    return {
        "iterations": iterations, 
        "results": results,
        "computed_locally": True
    }

# دوال مساعدة للتوافق مع الإصدار القديم
def discover_peers(timeout=1.5):
    """وظيفة التوافق مع الإصدار القديم"""
    peers_info = offload_manager.get_cached_peers()
    return [peer.url for peer in peers_info]

def try_offload(peer, payload, max_retries=3):
    """وظيفة التوافق مع الإصدار القديم"""
    peer_info = PeerInfo(
        url=peer,
        ip=peer.split(':')[0],
        port=int(peer.split(':')[1]),
        network_type="unknown",
        last_seen=time.time()
    )
    return try_offload_enhanced(peer_info, payload, max_retries)

def offload(func):
    """ديكوراتور التوافق مع الإصدار القديم"""
    return offload_enhanced()(func)

if __name__ == "__main__":
    # اختبار الوظائف
    print("اختبار نظام توزيع المهام المحسن...")
    
    # اختبار اكتشاف الأقران
    peers = discover_peers()
    print(f"الأقران المكتشفون: {peers}")
    
    # اختبار تقدير التعقيد
    test_complexity = estimate_complexity_improved(matrix_multiply, [100], {})
    print(f"تعقيد ضرب المصفوفات 100x100: {test_complexity:.1f}")
