#!/usr/bin/env python3
"""
security_layer.py - طبقة أمان متقدمة ومحسنة
============================================

نظام أمان شامل مع تشفير متقدم، إدارة مفاتيح ذكية، ومراقبة أمنية
"""

import os
import base64
import json
import logging
import secrets
import time
from typing import Dict, Optional, Tuple, List
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from enum import Enum
import hashlib
import hmac

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding, ec
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
from cryptography.exceptions import InvalidSignature, InvalidKey
from cryptography.fernet import Fernet, MultiFernet

# إعداد السجلات
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class SecurityLevel(Enum):
    """مستويات الأمان"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class KeyType(Enum):
    """أنواع المفاتيح"""
    SYMMETRIC = "symmetric"
    ASYMMETRIC = "asymmetric"
    SESSION = "session"

@dataclass
class KeyMetadata:
    """بيانات وصفية للمفتاح"""
    key_id: str
    key_type: KeyType
    created_at: datetime
    expires_at: Optional[datetime]
    security_level: SecurityLevel
    algorithm: str
    is_active: bool = True

@dataclass
class SecurityEvent:
    """حدث أمني"""
    event_id: str
    event_type: str
    timestamp: datetime
    severity: str
    description: str
    client_ip: str = ""
    details: Dict = None

class AdvancedSecurityManager:
    """
    مدير أمان متقدم مع تشفير متعدد المستويات وإدارة مفاتيح ذكية
    """
    
    def __init__(self, config: Dict = None):
        self.config = config or self._default_config()
        self.node_id = os.getenv("NODE_ID", f"node_{secrets.token_hex(8)}")
        
        # إدارة المفاتيح
        self._keys: Dict[str, KeyMetadata] = {}
        self._peer_keys: Dict[str, Dict] = {}  # {peer_id: {key: obj, metadata: KeyMetadata}}
        self._session_keys: Dict[str, Tuple[datetime, bytes]] = {}
        
        # سجل الأحداث الأمنية
        self.security_events: List[SecurityEvent] = []
        self.failed_attempts: Dict[str, List[datetime]] = {}
        
        # تهيئة المفاتيح
        self._initialize_keys()
        
        # إعداد Fernet متعدد للمفاتيح
        self._fernet = self._setup_fernet()
        
        logger.info(f"🔒 مدير الأمان المتقدم مُهيأ للعقدة {self.node_id}")
    
    def _default_config(self) -> Dict:
        """الإعدادات الافتراضية"""
        return {
            'key_rotation_days': 30,
            'session_key_lifetime_hours': 24,
            'max_failed_attempts': 5,
            'lockout_duration_minutes': 30,
            'security_level': SecurityLevel.MEDIUM,
            'algorithms': {
                'symmetric': 'AES-256-GCM',
                'asymmetric': 'RSA-2048',
                'hash': 'SHA-256',
                'kdf_iterations': 310000
            }
        }
    
    def _initialize_keys(self):
        """تهيئة المفاتيح الأساسية"""
        # مفتاح سري رئيسي من متغير البيئة أو إنشاء عشوائي
        master_secret = os.getenv("MASTER_SECRET")
        if not master_secret:
            master_secret = secrets.token_urlsafe(32)
            logger.warning("⚠️ استخدام مفتاح سري عشوائي - غير آمن للإنتاج")
        
        # اشتقاق المفاتيح من المفتاح الرئيسي
        self._derive_encryption_keys(master_secret)
        
        # إنشاء زوج مفاتيح غير متماثل
        self._generate_asymmetric_keys()
        
        self._log_security_event(
            "key_initialization",
            "INFO",
            "تم تهيئة المفاتيح الأساسية"
        )
    
    def _derive_encryption_keys(self, master_secret: str):
        """اشتقاق مفاتيح التشفير من المفتاح الرئيسي"""
        # استخدام salt عشوائي وفريد
        salt = os.urandom(16)
        
        # اشتقاق المفاتيح المختلفة
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=64,  # مفتاحين 32 بايت
            salt=salt,
            iterations=self.config['algorithms']['kdf_iterations'],
            backend=default_backend()
        )
        
        key_material = kdf.derive(master_secret.encode())
        encryption_key = base64.urlsafe_b64encode(key_material[:32])
        auth_key = key_material[32:]
        
        # حفظ المفاتيح
        key_id = f"sym_{int(time.time())}"
        self._keys[key_id] = KeyMetadata(
            key_id=key_id,
            key_type=KeyType.SYMMETRIC,
            created_at=datetime.now(),
            expires_at=datetime.now() + timedelta(days=self.config['key_rotation_days']),
            security_level=self.config['security_level'],
            algorithm=self.config['algorithms']['symmetric']
        )
        
        self._encryption_key = encryption_key
        self._auth_key = auth_key
        
        logger.info("✅ تم اشتقاق مفاتيح التشفير")
    
    def _generate_asymmetric_keys(self):
        """إنشاء زوج مفاتيح غير متماثل"""
        try:
            # استخدام RSA أو ECDSA حسب مستوى الأمان
            if self.config['security_level'] in [SecurityLevel.HIGH, SecurityLevel.CRITICAL]:
                # ECDSA لأمان أعلى وأداء أفضل
                self._private_key = ec.generate_private_key(
                    ec.SECP384R1(),
                    default_backend()
                )
                algorithm = "ECDSA-P384"
            else:
                # RSA لمستويات الأمان المتوسطة
                self._private_key = rsa.generate_private_key(
                    public_exponent=65537,
                    key_size=2048,
                    backend=default_backend()
                )
                algorithm = "RSA-2048"
            
            # المفتاح العام
            self._public_pem = (
                self._private_key.public_key()
                .public_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PublicFormat.SubjectPublicKeyInfo,
                )
                .decode()
            )
            
            key_id = f"asym_{int(time.time())}"
            self._keys[key_id] = KeyMetadata(
                key_id=key_id,
                key_type=KeyType.ASYMMETRIC,
                created_at=datetime.now(),
                expires_at=datetime.now() + timedelta(days=self.config['key_rotation_days']),
                security_level=self.config['security_level'],
                algorithm=algorithm
            )
            
            logger.info(f"✅ تم إنشاء المفاتيح غير المتماثلة ({algorithm})")
            
        except Exception as e:
            logger.error(f"❌ فشل إنشاء المفاتيح غير المتماثلة: {e}")
            raise
    
    def _setup_fernet(self) -> MultiFernet:
        """إعداد Fernet متعدد المفاتيح"""
        fernet_keys = [Fernet(self._encryption_key)]
        return MultiFernet(fernet_keys)
    
    def _log_security_event(self, event_type: str, severity: str, 
                          description: str, client_ip: str = "", details: Dict = None):
        """تسجيل حدث أمني"""
        event = SecurityEvent(
            event_id=f"evt_{int(time.time()*1000)}_{secrets.token_hex(4)}",
            event_type=event_type,
            timestamp=datetime.now(),
            severity=severity,
            description=description,
            client_ip=client_ip,
            details=details or {}
        )
        
        self.security_events.append(event)
        
        # الحفاظ على حجم السجل
        if len(self.security_events) > 1000:
            self.security_events = self.security_events[-1000:]
        
        # تسجيل حسب مستوى الخطورة
        if severity == "ERROR":
            logger.error(f"🔐 {event_type}: {description}")
        elif severity == "WARNING":
            logger.warning(f"🔐 {event_type}: {description}")
        else:
            logger.info(f"🔐 {event_type}: {description}")
    
    def _check_rate_limit(self, identifier: str) -> bool:
        """التحقق من حد المعدل لمحاولات فاشلة"""
        now = datetime.now()
        window_start = now - timedelta(minutes=self.config['lockout_duration_minutes'])
        
        if identifier not in self.failed_attempts:
            self.failed_attempts[identifier] = []
        
        # تنظيف المحاولات القديمة
        self.failed_attempts[identifier] = [
            attempt for attempt in self.failed_attempts[identifier]
            if attempt > window_start
        ]
        
        # التحقق من الحد
        if len(self.failed_attempts[identifier]) >= self.config['max_failed_attempts']:
            return False
        
        return True
    
    def _record_failed_attempt(self, identifier: str):
        """تسجيل محاولة فاشلة"""
        if identifier not in self.failed_attempts:
            self.failed_attempts[identifier] = []
        
        self.failed_attempts[identifier].append(datetime.now())
    
    def encrypt_data(self, data: bytes, use_session_key: bool = False) -> bytes:
        """
        تشفير البيانات مع خيارات متقدمة
        
        Args:
            data: البيانات للتشفير
            use_session_key: استخدام مفتاح جلسة مؤقت
            
        Returns:
            البيانات المشفرة
        """
        try:
            if use_session_key:
                # استخدام مفتاح جلسة
                session_key = self._generate_session_key()
                fernet = Fernet(session_key)
                encrypted = fernet.encrypt(data)
                
                # إضافة معرف الجلسة
                session_id = hashlib.sha256(session_key).hexdigest()[:16]
                result = base64.urlsafe_b64encode(
                    f"{session_id}:".encode() + encrypted
                )
            else:
                # استخدام المفتاح الرئيسي
                result = self._fernet.encrypt(data)
            
            return result
            
        except Exception as e:
            self._log_security_event(
                "encryption_failed",
                "ERROR",
                f"فشل تشفير البيانات: {e}"
            )
            raise
    
    def decrypt_data(self, encrypted_data: bytes, session_key: bytes = None) -> bytes:
        """
        فك تشفير البيانات
        
        Args:
            encrypted_data: البيانات المشفرة
            session_key: مفتاح الجلسة (اختياري)
            
        Returns:
            البيانات الأصلية
        """
        try:
            if session_key:
                # فك التشفير بمفتاح جلسة
                fernet = Fernet(session_key)
                return fernet.decrypt(encrypted_data)
            else:
                # فك التشفير بالمفاتيح المتاحة
                return self._fernet.decrypt(encrypted_data)
                
        except Exception as e:
            self._log_security_event(
                "decryption_failed",
                "ERROR",
                f"فشل فك تشفير البيانات: {e}"
            )
            raise
    
    def _generate_session_key(self) -> bytes:
        """إنشاء مفتاح جلسة مؤقت"""
        session_key = secrets.token_bytes(32)
        session_id = hashlib.sha256(session_key).hexdigest()
        
        expiry = datetime.now() + timedelta(
            hours=self.config['session_key_lifetime_hours']
        )
        
        self._session_keys[session_id] = (expiry, session_key)
        
        # تنظيف مفاتيح الجلسات المنتهية
        self._cleanup_expired_session_keys()
        
        return session_key
    
    def _cleanup_expired_session_keys(self):
        """تنظيف مفاتيح الجلسات المنتهية"""
        now = datetime.now()
        expired_keys = [
            key_id for key_id, (expiry, _) in self._session_keys.items()
            if expiry < now
        ]
        
        for key_id in expired_keys:
            del self._session_keys[key_id]
    
    def sign_data(self, data: Dict) -> Dict:
        """
        توقيع البيانات رقمياً
        
        Args:
            data: البيانات للتوقيع
            
        Returns:
            البيانات الموقعة
        """
        try:
            # تحضير البيانات للتوقيع
            data_str = json.dumps(data, sort_keys=True, separators=(",", ":"))
            
            # التوقيع
            if isinstance(self._private_key, ec.EllipticCurvePrivateKey):
                signature = self._private_key.sign(
                    data_str.encode(),
                    ec.ECDSA(hashes.SHA256())
                )
            else:
                signature = self._private_key.sign(
                    data_str.encode(),
                    padding.PSS(
                        mgf=padding.MGF1(hashes.SHA256()),
                        salt_length=padding.PSS.MAX_LENGTH,
                    ),
                    hashes.SHA256(),
                )
            
            # إعداد البيانات الموقعة
            signed_data = data.copy()
            signed_data.update({
                "_signature": base64.b64encode(signature).decode(),
                "_sender_id": self.node_id,
                "_timestamp": datetime.now().isoformat(),
                "_public_key": self._public_pem,
                "_algorithm": self._get_key_algorithm()
            })
            
            return signed_data
            
        except Exception as e:
            self._log_security_event(
                "signing_failed",
                "ERROR",
                f"فشل توقيع البيانات: {e}"
            )
            raise
    
    def verify_signature(self, signed_data: Dict, peer_id: str = None) -> bool:
        """
        التحقق من توقيع البيانات
        
        Args:
            signed_data: البيانات الموقعة
            peer_id: معرف العقدة (اختياري)
            
        Returns:
            صحة التوقيع
        """
        # التحقق من الحدود
        client_ip = signed_data.get('_client_ip', 'unknown')
        if not self._check_rate_limit(client_ip):
            self._log_security_event(
                "rate_limit_exceeded",
                "WARNING",
                f"تجاوز حد المعدل للعميل {client_ip}",
                client_ip
            )
            return False
        
        try:
            # استخراج التوقيع والبيانات
            if "_signature" not in signed_data:
                return False
            
            signature = base64.b64decode(signed_data["_signature"])
            data_to_verify = {
                k: v for k, v in signed_data.items()
                if not k.startswith('_') or k == "_timestamp"
            }
            
            data_str = json.dumps(data_to_verify, sort_keys=True, separators=(",", ":"))
            
            # الحصول على المفتاح العام
            public_key = self._get_peer_public_key(signed_data, peer_id)
            if not public_key:
                return False
            
            # التحقق من التوقيع
            if isinstance(public_key, ec.EllipticCurvePublicKey):
                public_key.verify(
                    signature,
                    data_str.encode(),
                    ec.ECDSA(hashes.SHA256())
                )
            else:
                public_key.verify(
                    signature,
                    data_str.encode(),
                    padding.PSS(
                        mgf=padding.MGF1(hashes.SHA256()),
                        salt_length=padding.PSS.MAX_LENGTH,
                    ),
                    hashes.SHA256(),
                )
            
            # تسجيل النجاح
            self._log_security_event(
                "signature_verified",
                "INFO",
                f"تم التحقق من توقيع بيانات من {signed_data.get('_sender_id', 'unknown')}",
                client_ip
            )
            
            return True
            
        except InvalidSignature:
            self._record_failed_attempt(client_ip)
            self._log_security_event(
                "invalid_signature",
                "WARNING",
                f"توقيع غير صالح من {client_ip}",
                client_ip
            )
            return False
            
        except Exception as e:
            self._record_failed_attempt(client_ip)
            self._log_security_event(
                "verification_failed",
                "ERROR",
                f"فشل التحقق من التوقيع: {e}",
                client_ip
            )
            return False
    
    def _get_peer_public_key(self, signed_data: Dict, peer_id: str = None) -> Optional:
        """
        الحصول على المفتاح العام للعقدة الشريكة
        """
        sender_id = peer_id or signed_data.get("_sender_id")
        
        if not sender_id:
            return None
        
        # البحث في المفاتيح المخزنة
        if sender_id in self._peer_keys:
            return self._peer_keys[sender_id]['key']
        
        # محاولة تحميل المفتاح من البيانات
        public_key_pem = signed_data.get("_public_key")
        if public_key_pem:
            try:
                public_key = serialization.load_pem_public_key(
                    public_key_pem.encode(),
                    backend=default_backend()
                )
                
                # تخزين المفتاح
                self._peer_keys[sender_id] = {
                    'key': public_key,
                    'metadata': KeyMetadata(
                        key_id=f"peer_{sender_id}",
                        key_type=KeyType.ASYMMETRIC,
                        created_at=datetime.now(),
                        expires_at=datetime.now() + timedelta(days=90),
                        security_level=SecurityLevel.MEDIUM,
                        algorithm=self._detect_key_algorithm(public_key)
                    )
                }
                
                return public_key
                
            except Exception as e:
                self._log_security_event(
                    "key_loading_failed",
                    "ERROR",
                    f"فشل تحميل المفتاح العام لـ {sender_id}: {e}"
                )
        
        return None
    
    def _get_key_algorithm(self) -> str:
        """الحصول على خوارزمية المفتاح الحالي"""
        if isinstance(self._private_key, ec.EllipticCurvePrivateKey):
            return "ECDSA-P384"
        else:
            return "RSA-2048"
    
    def _detect_key_algorithm(self, public_key) -> str:
        """كشف خوارزمية المفتاح"""
        if isinstance(public_key, ec.EllipticCurvePublicKey):
            return f"ECDSA-{public_key.curve.key_size}"
        else:
            return f"RSA-{public_key.key_size}"
    
    def add_peer_key(self, peer_id: str, public_key_pem: str, 
                    trust_level: SecurityLevel = SecurityLevel.MEDIUM):
        """
        إضافة مفتاح عام لعقدة شريكة
        
        Args:
            peer_id: معرف العقدة
            public_key_pem: المفتاح العام بصيغة PEM
            trust_level: مستوى الثقة
        """
        try:
            public_key = serialization.load_pem_public_key(
                public_key_pem.encode(),
                backend=default_backend()
            )
            
            self._peer_keys[peer_id] = {
                'key': public_key,
                'metadata': KeyMetadata(
                    key_id=f"peer_{peer_id}",
                    key_type=KeyType.ASYMMETRIC,
                    created_at=datetime.now(),
                    expires_at=datetime.now() + timedelta(days=90),
                    security_level=trust_level,
                    algorithm=self._detect_key_algorithm(public_key)
                )
            }
            
            self._log_security_event(
                "peer_key_added",
                "INFO",
                f"تم إضافة مفتاح العقدة {peer_id} بمستوى ثقة {trust_level.value}"
            )
            
        except Exception as e:
            self._log_security_event(
                "peer_key_failed",
                "ERROR",
                f"فشل إضافة مفتاح العقدة {peer_id}: {e}"
            )
            raise
    
    def rotate_keys(self):
        """تدوير المفاتيح تلقائياً"""
        try:
            # تدوير المفاتيح المتماثلة
            self._derive_encryption_keys(os.urandom(32).hex())
            
            # تدوير المفاتيح غير المتماثلة
            self._generate_asymmetric_keys()
            
            # تحديث Fernet
            self._fernet = self._setup_fernet()
            
            self._log_security_event(
                "key_rotation",
                "INFO",
                "تم تدوير جميع المفاتيح بنجاح"
            )
            
        except Exception as e:
            self._log_security_event(
                "key_rotation_failed",
                "ERROR",
                f"فشل تدوير المفاتيح: {e}"
            )
            raise
    
    def get_security_status(self) -> Dict:
        """الحصول على حالة الأمان الشاملة"""
        active_peer_keys = len(self._peer_keys)
        active_session_keys = len(self._session_keys)
        recent_events = len([
            e for e in self.security_events 
            if e.timestamp > datetime.now() - timedelta(hours=24)
        ])
        
        return {
            "node_id": self.node_id,
            "security_level": self.config['security_level'].value,
            "key_statistics": {
                "total_keys": len(self._keys),
                "active_peer_keys": active_peer_keys,
                "active_session_keys": active_session_keys,
                "keys_expiring_soon": len([
                    k for k in self._keys.values()
                    if k.expires_at and k.expires_at < datetime.now() + timedelta(days=7)
                ])
            },
            "event_statistics": {
                "total_events": len(self.security_events),
                "recent_events_24h": recent_events,
                "failed_attempts": sum(len(v) for v in self.failed_attempts.values())
            },
            "algorithms": self.config['algorithms']
        }

# التوافق مع الإصدار القديم
class SecurityManager(AdvancedSecurityManager):
    """فئة التوافق مع الإصدار القديم"""
    
    def __init__(self, shared_secret: str):
        config = {
            'security_level': SecurityLevel.MEDIUM,
            'key_rotation_days': 30
        }
        super().__init__(config)
        
        # الحفاظ على التوافق مع الواجهة القديمة
        self._legacy_cipher = Fernet(self._encryption_key)
    
    def encrypt_data(self, data: bytes) -> bytes:
        """واجهة التوافق مع الإصدار القديم"""
        return self._legacy_cipher.encrypt(data)
    
    def decrypt_data(self, encrypted: bytes) -> bytes:
        """واجهة التواسب مع الإصدار القديم"""
        return self._legacy_cipher.decrypt(encrypted)
    
    def sign_task(self, task: Dict) -> Dict:
        """واجهة التوافق مع الإصدار القديم"""
        return self.sign_data(task)
    
    def verify_task(self, signed_task: Dict) -> bool:
        """واجهة التوافق مع الإصدار القديم"""
        return self.verify_signature(signed_task)

# استخدام المثال
if __name__ == "__main__":
    # اختبار النظام المحسن
    security = AdvancedSecurityManager()
    
    # اختبار التشفير
    test_data = b"Hello, Secure World!"
    encrypted = security.encrypt_data(test_data)
    decrypted = security.decrypt_data(encrypted)
    
    print(f"✅ اختبار التشفير: {test_data.decode()} -> {decrypted.decode()}")
    
    # اختبار التوقيع
    test_task = {"action": "process", "data": "sample"}
    signed_task = security.sign_data(test_task)
    is_valid = security.verify_signature(signed_task)
    
    print(f"✅ اختبار التوقيع: {is_valid}")
    
    # عرض حالة الأمان
    status = security.get_security_status()
    print(f"📊 حالة الأمان: {status}")