#!/usr/bin/env python3
# utils.py - مجموعة أدوات مساعدة محسنة للنظام الموزع

import re
import logging
import time
import hashlib
import json
import uuid
import inspect
from typing import Any, Dict, List, Optional, Tuple, Union, Callable
from pathlib import Path
from datetime import datetime, timedelta
from functools import wraps, lru_cache
import threading
from concurrent.futures import ThreadPoolExecutor

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

class TextUtils:
    """أدوات معالجة النصوص المحسنة"""
    
    @staticmethod
    def clean_text(text: str, 
                  remove_extra_spaces: bool = True,
                  remove_special_chars: bool = False,
                  normalize_arabic: bool = True,
                  strip_text: bool = True) -> str:
        """
        تنظيف النص مع خيارات متعددة
        
        Args:
            text: النص المدخل
            remove_extra_spaces: إزالة المسافات الزائدة
            remove_special_chars: إزالة الرموز الخاصة
            normalize_arabic: توحيد التشكيل العربي
            strip_text: إزالة المسافات الطرفية
        
        Returns:
            النص المنظف
        """
        if not text or not isinstance(text, str):
            return ""
        
        cleaned_text = text
        
        # توحيد التشكيل العربي إذا مطلوب
        if normalize_arabic:
            cleaned_text = TextUtils.normalize_arabic_text(cleaned_text)
        
        # إزالة الرموز الخاصة إذا مطلوب
        if remove_special_chars:
            # الاحتفاظ بالأحرف العربية والإنجليزية والأرقام والمسافات
            cleaned_text = re.sub(r'[^\w\u0600-\u06FF\s]', ' ', cleaned_text)
        
        # إزالة المسافات الزائدة
        if remove_extra_spaces:
            cleaned_text = re.sub(r'\s+', ' ', cleaned_text)
        
        # إزالة المسافات الطرفية
        if strip_text:
            cleaned_text = cleaned_text.strip()
        
        return cleaned_text
    
    @staticmethod
    def normalize_arabic_text(text: str) -> str:
        """توحيد النص العربي (إزالة التشكيل الزائد)"""
        # إزالة التشكيل باستثناء الشدة والمد
        text = re.sub(r'[\u064B-\u0652]', '', text)  # إزالة الحركات
        # توحيد الهمزات
        text = text.replace('أ', 'ا')
        text = text.replace('إ', 'ا')
        text = text.replace('آ', 'ا')
        text = text.replace('ة', 'ه')
        return text
    
    @staticmethod
    def detect_language_advanced(text: str) -> Dict[str, Any]:
        """
        كشف لغة النص بشكل متقدم
        
        Returns:
            dict: معلومات عن اللغة المكتشفة
        """
        if not text or not isinstance(text, str):
            return {"language": "unknown", "confidence": 0.0, "details": {}}
        
        text = text.strip()
        if not text:
            return {"language": "unknown", "confidence": 0.0, "details": {}}
        
        # أنماط للكشف عن اللغات
        patterns = {
            "ar": re.compile(r'[\u0600-\u06FF]'),  # العربية
            "en": re.compile(r'[a-zA-Z]'),         # الإنجليزية
            "fr": re.compile(r'[éèêëàâçîïôûùü]', re.IGNORECASE),  # الفرنسية
            "es": re.compile(r'[áéíóúñü]', re.IGNORECASE),        # الإسبانية
            "fa": re.compile(r'[\u067E-\u06CC]'),  # الفارسية
            "ur": re.compile(r'[\u0670-\u06D4]'),  # الأردية
        }
        
        scores = {}
        total_chars = len(text)
        
        if total_chars == 0:
            return {"language": "unknown", "confidence": 0.0, "details": {}}
        
        # حساب نسبة كل لغة
        for lang, pattern in patterns.items():
            matches = len(pattern.findall(text))
            score = matches / total_chars if total_chars > 0 else 0
            scores[lang] = score
        
        # إيجاد اللغة الأعلى score
        if scores:
            best_lang = max(scores.items(), key=lambda x: x[1])
            confidence = best_lang[1]
            
            # إذا كانت الثقة منخفضة، نعتبرها إنجليزية (الافتراضية)
            if confidence < 0.1:
                best_lang = ("en", 0.1)
            
            return {
                "language": best_lang[0],
                "confidence": round(best_lang[1], 3),
                "details": scores,
                "is_rtl": best_lang[0] in ["ar", "fa", "ur", "he"]
            }
        
        return {"language": "en", "confidence": 0.1, "details": {}, "is_rtl": False}
    
    @staticmethod
    def truncate_text(text: str, max_length: int = 100, suffix: str = "...") -> str:
        """تقصير النص مع الحفاظ على الكلمات"""
        if len(text) <= max_length:
            return text
        
        # التقصير مع الحفاظ على كلمات كاملة
        truncated = text[:max_length].rsplit(' ', 1)[0]
        return truncated + suffix if truncated != text[:max_length] else text[:max_length] + suffix
    
    @staticmethod
    def extract_emails(text: str) -> List[str]:
        """استخراج عناوين البريد الإلكتروني من النص"""
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        return re.findall(email_pattern, text)
    
    @staticmethod
    def extract_urls(text: str) -> List[str]:
        """استخراج الروابط من النص"""
        url_pattern = r'https?://[^\s]+|www\.[^\s]+'
        return re.findall(url_pattern, text)
    
    @staticmethod
    def count_words(text: str) -> int:
        """عد الكلمات في النص"""
        words = re.findall(r'\b\w+\b', text)
        return len(words)

class ValidationUtils:
    """أدوات التحقق من الصحة"""
    
    @staticmethod
    def is_valid_email(email: str) -> bool:
        """التحقق من صحة البريد الإلكتروني"""
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return bool(re.match(pattern, email))
    
    @staticmethod
    def is_valid_url(url: str) -> bool:
        """التحقق من صحة الرابط"""
        pattern = r'^https?://[^\s/$.?#].[^\s]*$'
        return bool(re.match(pattern, url))
    
    @staticmethod
    def is_valid_phone(phone: str) -> bool:
        """التحقق من صحة رقم الهاتف (صيغة دولية)"""
        pattern = r'^\+?[1-9]\d{1,14}$'
        return bool(re.match(pattern, phone))
    
    @staticmethod
    def validate_args(args: tuple, expected_types: List[type]) -> bool:
        """التحقق من أنواع الوسائط"""
        if len(args) != len(expected_types):
            return False
        
        return all(isinstance(arg, expected_type) 
                  for arg, expected_type in zip(args, expected_types))

class SecurityUtils:
    """أدوات الأمان"""
    
    @staticmethod
    def generate_hash(data: str, algorithm: str = "sha256") -> str:
        """إنشاء هاش للبيانات"""
        hash_func = getattr(hashlib, algorithm, hashlib.sha256)
        return hash_func(data.encode()).hexdigest()
    
    @staticmethod
    def generate_api_key(length: int = 32) -> str:
        """إنشاء مفتاح API عشوائي"""
        return hashlib.sha256(uuid.uuid4().bytes).hexdigest()[:length]
    
    @staticmethod
    def sanitize_input(user_input: str) -> str:
        """تنظيف إدخال المستخدم من الهجمات"""
        # إزالة محاولات SQL injection
        user_input = re.sub(r'[\'\";]', '', user_input)
        # إزالة محاولات XSS
        user_input = re.sub(r'[<>]', '', user_input)
        return user_input.strip()

class PerformanceUtils:
    """أدوات قياس وتحسين الأداء"""
    
    @staticmethod
    def timer(func: Callable) -> Callable:
        """ديكوراتور لقياس وقت التنفيذ"""
        @wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()
            result = func(*args, **kwargs)
            end_time = time.time()
            execution_time = end_time - start_time
            
            logger = logging.getLogger('Performance')
            logger.info(f"⏱️ {func.__name__} - الوقت: {execution_time:.4f} ثانية")
            
            return result
        return wrapper
    
    @staticmethod
    @lru_cache(maxsize=128)
    def cached_function(func: Callable) -> Callable:
        """ديكوراتور للتخزين المؤقت للوظائف"""
        return func
    
    @staticmethod
    def get_system_usage() -> Dict[str, float]:
        """الحصول على استخدام النظام"""
        if not HAS_PSUTIL:
            return {}
        
        try:
            return {
                "cpu_percent": psutil.cpu_percent(interval=0.1),
                "memory_percent": psutil.virtual_memory().percent,
                "disk_percent": psutil.disk_usage('/').percent,
                "load_avg": psutil.getloadavg()[0] if hasattr(psutil, 'getloadavg') else 0
            }
        except:
            return {}

class FileUtils:
    """أدوات التعامل مع الملفات"""
    
    @staticmethod
    def read_file_safe(file_path: str, encoding: str = 'utf-8') -> Optional[str]:
        """قراءة ملف بشكل آمن"""
        try:
            path = Path(file_path)
            if path.exists() and path.is_file():
                return path.read_text(encoding=encoding)
            return None
        except Exception as e:
            logging.error(f"خطأ في قراءة الملف {file_path}: {e}")
            return None
    
    @staticmethod
    def write_file_safe(file_path: str, content: str, encoding: str = 'utf-8') -> bool:
        """كتابة ملف بشكل آمن"""
        try:
            path = Path(file_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding=encoding)
            return True
        except Exception as e:
            logging.error(f"خطأ في كتابة الملف {file_path}: {e}")
            return False
    
    @staticmethod
    def get_file_info(file_path: str) -> Dict[str, Any]:
        """الحصول على معلومات الملف"""
        try:
            path = Path(file_path)
            stat = path.stat()
            return {
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime),
                "created": datetime.fromtimestamp(stat.st_ctime),
                "extension": path.suffix.lower(),
                "is_file": path.is_file(),
                "is_dir": path.is_dir()
            }
        except:
            return {}

class NetworkUtils:
    """أدوات الشبكة"""
    
    @staticmethod
    def is_port_available(port: int, host: str = 'localhost') -> bool:
        """التحقق من توفر المنفذ"""
        import socket
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(1)
                return sock.connect_ex((host, port)) != 0
        except:
            return False
    
    @staticmethod
    def get_local_ip() -> str:
        """الحصول على IP المحلي"""
        import socket
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.connect(("8.8.8.8", 80))
                return sock.getsockname()[0]
        except:
            return "127.0.0.1"

class DataConversionUtils:
    """أدوات تحويل البيانات"""
    
    @staticmethod
    def dict_to_json_safe(data: Dict, indent: int = 2) -> Optional[str]:
        """تحويل القاموس إلى JSON بشكل آمن"""
        try:
            return json.dumps(data, ensure_ascii=False, indent=indent)
        except:
            return None
    
    @staticmethod
    def json_to_dict_safe(json_str: str) -> Optional[Dict]:
        """تحويل JSON إلى قاموس بشكل آمن"""
        try:
            return json.loads(json_str)
        except:
            return None
    
    @staticmethod
    def bytes_to_human_readable(size_bytes: int) -> str:
        """تحويل الحجم بايت إلى صيغة مقروءة"""
        if size_bytes == 0:
            return "0B"
        
        size_names = ["B", "KB", "MB", "GB", "TB"]
        i = 0
        while size_bytes >= 1024 and i < len(size_names) - 1:
            size_bytes /= 1024.0
            i += 1
        
        return f"{size_bytes:.2f} {size_names[i]}"

class AsyncUtils:
    """أدوات البرمجة غير المتزامنة"""
    
    def __init__(self, max_workers: int = 5):
        self.thread_pool = ThreadPoolExecutor(max_workers=max_workers)
    
    def run_in_thread(self, func: Callable, *args, **kwargs) -> Any:
        """تنفيذ دالة في خيط منفصل"""
        future = self.thread_pool.submit(func, *args, **kwargs)
        return future
    
    def run_parallel(self, tasks: List[Tuple[Callable, tuple, dict]]) -> List[Any]:
        """تنفيذ مهام متعددة بالتوازي"""
        futures = []
        for func, args, kwargs in tasks:
            future = self.thread_pool.submit(func, *args, **kwargs)
            futures.append(future)
        
        return [future.result() for future in futures]

# وظائف مختصرة للاستخدام السريع (Backward Compatibility)
def clean_text(text: str, **kwargs) -> str:
    """تنظيف النص (وظيفة مختصرة)"""
    return TextUtils.clean_text(text, **kwargs)

def detect_language(text: str) -> Dict[str, Any]:
    """كشف لغة النص (وظيفة مختصرة)"""
    return TextUtils.detect_language_advanced(text)

# تهيئة الأدوات
async_utils = AsyncUtils()
text_utils = TextUtils()
validation_utils = ValidationUtils()
security_utils = SecurityUtils()
performance_utils = PerformanceUtils()
file_utils = FileUtils()
network_utils = NetworkUtils()
conversion_utils = DataConversionUtils()

# إعداد التسجيل
def setup_logging(level=logging.INFO):
    """إعداد التسجيل"""
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('logs/utils.log', encoding='utf-8'),
            logging.StreamHandler()
        ]
    )

# مثال على الاستخدام
if __name__ == "__main__":
    setup_logging()
    
    # اختبار أدوات النص
    sample_text = "   مرحبا    بالعالم   !!   Hello   World   "
    print(f"📝 تنظيف النص: '{text_utils.clean_text(sample_text)}'")
    
    # اختبار كشف اللغة
    lang_info = text_utils.detect_language_advanced("مرحبا بالعالم Hello World")
    print(f"🌐 كشف اللغة: {lang_info}")
    
    # اختبار الأداء
    @performance_utils.timer
    def test_function():
        time.sleep(0.1)
        return "تم التنفيذ"
    
    result = test_function()
    print(f"⏱️ اختبار المؤقت: {result}")
    
    # اختبار النظام
    system_usage = performance_utils.get_system_usage()
    print(f"💻 استخدام النظام: {system_usage}")
    
    # اختبار التحويل
    size_readable = conversion_utils.bytes_to_human_readable(1024 * 1024 * 5)
    print(f"📊 تحويل الحجم: {size_readable}")