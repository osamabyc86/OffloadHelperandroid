#!/usr/bin/env python3
# port_manager.py - إدارة المنافذ وتجنب التعارضات

import socket
import logging
import threading
from typing import List, Tuple, Dict
from concurrent.futures import ThreadPoolExecutor, as_completed

class PortManager:
    def __init__(self):
        self.setup_logging()
        self.used_ports = set()
        self.lock = threading.Lock()
        self.scan_timeout = 2
        self.max_workers = 20  # الحد الأقصى لخيوط المسح المتوازي
    
    def setup_logging(self):
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger('PortManager')
    
    def is_port_available(self, port: int, host: str = '0.0.0.0') -> bool:
        """التحقق من توفر المنفذ"""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(1)
                result = sock.connect_ex((host, port))
                return result != 0
        except Exception as e:
            self.logger.debug(f"خطأ في التحقق من المنفذ {port}: {e}")
            return False
    
    def find_available_port(self, start_port: int = 1000, max_attempts: int = 100) -> int:
        """إيجاد منفذ متاح بدءاً من المنفذ 1000"""
        for port in range(start_port, start_port + max_attempts):
            if port > 65535:  # الحد الأقصى للمنافذ
                break
            if self.is_port_available(port):
                with self.lock:
                    self.used_ports.add(port)
                self.logger.info(f"✅ المنفذ {port} متاح")
                return port
        
        # إذا لم يتم العثور على منفذ في النطاق الأول، جرب نطاقات أخرى
        fallback_ranges = [
            (8000, 8100),   # نطاق تطوير شائع
            (3000, 3100),   # نطاق Node.js
            (3640, 5100),   # نطاق Flask
            (9000, 9100)    # نطاق تطبيقات متنوعة
        ]
        
        for start, end in fallback_ranges:
            for port in range(start, end):
                if self.is_port_available(port):
                    with self.lock:
                        self.used_ports.add(port)
                    self.logger.info(f"✅ المنفذ {port} متاح (من النطاق الاحتياطي)")
                    return port
        
        raise Exception(f"لم يتم إيجاد منفذ متاح بعد البحث في نطاقات متعددة")
    
    def scan_port(self, port: int) -> Tuple[int, bool, str]:
        """مسح منفذ فردي مع معلومات الخدمة"""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(self.scan_timeout)
                result = sock.connect_ex(('127.0.0.1', port))
                
                if result == 0:
                    service_info = self.get_port_service_info(port)
                    return (port, True, service_info)
                else:
                    return (port, False, "")
                    
        except Exception as e:
            return (port, False, f"خطأ: {e}")
    
    def get_port_service_info(self, port: int) -> str:
        """الحصول على معلومات عن الخدمة المشغلة على المنفذ"""
        common_services = {
            # خدمات الويب
            80: "HTTP",
            443: "HTTPS",
            8080: "HTTP-Alt",
            8443: "HTTPS-Alt",
            8000: "HTTP-Dev",
            3000: "Node.js",
            3640: "Flask/Dev",
            
            # قواعد البيانات
            3306: "MySQL",
            5432: "PostgreSQL",
            27017: "MongoDB",
            6379: "Redis",
            9200: "Elasticsearch",
            11211: "Memcached",
            
            # البريد والشبكات
            21: "FTP",
            22: "SSH",
            25: "SMTP",
            53: "DNS",
            110: "POP3",
            143: "IMAP",
            993: "IMAPS",
            995: "POP3S",
            
            # خدمات التطوير
            3001: "React/Next",
            4200: "Angular",
            5173: "Vite",
            6000: "X11",
            7000: "Dev-Server",
            9000: "PHP",
            
            # خدمات النظام
            135: "RPC",
            139: "NetBIOS",
            445: "SMB",
            1433: "MSSQL",
            1521: "Oracle",
            3389: "RDP"
        }
        
        return common_services.get(port, "خدمة مخصصة")
    
    def get_recommended_ports(self, count: int = 15, scan_range: Tuple[int, int] = (1000, 9999)) -> List[int]:
        """إيجاد منافذ متصلة ونشطة بدلاً من قائمة ثابتة"""
        self.logger.info(f"🔍 بدء مسح المنافذ من {scan_range[0]} إلى {scan_range[1]}...")
        
        connected_ports = []
        start_port, end_port = scan_range
        
        # استخدام المسح المتوازي للأداء الأفضل
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # إنشاء مهام المسح لجميع المنافذ في النطاق
            future_to_port = {
                executor.submit(self.scan_port, port): port 
                for port in range(start_port, min(end_port + 1, start_port + 500))  # حد معقول للمسح
            }
            
            for future in as_completed(future_to_port):
                try:
                    port, is_connected, service_info = future.result()
                    if is_connected:
                        connected_ports.append(port)
                        self.logger.info(f"✅ منفذ متصل: {port} - {service_info}")
                        
                        if len(connected_ports) >= count:
                            break
                            
                except Exception as e:
                    continue
        
        # إذا لم نجد منافذ متصلة كافية، نضيف منافذ شائعة متاحة
        if len(connected_ports) < count:
            self.logger.info("🔄 إضافة منافذ شائعة متاحة...")
            additional_ports = self.get_common_available_ports(count - len(connected_ports))
            connected_ports.extend(additional_ports)
        
        # إزالة التكرارات وترتيب المنافذ
        unique_ports = list(dict.fromkeys(connected_ports))
        final_ports = unique_ports[:count]
        
        self.logger.info(f"🎯 تم تجميع {len(final_ports)} منفذ موصى به")
        return final_ports
    
    def get_common_available_ports(self, count: int) -> List[int]:
        """الحصول على منافذ شائعة متاحة"""
        common_ports = [
            # نطاق تطوير ويب
            3640, 3641, 5002, 5003, 5004, 3645,
            8000, 8001, 8002, 8003, 8004, 8005,
            3000, 3001, 3002, 3003, 3004, 3005,
            8080, 8081, 8082, 8083, 8084, 8085,
            
            # نطاقات تطوير إضافية
            7000, 7001, 7002, 7003,
            9000, 9001, 9002, 9003,
            6000, 6001, 6002, 6003,
            
            # منافذ احتياطية
            4000, 4001, 4002,
            3500, 3501, 3502,
            4500, 4501, 4502
        ]
        
        available_ports = []
        for port in common_ports:
            if len(available_ports) >= count:
                break
            if self.is_port_available(port):
                available_ports.append(port)
                with self.lock:
                    self.used_ports.add(port)
        
        return available_ports
    
    def find_best_available_port(self, preferred_ports: List[int] = None) -> int:
        """إيجاد أفضل منفذ متاح مع الأفضلية للمنافذ المفضلة"""
        if preferred_ports:
            # التحقق أولاً من المنافذ المفضلة
            for port in preferred_ports:
                if self.is_port_available(port):
                    with self.lock:
                        self.used_ports.add(port)
                    self.logger.info(f"🎯 تم اختيار المنفذ المفضل {port}")
                    return port
        
        # إذا لم توجد منافذ مفضلة متاحة، البحث عن منفذ جديد
        return self.find_available_port()
    
    def get_detailed_port_report(self, scan_samples: int = 10) -> Dict:
        """تقرير مفصل عن حالة المنافذ"""
        self.logger.info("📊 إنشاء تقرير مفصل عن المنافذ...")
        
        # عينات من نطاقات مختلفة
        sample_ranges = [
            (1000, 1500),   # منافذ نظام منخفضة
            (3000, 3500),   # تطوير ويب
            (3640, 5500),   # تطوير بايثون
            (8000, 8500),   # تطوير عام
            (9000, 9500)    # تطبيقات متنوعة
        ]
        
        port_samples = []
        for start, end in sample_ranges:
            sample = self.get_recommended_ports(2, (start, end))
            port_samples.extend(sample)
        
        recommended_ports = self.get_recommended_ports(15)
        available_recommended = [port for port in recommended_ports if self.is_port_available(port)]
        
        return {
            "total_recommended_ports": len(recommended_ports),
            "available_recommended_ports": available_recommended,
            "used_ports_by_manager": list(self.used_ports),
            "port_samples_from_ranges": port_samples,
            "next_available_port": self.find_available_port(1000, 1) if available_recommended else None,
            "scan_config": {
                "max_workers": self.max_workers,
                "timeout": self.scan_timeout
            }
        }
    
    def release_port(self, port: int) -> bool:
        """تحرير منفذ محجوز"""
        with self.lock:
            if port in self.used_ports:
                self.used_ports.remove(port)
                self.logger.info(f"🔓 تم تحرير المنفذ {port}")
                return True
        return False
    
    def bulk_check_ports(self, ports: List[int]) -> Dict[int, bool]:
        """فحص مجموعة من المنافذ مرة واحدة"""
        results = {}
        
        with ThreadPoolExecutor(max_workers=min(len(ports), self.max_workers)) as executor:
            future_to_port = {
                executor.submit(self.is_port_available, port): port 
                for port in ports
            }
            
            for future in as_completed(future_to_port):
                port = future_to_port[future]
                try:
                    results[port] = future.result()
                except Exception as e:
                    results[port] = False
        
        return results

# استخدام فوري
port_manager = PortManager()

# دوال مساعدة للاستخدام المباشر
def find_available_port_in_range(start: int = 1000, end: int = 9999) -> int:
    """إيجاد منفذ متاح في نطاق محدد"""
    return port_manager.find_available_port(start, end - start + 1)

def get_quick_recommended_ports(count: int = 10) -> List[int]:
    """الحصول على منافذ موصى بها بسرعة"""
    return port_manager.get_recommended_ports(count, (3640, 6000))

# مثال على الاستخدام
if __name__ == "__main__":
    print("🔍 مدير المنافذ المتقدم - الإصدار المحسن")
    print("=" * 50)
    
    try:
        # البحث عن منافذ موصى بها
        recommended = port_manager.get_recommended_ports(8)
        print(f"🎯 المنافذ الموصى بها: {recommended}")
        
        # إيجاد أفضل منفذ متاح
        best_port = port_manager.find_best_available_port(recommended)
        print(f"✅ أفضل منفذ متاح: {best_port}")
        
        # فحص مجموعة من المنافذ
        test_ports = [3640, 8080, 3000, 5432, 6379]
        bulk_results = port_manager.bulk_check_ports(test_ports)
        print(f"🔍 نتائج فحص المنافذ: {bulk_results}")
        
        # تقرير مفصل
        report = port_manager.get_detailed_port_report()
        print(f"📊 التقرير المفصل:")
        print(f"   - المنافذ المتاحة: {report['available_recommended_ports']}")
        print(f"   - المنافذ المحجوزة: {report['used_ports_by_manager']}")
        print(f"   - المنفذ التالي المتاح: {report['next_available_port']}")
        
    except Exception as e:
        print(f"❌ خطأ: {e}")
        
