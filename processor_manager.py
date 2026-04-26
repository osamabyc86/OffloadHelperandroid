#!/usr/bin/env python3
"""
مدير المعالج المحسن - الإصدار 3.0
نظام مراقبة موارد ذكي مع تحليلات تنبؤية وتكيف ذاتي
"""

import psutil
import time
import logging
from collections import deque
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Tuple
from enum import Enum
import threading
from datetime import datetime, timedelta
import statistics

# إعداد السجلات
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class ResourceType(Enum):
    """أنواع الموارد"""
    CPU = "cpu"
    MEMORY = "memory"
    DISK = "disk"
    NETWORK = "network"

class Decision(Enum):
    """قرارات إدارة الموارد"""
    LOCAL = "local"
    OFFLOAD = "offload"
    DEFER = "defer"
    CRITICAL = "critical"

@dataclass
class ResourceMetrics:
    """مقاييس موارد شاملة"""
    cpu_usage: float
    memory_available: float
    memory_total: float
    disk_usage: float
    network_io: Tuple[float, float]  # upload, download MB/s
    load_average: Tuple[float, float, float]
    timestamp: datetime

@dataclass
class SystemStatus:
    """حالة النظام الشاملة"""
    instant_metrics: ResourceMetrics
    historical_metrics: Dict[str, deque]
    trends: Dict[str, float]
    recommendations: List[str]
    decisions: Dict[str, bool]
    capacity_score: float

class AdaptiveResourceMonitor:
    """
    مراقب موارد تكيفي مع تعلم ذاتي
    """
    
    def __init__(self, history_size: int = 30):
        self.history_size = history_size
        
        # تخزين التاريخ
        self.cpu_history = deque(maxlen=history_size)
        self.memory_history = deque(maxlen=history_size)
        self.disk_history = deque(maxlen=history_size)
        self.network_history = deque(maxlen=history_size)
        
        # العتبات التكيفية
        self.cpu_threshold = 0.40  # ابتدائي، يتكيف تلقائياً
        self.memory_threshold_mb = 2048  # 2GB حد أدنى
        self.disk_threshold = 0.85  # 85% استخدام قرص
        
        # إحصائيات الاستخدام
        self.usage_patterns = {
            'peak_hours': [],
            'quiet_hours': [],
            'avg_daily_usage': 0.0
        }
        
        # قفل للتزامن
        self._lock = threading.RLock()
        self._last_update = datetime.now()
        
        # بدء المراقبة الخلفية
        self._monitoring = True
        self._monitor_thread = threading.Thread(
            target=self._background_monitoring,
            daemon=True,
            name="ResourceMonitor"
        )
        self._monitor_thread.start()
        
        logger.info("🚀 بدء مراقب الموارد التكيفي")
    
    def _background_monitoring(self):
        """مراقبة خلفية مستمرة للموارد"""
        while self._monitoring:
            try:
                metrics = self._collect_comprehensive_metrics()
                self._update_historical_data(metrics)
                self._analyze_usage_patterns()
                self._adapt_thresholds()
                
                time.sleep(2)  # جمع البيانات كل 2 ثانية
                
            except Exception as e:
                logger.error(f"❌ خطأ في المراقبة الخلفية: {e}")
                time.sleep(5)
    
    def _collect_comprehensive_metrics(self) -> ResourceMetrics:
        """جمع مقاييس موارد شاملة"""
        try:
            # استخدام CPU
            cpu_usage = psutil.cpu_percent(interval=0.3) / 100.0
            
            # الذاكرة
            memory = psutil.virtual_memory()
            memory_available = memory.available / (1024 ** 2)  # MB
            memory_total = memory.total / (1024 ** 2)  # MB
            
            # القرص
            disk_usage = psutil.disk_usage('/').percent / 100.0
            
            # الشبكة
            net_io = psutil.net_io_counters()
            network_upload = net_io.bytes_sent / (1024 ** 2)  # MB
            network_download = net_io.bytes_recv / (1024 ** 2)  # MB
            
            # متوسط التحميل (على أنظمة Unix)
            try:
                load_avg = psutil.getloadavg()
            except AttributeError:
                load_avg = (0.0, 0.0, 0.0)
            
            return ResourceMetrics(
                cpu_usage=cpu_usage,
                memory_available=memory_available,
                memory_total=memory_total,
                disk_usage=disk_usage,
                network_io=(network_upload, network_download),
                load_average=load_avg,
                timestamp=datetime.now()
            )
            
        except Exception as e:
            logger.error(f"❌ فشل جمع المقاييس: {e}")
            # قيم افتراضية آمنة
            return ResourceMetrics(
                cpu_usage=0.0,
                memory_available=4096,  # 4GB افتراضي
                memory_total=8192,      # 8GB افتراضي
                disk_usage=0.0,
                network_io=(0.0, 0.0),
                load_average=(0.0, 0.0, 0.0),
                timestamp=datetime.now()
            )
    
    def _update_historical_data(self, metrics: ResourceMetrics):
        """تحديث البيانات التاريخية"""
        with self._lock:
            self.cpu_history.append(metrics.cpu_usage)
            self.memory_history.append(metrics.memory_available)
            self.disk_history.append(metrics.disk_usage)
            self.network_history.append(metrics.network_io)
            self._last_update = metrics.timestamp
    
    def _analyze_usage_patterns(self):
        """تحليل أنماط الاستخدام"""
        if len(self.cpu_history) < 10:
            return
        
        with self._lock:
            current_hour = datetime.now().hour
            
            # تحليل ساعات الذروة
            recent_cpu = list(self.cpu_history)[-10:]
            avg_recent_cpu = statistics.mean(recent_cpu)
            
            if avg_recent_cpu > 0.6 and current_hour not in self.usage_patterns['peak_hours']:
                self.usage_patterns['peak_hours'].append(current_hour)
                logger.info(f"📈 تم تحديد ساعة ذروة: {current_hour}:00")
            
            elif avg_recent_cpu < 0.2 and current_hour not in self.usage_patterns['quiet_hours']:
                self.usage_patterns['quiet_hours'].append(current_hour)
                logger.info(f"📉 تم تحديد ساعة هادئة: {current_hour}:00")
    
    def _adapt_thresholds(self):
        """تكيف العتبات تلقائياً بناءً على أنماط الاستخدام"""
        if len(self.cpu_history) < 20:
            return
        
        current_hour = datetime.now().hour
        
        # تكيف عتبة CPU بناءً على ساعات الذروة
        if current_hour in self.usage_patterns['peak_hours']:
            self.cpu_threshold = 0.35  # أكثر تحفظاً في ساعات الذروة
        elif current_hour in self.usage_patterns['quiet_hours']:
            self.cpu_threshold = 0.50  # أقل تحفظاً في الساعات الهادئة
        else:
            self.cpu_threshold = 0.40  # افتراضي
    
    def get_current_status(self) -> SystemStatus:
        """
        الحصول على حالة النظام الشاملة
        
        Returns:
            SystemStatus: حالة النظام مع التوصيات والقرارات
        """
        metrics = self._collect_comprehensive_metrics()
        self._update_historical_data(metrics)
        
        # حساب المتوسطات
        with self._lock:
            avg_cpu = statistics.mean(self.cpu_history) if self.cpu_history else 0.0
            avg_memory = statistics.mean(self.memory_history) if self.memory_history else 0.0
            avg_disk = statistics.mean(self.disk_history) if self.disk_history else 0.0
        
        # تحليل الاتجاهات
        trends = self._calculate_trends()
        
        # توليد التوصيات
        recommendations = self._generate_recommendations(metrics, avg_cpu, avg_memory, avg_disk)
        
        # اتخاذ القرارات
        decisions = self._make_decisions(metrics, avg_cpu, avg_memory, avg_disk)
        
        # حساب درجة السعة
        capacity_score = self._calculate_capacity_score(metrics, avg_cpu, avg_memory)
        
        return SystemStatus(
            instant_metrics=metrics,
            historical_metrics={
                'cpu': self.cpu_history,
                'memory': self.memory_history,
                'disk': self.disk_history,
                'network': self.network_history
            },
            trends=trends,
            recommendations=recommendations,
            decisions=decisions,
            capacity_score=capacity_score
        )
    
    def _calculate_trends(self) -> Dict[str, float]:
        """حساب اتجاهات استخدام الموارد"""
        trends = {}
        
        with self._lock:
            if len(self.cpu_history) >= 10:
                recent_cpu = list(self.cpu_history)[-10:]
                older_cpu = list(self.cpu_history)[-20:-10] if len(self.cpu_history) >= 20 else recent_cpu
                
                if older_cpu:
                    trends['cpu_trend'] = statistics.mean(recent_cpu) - statistics.mean(older_cpu)
            
            if len(self.memory_history) >= 10:
                recent_mem = list(self.memory_history)[-10:]
                trends['memory_trend'] = statistics.mean(recent_mem) - statistics.mean(list(self.memory_history)[-20:-10])
        
        return trends
    
    def _generate_recommendations(self, metrics: ResourceMetrics, 
                                avg_cpu: float, avg_memory: float, avg_disk: float) -> List[str]:
        """توليد توصيات ذكية"""
        recommendations = []
        
        # توصيات CPU
        if avg_cpu > 0.7:
            recommendations.append("🚨 استخدام CPU مرتفع - تقليل المهام الحرجة")
        elif avg_cpu > 0.5:
            recommendations.append("⚠️ استخدام CPU متوسط - مراقبة التحميل")
        
        # توصيات الذاكرة
        if metrics.memory_available < 1024:  # أقل من 1GB
            recommendations.append("🚨 الذاكرة منخفضة - تحرير الذاكرة أو إيقاف التطبيقات")
        elif metrics.memory_available < 2048:  # أقل من 2GB
            recommendations.append("⚠️ الذاكرة محدودة - تجنب المهام الكبيرة")
        
        # توصيات القرص
        if metrics.disk_usage > 0.9:
            recommendations.append("🚨 مساحة القرص منخفضة - تنظيف الملفات المؤقتة")
        
        if not recommendations:
            recommendations.append("✅ حالة النظام جيدة - يمكن استقبال مهام جديدة")
        
        return recommendations
    
    def _make_decisions(self, metrics: ResourceMetrics, 
                       avg_cpu: float, avg_memory: float, avg_disk: float) -> Dict[str, bool]:
        """اتخاذ قرارات إدارة الموارد"""
        return {
            'can_receive_tasks': avg_cpu <= self.cpu_threshold and metrics.memory_available > self.memory_threshold_mb,
            'should_offload': avg_cpu > 0.6 or metrics.memory_available < 1024,
            'is_critical': avg_cpu > 0.8 or metrics.memory_available < 512,
            'can_handle_complex': avg_cpu <= 0.3 and metrics.memory_available > 4096
        }
    
    def _calculate_capacity_score(self, metrics: ResourceMetrics, 
                                avg_cpu: float, avg_memory: float) -> float:
        """حساب درجة سعة النظام (0-1)"""
        # درجة CPU (أعلى عندما يكون الاستخدام أقل)
        cpu_score = max(0, 1 - avg_cpu)
        
        # درجة الذاكرة (نسبة المتاحة إلى الإجمالي)
        memory_ratio = metrics.memory_available / metrics.memory_total
        memory_score = min(1, memory_ratio * 2)  # تضخيم للأهمية
        
        # درجة القرص
        disk_score = 1 - metrics.disk_usage
        
        # متوسط مرجح
        capacity_score = (cpu_score * 0.5 + memory_score * 0.3 + disk_score * 0.2)
        
        return round(capacity_score, 2)
    
    def should_offload(self, task_complexity: float = 0) -> Tuple[bool, str]:
        """
        تحديد ما إذا كان يجب توزيع المهمة
        
        Args:
            task_complexity: تعقيد المهمة (0-100)
            
        Returns:
            tuple: (should_offload, reason)
        """
        status = self.get_current_status()
        decisions = status.decisions
        
        if decisions['is_critical']:
            return True, "حالة النظام حرجة"
        
        if decisions['should_offload']:
            return True, "تحميل النظام مرتفع"
        
        if task_complexity > 75 and not decisions['can_handle_complex']:
            return True, "المهمة معقدة والنظام لا يستطيع معالجتها"
        
        if task_complexity > 50 and status.capacity_score < 0.6:
            return True, "سعة النظام غير كافية للمهمة المتوسطة"
        
        return False, "يمكن المعالجة محلياً"
    
    def can_receive_task(self, task_complexity: float = 0) -> Tuple[bool, str]:
        """
        التحقق من إمكانية استقبال مهمة جديدة
        
        Args:
            task_complexity: تعقيد المهمة (0-100)
            
        Returns:
            tuple: (can_receive, reason)
        """
        status = self.get_current_status()
        decisions = status.decisions
        
        if not decisions['can_receive_tasks']:
            return False, "تحميل النظام مرتفع جداً"
        
        if task_complexity > 80 and not decisions['can_handle_complex']:
            return False, "المهمة معقدة جداً للنظام الحالي"
        
        if status.capacity_score < 0.3:
            return False, "سعة النظام منخفضة جداً"
        
        return True, "يمكن استقبال المهمة"
    
    def get_detailed_report(self) -> Dict[str, any]:
        """الحصول على تقرير مفصل عن حالة النظام"""
        status = self.get_current_status()
        
        return {
            'timestamp': datetime.now().isoformat(),
            'system_status': {
                'capacity_score': status.capacity_score,
                'instant_metrics': asdict(status.instant_metrics),
                'decisions': status.decisions,
                'recommendations': status.recommendations,
                'trends': status.trends
            },
            'adaptive_thresholds': {
                'cpu_threshold': self.cpu_threshold,
                'memory_threshold_mb': self.memory_threshold_mb,
                'disk_threshold': self.disk_threshold
            },
            'usage_patterns': self.usage_patterns,
            'historical_stats': {
                'cpu_avg': statistics.mean(self.cpu_history) if self.cpu_history else 0,
                'memory_avg': statistics.mean(self.memory_history) if self.memory_history else 0,
                'data_points': len(self.cpu_history)
            }
        }
    
    def stop_monitoring(self):
        """إيقاف المراقبة الخلفية"""
        self._monitoring = False
        if self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=5)
        logger.info("🛑 توقفت مراقبة الموارد")

# دوال التوافق مع الإصدار القديم
def trigger_offload():
    """وظيفة التوافق مع الإصدار القديم"""
    logger.info("⚠️ تم استدعاء توزيع المهام")
    return True

def should_offload(task_complexity=0):
    """وظيفة التوافق مع الإصدار القديم"""
    monitor = AdaptiveResourceMonitor()
    should_offload, reason = monitor.should_offload(task_complexity)
    
    if should_offload:
        trigger_offload()
        logger.info(f"💡 ينصح بتوزيع المهمة: {reason}")
    else:
        logger.info(f"✅ يمكن تنفيذ المهمة محلياً: {reason}")
    
    return should_offload

def can_receive_task():
    """وظيفة التوافق مع الإصدار القديم"""
    monitor = AdaptiveResourceMonitor()
    can_receive, reason = monitor.can_receive_task()
    
    logger.info(f"📊 قدرة استقبال المهام: {can_receive} - {reason}")
    return can_receive

# النسخة العالمية للمراقب
global_monitor = AdaptiveResourceMonitor()

if __name__ == "__main__":
    # اختبار النظام المحسن
    monitor = AdaptiveResourceMonitor()
    
    print("🔧 اختبار مدير المعالج المحسن...")
    time.sleep(3)  # انتظار جمع البيانات الأولية
    
    # الحصول على تقرير مفصل
    report = monitor.get_detailed_report()
    
    print(f"\n📊 تقرير النظام:")
    print(f"   • درجة السعة: {report['system_status']['capacity_score']}")
    print(f"   • استخدام CPU: {report['system_status']['instant_metrics']['cpu_usage']:.1%}")
    print(f"   • الذاكرة المتاحة: {report['system_status']['instant_metrics']['memory_available']:.0f} MB")
    print(f"   • العتبة التكيفية: {report['adaptive_thresholds']['cpu_threshold']:.0%}")
    
    print(f"\n💡 التوصيات:")
    for rec in report['system_status']['recommendations']:
        print(f"   • {rec}")
    
    print(f"\n🔍 قرارات النظام:")
    for decision, value in report['system_status']['decisions'].items():
        print(f"   • {decision}: {value}")
    
    # اختبار التوافق
    print(f"\n🔄 اختبار دوال التوافق:")
    can_receive = can_receive_task()
    should_offload_val = should_offload(80)
    
    print(f"   • يمكن استقبال المهام: {can_receive}")
    print(f"   • يجب توزيع المهمة: {should_offload_val}")
    
    # تنظيف
    monitor.stop_monitoring()
