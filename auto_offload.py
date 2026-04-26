import subprocess
import torch
import GPUtil
import psutil
import logging
import threading
import time
from typing import Dict, List, Callable, Any, Optional
from dataclasses import dataclass
from enum import Enum

# إعداد اللوجر
logging.getLogger().setLevel(logging.CRITICAL)

class DeviceType(Enum):
    CPU = "CPU"
    GPU = "GPU"
    DSP = "DSP"
    NPU = "NPU"  # للمعالجات العصبية المستقبلية

@dataclass
class DeviceInfo:
    type: DeviceType
    index: int
    name: str
    memory_total: int = 0
    memory_used: int = 0
    load: float = 0.0
    temperature: float = 0.0
    supported_task_types: List[str] = None

    def __post_init__(self):
        if self.supported_task_types is None:
            self.supported_task_types = []

    def get_memory_usage_percent(self) -> float:
        if self.memory_total == 0:
            return 0.0
        return (self.memory_used / self.memory_total) * 100

    def is_available(self, task_type: str = None) -> bool:
        if task_type and self.supported_task_types:
            return task_type in self.supported_task_types
        return self.load < 85 and self.get_memory_usage_percent() < 90

class DeviceManager:
    def __init__(self):
        self.devices: Dict[DeviceType, List[DeviceInfo]] = {}
        self._monitoring = False
        self._monitor_thread = None
        self._update_callbacks = []
        self._detect_all_devices()
        
    def _detect_all_devices(self):
        """اكتشاف جميع الأجهزة المتاحة"""
        self.devices = {
            DeviceType.CPU: [self._detect_cpu()],
            DeviceType.GPU: self._detect_gpus(),
            DeviceType.DSP: self._detect_dsps(),
            DeviceType.NPU: self._detect_npus()
        }
    
    def _detect_cpu(self) -> DeviceInfo:
        """اكتشاف معلومات CPU"""
        cpu_load = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory()
        
        return DeviceInfo(
            type=DeviceType.CPU,
            index=0,
            name="CPU",
            memory_total=memory.total,
            memory_used=memory.used,
            load=cpu_load,
            supported_task_types=["computation", "data_processing", "general"]
        )
    
    def _detect_gpus(self) -> List[DeviceInfo]:
        """اكتشاف جميع الـ GPUs المتاحة"""
        gpus = []
        try:
            # استخدام GPUtil
            gpu_list = GPUtil.getGPUs()
            for i, gpu in enumerate(gpu_list):
                gpu_info = DeviceInfo(
                    type=DeviceType.GPU,
                    index=i,
                    name=gpu.name,
                    memory_total=gpu.memoryTotal,
                    memory_used=gpu.memoryUsed,
                    load=gpu.load * 100,
                    temperature=gpu.temperature,
                    supported_task_types=["video", "inference", "training", "rendering"]
                )
                gpus.append(gpu_info)
            
            # اكتشاف كروت PyTorch أيضًا
            if torch.cuda.is_available():
                for i in range(torch.cuda.device_count()):
                    torch_device_name = torch.cuda.get_device_name(i)
                    # تجنب التكرار
                    if not any(torch_device_name in gpu.name for gpu in gpus):
                        gpu_info = DeviceInfo(
                            type=DeviceType.GPU,
                            index=len(gpus),
                            name=torch_device_name,
                            memory_total=torch.cuda.get_device_properties(i).total_memory,
                            memory_used=0,  # سيتم تحديثه لاحقًا
                            supported_task_types=["video", "inference", "training", "rendering"]
                        )
                        gpus.append(gpu_info)
                        
        except Exception as e:
            logging.debug(f"فشل في اكتشاف GPUs: {e}")
        
        return gpus
    
    def _detect_dsps(self) -> List[DeviceInfo]:
        """اكتشاف معالجات الإشارة الرقمية"""
        dsps = []
        try:
            # اكتشاف كروت الصوت
            output = subprocess.check_output(["aplay", "-l"], stderr=subprocess.DEVNULL).decode()
            if "card" in output.lower():
                dsp_info = DeviceInfo(
                    type=DeviceType.DSP,
                    index=0,
                    name="Audio_DSP",
                    supported_task_types=["audio", "signal_processing"]
                )
                dsps.append(dsp_info)
        except Exception:
            pass
            
        # اكتشاف DSPs أخرى (مثل كروت AI المتخصصة)
        try:
            # يمكن إضافة اكتشافات إضافية هنا
            pass
        except Exception:
            pass
            
        return dsps
    
    def _detect_npus(self) -> List[DeviceInfo]:
        """اكتشاف المعالجات العصبية (للاستخدام المستقبلي)"""
        npus = []
        # يمكن إضافة اكتشاف NPUs هنا
        return npus
    
    def get_best_device(self, task_type: str, min_memory: int = 0) -> Optional[DeviceInfo]:
        """الحصول على أفضل جهاز لنوع المهمة"""
        candidate_devices = []
        
        for device_type, devices in self.devices.items():
            for device in devices:
                if device.is_available(task_type) and device.memory_total >= min_memory:
                    candidate_devices.append(device)
        
        if not candidate_devices:
            return None
        
        # ترتيب حسب الحمل (الأقل حملًا أولاً)
        candidate_devices.sort(key=lambda x: x.load)
        return candidate_devices[0]
    
    def get_device_load(self, device_type: DeviceType, index: int = 0) -> float:
        """الحصول على حمل جهاز محدد"""
        devices = self.devices.get(device_type, [])
        if index < len(devices):
            return devices[index].load
        return 0.0
    
    def start_monitoring(self, interval: float = 2.0):
        """بدء مراقبة الأجهزة في الخلفية"""
        if self._monitoring:
            return
            
        self._monitoring = True
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            args=(interval,),
            daemon=True
        )
        self._monitor_thread.start()
    
    def stop_monitoring(self):
        """إيقاف مراقبة الأجهزة"""
        self._monitoring = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=1.0)
    
    def _monitor_loop(self, interval: float):
        """حلقة المراقبة المستمرة"""
        while self._monitoring:
            self.update_device_status()
            time.sleep(interval)
    
    def update_device_status(self):
        """تحديث حالة جميع الأجهزة"""
        # تحديث CPU
        if DeviceType.CPU in self.devices:
            self.devices[DeviceType.CPU][0] = self._detect_cpu()
        
        # تحديث GPUs
        try:
            gpu_list = GPUtil.getGPUs()
            for i, gpu in enumerate(gpu_list):
                if i < len(self.devices[DeviceType.GPU]):
                    self.devices[DeviceType.GPU][i].load = gpu.load * 100
                    self.devices[DeviceType.GPU][i].memory_used = gpu.memoryUsed
                    self.devices[DeviceType.GPU][i].temperature = gpu.temperature
        except Exception:
            pass
        
        # استدعاء callbacks التحديث
        for callback in self._update_callbacks:
            try:
                callback(self.devices)
            except Exception:
                pass
    
    def add_update_callback(self, callback: Callable):
        """إضافة دالة استدعاء عند تحديث الأجهزة"""
        self._update_callbacks.append(callback)
    
    def get_system_summary(self) -> Dict[str, Any]:
        """الحصول على ملخص حالة النظام"""
        summary = {
            "total_devices": 0,
            "available_devices": 0,
            "device_details": {}
        }
        
        for device_type, devices in self.devices.items():
            summary["device_details"][device_type.value] = []
            for device in devices:
                device_summary = {
                    "name": device.name,
                    "load": device.load,
                    "memory_usage": device.get_memory_usage_percent(),
                    "available": device.is_available()
                }
                summary["device_details"][device_type.value].append(device_summary)
                summary["total_devices"] += 1
                if device.is_available():
                    summary["available_devices"] += 1
        
        return summary

class AutoOffloadExecutor:
    def __init__(self, executor, config: Dict[str, Any] = None):
        self.executor = executor
        self.devices = DeviceManager()
        self.config = config or {
            "offload_threshold": 70,
            "receive_threshold": 30,
            "prefer_local": True,
            "task_mapping": {
                "video": DeviceType.GPU,
                "audio": DeviceType.DSP,
                "inference": DeviceType.GPU,
                "training": DeviceType.GPU,
                "general": DeviceType.CPU
            }
        }
        
        # بدء المراقبة التلقائية
        self.devices.start_monitoring()
    
    def __del__(self):
        """التنظيف عند الحذف"""
        self.devices.stop_monitoring()
    
    def _get_task_device_type(self, task_type: str) -> DeviceType:
        """الحصول على نوع الجهاز المناسب لنوع المهمة"""
        return self.config["task_mapping"].get(
            task_type, 
            DeviceType.CPU
        )
    
    def _should_offload(self, device_type: DeviceType, index: int = 0) -> bool:
        """تحديد إذا كان يجب نقل المهمة"""
        load = self.devices.get_device_load(device_type, index)
        return load >= self.config["offload_threshold"]
    
    def _can_receive(self, device_type: DeviceType, index: int = 0) -> bool:
        """تحديد إذا كان يمكن استقبال المهمة"""
        load = self.devices.get_device_load(device_type, index)
        return load <= self.config["receive_threshold"]
    
    def submit_auto(self, task_func: Callable, *args, 
                   task_type: str = "general", 
                   priority: int = 0,
                   **kwargs) -> Any:
        """إرسال تلقائي للمهمة حسب حالة الأجهزة"""
        
        # تحديد الجهاز المستهدف
        target_device_type = self._get_task_device_type(task_type)
        best_device = self.devices.get_best_device(task_type)
        
        decision_info = {
            "task_type": task_type,
            "target_device": target_device_type.value,
            "best_device": best_device.name if best_device else "None",
            "offload_decision": "local"
        }
        
        # اتخاذ قرار النقل
        if (best_device and 
            best_device.type != DeviceType.CPU and 
            self._should_offload(target_device_type)):
            
            # نقل المهمة
            decision_info["offload_decision"] = "offload"
            future = self.executor.submit(task_func, *args, **kwargs)
            future.device_info = decision_info
            return future
            
        elif (best_device and 
              self._can_receive(target_device_type) and 
              not self.config["prefer_local"]):
            
            # تنفيذ على الجهاز المستهدف
            decision_info["offload_decision"] = "remote"
            # يمكن إضافة تنفيذ على جهاز معين هنا
            return task_func(*args, **kwargs)
        
        else:
            # تنفيذ محلي
            decision_info["offload_decision"] = "local"
            return task_func(*args, **kwargs)
    
    def get_system_status(self) -> Dict[str, Any]:
        """الحصول على حالة النظام الحالية"""
        return self.devices.get_system_summary()
    
    def update_config(self, new_config: Dict[str, Any]):
        """تحديث إعدادات النقل التلقائي"""
        self.config.update(new_config)

# مثال على الاستخدام
if __name__ == "__main__":
    from concurrent.futures import ThreadPoolExecutor
    
    # مثال على التنفيذ
    with ThreadPoolExecutor() as executor:
        auto_executor = AutoOffloadExecutor(executor)
        
        def sample_task(data):
            print(f"معالجة: {data}")
            return f"نتيجة {data}"
        
        # إرسال مهام بأنواع مختلفة
        result1 = auto_executor.submit_auto(
            sample_task, "مهمة فيديو", 
            task_type="video"
        )
        
        result2 = auto_executor.submit_auto(
            sample_task, "مهمة صوت", 
            task_type="audio"
        )
        
        # عرض حالة النظام
        print("حالة النظام:")
        status = auto_executor.get_system_status()
        for device_type, devices in status["device_details"].items():
            print(f"{device_type}:")
            for device in devices:
                print(f"  - {device['name']}: {device['load']:.1f}%")