#!/usr/bin/env python3
# system_check.py - فحص شامل ومحسّن لحالة النظام الموزع

import time
import requests
import psutil
import threading
import logging
import socket
import subprocess
import sys
from typing import List, Tuple, Dict, Any, Optional
from pathlib import Path

# التهيئة العامة
DEFAULT_PORT = 7521  # افتراضي إذا لم يتم تحديده
CHECK_TIMEOUT = 5    # مهلة الفحص بالثواني

try:
    from offload_lib import discover_peers
    HAS_OFFLOAD_LIB = True
except ImportError:
    HAS_OFFLOAD_LIB = False
    print("⚠️ مكتبة offload_lib غير متوفرة - بعض الفحوصات معطلة")

try:
    from peer_discovery import PORT as DISCOVERY_PORT
    CURRENT_PORT = DISCOVERY_PORT
except:
    CURRENT_PORT = DEFAULT_PORT

class SystemChecker:
    """مدير فحص النظام المحسّن"""
    
    def __init__(self, port: int = None):
        self.port = port or CURRENT_PORT
        self.results: List[Tuple[str, bool, str]] = []
        self.setup_logging()
        self.start_time = time.time()
    
    def setup_logging(self):
        """إعداد نظام التسجيل"""
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            handlers=[
                logging.FileHandler("logs/system_check.log", encoding='utf-8'),
                logging.StreamHandler(sys.stdout)
            ]
        )
        self.logger = logging.getLogger('SystemChecker')
    
    def add_result(self, check_name: str, success: bool, details: str = ""):
        """إضافة نتيجة فحص"""
        self.results.append((check_name, success, details))
        status = "✅" if success else "❌"
        self.logger.info(f"{status} {check_name}: {details}")
        return success
    
    def check_system_resources(self) -> bool:
        """فحص موارد النظام المحلي بشكل مفصل"""
        self.logger.info("🔍 فحص موارد النظام المحلي...")
        
        try:
            # فحص المعالج
            cpu_percent = psutil.cpu_percent(interval=1)
            cpu_cores = psutil.cpu_count()
            cpu_freq = psutil.cpu_freq()
            
            # فحص الذاكرة
            memory = psutil.virtual_memory()
            swap = psutil.swap_memory()
            
            # فحص القرص
            disk = psutil.disk_usage('/')
            
            # تحليل النتائج
            cpu_ok = cpu_percent < 85
            memory_ok = memory.percent < 90
            disk_ok = disk.percent < 95
            
            details = (
                f"المعالج: {cpu_percent}% ({cpu_cores} نواة), "
                f"الذاكرة: {memory.percent}% ({memory.used//(1024**3)}GB/{memory.total//(1024**3)}GB), "
                f"القرص: {disk.percent}%"
            )
            
            return self.add_result("موارد النظام", cpu_ok and memory_ok and disk_ok, details)
            
        except Exception as e:
            return self.add_result("موارد النظام", False, f"خطأ في الفحص: {e}")
    
    def check_network_connectivity(self) -> bool:
        """فحص اتصال الشبكة"""
        self.logger.info("🌐 فحص اتصال الشبكة...")
        
        test_hosts = [
            ("8.8.8.8", "Google DNS"),
            ("1.1.1.1", "Cloudflare DNS"),
            ("localhost", "الخادم المحلي")
        ]
        
        successful_checks = 0
        details = []
        
        for host, description in test_hosts:
            try:
                socket.setdefaulttimeout(3)
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                    result = sock.connect_ex((host, 80 if host != "localhost" else self.port))
                    if result == 0:
                        successful_checks += 1
                        details.append(f"✅ {description}")
                    else:
                        details.append(f"❌ {description}")
            except Exception:
                details.append(f"❌ {description}")
        
        network_ok = successful_checks >= 2  # نجاح 2 من 3 على الأقل
        return self.add_result("اتصال الشبكة", network_ok, " | ".join(details))
    
    def check_local_server(self) -> bool:
        """فحص الخادم المحلي بشكل متقدم"""
        self.logger.info("🖥️ فحص الخادم المحلي...")
        
        endpoints_to_check = [
            f"http://localhost:{self.port}/health",
            f"http://localhost:{self.port}/status",
            f"http://localhost:{self.port}/"
        ]
        
        for endpoint in endpoints:
            try:
                response = requests.get(endpoint, timeout=CHECK_TIMEOUT)
                if response.status_code == 200:
                    # محاولة تحليل الرد إذا كان JSON
                    try:
                        data = response.json()
                        status_info = data.get('status', 'active')
                        return self.add_result("الخادم المحلي", True, 
                                            f"يعمل على port {self.port} - حالة: {status_info}")
                    except:
                        return self.add_result("الخادم المحلي", True, 
                                            f"يعمل على port {self.port}")
            except requests.exceptions.ConnectionError:
                continue
            except requests.exceptions.Timeout:
                continue
            except Exception as e:
                continue
        
        return self.add_result("الخادم المحلي", False, 
                             f"غير متاح على port {self.port} - تأكد من تشغيل server.py")
    
    def check_peer_discovery(self) -> bool:
        """فحص اكتشاف الأقران بشكل محسّن"""
        self.logger.info("🔍 فحص اكتشاف الأجهزة...")
        
        if not HAS_OFFLOAD_LIB:
            return self.add_result("اكتشاف الأجهزة", False, 
                                 "مكتبة offload_lib غير متوفرة")
        
        try:
            peers = discover_peers(timeout=3)
            if peers:
                peer_list = ", ".join([f"{peer.get('ip', 'unknown')}:{peer.get('port', 'unknown')}" 
                                     for peer in peers[:3]])  # عرض أول 3 فقط
                details = f"تم اكتشاف {len(peers)} جهاز: {peer_list}" + (
                    " و..." if len(peers) > 3 else ""
                )
                return self.add_result("اكتشاف الأجهزة", True, details)
            else:
                return self.add_result("اكتشاف الأجهزة", False, 
                                     "لم يتم اكتشاف أجهزة أخرى على الشبكة")
                
        except Exception as e:
            return self.add_result("اكتشاف الأجهزة", False, 
                                 f"خطأ في الاكتشاف: {str(e)}")
    
    def check_task_execution(self) -> bool:
        """فحص تنفيذ المهام بشكل شامل"""
        self.logger.info("⚡ اختبار تنفيذ المهام...")
        
        test_cases = [
            {"name": "مهمة بسيطة", "size": 2},
            {"name": "مهمة متوسطة", "size": 5},
            {"name": "معالجة بيانات", "size": 100}
        ]
        
        successful_tests = 0
        details = []
        
        for test in test_cases:
            try:
                if test["name"] == "معالجة بيانات":
                    from smart_tasks import data_processing
                    start_time = time.time()
                    result = data_processing(test["size"])
                    duration = time.time() - start_time
                else:
                    from smart_tasks import matrix_multiply
                    start_time = time.time()
                    result = matrix_multiply(test["size"])
                    duration = time.time() - start_time
                
                if result and "error" not in result:
                    successful_tests += 1
                    details.append(f"✅ {test['name']}: {duration:.2f}ث")
                else:
                    details.append(f"❌ {test['name']}: فشل")
                    
            except Exception as e:
                details.append(f"❌ {test['name']}: {str(e)}")
        
        tasks_ok = successful_tests >= 2  # نجاح 2 من 3 على الأقل
        return self.add_result("تنفيذ المهام", tasks_ok, " | ".join(details))
    
    def check_service_processes(self) -> bool:
        """فحص عمليات الخدمات النشطة"""
        self.logger.info("🔎 فحص عمليات الخدمات...")
        
        expected_services = ["python", "server.py", "peer_server.py"]
        found_services = []
        
        try:
            for process in psutil.process_iter(['name', 'cmdline']):
                try:
                    cmdline = process.info['cmdline'] or []
                    name = process.info['name'] or ''
                    
                    # البحث في سطر الأوامر عن الخدمات المتوقعة
                    for service in expected_services:
                        if any(service in str(arg) for arg in cmdline) or service in name:
                            found_services.append(service)
                            break
                            
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            
            # إزالة التكرارات
            found_services = list(set(found_services))
            details = f"الخدمات النشطة: {', '.join(found_services) if found_services else 'لا توجد'}"
            
            services_ok = len(found_services) >= 1  # خدمة واحدة على الأقل نشطة
            return self.add_result("عمليات الخدمات", services_ok, details)
            
        except Exception as e:
            return self.add_result("عمليات الخدمات", False, f"خطأ في الفحص: {e}")
    
    def check_port_availability(self) -> bool:
        """فحص توفر المنافذ"""
        self.logger.info("🔌 فحص المنافذ...")
        
        ports_to_check = [self.port, 7520, 7522]  # المنافذ المتوقعة
        
        available_ports = []
        details = []
        
        for port in ports_to_check:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                    sock.settimeout(1)
                    result = sock.connect_ex(('localhost', port))
                    if result == 0:
                        available_ports.append(port)
                        details.append(f"✅ {port}")
                    else:
                        details.append(f"❌ {port}")
            except Exception:
                details.append(f"❌ {port}")
        
        ports_ok = self.port in available_ports  # المنفذ الرئيسي يجب أن يكون متاحاً
        return self.add_result("توفر المنافذ", ports_ok, " | ".join(details))
    
    def generate_report(self) -> Dict[str, Any]:
        """إنشاء تقرير مفصل عن الفحص"""
        total_checks = len(self.results)
        passed_checks = sum(1 for _, success, _ in self.results if success)
        overall_status = passed_checks >= total_checks * 0.7  # 70% نجاح
        
        execution_time = time.time() - self.start_time
        
        report = {
            "overall_status": "✅ جيد" if overall_status else "❌ يحتاج اهتمام",
            "summary": {
                "total_checks": total_checks,
                "passed_checks": passed_checks,
                "failed_checks": total_checks - passed_checks,
                "success_rate": f"{(passed_checks/total_checks)*100:.1f}%",
                "execution_time": f"{execution_time:.2f} ثانية"
            },
            "detailed_results": [
                {
                    "check": name,
                    "status": "✅ ناجح" if success else "❌ فاشل",
                    "details": details
                }
                for name, success, details in self.results
            ],
            "recommendations": self.generate_recommendations()
        }
        
        return report
    
    def generate_recommendations(self) -> List[str]:
        """إنشاء توصيات بناءً على نتائج الفحص"""
        recommendations = []
        failed_checks = [name for name, success, _ in self.results if not success]
        
        if "الخادم المحلي" in failed_checks:
            recommendations.append("تشغيل: python server.py")
        
        if "اكتشاف الأجهزة" in failed_checks:
            recommendations.append("التحقق من إعدادات الشبكة والجدار الناري")
        
        if "تنفيذ المهام" in failed_checks:
            recommendations.append("التحقق من تثبيت المكتبات: pip install numpy")
        
        if "اتصال الشبكة" in failed_checks:
            recommendations.append("التحقق من اتصال الإنترنت وإعدادات الشبكة")
        
        if not recommendations:
            recommendations.append("كل شيء يعمل بشكل ممتاز! يمكنك متابعة الاستخدام العادي.")
        
        return recommendations
    
    def print_report(self, report: Dict[str, Any]):
        """طباعة التقرير بشكل منسق"""
        print("\n" + "="*60)
        print("📊 تقرير فحص النظام الشامل")
        print("="*60)
        
        print(f"\nالحالة العامة: {report['overall_status']}")
        
        summary = report['summary']
        print(f"\n📈 الإحصاءات:")
        print(f"   • إجمالي الفحوصات: {summary['total_checks']}")
        print(f"   • الفحوصات الناجحة: {summary['passed_checks']}")
        print(f"   • الفحوصات الفاشلة: {summary['failed_checks']}")
        print(f"   • معدل النجاح: {summary['success_rate']}")
        print(f"   • وقت التنفيذ: {summary['execution_time']}")
        
        print(f"\n🔍 النتائج التفصيلية:")
        for result in report['detailed_results']:
            print(f"   {result['status']} {result['check']}: {result['details']}")
        
        print(f"\n💡 التوصيات:")
        for i, recommendation in enumerate(report['recommendations'], 1):
            print(f"   {i}. {recommendation}")
        
        print("\n" + "="*60)
    
    def run_comprehensive_check(self):
        """تشغيل فحص شامل للنظام"""
        print("🚀 بدء الفحص الشامل للنظام الموزع...")
        print(f"🌐 المنفذ المستهدف: {self.port}")
        print("="*50)
        
        # تشغيل جميع الفحوصات
        checks = [
            self.check_system_resources,
            self.check_network_connectivity,
            self.check_local_server,
            self.check_peer_discovery,
            self.check_task_execution,
            self.check_service_processes,
            self.check_port_availability
        ]
        
        for check_func in checks:
            try:
                check_func()
                time.sleep(0.5)  # فاصل بين الفحوصات
            except Exception as e:
                self.logger.error(f"خطأ في تنفيذ الفحص {check_func.__name__}: {e}")
        
        # إنشاء وعرض التقرير
        report = self.generate_report()
        self.print_report(report)
        
        return report['overall_status'].startswith('✅')


def main():
    """الدالة الرئيسية"""
    try:
        # استخدام المنفذ من الإعدادات أو الافتراضي
        port = CURRENT_PORT
        
        checker = SystemChecker(port)
        success = checker.run_comprehensive_check()
        
        # كود الخروج بناءً على النتيجة
        sys.exit(0 if success else 1)
        
    except KeyboardInterrupt:
        print("\n⏹️ تم إيقاف الفحص بواسطة المستخدم")
        sys.exit(1)
    except Exception as e:
        print(f"❌ خطأ غير متوقع: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()