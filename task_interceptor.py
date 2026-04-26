#!/usr/bin/env python3
# task_interceptor.py - نظام اعتراض وتوزيع المهام المحسّن

import time
import logging
import functools
import threading
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
from dataclasses import dataclass
from enum import Enum
from concurrent.futures import Future, ThreadPoolExecutor

try:
    from processor_manager import should_offload, get_optimal_node
    from remote_executor import execute_remotely, broadcast_task
    HAS_DEPENDENCIES = True
except ImportError as e:
    HAS_DEPENDENCIES = False
    print(f"⚠️ تحذير: بعض المكتبات غير متوفرة - {e}")

class TaskPriority(Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"

class ExecutionMode(Enum):
    AUTO = "auto"
    LOCAL_ONLY = "local_only"
    REMOTE_ONLY = "remote_only"
    BROADCAST = "broadcast"

@dataclass
class TaskResult:
    """نتيجة تنفيذ المهمة"""
    success: bool
    data: Any
    execution_time: float
    executed_remotely: bool
    node_id: Optional[str] = None
    error: Optional[str] = None
    retry_count: int = 0

@dataclass
class TaskMetadata:
    """بيانات وصفية للمهمة"""
    function_name: str
    priority: TaskPriority
    mode: ExecutionMode
    timeout: float
    max_retries: int
    created_at: float
    estimated_complexity: int

class TaskInterceptor:
    """مدير اعتراض وتوزيع المهام المحسّن"""
    
    def __init__(self, max_workers: int = 5):
        self.setup_logging()
        self.execution_mode = ExecutionMode.AUTO
        self.task_timeout = 30.0  # ثانية
        self.max_retries = 2
        self.enable_caching = True
        self.cache: Dict[str, Tuple[float, Any]] = {}  # تخزين مؤقت بسيط
        self.cache_ttl = 300  # 5 دقائق
        self.task_history: List[Dict[str, Any]] = []
        self.max_history_size = 1000
        self.thread_pool = ThreadPoolExecutor(max_workers=max_workers)
        
        # إحصائيات
        self.stats = {
            "total_tasks": 0,
            "local_executions": 0,
            "remote_executions": 0,
            "failed_tasks": 0,
            "cache_hits": 0,
            "average_time_local": 0.0,
            "average_time_remote": 0.0
        }
    
    def setup_logging(self):
        """إعداد نظام التسجيل"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('logs/task_interceptor.log', encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger('TaskInterceptor')
    
    def set_execution_mode(self, mode: ExecutionMode):
        """تعيين نمط التنفيذ"""
        self.execution_mode = mode
        self.logger.info(f"تم تعيين نمط التنفيذ إلى: {mode.value}")
    
    def set_timeout(self, timeout: float):
        """تعيين المهلة الافتراضية للمهام"""
        self.task_timeout = timeout
        self.logger.info(f"تم تعيين مهلة المهام إلى: {timeout} ثانية")
    
    def should_offload_enhanced(self, func_name: str, args: tuple, complexity: int = 1) -> bool:
        """تقرير محسّن لنقل المهام"""
        if not HAS_DEPENDENCIES:
            return False
        
        if self.execution_mode == ExecutionMode.LOCAL_ONLY:
            return False
        elif self.execution_mode == ExecutionMode.REMOTE_ONLY:
            return True
        
        try:
            # استخدام المنطق الأساسي مع تحسينات
            base_decision = should_offload()
            
            # عوامل إضافية للتقرير
            if complexity > 5:  # مهام معقدة
                return True
            elif len(self.task_history) > 10 and self.stats["local_executions"] > self.stats["remote_executions"] * 2:
                return True  # تحميل مرتفع محلي
            
            return base_decision
            
        except Exception as e:
            self.logger.warning(f"خطأ في تقرير نقل المهام: {e}")
            return False
    
    def get_cache_key(self, func_name: str, args: tuple, kwargs: dict) -> str:
        """إنشاء مفتاح فريد للتخزين المؤقت"""
        import hashlib
        import pickle
        
        try:
            data = {
                'func': func_name,
                'args': args,
                'kwargs': frozenset(kwargs.items()) if kwargs else None
            }
            serialized = pickle.dumps(data)
            return hashlib.md5(serialized).hexdigest()
        except:
            # fallback بسيط إذا فشل التخزين
            return f"{func_name}_{hash(str(args) + str(kwargs))}"
    
    def get_cached_result(self, cache_key: str) -> Optional[Any]:
        """الحصول على نتيجة من التخزين المؤقت"""
        if not self.enable_caching:
            return None
        
        if cache_key in self.cache:
            timestamp, result = self.cache[cache_key]
            if time.time() - timestamp < self.cache_ttl:
                self.stats["cache_hits"] += 1
                self.logger.debug(f"ضرب تخزين مؤقت للمهمة: {cache_key}")
                return result
            else:
                # انتهت صلاحية التخزين المؤقت
                del self.cache[cache_key]
        
        return None
    
    def set_cached_result(self, cache_key: str, result: Any):
        """تعيين نتيجة في التخزين المؤقت"""
        if self.enable_caching:
            self.cache[cache_key] = (time.time(), result)
            # تنظيف التخزين المؤقت القديم
            if len(self.cache) > 1000:  # حد أقصى للعناصر
                oldest_key = min(self.cache.keys(), key=lambda k: self.cache[k][0])
                del self.cache[oldest_key]
    
    def execute_with_timeout(self, func: Callable, args: tuple, kwargs: dict, 
                           timeout: float) -> TaskResult:
        """تنفيذ مهمة مع مهلة"""
        start_time = time.time()
        future = self.thread_pool.submit(func, *args, **kwargs)
        
        try:
            result_data = future.result(timeout=timeout)
            execution_time = time.time() - start_time
            
            return TaskResult(
                success=True,
                data=result_data,
                execution_time=execution_time,
                executed_remotely=False
            )
            
        except Exception as e:
            execution_time = time.time() - start_time
            return TaskResult(
                success=False,
                data=None,
                execution_time=execution_time,
                executed_remotely=False,
                error=str(e)
            )
    
    def execute_remote_with_fallback(self, func_name: str, args: tuple, kwargs: dict, 
                                   fallback_func: Callable, retry_count: int = 0) -> TaskResult:
        """تنفيذ عن بعد مع معاودة للتنفيذ المحلي"""
        if not HAS_DEPENDENCIES or retry_count >= self.max_retries:
            # معاودة للتنفيذ المحلي
            self.logger.warning(f"معاودة المهمة {func_name} للتنفيذ المحلي")
            return self.execute_with_timeout(fallback_func, args, kwargs, self.task_timeout)
        
        try:
            start_time = time.time()
            result_data = execute_remotely(func_name, args, kwargs)
            execution_time = time.time() - start_time
            
            return TaskResult(
                success=True,
                data=result_data,
                execution_time=execution_time,
                executed_remotely=True,
                node_id="remote"  # يمكن جلب ID العقدة الفعلية
            )
            
        except Exception as e:
            self.logger.warning(f"فشل التنفيذ عن بعد للمهمة {func_name}: {e}")
            # إعادة المحاولة
            return self.execute_remote_with_fallback(
                func_name, args, kwargs, fallback_func, retry_count + 1
            )
    
    def broadcast_task_execution(self, func_name: str, args: tuple, kwargs: dict) -> TaskResult:
        """بث المهمة لعدة عقد"""
        if not HAS_DEPENDENCIES:
            return TaskResult(
                success=False,
                data=None,
                execution_time=0.0,
                executed_remotely=False,
                error="المكتبات غير متوفرة"
            )
        
        try:
            start_time = time.time()
            results = broadcast_task(func_name, args, kwargs)
            execution_time = time.time() - start_time
            
            # معالجة النتائج (يمكن تطويرها حسب الحاجة)
            successful_results = [r for r in results if r.get('success', False)]
            
            if successful_results:
                # استخدام أول نتيجة ناجحة
                best_result = successful_results[0]
                return TaskResult(
                    success=True,
                    data=best_result.get('data'),
                    execution_time=execution_time,
                    executed_remotely=True,
                    node_id=best_result.get('node_id', 'multiple')
                )
            else:
                return TaskResult(
                    success=False,
                    data=None,
                    execution_time=execution_time,
                    executed_remotely=True,
                    error="فشل البث لجميع العقد"
                )
                
        except Exception as e:
            return TaskResult(
                success=False,
                data=None,
                execution_time=0.0,
                executed_remotely=True,
                error=f"خطأ في البث: {str(e)}"
            )
    
    def update_statistics(self, result: TaskResult):
        """تحديث الإحصائيات"""
        self.stats["total_tasks"] += 1
        
        if result.success:
            if result.executed_remotely:
                self.stats["remote_executions"] += 1
                # تحديث متوسط الوقت
                current_avg = self.stats["average_time_remote"]
                count = self.stats["remote_executions"]
                self.stats["average_time_remote"] = (
                    (current_avg * (count - 1) + result.execution_time) / count
                )
            else:
                self.stats["local_executions"] += 1
                current_avg = self.stats["average_time_local"]
                count = self.stats["local_executions"]
                self.stats["average_time_local"] = (
                    (current_avg * (count - 1) + result.execution_time) / count
                )
        else:
            self.stats["failed_tasks"] += 1
    
    def log_task_execution(self, metadata: TaskMetadata, result: TaskResult):
        """تسجيل تنفيذ المهمة"""
        log_entry = {
            "timestamp": time.time(),
            "function": metadata.function_name,
            "priority": metadata.priority.value,
            "mode": metadata.mode.value,
            "executed_remotely": result.executed_remotely,
            "success": result.success,
            "execution_time": result.execution_time,
            "retry_count": result.retry_count,
            "error": result.error
        }
        
        self.task_history.append(log_entry)
        
        # الحفاظ على حجم السجل
        if len(self.task_history) > self.max_history_size:
            self.task_history.pop(0)
        
        # تسجيل تفصيلي
        status = "✅" if result.success else "❌"
        location = "🌐 عن بعد" if result.executed_remotely else "💻 محلي"
        self.logger.info(
            f"{status} {metadata.function_name} - {location} - "
            f"{result.execution_time:.2f}ث - إعادة: {result.retry_count}"
        )
    
    def offload_if_needed_enhanced(self, func: Callable, priority: TaskPriority = TaskPriority.NORMAL,
                                 complexity: int = 1, timeout: Optional[float] = None,
                                 use_cache: bool = True) -> Callable:
        """ديكوراتور محسّن لنقل المهام"""
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            nonlocal timeout
            
            # إعداد البيانات الوصفية
            timeout = timeout or self.task_timeout
            metadata = TaskMetadata(
                function_name=func.__name__,
                priority=priority,
                mode=self.execution_mode,
                timeout=timeout,
                max_retries=self.max_retries,
                created_at=time.time(),
                estimated_complexity=complexity
            )
            
            # التحقق من التخزين المؤقت
            cache_key = None
            if use_cache and self.enable_caching:
                cache_key = self.get_cache_key(func.__name__, args, kwargs)
                cached_result = self.get_cached_result(cache_key)
                if cached_result is not None:
                    result = TaskResult(
                        success=True,
                        data=cached_result,
                        execution_time=0.0,  # وقت التخزين المؤقت ضئيل
                        executed_remotely=False
                    )
                    self.update_statistics(result)
                    self.log_task_execution(metadata, result)
                    return cached_result
            
            # تقرير التنفيذ
            task_result = None
            
            if self.execution_mode == ExecutionMode.BROADCAST:
                task_result = self.broadcast_task_execution(func.__name__, args, kwargs)
            
            elif self.execution_mode == ExecutionMode.REMOTE_ONLY:
                task_result = self.execute_remote_with_fallback(func.__name__, args, kwargs, func)
            
            elif self.execution_mode == ExecutionMode.LOCAL_ONLY:
                task_result = self.execute_with_timeout(func, args, kwargs, timeout)
            
            else:  # AUTO mode
                if self.should_offload_enhanced(func.__name__, args, complexity):
                    task_result = self.execute_remote_with_fallback(func.__name__, args, kwargs, func)
                else:
                    task_result = self.execute_with_timeout(func, args, kwargs, timeout)
            
            # تحديث الإحصائيات والتسجيل
            self.update_statistics(task_result)
            self.log_task_execution(metadata, task_result)
            
            # التخزين المؤقت للنتائج الناجحة
            if task_result.success and use_cache and cache_key:
                self.set_cached_result(cache_key, task_result.data)
            
            # إعادة النتيجة أو رفع استثناء
            if task_result.success:
                return task_result.data
            else:
                raise Exception(f"فشل تنفيذ المهمة: {task_result.error}")
        
        return wrapper
    
    def get_statistics(self) -> Dict[str, Any]:
        """الحصول على إحصائيات التنفيذ"""
        stats = self.stats.copy()
        stats["cache_size"] = len(self.cache)
        stats["history_size"] = len(self.task_history)
        stats["success_rate"] = (
            (stats["total_tasks"] - stats["failed_tasks"]) / stats["total_tasks"] * 100
            if stats["total_tasks"] > 0 else 0
        )
        return stats
    
    def clear_cache(self):
        """مسح التخزين المؤقت"""
        self.cache.clear()
        self.logger.info("تم مسح التخزين المؤقت")
    
    def cleanup(self):
        """تنظيف الموارد"""
        self.thread_pool.shutdown(wait=True)
        self.logger.info("تم تنظيف موارد المعترض")

# نسخة مبسطة للاستخدام السريع
interceptor = TaskInterceptor()

def offload_if_needed(func=None, *, priority: str = "normal", complexity: int = 1, 
                     timeout: float = None, use_cache: bool = True):
    """
    ديكوراتور مبسط لنقل المهام
    
    الاستخدام:
    @offload_if_needed(priority='high', complexity=3)
    def my_heavy_function():
        ...
    """
    if func is None:
        return lambda f: offload_if_needed(
            f, priority=priority, complexity=complexity, 
            timeout=timeout, use_cache=use_cache
        )
    
    priority_enum = TaskPriority(priority.lower())
    return interceptor.offload_if_needed_enhanced(
        func, priority_enum, complexity, timeout, use_cache
    )

# مثال على الاستخدام
if __name__ == "__main__":
    # اختبار الديكوراتور
    @offload_if_needed(priority='high', complexity=5)
    def heavy_computation(n: int) -> int:
        print(f"تنفيذ محلي للحساب: {n}")
        return sum(i * i for i in range(n))
    
    # اختبار التنفيذ
    try:
        result = heavy_computation(1000)
        print(f"النتيجة: {result}")
        
        # عرض الإحصائيات
        stats = interceptor.get_statistics()
        print(f"الإحصائيات: {stats}")
        
    except Exception as e:
        print(f"خطأ: {e}")
    
    finally:
        interceptor.cleanup()