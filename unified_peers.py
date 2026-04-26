# unified_peers.py - مصدر موحد لجميع معلومات الأقران
import threading
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass

@dataclass
class UnifiedPeer:
    node_id: str
    ip: str
    port: int
    url: str
    last_seen: datetime
    capabilities: List[str]
    is_active: bool = True
    cpu_usage: float = 0.0
    memory_available: float = 0.0

class UnifiedPeerManager:
    """مدير موحد للأقران – مصدر واحد للحقيقة"""
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self.peers: Dict[str, UnifiedPeer] = {}
        self._lock = threading.RLock()
    
    def add_or_update(self, ip: str, port: int, node_id: str = None, capabilities: List[str] = None):
        """إضافة أو تحديث قرين"""
        url = f"http://{ip}:{port}"
        with self._lock:
            if url in self.peers:
                self.peers[url].last_seen = datetime.now()
                if capabilities:
                    self.peers[url].capabilities = capabilities
            else:
                self.peers[url] = UnifiedPeer(
                    node_id=node_id or f"node_{ip}",
                    ip=ip,
                    port=port,
                    url=url,
                    last_seen=datetime.now(),
                    capabilities=capabilities or []
                )
    
    def get_all(self) -> List[UnifiedPeer]:
        """الحصول على جميع الأقران"""
        with self._lock:
            return list(self.peers.values())
    
    def get_active(self) -> List[UnifiedPeer]:
        """الحصول على الأقران النشطين فقط"""
        with self._lock:
            return [p for p in self.peers.values() if p.is_active]
    
    def get_by_capability(self, capability: str) -> List[UnifiedPeer]:
        """الحصول على الأقران حسب القدرة"""
        with self._lock:
            return [p for p in self.peers.values() if capability in p.capabilities]

# نسخة عالمية للاستيراد
unified_manager = UnifiedPeerManager()
