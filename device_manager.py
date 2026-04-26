#!/usr/bin/env python3
"""
مدير الأجهزة المتقدم - نظام اكتشاف ومراقبة متكامل للأجهزة
إصدار محسن مع مراقبة في الوقت الحقيقي وإدارة ذكية للموارد
"""

import subprocess
import GPUtil
import psutil
import logging
import threading
import time
import json
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import asyncio

# إعداد اللوجر المتقدم
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("DeviceManager")

class DeviceType(Enum):
    """أنواع الأجهزة المدعومة"""
    GPU = "GPU"
    DSP = "DSP"
    NIC = "NIC"
    STORAGE = "STORAGE"
    CAPTURE = "CAPTURE"
    ACCELERATOR = "ACCELERATOR"
    CPU = "CPU"
    MEMORY = "MEMORY"

class DeviceStatus(Enum):
    """حالة الجهاز"""
    ONLINE = "online"
    OFFLINE = "offline"
    OVERLOADED = "overloaded"
    MAINTENANCE = "maintenance"
    ERROR = "error"

@dataclass
class DeviceInfo:
    """معلومات شاملة عن الجهاز"""
    device_type: DeviceType
    device_id: str
    name: str
    status: DeviceStatus
    driver_version: Optional[str] = None
    capabilities: List[str] = field(default_factory=list)
    max_load: float = 100.0  # أقصى حمل ممكن
    current_load: float = 0.0
    temperature: Optional[float] = None
    memory_total: int = 0
    memory_used: int = 0
    clock_speed: Optional[float] = None
    power_usage: Optional[float] = None
    pci_address: Optional[str] = None
    last_updated: float = field(default_factory=time.time)
    
    @property
    def memory_usage_percent(self) -> float:
        """نسبة استخدام الذاكرة"""
        if self.memory_total == 0:
            return 0.0
        return (self.memory_used / self.memory_total) * 100
    
    @property
    def is_available(self) -> bool:
        """التحقق من توفر الجهاز"""
        return (self.status == DeviceStatus.ONLINE and 
                self.current_load < self.max_load * 0.9)
    
    def to_dict(self) -> Dict[str, Any]:
        """تحويل إلى قاموس للتسلسل"""
        return {
            "device_type": self.device_type.value,
            "device_id": self.device_id,
            "name": self.name,
            "status": self.status.value,
            "current_load": round(self.current_load, 2),
            "memory_usage_percent": round(self.memory_usage_percent, 2),
            "temperature": self.temperature,
            "is_available": self.is_available,
            "capabilities": self.capabilities,
            "last_updated": self.last_updated
        }

class DeviceManager:
    """
    مدير أجهزة متقدم مع مراقبة في الوقت الحقيقي
    واكتشاف ديناميكي للأجهزة
    """
    
    def __init__(self, config_file: str = "device_config.json"):
        self.devices: Dict[str, DeviceInfo] = {}
        self._monitoring = False
        self._monitor_thread: Optional[threading.Thread] = None
        self._update_callbacks = []
        self._config_file = Path(config_file)
        self._load_config()
        
        # إعدادات المراقبة
        self.monitor_interval = 2.0  # ثواني
        self.offload_threshold = 70.0  # %
        self.receive_threshold = 30.0  # %
        
        # الاكتشاف الأولي
        self._detect_all_devices()
        
    def _load_config(self):
        """تحميل التكوين من ملف"""
        default_config = {
            "monitor_interval": 2.0,
            "offload_threshold": 70.0,
            "receive_threshold": 30.0,
            "gpu_monitoring": True,
            "storage_monitoring": True,
            "network_monitoring": True,
            "max_temperature": 85.0
        }
        
        try:
            if self._config_file.exists():
                with open(self._config_file, 'r', encoding='utf-8') as f:
                    self.config = json.load(f)
            else:
                self.config = default_config
                self._save_config()
        except Exception as e:
            logger.warning(f"فشل في تحميل التكوين: {e}")
            self.config = default_config
    
    def _save_config(self):
        """حفظ التكوين إلى ملف"""
        try:
            with open(self._config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"فشل في حفظ التكوين: {e}")
    
    def _detect_all_devices(self):
        """اكتشاف جميع الأجهزة المتاحة"""
        logger.info("بدء اكتشاف الأجهزة...")
        
        detection_methods = [
            (DeviceType.CPU, self._detect_cpus),
            (DeviceType.GPU, self._detect_gpus),
            (DeviceType.MEMORY, self._detect_memory),
            (DeviceType.DSP, self._detect_dsps),
            (DeviceType.NIC, self._detect_nics),
            (DeviceType.STORAGE, self._detect_storage),
            (DeviceType.CAPTURE, self._detect_capture),
            (DeviceType.ACCELERATOR, self._detect_accelerators)
        ]
        
        for device_type, detection_method in detection_methods:
            try:
                devices = detection_method()
                for device in devices:
                    self.devices[device.device_id] = device
                logger.info(f"تم اكتشاف {len(devices)} من أجهزة {device_type.value}")
            except Exception as e:
                logger.error(f"فشل في اكتشاف أجهزة {device_type.value}: {e}")
    
    def _detect_cpus(self) -> List[DeviceInfo]:
        """اكتشاف المعالجات"""
        try:
            cpu_info = DeviceInfo(
                device_type=DeviceType.CPU,
                device_id="cpu_0",
                name=f"CPU - {psutil.cpu_count()} Cores",
                status=DeviceStatus.ONLINE,
                capabilities=["computation", "parallel_processing"],
                max_load=100.0
            )
            return [cpu_info]
        except Exception as e:
            logger.error(f"فشل في اكتشاف المعالجات: {e}")
            return []
    
    def _detect_gpus(self) -> List[DeviceInfo]:
        """اكتشاف كروت الشاشة"""
        gpus = []
        try:
            # استخدام GPUtil
            gpu_list = GPUtil.getGPUs()
            for i, gpu in enumerate(gpu_list):
                gpu_info = DeviceInfo(
                    device_type=DeviceType.GPU,
                    device_id=f"gpu_{i}",
                    name=gpu.name,
                    status=DeviceStatus.ONLINE,
                    driver_version=getattr(gpu, 'driver', 'Unknown'),
                    capabilities=["graphics", "compute", "ai_inference"],
                    memory_total=gpu.memoryTotal,
                    memory_used=gpu.memoryUsed,
                    temperature=gpu.temperature,
                    max_load=100.0
                )
                gpus.append(gpu_info)
            
            # اكتشاف كروت PyTorch الإضافية
            try:
                import torch
                if torch.cuda.is_available():
                    for i in range(torch.cuda.device_count()):
                        device_name = torch.cuda.get_device_name(i)
                        # تجنب التكرار
                        if not any(device_name in gpu.name for gpu in gpus):
                            gpu_info = DeviceInfo(
                                device_type=DeviceType.GPU,
                                device_id=f"cuda_gpu_{i}",
                                name=device_name,
                                status=DeviceStatus.ONLINE,
                                capabilities=["graphics", "compute", "ai_inference", "pytorch"],
                                max_load=100.0
                            )
                            gpus.append(gpu_info)
            except ImportError:
                pass
                
        except Exception as e:
            logger.error(f"فشل في اكتشاف كروت الشاشة: {e}")
        
        return gpus
    
    def _detect_memory(self) -> List[DeviceInfo]:
        """اكتشاف الذاكرة"""
        try:
            memory = psutil.virtual_memory()
            memory_info = DeviceInfo(
                device_type=DeviceType.MEMORY,
                device_id="memory_0",
                name="System Memory",
                status=DeviceStatus.ONLINE,
                memory_total=memory.total,
                memory_used=memory.used,
                max_load=95.0,  # تجنب الاستخدام الكامل
                capabilities=["data_storage", "caching"]
            )
            return [memory_info]
        except Exception as e:
            logger.error(f"فشل في اكتشاف الذاكرة: {e}")
            return []
    
    def _detect_dsps(self) -> List[DeviceInfo]:
        """اكتشاف معالجات الإشارة الرقمية"""
        dsps = []
        try:
            # اكتشاف كروت الصوت باستخدام aplay
            result = subprocess.run(
                ["aplay", "-l"], 
                capture_output=True, 
                text=True, 
                timeout=5
            )
            if result.returncode == 0 and "card" in result.stdout.lower():
                dsp_info = DeviceInfo(
                    device_type=DeviceType.DSP,
                    device_id="audio_dsp_0",
                    name="Audio DSP",
                    status=DeviceStatus.ONLINE,
                    capabilities=["audio_processing", "signal_processing"],
                    max_load=80.0
                )
                dsps.append(dsp_info)
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError, FileNotFoundError):
            pass
        except Exception as e:
            logger.debug(f"فشل في اكتشاف كروت الصوت: {e}")
        
        # اكتشاف DSPs أخرى
        try:
            # يمكن إضافة اكتشافات إضافية هنا
            pass
        except Exception as e:
            logger.debug(f"فشل في اكتشاف DSPs إضافية: {e}")
        
        return dsps
    
    def _detect_nics(self) -> List[DeviceInfo]:
        """اكتشاف واجهات الشبكة"""
        nics = []
        try:
            net_if_addrs = psutil.net_if_addrs()
            for i, (interface_name, addrs) in enumerate(net_if_addrs.items()):
                # تخطى الواجهات الافتراضية
                if interface_name in ['lo', 'docker0', 'virbr0']:
                    continue
                    
                nic_info = DeviceInfo(
                    device_type=DeviceType.NIC,
                    device_id=f"nic_{i}",
                    name=interface_name,
                    status=DeviceStatus.ONLINE,
                    capabilities=["network_communication", "data_transfer"],
                    max_load=90.0
                )
                nics.append(nic_info)
        except Exception as e:
            logger.error(f"فشل في اكتشاف واجهات الشبكة: {e}")
        
        return nics
    
    def _detect_storage(self) -> List[DeviceInfo]:
        """اكتشاف أجهزة التخزين"""
        storage_devices = []
        try:
            # استخدام lsblk لاكتشاف أجهزة التخزين
            result = subprocess.run(
                ["lsblk", "-o", "NAME,SIZE,TYPE,MOUNTPOINT", "-J"],
                capture_output=True, 
                text=True, 
                timeout=5
            )
            
            if result.returncode == 0:
                # تم استيراد json في الأعلى، لا حاجة لاستيراده هنا
                lsblk_data = json.loads(result.stdout)
                for device in lsblk_data.get('blockdevices', []):
                    if device['type'] == 'disk':
                        storage_info = DeviceInfo(
                            device_type=DeviceType.STORAGE,
                            device_id=f"storage_{device['name']}",
                            name=f"Storage {device['name']}",
                            status=DeviceStatus.ONLINE,
                            capabilities=["data_storage", "io_operations"],
                            max_load=95.0
                        )
                        storage_devices.append(storage_info)
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError):
            pass
        except Exception as e:
            logger.debug(f"فشل في اكتشاف أجهزة التخزين: {e}")
        
        # إذا لم نتمكن من اكتشاف التخزين باستخدام lsblk، نستخدم psutil كبديل
        if not storage_devices:
            try:
                # استخدام psutil لاكتشاف أقسام التخزين
                partitions = psutil.disk_partitions()
                for i, partition in enumerate(partitions):
                    if partition.fstype and partition.fstype.lower() not in ['squashfs', 'tmpfs']:
                        storage_info = DeviceInfo(
                            device_type=DeviceType.STORAGE,
                            device_id=f"storage_{i}",
                            name=f"Storage {partition.device}",
                            status=DeviceStatus.ONLINE,
                            capabilities=["data_storage", "io_operations"],
                            max_load=95.0
                        )
                        storage_devices.append(storage_info)
            except Exception as e:
                logger.debug(f"فشل في اكتشاف التخزين باستخدام psutil: {e}")
        
        return storage_devices
    
    def _detect_capture(self) -> List[DeviceInfo]:
        """اكتشاف أجهزة الالتقاط (كاميرات، إلخ)"""
        capture_devices = []
        try:
            # استخدام v4l2-ctl لاكتشاف أجهزة الفيديو
            result = subprocess.run(
                ["v4l2-ctl", "--list-devices"],
                capture_output=True, 
                text=True, 
                timeout=5
            )
            
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                current_device = ""
                for line in lines:
                    if line and not line.startswith('\t'):
                        current_device = line.strip()
                        capture_info = DeviceInfo(
                            device_type=DeviceType.CAPTURE,
                            device_id=f"capture_{len(capture_devices)}",
                            name=current_device,
                            status=DeviceStatus.ONLINE,
                            capabilities=["video_capture", "image_processing"],
                            max_load=70.0
                        )
                        capture_devices.append(capture_info)
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError, FileNotFoundError):
            pass
        except Exception as e:
            logger.debug(f"فشل في اكتشاف أجهزة الالتقاط: {e}")
        
        return capture_devices
    
    def _detect_accelerators(self) -> List[DeviceInfo]:
        """اكتشاف مسرعات الأجهزة (FPGA, TPU, إلخ)"""
        accelerators = []
        
        # اكتشاف TPUs (Google Tensor Processing Units)
        try:
            # يمكن إضافة اكتشاف TPU هنا
            pass
        except Exception as e:
            logger.debug(f"فشل في اكتشاف TPUs: {e}")
        
        # اكتشاف FPGAs
        try:
            # يمكن إضافة اكتشاف FPGA هنا
            pass
        except Exception as e:
            logger.debug(f"فشل في اكتشاف FPGAs: {e}")
        
        return accelerators
    
    def start_monitoring(self):
        """بدء مراقبة الأجهزة في الخلفية"""
        if self._monitoring:
            return
        
        self._monitoring = True
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            daemon=True
        )
        self._monitor_thread.start()
        logger.info("بدأ مراقبة الأجهزة")
    
    def stop_monitoring(self):
        """إيقاف مراقبة الأجهزة"""
        self._monitoring = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5.0)
        logger.info("أوقفت مراقبة الأجهزة")
    
    def _monitor_loop(self):
        """حلقة المراقبة المستمرة"""
        while self._monitoring:
            try:
                self.update_device_status()
                time.sleep(self.monitor_interval)
            except Exception as e:
                logger.error(f"خطأ في حلقة المراقبة: {e}")
                time.sleep(5)  # انتظار أطول في حالة الخطأ
    
    def update_device_status(self):
        """تحديث حالة جميع الأجهزة"""
        updates = {}
        
        try:
            # تحديث حالة CPU
            cpu_device = self._get_device_by_id("cpu_0")
            if cpu_device:
                cpu_device.current_load = psutil.cpu_percent(interval=0.1)
                cpu_device.memory_used = psutil.virtual_memory().used
                updates["cpu_0"] = cpu_device
            
            # تحديث حالة GPUs
            try:
                gpu_list = GPUtil.getGPUs()
                for i, gpu in enumerate(gpu_list):
                    device_id = f"gpu_{i}"
                    gpu_device = self._get_device_by_id(device_id)
                    if gpu_device:
                        gpu_device.current_load = gpu.load * 100
                        gpu_device.memory_used = gpu.memoryUsed
                        gpu_device.temperature = gpu.temperature
                        updates[device_id] = gpu_device
            except Exception as e:
                logger.debug(f"فشل في تحديث حالة GPUs: {e}")
            
            # تحديث حالة الذاكرة
            memory_device = self._get_device_by_id("memory_0")
            if memory_device:
                memory = psutil.virtual_memory()
                memory_device.current_load = memory.percent
                memory_device.memory_used = memory.used
                updates["memory_0"] = memory_device
            
            # تحديث حالة التخزين
            storage_devices = self._get_devices_by_type(DeviceType.STORAGE)
            for device in storage_devices:
                try:
                    # استخدام مسار الجذر للتحديث
                    disk_usage = psutil.disk_usage('/')
                    device.current_load = disk_usage.percent
                    updates[device.device_id] = device
                except Exception as e:
                    logger.debug(f"فشل في تحديث حالة التخزين: {e}")
            
            # استدعاء callbacks التحديث
            for callback in self._update_callbacks:
                try:
                    callback(updates)
                except Exception as e:
                    logger.error(f"خطأ في callback التحديث: {e}")
                    
        except Exception as e:
            logger.error(f"خطأ في تحديث حالة الأجهزة: {e}")
    
    def _get_device_by_id(self, device_id: str) -> Optional[DeviceInfo]:
        """الحصول على جهاز بواسطة المعرف"""
        return self.devices.get(device_id)
    
    def _get_devices_by_type(self, device_type: DeviceType) -> List[DeviceInfo]:
        """الحصول على جميع الأجهزة من نوع معين"""
        return [device for device in self.devices.values() 
                if device.device_type == device_type]
    
    def get_device_load(self, device_type: DeviceType, index: int = 0) -> float:
        """الحصول على حمل جهاز محدد"""
        devices = self._get_devices_by_type(device_type)
        if index < len(devices):
            return devices[index].current_load
        return 0.0
    
    def can_receive(self, device_type: DeviceType, index: int = 0) -> bool:
        """التحقق من إمكانية استقبال المهمة"""
        load = self.get_device_load(device_type, index)
        return load <= self.receive_threshold
    
    def should_offload(self, device_type: DeviceType, index: int = 0) -> bool:
        """التحقق من ضرورة نقل المهمة"""
        load = self.get_device_load(device_type, index)
        return load >= self.offload_threshold
    
    def get_best_device_for_task(self, task_type: str, min_memory: int = 0) -> Optional[DeviceInfo]:
        """الحصول على أفضل جهاز لنوع المهمة"""
        suitable_devices = []
        
        for device in self.devices.values():
            if (device.is_available and 
                device.memory_total >= min_memory and
                self._is_device_suitable(device, task_type)):
                suitable_devices.append(device)
        
        if not suitable_devices:
            return None
        
        # ترتيب حسب الحمل (الأقل حملًا أولاً)
        suitable_devices.sort(key=lambda x: x.current_load)
        return suitable_devices[0]
    
    def _is_device_suitable(self, device: DeviceInfo, task_type: str) -> bool:
        """التحقق من ملائمة الجهاز لنوع المهمة"""
        task_mapping = {
            "video_processing": [DeviceType.GPU, DeviceType.ACCELERATOR],
            "audio_processing": [DeviceType.DSP, DeviceType.CPU],
            "ai_inference": [DeviceType.GPU, DeviceType.ACCELERATOR],
            "data_processing": [DeviceType.CPU, DeviceType.MEMORY],
            "network_io": [DeviceType.NIC],
            "storage_io": [DeviceType.STORAGE],
            "capture": [DeviceType.CAPTURE]
        }
        
        suitable_types = task_mapping.get(task_type, [DeviceType.CPU])
        return device.device_type in suitable_types
    
    def add_update_callback(self, callback):
        """إضافة دالة استدعاء عند تحديث الأجهزة"""
        self._update_callbacks.append(callback)
    
    def get_system_summary(self) -> Dict[str, Any]:
        """الحصول على ملخص حالة النظام"""
        summary = {
            "total_devices": len(self.devices),
            "online_devices": len([d for d in self.devices.values() if d.status == DeviceStatus.ONLINE]),
            "average_load": 0.0,
            "devices_by_type": {}
        }
        
        total_load = 0.0
        online_count = 0
        
        for device_type in DeviceType:
            devices = self._get_devices_by_type(device_type)
            if devices:
                summary["devices_by_type"][device_type.value] = []
                for device in devices:
                    device_summary = device.to_dict()
                    summary["devices_by_type"][device_type.value].append(device_summary)
                    
                    if device.status == DeviceStatus.ONLINE:
                        total_load += device.current_load
                        online_count += 1
        
        if online_count > 0:
            summary["average_load"] = round(total_load / online_count, 2)
        
        return summary
    
    def __del__(self):
        """التنظيف عند الحذف"""
        self.stop_monitoring()

# مثال على الاستخدام
if __name__ == "__main__":
    def print_updates(updates):
        """دالة استدعاء لعرض التحديثات"""
        for device_id, device in updates.items():
            print(f"📊 {device.name}: {device.current_load:.1f}%")
    
    # إنشاء مدير الأجهزة
    device_manager = DeviceManager()
    
    # إضافة callback للتحديثات
    device_manager.add_update_callback(print_updates)
    
    # بدء المراقبة
    device_manager.start_monitoring()
    
    try:
        # عرض ملخص النظام
        summary = device_manager.get_system_summary()
        print("\n" + "="*50)
        print("ملخص حالة النظام:")
        print("="*50)
        print(f"إجمالي الأجهزة: {summary['total_devices']}")
        print(f"الأجهزة المتاحة: {summary['online_devices']}")
        print(f"متوسط الحمل: {summary['average_load']}%")
        
        # عرض تفاصيل الأجهزة
        print("\nتفاصيل الأجهزة:")
        print("-" * 30)
        for device_type, devices in summary["devices_by_type"].items():
            print(f"\n{device_type}:")
            for device in devices:
                status_icon = "🟢" if device["is_available"] else "🔴"
                print(f"  {status_icon} {device['name']}: {device['current_load']}%")
        
        # الانتظار لرؤية بعض التحديثات
        print(f"\nجاري المراقبة لمدة 10 ثواني...")
        time.sleep(10)
        
    except KeyboardInterrupt:
        print("\nإيقاف المراقبة...")
    finally:
        device_manager.stop_monitoring()
