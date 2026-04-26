#!/usr/bin/env python3
# your_tasks.py - نظام المهام الموحد المحسّن للنظام الموزع

import math
import numpy as np
import time
import logging
from typing import List, Dict, Any, Optional, Union
from functools import wraps
from dataclasses import dataclass
from enum import Enum

try:
    from offload_lib import offload
    HAS_OFFLOAD = True
except ImportError:
    HAS_OFFLOAD = False
    print("⚠️ تحذير: offload_lib غير متوفر - استخدام الوضع المحلي")

try:
    from peer_discovery import PORT
except ImportError:
    PORT = 7521  # منفذ افتراضي

class TaskPriority(Enum):
    LOW = "low"
    NORMAL = "normal" 
    HIGH = "high"
    CRITICAL = "critical"

class ExecutionMode(Enum):
    AUTO = "auto"
    LOCAL = "local"
    DISTRIBUTED = "distributed"

@dataclass
class TaskConfig:
    """تهيئة المهمة"""
    timeout: float = 30.0
    priority: TaskPriority = TaskPriority.NORMAL
    max_retries: int = 2
    execution_mode: ExecutionMode = ExecutionMode.AUTO

def safe_offload(func):
    """ديكوراتور آمن لنقل المهام مع fallback"""
    if not HAS_OFFLOAD:
        return func  # العودة للدالة الأصلية إذا لم يكن المكتبة متوفرة
    
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return offload(func)(*args, **kwargs)
        except Exception as e:
            logging.warning(f"فشل النقل للدالة {func.__name__}, التنفيذ محلياً: {e}")
            return func(*args, **kwargs)
    return wrapper

def validate_input(value, min_val, max_val, value_name: str):
    """التحقق من صحة المدخلات"""
    if value < min_val:
        raise ValueError(f"{value_name} يجب أن يكون على الأقل {min_val}")
    if value > max_val:
        raise ValueError(f"{value_name} يجب أن يكون على الأكثر {max_val}")

def setup_logging():
    """إعداد التسجيل"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('logs/your_tasks.log', encoding='utf-8'),
            logging.StreamHandler()
        ]
    )

# إعداد التسجيل
setup_logging()

# =============================================================================
# دوال الرياضيات والحسابات المحسنة
# =============================================================================

def optimized_prime_calculation(n: int) -> Dict[str, Any]:
    """
    حساب الأعداد الأولية باستخدام خوارزمية محسنة
    
    Args:
        n: الحد الأعلى للبحث
        
    Returns:
        dict: عدد وقائمة الأعداد الأولية
    """
    validate_input(n, 1, 10**7, "n")
    
    if n < 2:
        return {"count": 0, "primes": []}
    
    # استخدام غربال إراتوستينس المحسن
    sieve = [True] * (n + 1)
    sieve[0] = sieve[1] = False
    
    for i in range(2, int(math.sqrt(n)) + 1):
        if sieve[i]:
            sieve[i*i : n+1 : i] = [False] * len(sieve[i*i : n+1 : i])
    
    primes = [i for i, is_prime in enumerate(sieve) if is_prime]
    
    return {
        "count": len(primes),
        "primes": primes,
        "largest_prime": primes[-1] if primes else None,
        "calculation_method": "optimized_sieve"
    }

def optimized_matrix_multiply(size: int) -> Dict[str, Any]:
    """
    ضرب مصفوفات مع تحسينات الأداء
    
    Args:
        size: حجم المصفوفة (size × size)
        
    Returns:
        dict: نتيجة الضرب ومعلومات إضافية
    """
    validate_input(size, 1, 5000, "حجم المصفوفة")
    
    # استخدام أنواع بيانات موفرة للذاكرة
    A = np.random.rand(size, size).astype(np.float32)
    B = np.random.rand(size, size).astype(np.float32)
    
    start_time = time.time()
    result = np.dot(A, B)
    execution_time = time.time() - start_time
    
    return {
        "result": result.tolist(),
        "execution_time": execution_time,
        "matrix_size": size,
        "memory_usage_mb": round(result.nbytes / (1024 * 1024), 2),
        "data_type": "float32"
    }

def enhanced_data_processing(data_size: int) -> Dict[str, Any]:
    """
    معالجة بيانات متقدمة مع إحصائيات شاملة
    
    Args:
        data_size: حجم البيانات المراد معالجتها
        
    Returns:
        dict: إحصائيات وتحليلات البيانات
    """
    validate_input(data_size, 10, 10**8, "حجم البيانات")
    
    # توليد بيانات واقعية بأنماط مختلفة
    data = np.random.normal(0, 1, data_size)
    
    return {
        "data_size": data_size,
        "mean": float(np.mean(data)),
        "std_dev": float(np.std(data)),
        "variance": float(np.var(data)),
        "min": float(np.min(data)),
        "max": float(np.max(data)),
        "median": float(np.median(data)),
        "q1": float(np.percentile(data, 25)),
        "q3": float(np.percentile(data, 75)),
        "skewness": float(float(np.mean((data - np.mean(data))**3)) / (np.std(data)**3)) if np.std(data) > 0 else 0,
        "is_normal_distribution": abs(np.mean(data)) < 0.1 and abs(1 - np.std(data)) < 0.1
    }

# =============================================================================
# المهام القابلة للتوزيع المحسنة
# =============================================================================

@safe_offload
def distributed_matrix_multiply(size: int, config: TaskConfig = None) -> Dict[str, Any]:
    """
    ضرب مصفوفات قابل للتوزيع مع إدارة متقدمة
    
    Args:
        size: حجم المصفوفة
        config: تهيئة المهمة
        
    Returns:
        dict: نتيجة الضرب ومعلومات الأداء
    """
    return optimized_matrix_multiply(size)

@safe_offload
def distributed_prime_calculation(n: int, config: TaskConfig = None) -> Dict[str, Any]:
    """
    حساب الأعداد الأولية القابل للتوزيع
    
    Args:
        n: الحد الأعلى للبحث
        config: تهيئة المهمة
        
    Returns:
        dict: عدد وقائمة الأعداد الأولية
    """
    return optimized_prime_calculation(n)

@safe_offload
def distributed_data_processing(size: int, config: TaskConfig = None) -> Dict[str, Any]:
    """
    معالجة بيانات كبيرة قابلة للتوزيع
    
    Args:
        size: حجم البيانات
        config: تهيئة المهمة
        
    Returns:
        dict: إحصائيات وتحليلات البيانات
    """
    return enhanced_data_processing(size)

@safe_offload
def complex_mathematical_operation(x: int, config: TaskConfig = None) -> Dict[str, Any]:
    """
    عملية رياضية معقدة قابلة للتوزيع
    
    Args:
        x: معامل التعقيد
        config: تهيئة المهمة
        
    Returns:
        dict: نتيجة العملية ومعلومات الأداء
    """
    validate_input(x, 1, 10000, "معامل التعقيد")
    
    start_time = time.time()
    
    # عمليات رياضية متنوعة
    fibonacci = [0, 1]
    for i in range(2, min(x, 1000)):
        fibonacci.append(fibonacci[-1] + fibonacci[-2])
    
    factorial_result = math.factorial(min(x, 100))
    
    prime_check = optimized_prime_calculation(min(x * 10, 10000))
    
    execution_time = time.time() - start_time
    
    return {
        "fibonacci_sequence": fibonacci,
        "factorial_result": factorial_result,
        "primes_found": prime_check["count"],
        "execution_time": execution_time,
        "operations_performed": [
            "fibonacci_calculation",
            "factorial_computation", 
            "prime_detection"
        ]
    }

# =============================================================================
# مهام معالجة الفيديو المحسنة
# =============================================================================

@safe_offload
def video_format_conversion(duration_seconds: float, quality_level: int, 
                          input_format: str = "mp4", output_format: str = "avi",
                          config: TaskConfig = None) -> Dict[str, Any]:
    """
    تحويل صيغة الفيديو مع معالجة متقدمة
    
    Args:
        duration_seconds: مدة الفيديو بالثواني
        quality_level: مستوى الجودة (1-10)
        input_format: صيغة الإدخال
        output_format: صيغة الإخراج
        config: تهيئة المهمة
        
    Returns:
        dict: نتيجة التحويل ومعلومات الجودة
    """
    validate_input(duration_seconds, 1, 36000, "مدة الفيديو")  # حد أقصى 10 ساعات
    validate_input(quality_level, 1, 10, "مستوى الجودة")
    
    try:
        from video_processing import video_format_conversion as vfc
        return vfc(duration_seconds, quality_level, input_format, output_format)
    except ImportError:
        logging.warning("وحدة video_processing غير متوفرة - استخدام المحاكاة")
        return _simulate_video_conversion(duration_seconds, quality_level, input_format, output_format)

@safe_offload
def video_effects_processing(video_length: float, effects_count: int, 
                           resolution: str = "1080p", config: TaskConfig = None) -> Dict[str, Any]:
    """
    معالجة تأثيرات الفيديو مع خيارات متقدمة
    
    Args:
        video_length: طول الفيديو
        effects_count: عدد التأثيرات
        resolution: دقة الفيديو
        config: تهيئة المهمة
        
    Returns:
        dict: نتيجة المعالجة والتأثيرات المطبقة
    """
    validate_input(video_length, 1, 3600, "طول الفيديو")
    validate_input(effects_count, 1, 20, "عدد التأثيرات")
    
    try:
        from video_processing import video_effects_processing as vep
        return vep(video_length, effects_count, resolution)
    except ImportError:
        logging.warning("وحدة video_processing غير متوفرة - استخدام المحاكاة")
        return _simulate_video_effects(video_length, effects_count, resolution)

@safe_offload
def render_3d_scene(objects_count: int, resolution_width: int, resolution_height: int,
                   lighting_quality: str = "medium", texture_quality: str = "high",
                   config: TaskConfig = None) -> Dict[str, Any]:
    """
    رندر مشهد ثلاثي الأبعاد مع إعدادات متقدمة
    
    Args:
        objects_count: عدد الكائنات
        resolution_width: عرض الدقة
        resolution_height: ارتفاع الدقة
        lighting_quality: جودة الإضاءة
        texture_quality: جودة النسيج
        config: تهيئة المهمة
        
    Returns:
        dict: نتيجة الرندر ومعلومات الأداء
    """
    validate_input(objects_count, 1, 100000, "عدد الكائنات")
    validate_input(resolution_width, 100, 7680, "عرض الدقة")
    validate_input(resolution_height, 100, 4320, "ارتفاع الدقة")
    
    try:
        from video_processing import render_3d_scene as r3d
        return r3d(objects_count, resolution_width, resolution_height,
                  lighting_quality, texture_quality)
    except ImportError:
        logging.warning("وحدة video_processing غير متوفرة - استخدام المحاكاة")
        return _simulate_3d_render(objects_count, resolution_width, resolution_height,
                                 lighting_quality, texture_quality)

# =============================================================================
# محاكاة المهام (fallback عند عدم توفر الوحدات)
# =============================================================================

def _simulate_video_conversion(duration: float, quality: int, 
                             input_fmt: str, output_fmt: str) -> Dict[str, Any]:
    """محاكاة تحويل الفيديو"""
    processing_time = duration * quality * 0.05
    time.sleep(min(processing_time, 2))
    
    return {
        "status": "success",
        "operation": "format_conversion",
        "input_format": input_fmt,
        "output_format": output_fmt,
        "duration": duration,
        "quality": quality,
        "processing_time": processing_time,
        "estimated_size_mb": duration * quality * 0.3,
        "simulated": True
    }

def _simulate_video_effects(length: float, effects: int, resolution: str) -> Dict[str, Any]:
    """محاكاة تأثيرات الفيديو"""
    resolution_multiplier = {"480p": 1, "720p": 2, "1080p": 3, "4K": 5}
    multiplier = resolution_multiplier.get(resolution, 2)
    
    processing_time = length * effects * multiplier * 0.03
    time.sleep(min(processing_time, 2))
    
    available_effects = ["Color Correction", "Motion Blur", "Lens Flare", 
                        "Depth of Field", "Particle Effects", "Lighting"]
    
    return {
        "status": "success",
        "video_length": length,
        "effects_applied": available_effects[:effects],
        "resolution": resolution,
        "processing_time": processing_time,
        "simulated": True
    }

def _simulate_3d_render(objects: int, width: int, height: int, 
                       lighting: str, texture: str) -> Dict[str, Any]:
    """محاكاة الرندر ثلاثي الأبعاد"""
    complexity = objects * (width * height) / 1000000
    processing_time = complexity * 0.01
    time.sleep(min(processing_time, 3))
    
    fps = max(1, 60 - (complexity / 10))
    
    return {
        "status": "success",
        "objects_rendered": objects,
        "resolution": f"{width}x{height}",
        "estimated_fps": round(fps, 1),
        "complexity_score": round(complexity, 2),
        "processing_time": processing_time,
        "simulated": True
    }

# =============================================================================
# دوال مساعدة وإدارة المهام
# =============================================================================

def get_available_tasks() -> Dict[str, Dict[str, Any]]:
    """الحصول على قائمة بالمهام المتاحة"""
    tasks = {
        "distributed_matrix_multiply": {
            "description": "ضرب مصفوفات قابل للتوزيع",
            "parameters": ["size"],
            "complexity": "medium",
            "category": "mathematics"
        },
        "distributed_prime_calculation": {
            "description": "حساب الأعداد الأولية القابل للتوزيع", 
            "parameters": ["n"],
            "complexity": "high",
            "category": "mathematics"
        },
        "video_format_conversion": {
            "description": "تحويل صيغة الفيديو",
            "parameters": ["duration_seconds", "quality_level", "input_format", "output_format"],
            "complexity": "medium",
            "category": "video_processing"
        },
        "render_3d_scene": {
            "description": "رندر مشهد ثلاثي الأبعاد",
            "parameters": ["objects_count", "resolution_width", "resolution_height"],
            "complexity": "high", 
            "category": "3d_rendering"
        }
    }
    
    return tasks

def create_task_config(timeout: float = 30.0, priority: str = "normal",
                      max_retries: int = 2, execution_mode: str = "auto") -> TaskConfig:
    """إنشاء تهيئة مهمة"""
    return TaskConfig(
        timeout=timeout,
        priority=TaskPriority(priority),
        max_retries=max_retries,
        execution_mode=ExecutionMode(execution_mode)
    )

# =============================================================================
# اختبار الوظائف
# =============================================================================

def run_tasks_benchmark():
    """تشغيل اختبار أداء للمهام"""
    print("\n🧪 اختبار أداء المهام")
    print("=" * 50)
    
    tests = [
        ("حساب أولي سريع", lambda: distributed_prime_calculation(1000)),
        ("ضرب مصفوفات صغيرة", lambda: distributed_matrix_multiply(50)),
        ("معالجة بيانات", lambda: distributed_data_processing(10000)),
        ("تحويل فيديو", lambda: video_format_conversion(60, 5)),
        ("رندر مشهد", lambda: render_3d_scene(100, 1920, 1080))
    ]
    
    for name, task in tests:
        print(f"\n🔧 تشغيل: {name}")
        try:
            start_time = time.time()
            result = task()
            execution_time = time.time() - start_time
            
            status = "✅" if result.get("status") != "error" else "❌"
            print(f"{status} {name} - {execution_time:.2f}ثانية")
            
        except Exception as e:
            print(f"❌ فشل: {name} - {e}")

if __name__ == "__main__":
    # تشغيل الاختبار عند التنفيذ المباشر
    run_tasks_benchmark()
    
    # عرض المهام المتاحة
    tasks = get_available_tasks()
    print(f"\n📋 المهام المتاحة: {len(tasks)} مهمة")
    for name, info in tasks.items():
        print(f"  • {name}: {info['description']}")