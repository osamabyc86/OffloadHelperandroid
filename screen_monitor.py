# screen_monitor.py - مراقبة الشاشة والتعلم منها بصمت
# Screen Monitor & Silent Learning System
# -*- coding: utf-8 -*-

import os
import sys
import time
import threading
import logging
import json
import hashlib
from datetime import datetime
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, asdict
from collections import deque
import hashlib

# محاولة استيراد المكتبات المطلوبة
try:
    import mss
    import mss.tools
    SCREEN_CAPTURE_AVAILABLE = True
except ImportError:
    SCREEN_CAPTURE_AVAILABLE = False
    print("⚠️ mss غير مثبتة. قم بتثبيتها: pip install mss")

try:
    import pytesseract
    from PIL import Image
    import numpy as np
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False
    print("⚠️ pytesseract أو PIL غير مثبتة. قم بتثبيتها: pip install pytesseract pillow")

try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False
    print("⚠️ opencv-python غير مثبت. قم بتثبيته: pip install opencv-python")

try:
    from difflib import SequenceMatcher
    import re
    STANDARD_LIBS = True
except ImportError:
    STANDARD_LIBS = False

# إعداد التسجيل
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - ScreenMonitor - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("screen_monitor.log", encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


@dataclass
class ScreenContent:
    """معلومات عن محتوى الشاشة"""
    timestamp: str
    text_content: str
    window_title: str
    region: tuple
    hash: str
    word_count: int
    detected_language: str
    confidence: float


@dataclass
class LearnedPattern:
    """نمط تم تعلمه من الشاشة"""
    pattern_id: str
    content: str
    context: str
    frequency: int
    last_seen: str
    first_seen: str
    importance_score: float
    tags: List[str]


class ScreenRegion:
    """مناطق مختلفة على الشاشة"""
    
    FULL_SCREEN = "full_screen"
    TOP_BAR = "top_bar"
    BOTTOM_BAR = "bottom_bar"
    LEFT_SIDE = "left_side"
    RIGHT_SIDE = "right_side"
    CENTER = "center"
    
    # مناطق مخصصة للتطبيقات الشائعة
    CHROME_ADDRESS_BAR = "chrome_address_bar"
    VS_CODE_EDITOR = "vscode_editor"
    TERMINAL = "terminal"
    BROWSER_CONTENT = "browser_content"
    
    @classmethod
    def get_all_regions(cls):
        """الحصول على جميع المناطق"""
        return [
            cls.FULL_SCREEN,
            cls.TOP_BAR,
            cls.BOTTOM_BAR,
            cls.LEFT_SIDE,
            cls.RIGHT_SIDE,
            cls.CENTER
        ]


class ScreenMonitor:
    """
    نظام مراقبة الشاشة والتعلم منها بصمت
    """
    
    def __init__(self, 
                 monitor_interval: float = 5.0,
                 capture_full_screen: bool = True,
                 capture_regions: bool = True,
                 enable_ocr: bool = True,
                 enable_learning: bool = True,
                 save_screenshots: bool = False,
                 screenshots_dir: str = "screen_captures",
                 memory_file: str = "screen_memory.json",
                 max_memory_size: int = 1000,
                 similarity_threshold: float = 0.8):
        """
        تهيئة نظام مراقبة الشاشة
        
        Args:
            monitor_interval: الفاصل الزمني بين كل مراقبة (بالثواني)
            capture_full_screen: هل نلتقط الشاشة كاملة
            capture_regions: هل نلتقط مناطق محددة
            enable_ocr: هل نستخدم OCR لاستخراج النص
            enable_learning: هل نتعلم من المحتوى
            save_screenshots: هل نحفظ لقطات الشاشة
            screenshots_dir: مجلد حفظ اللقطات
            memory_file: ملف حفظ الذاكرة
            max_memory_size: الحد الأقصى لحجم الذاكرة
            similarity_threshold: عتبة التشابه للتعرف على المحتوى المكرر
        """
        self.monitor_interval = monitor_interval
        self.capture_full_screen = capture_full_screen
        self.capture_regions = capture_regions
        self.enable_ocr = enable_ocr
        self.enable_learning = enable_learning
        self.save_screenshots = save_screenshots
        self.screenshots_dir = screenshots_dir
        self.memory_file = memory_file
        self.max_memory_size = max_memory_size
        self.similarity_threshold = similarity_threshold
        
        # حالة النظام
        self.is_running = False
        self.monitor_thread = None
        
        # الذاكرة والتاريخ
        self.screen_history: deque = deque(maxlen=100)  # آخر 100 لقطة
        self.learned_patterns: Dict[str, LearnedPattern] = {}
        self.knowledge_base: Dict[str, Any] = {}
        
        # الإحصائيات
        self.stats = {
            "total_captures": 0,
            "unique_contents": 0,
            "patterns_learned": 0,
            "last_capture": None,
            "ocr_success_rate": 0,
            "total_ocr_attempts": 0,
            "total_ocr_successes": 0
        }
        
        # تحقق من توفر المكتبات
        self.ocr_available = OCR_AVAILABLE and self.enable_ocr
        self.screenshot_available = SCREEN_CAPTURE_AVAILABLE
        self.cv2_available = CV2_AVAILABLE
        
        # إنشاء مجلد للحفظ إذا لزم الأمر
        if self.save_screenshots and not os.path.exists(screenshots_dir):
            os.makedirs(screenshots_dir)
        
        # تحميل الذاكرة السابقة
        self._load_memory()
        
        # تهيئة أدوات إضافية
        self._setup_ocr_config()
        
        logger.info(f"✅ تم تهيئة نظام مراقبة الشاشة (الفاصل: {monitor_interval} ثانية)")
        logger.info(f"   OCR: {self.ocr_available}, التعلم: {self.enable_learning}")
    
    def _setup_ocr_config(self):
        """تهيئة إعدادات OCR"""
        if self.ocr_available:
            # محاولة تعيين مسار tesseract إذا كان في موقع مختلف
            possible_paths = [
                r'C:\Program Files\Tesseract-OCR\tesseract.exe',
                r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe',
                '/usr/bin/tesseract',
                '/usr/local/bin/tesseract'
            ]
            
            for path in possible_paths:
                if os.path.exists(path):
                    pytesseract.pytesseract.tesseract_cmd = path
                    logger.info(f"✅ تم تحديد مسار Tesseract: {path}")
                    break
            
            # إعدادات OCR
            self.ocr_config = {
                'lang': 'ara+eng',  # العربية والإنجليزية
                'config': '--oem 3 --psm 6'
            }
    
    def start_monitoring(self):
        """بدء مراقبة الشاشة"""
        if self.is_running:
            logger.warning("⚠️ نظام المراقبة يعمل بالفعل")
            return
        
        self.is_running = True
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()
        logger.info("🚀 بدء مراقبة الشاشة...")
    
    def stop_monitoring(self):
        """إيقاف مراقبة الشاشة"""
        self.is_running = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=5)
        self._save_memory()
        logger.info("🛑 إيقاف مراقبة الشاشة")
    
    def _monitor_loop(self):
        """حلقة المراقبة الرئيسية"""
        while self.is_running:
            try:
                self.capture_and_learn()
                time.sleep(self.monitor_interval)
            except Exception as e:
                logger.error(f"❌ خطأ في حلقة المراقبة: {e}")
                time.sleep(1)
    
    def capture_and_learn(self) -> Optional[ScreenContent]:
        """
        التقاط الشاشة والتعلم منها
        
        Returns:
            ScreenContent: المحتوى المستخرج أو None في حالة الفشل
        """
        if not self.screenshot_available:
            logger.warning("⚠️ أداة التقاط الشاشة غير متاحة")
            return None
        
        try:
            start_time = time.time()
            
            # التقاط الشاشة
            screenshot = self._capture_screen()
            if screenshot is None:
                return None
            
            # استخراج النص إذا أمكن
            text_content = ""
            confidence = 0.0
            
            if self.ocr_available:
                text_content, confidence = self._extract_text_from_image(screenshot)
                self.stats["total_ocr_attempts"] += 1
                if text_content and len(text_content) > 10:
                    self.stats["total_ocr_successes"] += 1
            
            # حساب هاش المحتوى
            content_hash = hashlib.md5(text_content.encode('utf-8') if text_content else str(time.time()).encode()).hexdigest()
            
            # إنشاء كائن المحتوى
            screen_content = ScreenContent(
                timestamp=datetime.now().isoformat(),
                text_content=text_content[:5000] if text_content else "",  # حد أقصى 5000 حرف
                window_title=self._get_active_window_title(),
                region=(0, 0, 0, 0),  # سيتم تحديثه لاحقاً
                hash=content_hash,
                word_count=len(text_content.split()) if text_content else 0,
                detected_language=self._detect_language(text_content) if text_content else "unknown",
                confidence=confidence
            )
            
            # حفظ في التاريخ
            self.screen_history.append(screen_content)
            self.stats["total_captures"] += 1
            self.stats["last_capture"] = screen_content.timestamp
            
            # حفظ لقطة الشاشة إذا كان مطلوباً
            if self.save_screenshots and text_content and len(text_content) > 50:
                self._save_screenshot(screenshot, content_hash)
            
            # التعلم من المحتوى
            if self.enable_learning and text_content and len(text_content) > 20:
                self._learn_from_content(screen_content)
            
            # تحديث إحصائيات OCR
            if self.stats["total_ocr_attempts"] > 0:
                self.stats["ocr_success_rate"] = (
                    self.stats["total_ocr_successes"] / self.stats["total_ocr_attempts"] * 100
                )
            
            processing_time = time.time() - start_time
            if text_content and len(text_content) > 10:
                logger.info(f"📸 تم التقاط: {screen_content.word_count} كلمة (وقت: {processing_time:.2f}ث)")
            
            return screen_content
            
        except Exception as e:
            logger.error(f"❌ خطأ في capture_and_learn: {e}")
            return None
    
    def _capture_screen(self):
        """التقاط الشاشة باستخدام mss"""
        try:
            with mss.mss() as sct:
                # التقاط الشاشة الأساسية
                monitor = sct.monitors[1]  # الشاشة الرئيسية
                screenshot = sct.grab(monitor)
                
                # تحويل إلى PIL Image
                from PIL import Image
                img = Image.frombytes("RGB", screenshot.size, screenshot.rgb)
                
                return img
        except Exception as e:
            logger.error(f"❌ خطأ في التقاط الشاشة: {e}")
            return None
    
    def _extract_text_from_image(self, image):
        """
        استخراج النص من الصورة باستخدام OCR
        
        Returns:
            tuple: (text, confidence)
        """
        try:
            # تحسين الصورة لـ OCR
            processed_image = self._preprocess_image_for_ocr(image)
            
            # استخراج النص
            text = pytesseract.image_to_string(
                processed_image, 
                lang=self.ocr_config['lang'],
                config=self.ocr_config['config']
            )
            
            # تنظيف النص
            text = self._clean_ocr_text(text)
            
            # حساب درجة الثقة (تقديرية)
            confidence = self._calculate_ocr_confidence(text, processed_image)
            
            return text, confidence
            
        except Exception as e:
            logger.error(f"❌ خطأ في OCR: {e}")
            return "", 0.0
    
    def _preprocess_image_for_ocr(self, image):
        """تحسين الصورة لـ OCR"""
        try:
            if self.cv2_available:
                # تحويل PIL إلى numpy array
                import cv2
                import numpy as np
                
                img_np = np.array(image)
                
                # تحويل إلى grayscale
                gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
                
                # تطبيق thresholding
                _, thresh = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)
                
                # إزالة الضوضاء
                denoised = cv2.medianBlur(thresh, 3)
                
                # تحويل مرة أخرى إلى PIL Image
                from PIL import Image
                return Image.fromarray(denoised)
            else:
                return image
        except Exception as e:
            logger.debug(f"تحسين الصورة فشل: {e}")
            return image
    
    def _clean_ocr_text(self, text: str) -> str:
        """تنظيف النص المستخرج من OCR"""
        if not text:
            return ""
        
        # إزالة المسافات الزائدة
        text = re.sub(r'\s+', ' ', text)
        
        # إزالة الأحرف غير المرغوب فيها
        text = re.sub(r'[^\w\s\.\,\!\?\-\:\؛\،\؟\u0600-\u06FF]', '', text)
        
        # إزالة الأسطر الفارغة
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        text = '\n'.join(lines)
        
        return text.strip()
    
    def _calculate_ocr_confidence(self, text: str, image) -> float:
        """حساب درجة الثقة في نتائج OCR"""
        if not text or len(text) < 5:
            return 0.0
        
        # معايير التقييم
        score = 0.0
        
        # طول النص
        if len(text) > 100:
            score += 0.3
        elif len(text) > 50:
            score += 0.2
        elif len(text) > 10:
            score += 0.1
        
        # وجود كلمات عربية
        arabic_pattern = re.compile(r'[\u0600-\u06FF]')
        arabic_chars = len(arabic_pattern.findall(text))
        if arabic_chars > 0:
            score += 0.3
        
        # وجود كلمات إنجليزية
        english_words = len(re.findall(r'[a-zA-Z]{3,}', text))
        if english_words > 5:
            score += 0.2
        
        # متوسط طول الكلمات
        words = text.split()
        if words:
            avg_word_len = sum(len(w) for w in words) / len(words)
            if avg_word_len > 3:
                score += 0.2
        
        return min(score, 1.0)
    
    def _detect_language(self, text: str) -> str:
        """كشف لغة النص"""
        if not text:
            return "unknown"
        
        # فحص الحروف العربية
        arabic_pattern = re.compile(r'[\u0600-\u06FF]')
        arabic_ratio = len(arabic_pattern.findall(text)) / len(text) if text else 0
        
        if arabic_ratio > 0.3:
            return "arabic"
        elif arabic_ratio > 0.1:
            return "mixed"
        else:
            return "english"
    
    def _get_active_window_title(self) -> str:
        """الحصول على عنوان النافذة النشطة"""
        try:
            if sys.platform == "win32":
                import ctypes
                from ctypes import wintypes
                
                user32 = ctypes.windll.user32
                GetForegroundWindow = user32.GetForegroundWindow
                GetWindowTextLengthW = user32.GetWindowTextLengthW
                GetWindowTextW = user32.GetWindowTextW
                
                hwnd = GetForegroundWindow()
                length = GetWindowTextLengthW(hwnd)
                
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    GetWindowTextW(hwnd, buff, length + 1)
                    return buff.value
            elif sys.platform == "darwin":  # macOS
                import subprocess
                result = subprocess.run(
                    ['osascript', '-e', 'tell application "System Events" to get name of first application process whose frontmost is true'],
                    capture_output=True, text=True
                )
                if result.returncode == 0:
                    return result.stdout.strip()
            else:  # Linux
                import subprocess
                result = subprocess.run(
                    ['xdotool', 'getwindowfocus', 'getwindowname'],
                    capture_output=True, text=True
                )
                if result.returncode == 0:
                    return result.stdout.strip()
        except Exception as e:
            logger.debug(f"فشل الحصول على عنوان النافذة: {e}")
        
        return "unknown"
    
    def _save_screenshot(self, image, content_hash: str):
        """حفظ لقطة الشاشة"""
        try:
            filename = f"{content_hash[:16]}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            filepath = os.path.join(self.screenshots_dir, filename)
            image.save(filepath, "PNG")
            logger.debug(f"💾 تم حفظ لقطة الشاشة: {filename}")
        except Exception as e:
            logger.error(f"❌ فشل حفظ لقطة الشاشة: {e}")
    
    def _learn_from_content(self, content: ScreenContent):
        """التعلم من محتوى الشاشة"""
        if not content.text_content or len(content.text_content) < 20:
            return
        
        # استخراج الأنماط والمعلومات
        patterns = self._extract_patterns(content)
        
        # استخراج الكلمات المفتاحية
        keywords = self._extract_keywords(content.text_content)
        
        # استخراج الروابط إن وجدت
        links = self._extract_links(content.text_content)
        
        # استخراج الأكواد البرمجية إن وجدت
        code_blocks = self._extract_code_blocks(content.text_content)
        
        # تحديث قاعدة المعرفة
        for pattern in patterns:
            self._update_learned_pattern(pattern, content)
        
        # حفظ المعلومات المستخرجة
        knowledge_entry = {
            "timestamp": content.timestamp,
            "window_title": content.window_title,
            "keywords": keywords,
            "links": links,
            "code_blocks": code_blocks,
            "text_preview": content.text_content[:500],
            "word_count": content.word_count
        }
        
        # حفظ في قاعدة المعرفة
        entry_id = content.hash[:16]
        self.knowledge_base[entry_id] = knowledge_entry
        
        # تحديث الإحصائيات
        if len(self.knowledge_base) > self.stats["unique_contents"]:
            self.stats["unique_contents"] = len(self.knowledge_base)
        
        # تنظيف قاعدة المعرفة إذا كبرت
        self._cleanup_knowledge_base()
        
        logger.info(f"🧠 تم التعلم: {len(keywords)} كلمة مفتاحية, {len(links)} رابط, {len(code_blocks)} مقطع برمجي")
    
    def _extract_patterns(self, content: ScreenContent) -> List[str]:
        """استخراج الأنماط المتكررة من المحتوى"""
        patterns = []
        text = content.text_content
        
        # أنماط الأرقام
        number_patterns = re.findall(r'\b\d{3,}\b', text)
        if number_patterns:
            patterns.extend(number_patterns[:5])
        
        # أنماط البريد الإلكتروني
        email_patterns = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', text)
        if email_patterns:
            patterns.extend(email_patterns)
        
        # أنماط التاريخ
        date_patterns = re.findall(r'\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}', text)
        if date_patterns:
            patterns.extend(date_patterns)
        
        return patterns
    
    def _extract_keywords(self, text: str) -> List[str]:
        """استخراج الكلمات المفتاحية من النص"""
        # قائمة الكلمات الشائعة للتجاهل
        stop_words = {'ال', 'و', 'في', 'من', 'إلى', 'على', 'عن', 'مع', 'هذا', 'هذه', 
                      'ذلك', 'تلك', 'كان', 'كانت', 'يكون', 'تكون', 'أو', 'ثم', 'بعد',
                      'قبل', 'حيث', 'بين', 'كل', 'بعض', 'نفس', 'حتى', 'عند', 'لقد',
                      'قد', 'ربما', 'لذلك', 'لأن', 'لكن', 'ومع', 'هو', 'هي', 'هم'}
        
        # تنظيف النص
        text = text.lower()
        
        # استخراج الكلمات
        words = re.findall(r'[\w\u0600-\u06FF]{4,}', text)
        
        # تصفية الكلمات المفتاحية
        keywords = []
        for word in words:
            if word not in stop_words and len(word) > 2:
                keywords.append(word)
        
        # إزالة التكرارات والحفاظ على الترتيب
        seen = set()
        unique_keywords = []
        for kw in keywords:
            if kw not in seen:
                seen.add(kw)
                unique_keywords.append(kw)
        
        return unique_keywords[:20]  # حد أقصى 20 كلمة مفتاحية
    
    def _extract_links(self, text: str) -> List[str]:
        """استخراج الروابط من النص"""
        link_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
        links = re.findall(link_pattern, text)
        return list(set(links))  # إزالة التكرارات
    
    def _extract_code_blocks(self, text: str) -> List[str]:
        """استخراج مقاطع برمجية من النص"""
        code_blocks = []
        
        # أنماط الأكواد الشائعة
        code_patterns = [
            r'```[\s\S]*?```',  # كتل markdown
            r'def\s+\w+\([^)]*\)\s*:',  # دوال Python
            r'function\s+\w+\s*\([^)]*\)\s*\{',  # دوال JavaScript
            r'class\s+\w+',  # كلاسات
            r'import\s+\w+',  # import statements
            r'from\s+\w+\s+import',  # from import
            r'console\.log\([^)]+\)',  # console.log
            r'print\([^)]+\)',  # print statements
            r'if\s*\([^)]+\)\s*\{',  # if statements
            r'for\s*\([^)]+\)\s*\{',  # for loops
            r'while\s*\([^)]+\)\s*\{',  # while loops
        ]
        
        for pattern in code_patterns:
            matches = re.findall(pattern, text, re.MULTILINE)
            if matches:
                code_blocks.extend(matches)
        
        return code_blocks[:10]  # حد أقصى 10 مقاطع
    
    def _update_learned_pattern(self, pattern: str, content: ScreenContent):
        """تحديث النمط المتعلم"""
        pattern_id = hashlib.md5(pattern.encode()).hexdigest()[:16]
        
        if pattern_id in self.learned_patterns:
            # تحديث النمط الموجود
            existing = self.learned_patterns[pattern_id]
            existing.frequency += 1
            existing.last_seen = content.timestamp
            existing.importance_score = min(existing.importance_score + 0.1, 1.0)
        else:
            # إضافة نمط جديد
            self.learned_patterns[pattern_id] = LearnedPattern(
                pattern_id=pattern_id,
                content=pattern[:200],
                context=content.window_title,
                frequency=1,
                last_seen=content.timestamp,
                first_seen=content.timestamp,
                importance_score=0.3,
                tags=self._generate_tags(pattern)
            )
            self.stats["patterns_learned"] += 1
    
    def _generate_tags(self, text: str) -> List[str]:
        """توليد علامات للنص"""
        tags = []
        
        # علامات بناءً على المحتوى
        if re.search(r'https?://', text):
            tags.append("link")
        if re.search(r'@\w+', text):
            tags.append("mention")
        if re.search(r'\d{3,}', text):
            tags.append("numbers")
        if re.search(r'[\u0600-\u06FF]', text):
            tags.append("arabic")
        if re.search(r'[a-zA-Z]', text):
            tags.append("english")
        if re.search(r'def\s+\w+|function\s+\w+', text):
            tags.append("code")
        
        return tags
    
    def _cleanup_knowledge_base(self):
        """تنظيف قاعدة المعرفة من المدخلات القديمة"""
        if len(self.knowledge_base) > self.max_memory_size:
            # حذف أقدم 20% من المدخلات
            items_to_remove = int(self.max_memory_size * 0.2)
            sorted_items = sorted(
                self.knowledge_base.items(),
                key=lambda x: x[1].get('timestamp', '')
            )
            for key, _ in sorted_items[:items_to_remove]:
                del self.knowledge_base[key]
            logger.info(f"🧹 تم تنظيف قاعدة المعرفة: حذف {items_to_remove} مدخل قديم")
    
    def _load_memory(self):
        """تحميل الذاكرة من ملف"""
        if os.path.exists(self.memory_file):
            try:
                with open(self.memory_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # استعادة الأنماط المتعلمة
                    patterns_data = data.get('learned_patterns', {})
                    for pid, pdata in patterns_data.items():
                        self.learned_patterns[pid] = LearnedPattern(**pdata)
                    
                    # استعادة قاعدة المعرفة
                    self.knowledge_base = data.get('knowledge_base', {})
                    
                    # استعادة الإحصائيات
                    self.stats = data.get('stats', self.stats)
                    
                    logger.info(f"📂 تم تحميل الذاكرة: {len(self.learned_patterns)} نمط, {len(self.knowledge_base)} مدخل")
            except Exception as e:
                logger.error(f"❌ فشل تحميل الذاكرة: {e}")
    
    def _save_memory(self):
        """حفظ الذاكرة إلى ملف"""
        try:
            data = {
                'learned_patterns': {pid: asdict(p) for pid, p in self.learned_patterns.items()},
                'knowledge_base': self.knowledge_base,
                'stats': self.stats,
                'saved_at': datetime.now().isoformat()
            }
            with open(self.memory_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info(f"💾 تم حفظ الذاكرة: {len(self.learned_patterns)} نمط")
        except Exception as e:
            logger.error(f"❌ فشل حفظ الذاكرة: {e}")
    
    def get_knowledge_summary(self) -> Dict:
        """الحصول على ملخص المعرفة المكتسبة"""
        return {
            "total_captures": self.stats["total_captures"],
            "unique_contents": self.stats["unique_contents"],
            "patterns_learned": self.stats["patterns_learned"],
            "ocr_success_rate": self.stats["ocr_success_rate"],
            "memory_size": len(self.knowledge_base),
            "recent_captures": len(self.screen_history),
            "learned_patterns_summary": [
                {
                    "id": p.pattern_id,
                    "content": p.content[:50],
                    "frequency": p.frequency,
                    "importance": p.importance_score
                }
                for p in list(self.learned_patterns.values())[:10]
            ]
        }
    
    def search_knowledge(self, query: str) -> List[Dict]:
        """البحث في المعرفة المكتسبة"""
        results = []
        query_lower = query.lower()
        
        for entry_id, entry in self.knowledge_base.items():
            # البحث في النص
            text_preview = entry.get('text_preview', '').lower()
            if query_lower in text_preview:
                results.append({
                    "id": entry_id,
                    "timestamp": entry.get('timestamp'),
                    "window_title": entry.get('window_title'),
                    "text_preview": entry.get('text_preview', '')[:200],
                    "keywords": entry.get('keywords', [])[:5],
                    "score": 1.0
                })
                continue
            
            # البحث في الكلمات المفتاحية
            keywords = entry.get('keywords', [])
            for keyword in keywords:
                if query_lower in keyword.lower():
                    results.append({
                        "id": entry_id,
                        "timestamp": entry.get('timestamp'),
                        "window_title": entry.get('window_title'),
                        "text_preview": entry.get('text_preview', '')[:200],
                        "matched_keyword": keyword,
                        "score": 0.8
                    })
                    break
        
        # ترتيب النتائج حسب التاريخ
        results.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        return results[:20]
    
    def get_frequent_patterns(self, min_frequency: int = 3) -> List[LearnedPattern]:
        """الحصول على الأنماط المتكررة"""
        return [
            p for p in self.learned_patterns.values()
            if p.frequency >= min_frequency
        ]
    
    def get_window_statistics(self) -> Dict:
        """إحصائيات حسب النوافذ"""
        window_stats = {}
        for entry in self.knowledge_base.values():
            window = entry.get('window_title', 'unknown')
            if window not in window_stats:
                window_stats[window] = 0
            window_stats[window] += 1
        
        return dict(sorted(window_stats.items(), key=lambda x: x[1], reverse=True)[:10])


# ===== نظام التكامل مع Brain =====
class ScreenMonitorIntegration:
    """
    تكامل مراقبة الشاشة مع نظام Brain الرئيسي
    """
    
    def __init__(self, brain_instance=None):
        self.brain = brain_instance
        self.monitor = None
        self.is_active = False
        self._setup_monitor()
    
    def _setup_monitor(self):
        """إعداد نظام المراقبة"""
        try:
            self.monitor = ScreenMonitor(
                monitor_interval=10.0,  # كل 10 ثواني
                capture_full_screen=True,
                capture_regions=False,
                enable_ocr=True,
                enable_learning=True,
                save_screenshots=False,  # لا نحفظ اللقطات لتوفير المساحة
                memory_file="screen_knowledge.json"
            )
            logger.info("✅ تم تهيئة تكامل مراقبة الشاشة")
        except Exception as e:
            logger.error(f"❌ فشل تهيئة تكامل مراقبة الشاشة: {e}")
    
    def start(self):
        """بدء المراقبة"""
        if self.monitor:
            self.monitor.start_monitoring()
            self.is_active = True
            logger.info("🚀 بدء مراقبة الشاشة (تعلم بصمت)")
    
    def stop(self):
        """إيقاف المراقبة"""
        if self.monitor:
            self.monitor.stop_monitoring()
            self.is_active = False
            logger.info("🛑 إيقاف مراقبة الشاشة")
    
    def get_status(self) -> Dict:
        """الحالة الحالية للنظام"""
        if self.monitor:
            return {
                "active": self.is_active,
                "knowledge_summary": self.monitor.get_knowledge_summary(),
                "window_stats": self.monitor.get_window_statistics(),
                "frequent_patterns_count": len(self.monitor.get_frequent_patterns())
            }
        return {"active": False, "error": "النظام غير مهيأ"}
    
    def search_screen_knowledge(self, query: str) -> List[Dict]:
        """البحث في المعرفة المكتسبة من الشاشة"""
        if self.monitor:
            return self.monitor.search_knowledge(query)
        return []
    
    def get_learned_insights(self) -> str:
        """الحصول على insights من التعلم"""
        if not self.monitor:
            return "نظام المراقبة غير متاح"
        
        summary = self.monitor.get_knowledge_summary()
        frequent = self.monitor.get_frequent_patterns(min_frequency=3)
        window_stats = self.monitor.get_window_statistics()
        
        insights = []
        insights.append(f"📊 إحصائيات المراقبة:")
        insights.append(f"   • عدد اللقطات: {summary['total_captures']}")
        insights.append(f"   • محتوى فريد: {summary['unique_contents']}")
        insights.append(f"   • أنماط متعلمة: {summary['patterns_learned']}")
        insights.append(f"   • دقة OCR: {summary['ocr_success_rate']:.1f}%")
        
        if frequent:
            insights.append(f"\n🔄 الأنماط المتكررة (الأهم):")
            for p in frequent[:5]:
                insights.append(f"   • {p.content[:50]}... (تكرار: {p.frequency})")
        
        if window_stats:
            insights.append(f"\n🪟 النوافذ الأكثر مراقبة:")
            for window, count in list(window_stats.items())[:5]:
                insights.append(f"   • {window[:40]}: {count} مرة")
        
        return "\n".join(insights)


# ===== دوال مساعدة للاستخدام السريع =====

_screen_monitor_integration = None

def init_screen_monitoring(brain_instance=None):
    """تهيئة نظام مراقبة الشاشة"""
    global _screen_monitor_integration
    _screen_monitor_integration = ScreenMonitorIntegration(brain_instance)
    return _screen_monitor_integration

def start_screen_monitoring():
    """بدء مراقبة الشاشة"""
    if _screen_monitor_integration:
        _screen_monitor_integration.start()
        return True
    return False

def stop_screen_monitoring():
    """إيقاف مراقبة الشاشة"""
    if _screen_monitor_integration:
        _screen_monitor_integration.stop()
        return True
    return False

def get_screen_insights():
    """الحصول على insights من الشاشة"""
    if _screen_monitor_integration:
        return _screen_monitor_integration.get_learned_insights()
    return "نظام مراقبة الشاشة غير مهيأ"

def search_screen_memory(query: str):
    """البحث في ذاكرة الشاشة"""
    if _screen_monitor_integration:
        return _screen_monitor_integration.search_screen_knowledge(query)
    return []


# ===== تشغيل مستقل للاختبار =====
def main():
    """تشغيل مستقل لاختبار النظام"""
    print("🧠 Screen Monitor - نظام مراقبة الشاشة والتعلم منها بصمت")
    print("=" * 60)
    
    # التحقق من المتطلبات
    if not SCREEN_CAPTURE_AVAILABLE:
        print("❌ mss غير مثبتة. قم بتثبيتها: pip install mss")
        return
    
    if not OCR_AVAILABLE:
        print("⚠️ OCR غير متاح. قم بتثبيت pytesseract و tesseract-OCR")
    
    print("✅ بدء تشغيل نظام المراقبة...")
    
    # تهيئة النظام
    monitor = ScreenMonitor(
        monitor_interval=5.0,
        capture_full_screen=True,
        enable_ocr=True,
        enable_learning=True,
        save_screenshots=False
    )
    
    # بدء المراقبة
    monitor.start_monitoring()
    
    print("\n📊 نظام المراقبة يعمل الآن...")
    print("   (اضغط Ctrl+C للإيقاف)")
    print("   سيتعلم النظام بصمت من كل ما يظهر على شاشتك\n")
    
    try:
        # عرض إحصائيات كل 30 ثانية
        while True:
            time.sleep(30)
            summary = monitor.get_knowledge_summary()
            print(f"\n📈 [التحديث التلقائي]")
            print(f"   لقطات: {summary['total_captures']}")
            print(f"   محتوى فريد: {summary['unique_contents']}")
            print(f"   أنماط متعلمة: {summary['patterns_learned']}")
            print(f"   دقة OCR: {summary['ocr_success_rate']:.1f}%")
            
            # عرض أكثر الأنماط تكراراً
            frequent = monitor.get_frequent_patterns(min_frequency=2)
            if frequent:
                print(f"   الأنماط المتكررة: {len(frequent)}")
    
    except KeyboardInterrupt:
        print("\n\n🛑 إيقاف النظام...")
        monitor.stop_monitoring()
        print("✅ تم الإيقاف بنجاح")


if __name__ == "__main__":
    main()