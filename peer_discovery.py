#!/usr/bin/env python3
"""
نظام اكتشاف أقران محسن - الإصدار 2.3
اكتشاف متكامل مع أولوية المنافذ وتحسينات الأداء
"""

import os
import socket
import threading
import time
import logging
import requests
import json
import subprocess
import platform
import re
from urllib.parse import urljoin
from zeroconf import Zeroconf, ServiceInfo, ServiceBrowser, ServiceListener
from concurrent.futures import ThreadPoolExecutor, as_completed
import ipaddress
from dataclasses import dataclass
from typing import Set, Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from port_manager import port_manager
# قدرات العقدة (Node Capabilities)
CAP_TENSOR_STORAGE = "tensor_storage"      # تخزين أوزان الطبقات
CAP_KV_CACHE = "kv_cache"                  # تخزين KV cache
CAP_CPU_INFERENCE = "cpu_inference"        # تنفيذ inference على CPU
CAP_EMBEDDINGS = "embeddings"              # توليد embeddings
CAP_TOKENIZER = "tokenizer"                # تشغيل tokenizer
# استيراد مدير المنافذ
try:
    from port_manager import PortManager
    port_manager = PortManager()
    DISCOVERY_PORT = port_manager.get_available_port()
except:
    DISCOVERY_PORT = 7520
    PORT = DISCOVERY_PORT
    #PEERS = discovery_manager.PEERS
# إعداد السجلات
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# إعدادات النظام
SERVICE_TYPE = "_http._tcp.local."
DISCOVERY_PORT = int(os.getenv("OFFLOAD_PORT", "7520"))
DISCOVERY_INTERVAL = 30
HEALTH_CHECK_INTERVAL = 60
NETWORK_SCAN_INTERVAL = 120  # كل دقيقتين

# إعدادات أولوية المنافذ
PRIORITY_PORT = 72500  # المنفذ ذو الأولوية القصوى
FALLBACK_PORT = 7520   # المنفذ الاحتياطي

@dataclass
class PeerInfo:
    """معلومات شاملة عن الجهاز الشريك"""
    url: str
    ip: str
    port: int
    hostname: str
    network_type: str  # lan, wan, internet
    last_seen: datetime
    last_health_check: datetime
    is_active: bool = True
    response_time: float = 0.0
    cpu_usage: float = 0.0
    memory_available: float = 0.0
    capabilities: List[str] = None
    discovery_method: str = "unknown"  # إضافة طريقة الاكتشاف
    
    def __post_init__(self):
        if self.capabilities is None:
            self.capabilities = []

@dataclass
class ResourceInfo:
    """معلومات عن الموارد المساعدة"""
    device_id: str
    name: str
    type: str  # storage, camera, sensor
    connection_type: str  # usb, network, bluetooth
    capabilities: List[str]
    status: str
    paired_at: datetime
    details: Dict = None
    
    def __post_init__(self):
        if self.details is None:
            self.details = {}

class NetworkScanner:
    """مسح الشبكة المتقدم"""
    
    def __init__(self):
        self.scan_results: Dict[str, dict] = {}
    
    def ping_host(self, ip: str, timeout: int = 2) -> bool:
        """فحص إذا كان الجهاز متجاوب"""
        try:
            if platform.system().lower() == "windows":
                cmd = f"ping -n 1 -w {timeout * 1000} {ip}"
            else:
                cmd = f"ping -c 1 -W {timeout} {ip}"
            
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            return result.returncode == 0
        except Exception:
            return False
    
    def check_port(self, ip: str, port: int, timeout: int = 3) -> bool:
        """فحص إذا كان المنفذ مفتوحاً"""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(timeout)
                result = sock.connect_ex((ip, port))
                return result == 0
        except Exception:
            return False
    
    def scan_ports_prioritized(self, ip: str) -> List[int]:
        """مسح منافذ مع أولوية 72500 أولاً"""
        open_ports = []
        
        # أولاً: فحص المنفذ 72500
        logger.info(f"🎯 فحص المنفذ المفضل {PRIORITY_PORT} على {ip}")
        if self.check_port(ip, PRIORITY_PORT, timeout=3):
            open_ports.append(PRIORITY_PORT)
            logger.info(f"✅ وجد خدمة على المنفذ المفضل {PRIORITY_PORT}")
            return open_ports
        
        # ثانياً: فحص منافذ مدير المنافذ (إذا كان معروفاً)
        try:
            from port_manager import PortManager
            port_manager = PortManager()
            dynamic_port = port_manager.get_available_port()
            if dynamic_port and self.check_port(ip, dynamic_port, timeout=2):
                open_ports.append(dynamic_port)
                logger.info(f"📍 وجد خدمة على منفذ المدير {dynamic_port}")
                return open_ports
        except:
            pass
        
        # ثالثاً: فحص المنافذ الثانوية
        secondary_ports = [7520, 9630, 5297, 80, 443, 8000, 8080]
        logger.info(f"🔍 مسح المنافذ الثانوية على {ip}")
        
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {
                executor.submit(self.check_port, ip, port, 2): port 
                for port in secondary_ports
            }
            for future in as_completed(futures):
                port = futures[future]
                if future.result():
                    open_ports.append(port)
                    logger.info(f"📍 وجد خدمة على المنفذ {port}")
        
        return open_ports
    
    def scan_ports(self, ip: str, ports: List[int]) -> List[int]:
        """مسح منافذ متعددة على جهاز"""
        open_ports = []
        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = {executor.submit(self.check_port, ip, port): port for port in ports}
            for future in as_completed(futures):
                port = futures[future]
                if future.result():
                    open_ports.append(port)
        return open_ports
    
    def get_hostname(self, ip: str) -> str:
        """الحصول على اسم المضيف"""
        try:
            return socket.gethostbyaddr(ip)[0]
        except (socket.herror, socket.gaierror):
            return "unknown"
    
    def scan_subnet_prioritized(self, subnet_base: str) -> List[dict]:
        """مسح شبكة فرعية مع أولوية المنفذ المفضل"""
        discovered_hosts = []
        
        def scan_single_host_prioritized(i):
            ip = f"{subnet_base}.{i}"
            if self.ping_host(ip):
                # استخدام المسح المُفضل بدلاً من العادي
                open_ports = self.scan_ports_prioritized(ip)
                if open_ports:
                    return {
                        'ip': ip,
                        'open_ports': open_ports,
                        'hostname': self.get_hostname(ip),
                        'discovery_method': 'network_scan_prioritized',
                        'priority_port_found': PRIORITY_PORT in open_ports,
                        'last_seen': datetime.now()
                    }
            return None
        
        with ThreadPoolExecutor(max_workers=50) as executor:
            futures = [executor.submit(scan_single_host_prioritized, i) for i in range(1, 255)]
            for future in as_completed(futures):
                result = future.result()
                if result:
                    discovered_hosts.append(result)
                    if result['priority_port_found']:
                        logger.info(f"🎯 جهاز بالمنفذ المفضل: {result['ip']}")
        
        return discovered_hosts
    
    def scan_subnet(self, subnet_base: str) -> List[dict]:
        """مسح شبكة فرعية كاملة"""
        discovered_hosts = []
        target_ports = [7520, 9630, 1000, 5297, 80, 443, 8000, 8080]  # منافذ الخدمة المحتملة
        
        def scan_single_host(i):
            ip = f"{subnet_base}.{i}"
            if self.ping_host(ip):
                open_ports = self.scan_ports(ip, target_ports)
                if open_ports:
                    return {
                        'ip': ip,
                        'open_ports': open_ports,
                        'hostname': self.get_hostname(ip),
                        'discovery_method': 'network_scan',
                        'last_seen': datetime.now()
                    }
            return None
        
        with ThreadPoolExecutor(max_workers=50) as executor:
            futures = [executor.submit(scan_single_host, i) for i in range(1, 255)]
            for future in as_completed(futures):
                result = future.result()
                if result:
                    discovered_hosts.append(result)
        
        return discovered_hosts

class HardwareDiscoverer:
    """مكتشف الأجهزة والموارد المساعدة"""
    
    def __init__(self):
        self.supported_types = ['storage', 'network_camera']
    
    def discover_storage_devices(self) -> List[dict]:
        """اكتشاف أجهزة التخزين المتصلة"""
        storage_devices = []
        
        try:
            if platform.system() == "Windows":
                # استخدام wmic في Windows
                cmd = "wmic logicaldisk where drivetype=2 get deviceid,size,freespace,description /format:csv"
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
                storage_devices = self.parse_windows_storage(result.stdout)
                
            elif platform.system() == "Linux":
                # استخدام lsblk في Linux
                cmd = "lsblk -J -o NAME,SIZE,TYPE,MOUNTPOINT"
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
                storage_devices = self.parse_linux_storage(result.stdout)
                
            elif platform.system() == "Darwin":
                # استخدام diskutil في macOS
                cmd = "diskutil list -plist"
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
                storage_devices = self.parse_macos_storage(result.stdout)
                
        except Exception as e:
            logger.error(f"خطأ في اكتشاف أجهزة التخزين: {e}")
        
        return storage_devices
    
    def parse_windows_storage(self, output: str) -> List[dict]:
        """تحليل مخرجات أجهزة التخزين في Windows"""
        devices = []
        lines = output.strip().split('\n')[1:]  # تخطي العنوان
        
        for line in lines:
            if line.strip():
                parts = line.split(',')
                if len(parts) >= 4:
                    devices.append({
                        'device_id': f"storage_{parts[1]}",
                        'name': parts[4] if len(parts) > 4 else 'USB Storage',
                        'type': 'storage',
                        'connection_type': 'usb',
                        'capacity': parts[2] if len(parts) > 2 else 'unknown',
                        'free_space': parts[3] if len(parts) > 3 else 'unknown'
                    })
        return devices
    
    def parse_linux_storage(self, output: str) -> List[dict]:
        """تحليل مخرجات أجهزة التخزين في Linux"""
        try:
            data = json.loads(output)
            devices = []
            
            for device in data.get('blockdevices', []):
                if device.get('type') == 'disk' and device.get('name', '').startswith('sd'):
                    devices.append({
                        'device_id': f"storage_{device['name']}",
                        'name': device.get('name', 'Storage Device'),
                        'type': 'storage',
                        'connection_type': 'usb',
                        'size': device.get('size', 'unknown'),
                        'mountpoint': device.get('mountpoint', '')
                    })
            return devices
        except json.JSONDecodeError:
            return []
    
    def parse_macos_storage(self, output: str) -> List[dict]:
        """تحليل مخرجات أجهزة التخزين في macOS"""
        devices = []
        # تحليل بسيط لمخرجات diskutil
        lines = output.split('\n')
        current_device = {}
        
        for line in lines:
            if 'Device Identifier' in line:
                if current_device:
                    devices.append(current_device)
                current_device = {'type': 'storage', 'connection_type': 'usb'}
            
            if 'Device Identifier' in line:
                current_device['device_id'] = f"storage_{line.split()[-1]}"
            elif 'Volume Name' in line:
                current_device['name'] = line.split('Volume Name:')[-1].strip()
            elif 'Size' in line and 'Disk Size' not in line:
                current_device['size'] = line.split('Size:')[-1].strip()
        
        if current_device:
            devices.append(current_device)
        
        return devices
    
    def discover_network_cameras(self) -> List[dict]:
        """اكتشاف كاميرات الشبكة"""
        cameras = []
        
        try:
            # مسح الشبكة للعثور على كاميرات
            local_ip = self.get_local_ip()
            network_base = ".".join(local_ip.split(".")[:3])
            
            common_camera_ports = [80, 81, 82, 83, 84, 85, 86, 87, 88, 443, 554, 1935, 8000, 8080, 8081]
            
            for i in range(1, 50):  # مسح نطاق محدود للأداء
                ip = f"{network_base}.{i}"
                open_ports = []
                
                for port in common_camera_ports:
                    if self.check_port(ip, port, timeout=1):
                        open_ports.append(port)
                
                if open_ports:
                    cameras.append({
                        'device_id': f"camera_{ip}",
                        'name': f'Network Camera {ip}',
                        'type': 'camera',
                        'connection_type': 'network',
                        'ip': ip,
                        'open_ports': open_ports,
                        'stream_urls': [f"http://{ip}:{port}" for port in open_ports]
                    })
                    
        except Exception as e:
            logger.error(f"خطأ في اكتشاف كاميرات الشبكة: {e}")
        
        return cameras
    
    def get_local_ip(self) -> str:
        """الحصول على IP المحلي"""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                return s.getsockname()[0]
        except Exception:
            return "127.0.0.1"
    
    def check_port(self, ip: str, port: int, timeout: int = 2) -> bool:
        """فحص المنفذ"""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(timeout)
                result = sock.connect_ex((ip, port))
                return result == 0
        except Exception:
            return False

class EnhancedPeerDiscovery:
    """نظام اكتشاف أقران محسن مع أولوية المنافذ"""
    
    def __init__(self):
        self.peers: Dict[str, PeerInfo] = {}
        self.resources: Dict[str, ResourceInfo] = {}  # الموارد المساعدة
        self.zeroconf: Optional[Zeroconf] = None
        self.service_info: Optional[ServiceInfo] = None
        self._lock = threading.RLock()
        self._running = False
        self._discovery_thread: Optional[threading.Thread] = None
        self._health_check_thread: Optional[threading.Thread] = None
        self._network_scan_thread: Optional[threading.Thread] = None
        self._resource_discovery_thread: Optional[threading.Thread] = None
        
        # إعدادات أولوية المنافذ
        self.current_discovery_port = None
        self.port_priority_index = 0
        self.port_strategy = "priority"
        
        # أدوات الاكتشاف
        self.network_scanner = NetworkScanner()
        self.hardware_discoverer = HardwareDiscoverer()
        
        # سيرفرات التسجيل المركزية - محدثة ومختبرة
        self.central_servers = [
            "http://localhost:",  # السيرفر المحلي للاختبار
            "http://127.0.0.1:",  # localhost بديل
            "https://offloadhelper.onrender.com",
            "http://cv5303201.regru.cloud",
            "https://amaloffload.onrender.com",
            "https://huggingface.co/spaces/mrwabnalas40/Ranoosh",
            "https://huggingface.co/spaces/mrwabnalas40/Tafreegh",
            "https://huggingface.co/spaces/mrwabnalas40/Offloadv3",
            "https://mrwabnalas40-gameplayergamer.hf.space",
            "https://mrwabnalas40-because.hf.space",
            "https://huggingface.co/spaces/mrwabnalas40/Tafreegh",
            "https://geregesdodi-offloadv2.hf.space",
            "https://geregesdodi-offload.hf.space",
            "https://osamabyc19866-nouravideo.hf.space"
        ]
        
        # سيرفرات الاكتشاف الاحتياطية
        self.backup_discovery_servers = [
            "https://discovery.offload-network.com",
            "https://peer-registry.fly.dev",
        ]
        
        # إحصائيات الاكتشاف
        self.discovery_stats = {
            'central_servers_working': 0,
            'central_servers_failed': 0,
            'last_central_discovery': None,
            'peers_found': 0
        }
        
        # سيرفرات التسجيل المركزية الصالحة فقط
        self.central_servers = [
            "https://offloadhelper.onrender.com",
            "http://cv5303201.regru.cloud",
            "https://amaloffload.onrender.com",
            "https://osamabyc86-offload.hf.space",
            "https://huggingface.co/spaces/osamabyc19866/omsd",
            "https://huggingface.co/spaces/osamabyc86/offload",
            "https://176.28.159.79",
            "https://167.28.156.149",
            "https://youtu.be/yj9x-2IbQ-Y?si=suBc9zTTAoLQm82r",
            "https://huggingface.co/spaces/mrwabnalas40/Ranoosh/discussions:7860",
            "https://omsdmail.gumroad.com/l/amaloffloadhelper",
            "https://mrwabnalas40-Offloadv3.hf.space:7861"
        ]
    
    def get_discovery_port_prioritized(self) -> int:
        """الحصول على منفذ الاكتشاف مع الأولوية"""
        strategies = [
            self._get_priority_port,      # 72500 أولاً
            self._get_dynamic_port,       # مدير المنافذ ثانياً
            self._get_fallback_port       # 7520 أخيراً
        ]
        
        for i, strategy in enumerate(strategies):
            try:
                port = strategy()
                if port:
                    self.port_priority_index = i
                    strategy_name = ["72500", "dynamic", "7520"][i]
                    logger.info(f"🎯 استخدام منفذ الاكتشاف: {port} (استراتيجية: {strategy_name})")
                    return port
            except Exception as e:
                logger.warning(f"⚠️ فشل استراتيجية المنفذ {i}: {e}")
                continue
        
        # إذا فشلت جميع الاستراتيجيات
        logger.error("💥 فشلت جميع استراتيجيات المنفذ، استخدام 7520 افتراضي")
        return FALLBACK_PORT

    def _get_priority_port(self) -> int:
        """المنفذ ذو الأولوية القصوى 72500"""
        port = PRIORITY_PORT
        if self.is_port_available(port):
            logger.info(f"✅ المنفذ {PRIORITY_PORT} متاح للاستخدام")
            return port
        else:
            raise Exception(f"المنفذ {PRIORITY_PORT} غير متاح")

    def _get_dynamic_port(self) -> int:
        """الحصول على منفذ ديناميكي من المدير"""
        try:
            from port_manager import PortManager
            port_manager = PortManager()
            dynamic_port = port_manager.get_available_port()
            if dynamic_port and self.is_port_available(dynamic_port):
                logger.info(f"✅ حصل على منفذ ديناميكي: {dynamic_port}")
                return dynamic_port
            else:
                raise Exception("فشل في الحصول على منفذ ديناميكي")
        except Exception as e:
            raise Exception(f"مدير المنافذ غير متاح: {e}")

    def _get_fallback_port(self) -> int:
        """المنفذ الاحتياطي 7520"""
        port = FALLBACK_PORT
        if self.is_port_available(port):
            logger.info(f"🔄 استخدام المنفذ الاحتياطي {FALLBACK_PORT}")
            return port
        else:
            raise Exception(f"المنفذ {FALLBACK_PORT} غير متاح")

    def is_port_available(self, port: int) -> bool:
        """فحص إذا كان المنفذ متاح للاستخدام محلياً"""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('0.0.0.0', port))
                return True
        except socket.error:
            return False

    def get_local_ip(self) -> str:
        """الحصول على IP المحلي"""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                return s.getsockname()[0]
        except Exception:
            return "127.0.0.1"
    
    def is_local_network(self, ip: str) -> bool:
        """فحص إذا كان IP في الشبكة المحلية"""
        try:
            addr = ipaddress.ip_address(ip)
            return addr.is_private
        except Exception:
            return False
    
    def register_local_service_prioritized(self):
        """تسجيل الخدمة مع أولوية المنافذ"""
        discovery_port = self.get_discovery_port_prioritized()
        self.current_discovery_port = discovery_port
        
        try:
            local_ip = self.get_local_ip()
            hostname = socket.gethostname()
            
            self.service_info = ServiceInfo(
                type_=SERVICE_TYPE,
                name=f"{hostname} Offload Service.{SERVICE_TYPE}",
                addresses=[socket.inet_aton(local_ip)],
                port=discovery_port,
                properties={
    b'version': b'2.3',
    b'hostname': hostname.encode(),
    b'service': b'offload',
    b'port': str(discovery_port).encode(),
    b'network_scan': b'enabled',
    b'discovery_strategy': self.port_strategy.encode(),
    b'priority_index': str(self.port_priority_index).encode(),  # <-- أضف فاصلة هنا
    b'capabilities': b','.join([
        CAP_TENSOR_STORAGE.encode(),
        CAP_KV_CACHE.encode(),
        CAP_CPU_INFERENCE.encode()
    ])
},
                server=f"{hostname}.local."
            )
            
            self.zeroconf = Zeroconf()
            self.zeroconf.register_service(self.service_info)
            logger.info(f"✅ الخدمة مسجلة على المنفذ {discovery_port} (استراتيجية: {self.get_strategy_name()})")
            
        except Exception as e:
            logger.error(f"❌ فشل تسجيل الخدمة على المنفذ {discovery_port}: {e}")
            # محاولة التراجع للمنفذ 7520 مباشرة
            self._fallback_to_default_port()

    def get_strategy_name(self) -> str:
        """اسم استراتيجية المنفذ الحالية"""
        strategies = ["72500", "مدير المنافذ", "7520 احتياطي"]
        return strategies[self.port_priority_index] if self.port_priority_index < len(strategies) else "غير معروف"

    def _fallback_to_default_port(self):
        """التراجع للمنفذ الافتراضي 7520"""
        try:
            self.current_discovery_port = FALLBACK_PORT
            local_ip = self.get_local_ip()
            hostname = socket.gethostname()
            
            self.service_info = ServiceInfo(
                type_=SERVICE_TYPE,
                name=f"{hostname} Offload Service.{SERVICE_TYPE}",
                addresses=[socket.inet_aton(local_ip)],
                port=FALLBACK_PORT,
                properties={b'version': b'2.3', b'hostname': hostname.encode()},
                server=f"{hostname}.local."
            )
            
            if self.zeroconf:
                self.zeroconf.unregister_service(self.service_info)
            self.zeroconf.register_service(self.service_info)
            logger.info(f"🔄 تم التراجع للمنفذ الافتراضي {FALLBACK_PORT}")
            
        except Exception as e:
            logger.error(f"💥 فشل كامل في تسجيل الخدمة: {e}")

    def register_local_service(self):
        """وظيفة التوافق - استخدام النظام الجديد"""
        self.register_local_service_prioritized()
    
    class PeerListener(ServiceListener):
        """مستمع لاكتشاف خدمات Zeroconf محسن"""
        
        def __init__(self, discovery_manager):
            self.manager = discovery_manager
        
        def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
            """اكتشاف خدمة جديدة"""
            try:
                info = zc.get_service_info(type_, name)
                if info and info.addresses:
                    ip = socket.inet_ntoa(info.addresses[0])
                    port = info.port
                    hostname = info.server[:-1] if info.server.endswith('.') else info.server
                    
                    peer_url = f"http://{ip}:{port}"
                    network_type = "lan"
                    
                    # فحص سريع للمنفذ قبل الإضافة
                    if self.manager.check_port_quick(ip, port):
                        peer_info = PeerInfo(
                            url=peer_url,
                            ip=ip,
                            port=port,
                            hostname=hostname,
                            network_type=network_type,
                            last_seen=datetime.now(),
                            last_health_check=datetime.now(),
                            discovery_method="zeroconf"
                        )
                        
                        # إضافة فورية مع فحص صحة
                        self.manager.add_peer_immediate(peer_info)
                        logger.info(f"🔍 اكتشاف جهاز عبر Zeroconf: {hostname} ({ip}:{port})")
                    
            except Exception as e:
                logger.debug(f"خطأ في معالجة الخدمة {name}: {e}")
        
        def remove_service(self, zc: Zeroconf, type_: str, name: str) -> None:
            """إزالة خدمة"""
            logger.info(f"خدمة تمت إزالتها: {name}")
        
        def update_service(self, zc: Zeroconf, type_: str, name: str) -> None:
            """تحديث خدمة"""
            logger.debug(f"خدمة محدثة: {name}")

    def check_port_quick(self, ip: str, port: int, timeout: int = 2) -> bool:
        """فحص سريع للمنفذ"""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(timeout)
                result = sock.connect_ex((ip, port))
                return result == 0
        except Exception:
            return False

    def add_peer_immediate(self, peer_info: PeerInfo):
        """إضافة قرين مع فحص صحة فوري"""
        with self._lock:
            if peer_info.url not in self.peers:
                self.peers[peer_info.url] = peer_info
                
                # فحص الصحة فوري وغير متزامن
                threading.Thread(
                    target=self.check_peer_health_prioritized,
                    args=(peer_info,),
                    daemon=True
                ).start()

    def start_lan_discovery(self):
        """بدء اكتشاف الأجهزة على الشبكة المحلية"""
        try:
            if self.zeroconf:
                listener = self.PeerListener(self)
                ServiceBrowser(self.zeroconf, SERVICE_TYPE, listener)
                logger.info("📡 بدء اكتشاف الأجهزة على LAN")
        except Exception as e:
            logger.error(f"فشل بدء اكتشاف LAN: {e}")
    
    def start_network_scanning_prioritized(self):
        """بدء مسح الشبكة المُفضل"""
        def network_scan_worker():
            while self._running:
                try:
                    logger.info(f"🎯 بدء المسح المُفضل (المنفذ {PRIORITY_PORT} أولاً)...")
                    
                    local_ip = self.get_local_ip()
                    network_base = ".".join(local_ip.split(".")[:3])
                    
                    # استخدام المسح المُفضل
                    discovered_hosts = self.network_scanner.scan_subnet_prioritized(network_base)
                    
                    for host in discovered_hosts:
                        self.process_scanned_host_prioritized(host)
                    
                    # إحصائيات الأولوية
                    preferred_count = sum(1 for h in discovered_hosts if h['priority_port_found'])
                    logger.info(f"✅ المسح المُفضل مكتمل: {preferred_count} جهاز بالمنفذ المفضل")
                    
                except Exception as e:
                    logger.error(f"خطأ في المسح المُفضل: {e}")
                
                time.sleep(NETWORK_SCAN_INTERVAL)
        
        self._network_scan_thread = threading.Thread(
            target=network_scan_worker,
            daemon=True
        )
        self._network_scan_thread.start()

    def start_network_scanning(self):
        """وظيفة التوافق - استخدام النظام الجديد"""
        self.start_network_scanning_prioritized()
    
    def process_scanned_host_prioritized(self, host: dict):
        """معالجة الجهاز المكتشف من المسح المُفضل"""
        try:
            ip = host['ip']
            open_ports = host['open_ports']
            
            # استخدام أول منفذ مفتوح (مع الأولوية لـ 72500)
            if open_ports:
                port = open_ports[0]  # أول منفذ مفتوح (مع الأولوية)
                peer_url = f"http://{ip}:{port}"

                with self._lock:
                    if peer_url not in self.peers:
                        peer_info = PeerInfo(
                            url=peer_url,
                            ip=ip,
                            port=port,
                            hostname=host['hostname'],
                            network_type="lan",
                            last_seen=datetime.now(),
                            last_health_check=datetime.now(),
                            capabilities=['network_scan_discovered'],
                            discovery_method="network_scan_prioritized"
                        )
                        self.peers[peer_url] = peer_info

                        # فحص الصحة غير متزامن
                        threading.Thread(
                            target=self.check_peer_health_prioritized,
                            args=(peer_info,),
                            daemon=True
                        ).start()
                        
                        port_type = "مفضل" if port == PRIORITY_PORT else "ثانوي"
                        logger.info(f"➕ قرين جديد من المسح ({port_type}): {ip}:{port}")
            
        except Exception as e:
            logger.debug(f"خطأ في معالجة الجهاز المسح: {e}")

    def process_scanned_host(self, host: dict):
        """وظيفة التوافق - استخدام النظام الجديد"""
        self.process_scanned_host_prioritized(host)
    
    def start_resource_discovery(self):
        """بدء اكتشاف الموارد المساعدة"""
        def resource_discovery_worker():
            while self._running:
                try:
                    # اكتشاف أجهزة التخزين
                    storage_devices = self.hardware_discoverer.discover_storage_devices()
                    for device in storage_devices:
                        self.add_storage_resource(device)
                    
                    # اكتشاف كاميرات الشبكة
                    cameras = self.hardware_discoverer.discover_network_cameras()
                    for camera in cameras:
                        self.add_camera_resource(camera)
                    
                    logger.info(f"📦 اكتشاف الموارد: {len(storage_devices)} تخزين, {len(cameras)} كاميرا")
                    
                except Exception as e:
                    logger.error(f"خطأ في اكتشاف الموارد: {e}")
                
                time.sleep(300)  # كل 5 دقائق
        
        self._resource_discovery_thread = threading.Thread(
            target=resource_discovery_worker,
            daemon=True
        )
        self._resource_discovery_thread.start()
    
    def add_storage_resource(self, device: dict):
        """إضافة مورد تخزين"""
        resource_id = device['device_id']
        
        with self._lock:
            if resource_id not in self.resources:
                resource_info = ResourceInfo(
                    device_id=resource_id,
                    name=device['name'],
                    type='storage',
                    connection_type=device['connection_type'],
                    capabilities=['file_storage', 'backup', 'cache'],
                    status='available',
                    paired_at=datetime.now(),
                    details={
                        'capacity': device.get('capacity', 'unknown'),
                        'free_space': device.get('free_space', 'unknown'),
                        'mountpoint': device.get('mountpoint', '')
                    }
                )
                self.resources[resource_id] = resource_info
                logger.info(f"💾 مورد تخزين مضاف: {device['name']}")
    
    def add_camera_resource(self, camera: dict):
        """إضافة مورد كاميرا"""
        resource_id = camera['device_id']
        
        with self._lock:
            if resource_id not in self.resources:
                resource_info = ResourceInfo(
                    device_id=resource_id,
                    name=camera['name'],
                    type='camera',
                    connection_type='network',
                    capabilities=['video_stream', 'monitoring'],
                    status='available',
                    paired_at=datetime.now(),
                    details={
                        'ip': camera['ip'],
                        'ports': camera['open_ports'],
                        'stream_urls': camera['stream_urls']
                    }
                )
                self.resources[resource_id] = resource_info
                logger.info(f"📷 مورد كاميرا مضاف: {camera['name']}")
    
    def discover_central_peers_enhanced(self):
        """اكتشاف محسن من السيرفرات المركزية"""
        logger.info("🌍 بدء اكتشاف السيرفرات المركزية...")
        
        working_servers = 0
        total_peers_found = 0
        
        for server_url in self.central_servers:
            try:
                logger.info(f"🔗 محاولة الاتصال بـ: {server_url}")
                
                # محاولة endpoints مختلفة
                endpoints = [
                    "/api/peers",
                    "/peers", 
                    "/discovery/peers",
                    "/nodes",
                    "/health"  # قد يعطينا معلومات عن الأقران
                ]
                
                for endpoint in endpoints:
                    discovery_url = urljoin(server_url, endpoint)
                    try:
                        # تعطيل التحقق من SSL للسيرفرات المحلية والاختبار
                        verify_ssl = not any(domain in server_url for domain in ['localhost', '127.0.0.1', '192.168.'])
                        response = requests.get(discovery_url, timeout=10, verify=verify_ssl)
                        logger.info(f"📡 استجابة من {discovery_url}: {response.status_code}")
                        
                        if response.status_code == 200:
                            peers_data = response.json()
                            peers_list = peers_data.get('peers', []) or peers_data.get('nodes', []) or []
                            
                            if peers_list:
                                for peer_data in peers_list:
                                    self.add_peer_from_discovery_enhanced(peer_data, server_url)
                                    total_peers_found += 1
                            
                            working_servers += 1
                            logger.info(f"✅ {server_url} يعمل - وجد {len(peers_list)} جهاز")
                            break  # خروج عند النجاح
                            
                    except requests.exceptions.RequestException as e:
                        logger.debug(f"❌ فشل {endpoint} على {server_url}: {e}")
                        continue
                    except json.JSONDecodeError as e:
                        logger.debug(f"❌ خطأ في JSON من {server_url}: {e}")
                        continue
                
            except Exception as e:
                logger.warning(f"❌ فشل كامل مع {server_url}: {e}")
        
        # تحديث الإحصائيات
        self.discovery_stats.update({
            'central_servers_working': working_servers,
            'central_servers_failed': len(self.central_servers) - working_servers,
            'last_central_discovery': datetime.now(),
            'peers_found': total_peers_found
        })
        
        logger.info(f"📊 نتائج الاكتشاف المركزي: {working_servers}/{len(self.central_servers)} سيرفرات تعمل، {total_peers_found} جهاز مكتشف")

    def add_peer_from_discovery_enhanced(self, peer_data: dict, source_server: str):
        """إضافة جهاز من بيانات الاكتشاف مع تحسينات"""
        try:
            ip = peer_data.get('ip') or peer_data.get('address') or peer_data.get('host')
            port = peer_data.get('port', self.current_discovery_port or FALLBACK_PORT)
            hostname = peer_data.get('hostname') or peer_data.get('name', f'peer_from_{source_server}')
            
            if not ip:
                logger.debug("❌ بيانات جهاز بدون IP - تخطي")
                return
            
            # تنظيف الـ IP
            ip = str(ip).strip()
            if ip.startswith('http://'):
                ip = ip[7:]
            if ip.startswith('https://'):
                ip = ip[8:]
            if ':' in ip:
                ip = ip.split(':')[0]
            
            peer_url = f"http://{ip}:{port}"
            
            with self._lock:
                if peer_url not in self.peers:
                    peer_info = PeerInfo(
                        url=peer_url,
                        ip=ip,
                        port=port,
                        hostname=hostname,
                        network_type="wan",
                        last_seen=datetime.now(),
                        last_health_check=datetime.now(),
                        discovery_method=f"central_server_{source_server}"
                    )
                    self.peers[peer_url] = peer_info
                    
                    # فحص الصحة غير متزامن
                    threading.Thread(
                        target=self.check_peer_health_prioritized,
                        args=(peer_info,),
                        daemon=True
                    ).start()
                    
                    logger.info(f"🌍 قرين مركزي مضاف: {hostname} ({ip}:{port}) من {source_server}")
        
        except Exception as e:
            logger.error(f"❌ خطأ في إضافة جهاز من الاكتشاف: {e}")

    def check_peer_health_prioritized(self, peer_info: PeerInfo):
        """فحص صحة مع أولوية للمنفذ المفضل"""
        
        # أولاً: محاولة المنفذ المفضل 72500
        preferred_health_url = f"http://{peer_info.ip}:{PRIORITY_PORT}/health"
        
        try:
            start_time = time.time()
            verify_ssl = not self.is_local_network(peer_info.ip)
            response = requests.get(preferred_health_url, timeout=3, verify=verify_ssl)
            response_time = time.time() - start_time
            
            if response.status_code == 200:
                self._update_peer_health(peer_info, response, response_time, "preferred_port")
                logger.info(f"✅ {peer_info.hostname} صحي عبر المنفذ المفضل ({response_time:.2f}s)")
                return True
        except Exception as e:
            logger.debug(f"⏰ فشل المنفذ المفضل لـ {peer_info.hostname}: {e}")
        
        # ثانياً: إذا فشل، المحاولة بالمنافذ الأخرى
        return self.check_peer_health_enhanced(peer_info)

    def _update_peer_health(self, peer_info: PeerInfo, response, response_time: float, method: str):
        """تحديث صحة القرين"""
        try:
            health_data = response.json()
        except:
            health_data = {}
        
        with self._lock:
            peer_info.is_active = True
            peer_info.response_time = response_time
            peer_info.last_health_check = datetime.now()
            peer_info.cpu_usage = health_data.get('cpu_usage', 0)
            peer_info.memory_available = health_data.get('memory_available', 0)
            peer_info.capabilities = health_data.get('capabilities', [])

    def check_peer_health_enhanced(self, peer_info: PeerInfo):
        """فحص صحة محسن مع endpoints متعددة"""
        health_endpoints = [
            "/health",
            "/api/health", 
            "/status",
            "/api/status",
            "/",  # الصفحة الرئيسية قد تعطي معلومات
        ]
        
        for endpoint in health_endpoints:
            try:
                health_url = f"{peer_info.url}{endpoint}"
                start_time = time.time()
                
                # تعطيل SSL verification للأجهزة المحلية
                verify_ssl = not any(domain in peer_info.url for domain in ['localhost', '127.0.0.1', '192.168.'])
                response = requests.get(health_url, timeout=5, verify=verify_ssl)
                response_time = time.time() - start_time
                
                if response.status_code == 200:
                    self._update_peer_health(peer_info, response, response_time, endpoint)
                    logger.info(f"✅ {peer_info.hostname} صحي ({response_time:.2f}s) عبر {endpoint}")
                    return True
                    
            except requests.exceptions.Timeout:
                logger.debug(f"⏰ انتهت مهلة {endpoint} لـ {peer_info.hostname}")
                continue
            except requests.exceptions.ConnectionError:
                logger.debug(f"🔌 فشل اتصال {endpoint} لـ {peer_info.hostname}")
                continue
            except Exception as e:
                logger.debug(f"⚠️ خطأ في {endpoint} لـ {peer_info.hostname}: {e}")
                continue
        
        # إذا فشلت جميع المحاولات
        self.mark_peer_inactive(peer_info)
        logger.warning(f"❌ {peer_info.hostname} غير متجاوب بعد كل المحاولات")
        return False

    def mark_peer_inactive(self, peer_info: PeerInfo):
        """تعليم الجهاز كغير نشط"""
        with self._lock:
            peer_info.is_active = False
            peer_info.last_health_check = datetime.now()
            logger.info(f"🔴 {peer_info.hostname} معلم كغير نشط")

    def health_check_worker(self):
        """عامل فحص الصحة الدوري"""
        while self._running:
            try:
                current_peers = self.get_active_peers()
                
                if current_peers:
                    with ThreadPoolExecutor(max_workers=5) as executor:
                        futures = [
                            executor.submit(self.check_peer_health_prioritized, peer_info)
                            for peer_info in current_peers
                        ]
                        
                        for future in as_completed(futures):
                            try:
                                future.result(timeout=15)
                            except Exception:
                                continue
                
                logger.info(f"❤️ فحص صحة مكتمل - الأجهزة النشطة: {len(self.get_active_peers())}")
                
            except Exception as e:
                logger.error(f"💥 خطأ في فحص الصحة: {e}")
            
            time.sleep(HEALTH_CHECK_INTERVAL)
    
    def discovery_worker(self):
        """عامل الاكتشاف الدوري المحسن"""
        while self._running:
            try:
                # الاكتشاف من السيرفرات المركزية
                self.discover_central_peers_enhanced()
                
                # تنظيف الأجهزة القديمة
                self.cleanup_old_peers()
                
                # تسجيل الإحصائيات
                active_peers = len(self.get_active_peers())
                total_peers = len(self.peers)
                
                logger.info(
                    f"🔄 الاكتشاف الدوري - "
                    f"نشط: {active_peers}/{total_peers}, "
                    f"سيرفرات عاملة: {self.discovery_stats['central_servers_working']}"
                )
                
            except Exception as e:
                logger.error(f"💥 خطأ في الاكتشاف الدوري: {e}")
            
            time.sleep(DISCOVERY_INTERVAL)
    
    def cleanup_old_peers(self):
        """تنظيف الأجهزة القديمة"""
        cutoff_time = datetime.now() - timedelta(minutes=10)
        
        with self._lock:
            to_remove = [
                url for url, peer in self.peers.items()
                if peer.last_seen < cutoff_time and not peer.is_active
            ]
            
            for url in to_remove:
                del self.peers[url]
                logger.info(f"🧹 تنظيف جهاز قديم: {url}")
    
    def get_active_peers(self) -> List[PeerInfo]:
        """الحصول على قائمة الأجهزة النشطة"""
        with self._lock:
            return [
                peer for peer in self.peers.values()
                if peer.is_active
            ]
    
    def get_peers_by_network(self, network_type: str) -> List[PeerInfo]:
        """الحصول على الأجهزة حسب نوع الشبكة"""
        with self._lock:
            return [
                peer for peer in self.peers.values()
                if peer.network_type == network_type and peer.is_active
            ]
    
    def get_resources_by_type(self, resource_type: str) -> List[ResourceInfo]:
        """الحصول على الموارد حسب النوع"""
        with self._lock:
            return [
                resource for resource in self.resources.values()
                if resource.type == resource_type and resource.status == 'available'
            ]

    def start_enhanced_discovery(self):
        """بدء الاكتشاف المحسن مع أولوية المنافذ"""
        if self._running:
            return
        
        self._running = True
        
        # 1. تسجيل الخدمة مع الأولوية
        self.register_local_service_prioritized()
        
        # 2. بدء الاكتشاف المحلي
        self.start_lan_discovery()
        
        # 3. الاكتشاف الفوري مع الأولوية
        logger.info("🚀 بدء الاكتشاف الفوري مع أولوية المنفذ 72500...")
        self.discover_central_peers_enhanced()
        
        # 4. بدء المسح المُفضل
        self.start_network_scanning_prioritized()
        
        # 5. بدء اكتشاف الموارد
        self.start_resource_discovery()
        
        # 6. بدء الخيوط الدورية
        self._start_periodic_threads()
        
        logger.info(f"🎯 نظام الاكتشاف المحسن v2.3 يعمل على المنفذ {self.current_discovery_port}")

    def _start_periodic_threads(self):
        """بدء جميع الخيوط الدورية"""
        
        # الاكتشاف الدوري
        self._discovery_thread = threading.Thread(
            target=self.discovery_worker,
            daemon=True
        )
        self._discovery_thread.start()
        
        # فحص الصحة الدوري
        self._health_check_thread = threading.Thread(
            target=self.health_check_worker,
            daemon=True
        )
        self._health_check_thread.start()

    def start(self):
        """وظيفة البدء المتوافقة"""
        self.start_enhanced_discovery()
    
    def stop(self):
        """إيقاف نظام الاكتشاف"""
        self._running = False
        
        if self.zeroconf and self.service_info:
            self.zeroconf.unregister_service(self.service_info)
            self.zeroconf.close()
        
        logger.info("🛑 نظام اكتشاف الأقران متوقف")
    
    def get_port_strategy_report(self) -> dict:
        """تقرير استراتيجية المنافذ"""
        active_peers = self.get_active_peers()
        port_stats = {}
        
        for peer in active_peers:
            port = peer.port
            if port not in port_stats:
                port_stats[port] = 0
            port_stats[port] += 1
        
        return {
            'current_port': self.current_discovery_port,
            'current_strategy': self.get_strategy_name(),
            'priority_index': self.port_priority_index,
            'active_peers_by_port': port_stats,
            'total_peers': len(active_peers),
            'efficiency': self.calculate_port_efficiency()
        }

    def calculate_port_efficiency(self) -> float:
        """حساب كفاءة استراتيجية المنفذ"""
        active_peers = self.get_active_peers()
        if not active_peers:
            return 0.0
        
        # عدد الأقران على المنفذ المفضل 72500
        preferred_peers = sum(1 for p in active_peers if p.port == PRIORITY_PORT)
        return preferred_peers / len(active_peers)

    def set_preferred_port(self, port: int):
        """تعيين منفذ مفضل جديد"""
        global PRIORITY_PORT
        PRIORITY_PORT = port
        logger.info(f"🔄 تغيير المنفذ المفضل إلى: {port}")

    @property
    def PEERS(self) -> List[str]:
        """واجهة توافقية للحصول على روابط الأقران"""
        active_peers = self.get_active_peers()
        return [peer.url for peer in active_peers]
    
    @property 
    def PEERS_INFO(self) -> Dict[str, dict]:
        """معلومات مفصلة عن الأقران"""
        with self._lock:
            return {
                url: {
                    'ip': peer.ip,
                    'port': peer.port,
                    'hostname': peer.hostname,
                    'network_type': peer.network_type,
                    'is_active': peer.is_active,
                    'response_time': peer.response_time,
                    'cpu_usage': peer.cpu_usage,
                    'memory_available': peer.memory_available,
                    'last_seen': peer.last_seen.isoformat(),
                    'capabilities': peer.capabilities,
                    'discovery_method': peer.discovery_method
                }
                for url, peer in self.peers.items()
            }
    
    @property
    def RESOURCES_INFO(self) -> Dict[str, dict]:
        """معلومات عن الموارد المساعدة"""
        with self._lock:
            return {
                resource_id: {
                    'name': resource.name,
                    'type': resource.type,
                    'connection_type': resource.connection_type,
                    'capabilities': resource.capabilities,
                    'status': resource.status,
                    'paired_at': resource.paired_at.isoformat(),
                    'details': resource.details
                }
                for resource_id, resource in self.resources.items()
            }

    def get_discovery_report(self) -> dict:
        """تقرير مفصل عن حالة الاكتشاف"""
        active_peers = self.get_active_peers()
        
        return {
            'total_peers': len(self.peers),
            'active_peers': len(active_peers),
            'discovery_stats': self.discovery_stats,
            'peers_by_method': self._get_peers_by_discovery_method(),
            'central_servers_status': self._test_central_servers(),
            'port_strategy': self.get_port_strategy_report()
        }

    def _get_peers_by_discovery_method(self) -> dict:
        """تصنيف الأقران حسب طريقة الاكتشاف"""
        methods = {}
        with self._lock:
            for peer in self.peers.values():
                method = peer.discovery_method
                if method not in methods:
                    methods[method] = []
                methods[method].append({
                    'hostname': peer.hostname,
                    'url': peer.url,
                    'is_active': peer.is_active
                })
        return methods

    def _test_central_servers(self) -> dict:
        """فحص حالة السيرفرات المركزية"""
        results = {}
        for server in self.central_servers:
            try:
                verify_ssl = not any(domain in server for domain in ['localhost', '127.0.0.1', '192.168.'])
                response = requests.get(server, timeout=5, verify=verify_ssl)
                results[server] = {
                    'status': 'working' if response.status_code == 200 else 'failed',
                    'status_code': response.status_code
                }
            except Exception as e:
                results[server] = {
                    'status': 'failed',
                    'error': str(e)
                }
        return results

# نسخة عالمية للاستيراد
discovery_manager = EnhancedPeerDiscovery()

# دوال التوافق مع الإصدار القديم
def get_sequential_port():
    """وظيفة التوافق - استخدام المنفذ الثابت"""
    return discovery_manager.current_discovery_port or FALLBACK_PORT

def register_peer(ip, port):
    """وظيفة التوافق"""
    peer_url = f"http://{ip}:{port}"
    discovery_manager.add_peer_from_discovery_enhanced({
        'ip': ip,
        'port': port,
        'hostname': 'manual'
    }, "manual_registration")

def discover_lan_peers():
    """وظيفة التواسب - بدلاً من إرجاع Zeroconf"""
    discovery_manager.start_lan_discovery()
    return discovery_manager.zeroconf

def main():
    """الدالة الرئيسية المحسنة"""
    logger.info("🚀 بدء نظام اكتشاف الأقران المحسن v2.3...")
    
    try:
        # بدء النظام المحسن
        discovery_manager.start_enhanced_discovery()
        
        # حلقة العرض المحسنة
        counter = 0
        while True:
            counter += 1
            
            # كل 5 دورات عرض تقرير مفصل
            if counter % 5 == 0:
                report = discovery_manager.get_discovery_report()
                port_report = report['port_strategy']
                logger.info(f"📊 تقرير مفصل - الأقران: {report['active_peers']}/{report['total_peers']} نشط")
                logger.info(f"🎯 استراتيجية المنافذ: {port_report['current_strategy']} - الكفاءة: {port_report['efficiency']:.1%}")
            else:
                # عرض إحصائيات سريعة
                active_peers = discovery_manager.get_active_peers()
                stats = discovery_manager.discovery_stats
                port_stats = discovery_manager.get_port_strategy_report()
                
                logger.info(
                    f"📈 إحصائيات سريعة - "
                    f"أقران: {len(active_peers)} نشط, "
                    f"سيرفرات: {stats['central_servers_working']} تعمل, "
                    f"استراتيجية: {port_stats['current_strategy']}"
                )
            
            time.sleep(10)
            
    except KeyboardInterrupt:
        logger.info("🛑 إيقاف النظام...")
    finally:
        discovery_manager.stop()
    
if __name__ == "__main__":
    main()
