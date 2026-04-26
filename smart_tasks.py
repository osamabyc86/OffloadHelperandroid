import math
import numpy as np
import time
import logging
from typing import Dict, List, Any, Optional
from peer_discovery import PORT

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False
    print("تحذير: psutil غير مثبت، بعض ميزات مراقبة الموارد لن تعمل")

# تكوين النقاط الحدية للموارد
RESOURCE_LIMITS = {
    "max_matrix_size": 1000,
    "max_data_size": 10**6,
    "max_iterations": 10000,
    "max_video_duration": 3600,  # ثانية
    "max_objects_3d": 10000,
    "max_prime_calculation": 1000000
}

# إعداد التسجيل
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('smart_tasks')

class ResourceMonitor:
    """مراقبة استخدام الموارد"""
    
    @staticmethod
    def check_memory_usage() -> float:
        """التحقق من استخدام الذاكرة"""
        if HAS_PSUTIL:
            return psutil.virtual_memory().percent
        return 0.0
    
    @staticmethod
    def check_cpu_usage() -> float:
        """التحقق من استخدام المعالج"""
        if HAS_PSUTIL:
            return psutil.cpu_percent(interval=0.1)
        return 0.0
    
    @staticmethod
    def should_reject_task(memory_threshold: float = 85, cpu_threshold: float = 90) -> bool:
        """تحديد ما إذا كان يجب رفض المهمة"""
        memory_usage = ResourceMonitor.check_memory_usage()
        cpu_usage = ResourceMonitor.check_cpu_usage()
        
        if memory_usage > memory_threshold or cpu_usage > cpu_threshold:
            logger.warning(f"ارتفاع استخدام الموارد: الذاكرة {memory_usage}%، المعالج {cpu_usage}%")
            return True
        return False
    
    @staticmethod
    def get_system_info() -> Dict[str, Any]:
        """الحصول على معلومات النظام"""
        if not HAS_PSUTIL:
            return {"error": "psutil غير متوفر"}
        
        return {
            "memory_usage_percent": psutil.virtual_memory().percent,
            "cpu_usage_percent": psutil.cpu_percent(interval=0.1),
            "available_memory_gb": round(psutil.virtual_memory().available / (1024**3), 2),
            "total_memory_gb": round(psutil.virtual_memory().total / (1024**3), 2)
        }

def log_performance(func):
    """ديكوراتور لتسجيل أداء المهام"""
    from functools import wraps
    
    @wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        start_memory = psutil.Process().memory_info().rss if HAS_PSUTIL else 0
        
        # التحقق من الموارد قبل التنفيذ
        if ResourceMonitor.should_reject_task():
            return {"error": "الخادم مشغول حالياً، حاول لاحقاً", "server_processed": False}
        
        try:
            result = func(*args, **kwargs)
            execution_time = time.time() - start_time
            end_memory = psutil.Process().memory_info().rss if HAS_PSUTIL else 0
            memory_used = end_memory - start_memory
            
            logger.info(f"الأداء - {func.__name__}: الوقت {execution_time:.2f}ثانية, الذاكرة {memory_used}بايت")
            
            if isinstance(result, dict):
                result["performance"] = {
                    "execution_time_seconds": round(execution_time, 3),
                    "memory_used_bytes": memory_used,
                    "memory_used_mb": round(memory_used / (1024**2), 2)
                }
            
            return result
            
        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(f"خطأ في {func.__name__}: {str(e)} - الوقت المنقضي: {execution_time:.2f}ثانية")
            return {"error": f"فشل المعالجة: {str(e)}", "server_processed": False}
    
    return wrapper

def validate_input(value, min_val: float, max_val: float, value_name: str) -> Optional[Dict[str, Any]]:
    """التحقق من صحة المدخلات"""
    if value < min_val:
        return {"error": f"{value_name} يجب أن يكون على الأقل {min_val}", "server_processed": False}
    if value > max_val:
        return {"error": f"{value_name} يجب أن يكون على الأكثر {max_val}", "server_processed": False}
    return None

@log_performance
def prime_calculation(n: int) -> Dict[str, Any]:
    """ترجع قائمة الأعداد الأوليّة حتى n مع عددها - محسنة"""
    # التحقق من المدخلات
    validation = validate_input(n, 1, RESOURCE_LIMITS["max_prime_calculation"], "n")
    if validation:
        return validation
    
    if n < 2:
        return {"count": 0, "primes": [], "server_processed": True}
    
    # استخدام غربال إراتوستينس المحسن
    sieve = [True] * (n + 1)
    sieve[0] = sieve[1] = False
    
    for i in range(2, int(math.sqrt(n)) + 1):
        if sieve[i]:
            # استخدام slicing للتحسين
            sieve[i*i : n+1 : i] = [False] * len(sieve[i*i : n+1 : i])
    
    primes = [i for i, is_prime in enumerate(sieve) if is_prime]
    return {"count": len(primes), "primes": primes, "server_processed": True}

@log_performance
def matrix_multiply(size: int) -> Dict[str, Any]:
    """ضرب مصفوفات عشوائيّة (size × size) - محسنة"""
    # التحقق من المدخلات
    validation = validate_input(size, 1, RESOURCE_LIMITS["max_matrix_size"], "حجم المصفوفة")
    if validation:
        return validation
    
    try:
        A = np.random.rand(size, size).astype(np.float32)  # استخدام float32 لتوفير الذاكرة
        B = np.random.rand(size, size).astype(np.float32)
        result = np.dot(A, B)
        
        return {
            "result": result.tolist(),
            "dimensions": f"{size}x{size}",
            "memory_estimate_mb": round(result.nbytes / (1024**2), 2),
            "server_processed": True
        }
    except MemoryError:
        return {"error": "ذاكرة غير كافية لمعالجة المصفوفات", "server_processed": False}

@log_performance
def data_processing(data_size: int) -> Dict[str, Any]:
    """تنفيذ معالجة بيانات بسيطة كتجربة - محسنة"""
    # التحقق من المدخلات
    validation = validate_input(data_size, 1, RESOURCE_LIMITS["max_data_size"], "حجم البيانات")
    if validation:
        return validation
    
    data = np.random.rand(data_size)
    
    return {
        "data_size": data_size,
        "mean": float(np.mean(data)),
        "std_dev": float(np.std(data)),
        "min": float(np.min(data)),
        "max": float(np.max(data)),
        "median": float(np.median(data)),
        "q1": float(np.percentile(data, 25)),
        "q3": float(np.percentile(data, 75)),
        "server_processed": True
    }

@log_performance
def image_processing_emulation(iterations: int) -> Dict[str, Any]:
    """محاكاة معالجة الصور - محسنة"""
    # التحقق من المدخلات
    validation = validate_input(iterations, 1, RESOURCE_LIMITS["max_iterations"], "عدد التكرارات")
    if validation:
        return validation
    
    results = []
    total_operations = 0
    batch_size = 1000  # زيادة حجم الدفعة للأداء الأفضل
    
    for i in range(iterations):
        start = i * batch_size
        end = (i + 1) * batch_size
        
        # استخدام numpy للحسابات بدلاً من loop
        batch_data = np.arange(start, end)
        batch_result = np.sum(np.sqrt(batch_data))
        
        results.append(float(batch_result))
        total_operations += len(batch_data)
        
        time.sleep(0.005)  # تقليل وقت الانتظار
    
    return {
        "iterations": iterations,
        "batch_size": batch_size,
        "total_operations": total_operations,
        "results": results,
        "server_processed": True
    }

# مهام معالجة الفيديو والألعاب ثلاثية الأبعاد - محسنة
@log_performance
def video_format_conversion(duration_seconds: float, quality_level: int, 
                          input_format: str = "mp4", output_format: str = "avi") -> Dict[str, Any]:
    """تحويل صيغة الفيديو - محسنة"""
    # التحقق من المدخلات
    validation = validate_input(duration_seconds, 1, RESOURCE_LIMITS["max_video_duration"], "مدة الفيديو")
    if validation:
        return validation
    
    validation = validate_input(quality_level, 1, 10, "مستوى الجودة")
    if validation:
        return validation
    
    start_time = time.time()
    processing_time = duration_seconds * quality_level * 0.03  # معالجة أسرع
    
    # محاكاة المعالجة مع إمكانية الإلغاء
    end_time = time.time() + min(processing_time, 1.0)
    while time.time() < end_time:
        time.sleep(0.01)
        # التحقق من الموارد أثناء التنفيذ
        if ResourceMonitor.should_reject_task():
            return {"error": "تم إلغاء المهمة بسبب ارتفاع استخدام الموارد", "server_processed": False}

    return {
        "status": "success",
        "input_format": input_format,
        "output_format": output_format,
        "duration": duration_seconds,
        "quality": quality_level,
        "processing_time": time.time() - start_time,
        "server_processed": True
    }

@log_performance
def video_effects_processing(video_length: float, effects_count: int, 
                           resolution: str = "1080p") -> Dict[str, Any]:
    """معالجة تأثيرات الفيديو - محسنة"""
    # التحقق من المدخلات
    validation = validate_input(video_length, 1, RESOURCE_LIMITS["max_video_duration"], "طول الفيديو")
    if validation:
        return validation
    
    validation = validate_input(effects_count, 1, 100, "عدد المؤثرات")
    if validation:
        return validation
    
    start_time = time.time()

    resolution_multiplier = {"480p": 1, "720p": 2, "1080p": 3, "4K": 5}
    multiplier = resolution_multiplier.get(resolution, 2)
    processing_time = video_length * effects_count * multiplier * 0.02  # أسرع

    # محاكاة المعالجة
    end_time = time.time() + min(processing_time, 1.2)
    while time.time() < end_time:
        time.sleep(0.01)
        if ResourceMonitor.should_reject_task():
            return {"error": "تم إلغاء المهمة بسبب ارتفاع استخدام الموارد", "server_processed": False}

    return {
        "status": "success",
        "video_length": video_length,
        "effects_count": effects_count,
        "resolution": resolution,
        "processing_time": time.time() - start_time,
        "server_processed": True
    }

@log_performance
def render_3d_scene(objects_count: int, resolution_width: int, resolution_height: int, 
                   lighting_quality: str = "medium", texture_quality: str = "high") -> Dict[str, Any]:
    """رندر مشهد ثلاثي الأبعاد - محسنة"""
    # التحقق من المدخلات
    validation = validate_input(objects_count, 1, RESOURCE_LIMITS["max_objects_3d"], "عدد الكائنات")
    if validation:
        return validation
    
    validation = validate_input(resolution_width, 100, 7680, "عرض الدقة")
    if validation:
        return validation
    
    validation = validate_input(resolution_height, 100, 4320, "ارتفاع الدقة")
    if validation:
        return validation
    
    start_time = time.time()

    complexity = objects_count * (resolution_width * resolution_height) / 1500000  # تقليل التعقيد
    processing_time = complexity * 0.015

    # محاكاة المعالجة
    end_time = time.time() + min(processing_time, 1.8)
    progress = 0
    while time.time() < end_time:
        time.sleep(0.02)
        progress = min(100, ((time.time() - start_time) / processing_time) * 100)
        if ResourceMonitor.should_reject_task():
            return {"error": "تم إلغاء المهمة بسبب ارتفاع استخدام الموارد", "server_processed": False}

    fps = max(45, 120 - (complexity * 4))  # أداء أفضل

    return {
        "status": "success",
        "objects_rendered": objects_count,
        "resolution": f"{resolution_width}x{resolution_height}",
        "lighting_quality": lighting_quality,
        "texture_quality": texture_quality,
        "estimated_fps": round(fps, 1),
        "complexity_score": round(complexity, 2),
        "processing_time": time.time() - start_time,
        "progress_percent": round(progress, 1),
        "server_processed": True
    }

@log_performance
def physics_simulation(objects_count: int, frames_count: int, 
                     physics_quality: str = "medium") -> Dict[str, Any]:
    """محاكاة الفيزياء - محسنة"""
    # التحقق من المدخلات
    validation = validate_input(objects_count, 1, RESOURCE_LIMITS["max_objects_3d"], "عدد الكائنات")
    if validation:
        return validation
    
    validation = validate_input(frames_count, 1, 10000, "عدد الإطارات")
    if validation:
        return validation
    
    start_time = time.time()

    quality_multiplier = {"low": 1, "medium": 2, "high": 3, "ultra": 5}  # تقليل المضاعفات
    multiplier = quality_multiplier.get(physics_quality, 2)

    calculations = objects_count * frames_count * multiplier
    processing_time = calculations / 250000  # أسرع

    # محاكاة المعالجة مع تقدم
    end_time = time.time() + min(processing_time, 1.3)
    current_frame = 0
    total_frames = min(frames_count, 1000)  # حد معقول
    
    while time.time() < end_time and current_frame < total_frames:
        time.sleep(processing_time / total_frames)
        current_frame += 1
        if ResourceMonitor.should_reject_task():
            return {"error": "تم إلغاء المهمة بسبب ارتفاع استخدام الموارد", "server_processed": False}

    return {
        "status": "success",
        "objects_simulated": objects_count,
        "frames_processed": current_frame,
        "physics_quality": physics_quality,
        "calculations_performed": calculations,
        "processing_time": time.time() - start_time,
        "server_processed": True
    }

@log_performance
def game_ai_processing(ai_agents_count: int, decision_complexity: int, 
                      game_state_size: int) -> Dict[str, Any]:
    """معالجة ذكاء اصطناعي للألعاب - محسنة"""
    # التحقق من المدخلات
    validation = validate_input(ai_agents_count, 1, 1000, "عدد وكلاء الذكاء الاصطناعي")
    if validation:
        return validation
    
    validation = validate_input(decision_complexity, 1, 100, "تعقيد القرار")
    if validation:
        return validation
    
    validation = validate_input(game_state_size, 10, 10000, "حجم حالة اللعبة")
    if validation:
        return validation
    
    start_time = time.time()

    total_operations = ai_agents_count * decision_complexity * game_state_size
    processing_time = total_operations / 120000  # أسرع

    # محاكاة المعالجة
    end_time = time.time() + min(processing_time, 0.8)
    agents_processed = 0
    
    while time.time() < end_time and agents_processed < ai_agents_count:
        time.sleep(processing_time / ai_agents_count)
        agents_processed += 1
        if ResourceMonitor.should_reject_task():
            return {"error": "تم إلغاء المهمة بسبب ارتفاع استخدام الموارد", "server_processed": False}

    return {
        "status": "success",
        "ai_agents": ai_agents_count,
        "agents_processed": agents_processed,
        "decision_complexity": decision_complexity,
        "total_operations": total_operations,
        "processing_time": time.time() - start_time,
        "efficiency_score": round((agents_processed / ai_agents_count) * 100, 1),
        "server_processed": True
    }

# وظائف مساعدة إضافية
def get_system_status() -> Dict[str, Any]:
    """الحصول على حالة النظام الحالية"""
    system_info = ResourceMonitor.get_system_info()
    
    return {
        "system_status": "active",
        "resource_monitoring": HAS_PSUTIL,
        "limits": RESOURCE_LIMITS,
        **system_info
    }

def get_task_info() -> Dict[str, Any]:
    """الحصول على معلومات عن جميع المهام المتاحة"""
    tasks = {
        "prime_calculation": "حساب الأعداد الأولية",
        "matrix_multiply": "ضرب المصفوفات",
        "data_processing": "معالجة البيانات",
        "image_processing_emulation": "محاكاة معالجة الصور",
        "video_format_conversion": "تحويل صيغة الفيديو",
        "video_effects_processing": "معالجة تأثيرات الفيديو",
        "render_3d_scene": "رندر المشاهد ثلاثية الأبعاد",
        "physics_simulation": "محاكاة الفيزياء",
        "game_ai_processing": "معالجة الذكاء الاصطناعي للألعاب"
    }
    
    return {
        "available_tasks": tasks,
        "total_tasks": len(tasks),
        "resource_limits": RESOURCE_LIMITS,
        "system_info": get_system_status()
    }

# مثال على الاستخدام
if __name__ == "__main__":
    # اختبار المهام المحسنة
    print("=== اختبار المهام المحسنة ===")
    
    # اختبار حالة النظام
    status = get_system_status()
    print(f"حالة النظام: {status}")
    
    # اختبار مهمة بسيطة
    result = prime_calculation(100)
    print(f"الأعداد الأولية حتى 100: {result['count']} عدد")
    
    # اختبار معالجة البيانات
    result = data_processing(1000)
    print(f"معالجة البيانات: المتوسط = {result['mean']:.3f}")
    
    print("=== انتهى الاختبار ===")