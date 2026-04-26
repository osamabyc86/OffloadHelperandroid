#!/usr/bin/env python3
# wan_peer_test.py - نظام اختبار سيرفرات الموزعة المحسّن

import requests
import socket
import time
import json
import subprocess
import sys
import threading
import concurrent.futures
from typing import List, Dict, Any, Tuple, Optional
from dataclasses import dataclass
from enum import Enum
import ipaddress
import logging
from urllib.parse import urljoin

try:
    from flask import Flask, request, jsonify
    HAS_FLASK = True
except ImportError:
    HAS_FLASK = False
    print("⚠️ تحذير: Flask غير مثبت - بعض الميزات معطلة")

class ServerStatus(Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    SLOW = "slow"
    ERROR = "error"

@dataclass
class ServerInfo:
    """معلومات السيرفر"""
    ip: str
    port: int
    name: str
    type: str = "unknown"
    priority: int = 1

@dataclass
class TestResult:
    """نتيجة اختبار السيرفر"""
    server: ServerInfo
    status: ServerStatus
    response_time: float
    data: Optional[Dict] = None
    error: Optional[str] = None

class NetworkTester:
    """مختبر شبكة محسّن للسيرفرات الموزعة"""
    
    def __init__(self, timeout: float = 5.0, max_workers: int = 10):
        self.setup_logging()
        self.timeout = timeout
        self.max_workers = max_workers
        self.results: List[TestResult] = []
        
        # قائمة السيرفرات الافتراضية
        self.default_servers = [
            # السيرفرات الخارجية
            ServerInfo(ip="89.111.171.92", port=7520, name="السيرفر الخارجي الرئيسي", type="external", priority=1),
            ServerInfo(ip="176.28.159.79", port=7520, name="السيرفر الاحتياطي 1", type="external", priority=2),
            ServerInfo(ip="167.28.156.149", port=7520, name="السيرفر الاحتياطي 2", type="external", priority=3),
            
            # السيرفرات المحلية الشائعة
            ServerInfo(ip="localhost", port=8080, name="السيرفر المحلي 8080", type="local", priority=1),
            ServerInfo(ip="127.0.0.1", port=8080, name="السيرفر المحلي 127.0.0.1", type="local", priority=1),
            ServerInfo(ip="localhost", port=5000, name="السيرفر المحلي 5000", type="local", priority=2),
            ServerInfo(ip="127.0.0.1", port=5000, name="السيرفر المحلي 5000", type="local", priority=2),
            ServerInfo(ip="localhost", port=8000, name="السيرفر المحلي 8000", type="local", priority=3),
            ServerInfo(ip="127.0.0.1", port=8000, name="السيرفر المحلي 8000", type="local", priority=3),
            ServerInfo(ip="localhost", port=3000, name="السيرفر المحلي 3000", type="local", priority=4),
            ServerInfo(ip="localhost", port=7521, name="نظام المهام الموزع", type="local", priority=1),
        ]
    
    def setup_logging(self):
        """إعداد نظام التسجيل"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('logs/wan_peer_test.log', encoding='utf-8'),
                logging.StreamHandler(sys.stdout)
            ]
        )
        self.logger = logging.getLogger('NetworkTester')
    
    def get_local_ip(self) -> str:
        """الحصول على عنوان IP المحلي بشكل موثوق"""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                return s.getsockname()[0]
        except Exception as e:
            self.logger.warning(f"فشل الحصول على IP المحلي: {e}")
            return "127.0.0.1"
    
    def get_network_info(self) -> Dict[str, Any]:
        """الحصول على معلومات الشبكة"""
        try:
            hostname = socket.gethostname()
            local_ip = self.get_local_ip()
            
            return {
                "hostname": hostname,
                "local_ip": local_ip,
                "network": ".".join(local_ip.split(".")[:-1]) + ".0/24",
                "timestamp": time.time()
            }
        except Exception as e:
            self.logger.error(f"خطأ في الحصول على معلومات الشبكة: {e}")
            return {}
    
    def test_server_connection(self, server: ServerInfo) -> TestResult:
        """اختبار اتصال بسيرفر معين"""
        task = {
            "task": "add",
            "a": 15,
            "b": 7,
            "timestamp": time.time()
        }
        
        endpoints_to_try = [
            f"http://{server.ip}:{server.port}/run_task",
            f"http://{server.ip}:{server.port}/task",
            f"http://{server.ip}:{server.port}/execute",
            f"http://{server.ip}:{server.port}/api/task"
        ]
        
        for endpoint in endpoints_to_try:
            try:
                start_time = time.time()
                response = requests.post(
                    endpoint, 
                    json=task, 
                    timeout=self.timeout,
                    headers={'Content-Type': 'application/json'}
                )
                response_time = (time.time() - start_time) * 1000  # ملي ثانية
                
                if response.status_code == 200:
                    data = response.json()
                    if 'result' in data or 'status' in data:
                        status = ServerStatus.SLOW if response_time > 1000 else ServerStatus.ONLINE
                        return TestResult(
                            server=server,
                            status=status,
                            response_time=response_time,
                            data=data
                        )
                
            except requests.exceptions.ConnectionError:
                continue
            except requests.exceptions.Timeout:
                return TestResult(
                    server=server,
                    status=ServerStatus.SLOW,
                    response_time=self.timeout * 1000,
                    error="انتهت مهلة الاتصال"
                )
            except Exception as e:
                continue
        
        # محاولة اختبار الصحة إذا فشلت المهمة
        health_endpoints = [
            f"http://{server.ip}:{server.port}/health",
            f"http://{server.ip}:{server.port}/status",
            f"http://{server.ip}:{server.port}/"
        ]
        
        for endpoint in health_endpoints:
            try:
                response = requests.get(endpoint, timeout=2)
                if response.status_code == 200:
                    return TestResult(
                        server=server,
                        status=ServerStatus.ONLINE,
                        response_time=0,
                        data={"health": "available", "task_endpoint": "unknown"}
                    )
            except:
                continue
        
        return TestResult(
            server=server,
            status=ServerStatus.OFFLINE,
            response_time=0,
            error="لا يمكن الوصول إلى السيرفر"
        )
    
    def test_servers_concurrent(self, servers: List[ServerInfo]) -> List[TestResult]:
        """اختبار سيرفرات متعددة بالتزامن"""
        self.logger.info(f"بدء اختبار {len(servers)} سيرفر بالتزامن...")
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_server = {
                executor.submit(self.test_server_connection, server): server 
                for server in servers
            }
            
            results = []
            for future in concurrent.futures.as_completed(future_to_server):
                server = future_to_server[future]
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    results.append(TestResult(
                        server=server,
                        status=ServerStatus.ERROR,
                        response_time=0,
                        error=f"خطأ في الاختبار: {str(e)}"
                    ))
        
        return results
    
    def quick_network_scan(self, network: str = None, ports: List[int] = None) -> List[ServerInfo]:
        """مسح شبكة سريع وذكي"""
        if network is None:
            local_ip = self.get_local_ip()
            network = ".".join(local_ip.split(".")[:-1]) + ".0/24"
        
        if ports is None:
            ports = [8080, 5000, 8000, 3000, 7521, 7520, 8081, 8082]
        
        self.logger.info(f"بدء مسح الشبكة: {network} على المنافذ: {ports}")
        
        discovered_servers = []
        network_obj = ipaddress.IPv4Network(network, strict=False)
        
        # مسح المنافذ الشائعة أولاً على عناوين محددة
        common_ips = [
            str(network_obj.network_address + 1),  # router عادة
            self.get_local_ip(),  # الجهاز الحالي
            str(network_obj.broadcast_address - 1),  # آخر عنوان
        ]
        
        # إضافة بعض العناوين الشائعة
        for i in [10, 20, 50, 100, 150, 200]:
            ip = str(network_obj.network_address + i)
            common_ips.append(ip)
        
        # اختبار العناوين الشائعة أولاً
        test_servers = []
        for ip in common_ips:
            for port in ports:
                test_servers.append(ServerInfo(
                    ip=ip, port=port, name=f"جهاز شبكة {ip}:{port}", type="discovered"
                ))
        
        # اختبار سريع بالتزامن
        results = self.test_servers_concurrent(test_servers)
        
        for result in results:
            if result.status in [ServerStatus.ONLINE, ServerStatus.SLOW]:
                discovered_servers.append(result.server)
                self.logger.info(f"✅ اكتشاف سيرفر: {result.server.ip}:{result.server.port}")
        
        return discovered_servers
    
    def create_test_server(self, port: int = 5000) -> bool:
        """إنشاء سيرفر اختبار محلي"""
        if not HAS_FLASK:
            self.logger.error("Flask غير مثبت - لا يمكن إنشاء سيرفر اختبار")
            return False
        
        try:
            app = Flask(__name__)
            
            @app.route('/run_task', methods=['POST'])
            def run_task():
                try:
                    data = request.get_json()
                    if data and data.get('task') == 'add':
                        result = data.get('a', 0) + data.get('b', 0)
                        return jsonify({
                            'result': result,
                            'status': 'success',
                            'server': 'local_test_server',
                            'timestamp': time.time()
                        })
                    return jsonify({'error': 'Invalid task'}), 400
                except Exception as e:
                    return jsonify({'error': str(e)}), 500
            
            @app.route('/health', methods=['GET'])
            def health():
                return jsonify({
                    'status': 'healthy', 
                    'server': 'local_test',
                    'timestamp': time.time()
                })
            
            @app.route('/task', methods=['POST', 'GET'])
            def task():
                if request.method == 'POST':
                    data = request.get_json()
                    if data and data.get('task') == 'add':
                        result = data.get('a', 0) + data.get('b', 0)
                        return jsonify({'result': result})
                return jsonify({
                    'message': 'Task endpoint', 
                    'method': request.method,
                    'endpoints': ['/run_task', '/health', '/task']
                })
            
            # تشغيل في خيط منفصل
            def run_server():
                app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
            
            server_thread = threading.Thread(target=run_server, daemon=True)
            server_thread.start()
            
            # الانتظار قليلاً للتأكد من بدء التشغيل
            time.sleep(2)
            
            # اختبار السيرفر
            test_server = ServerInfo(ip="localhost", port=port, name="سيرفر اختبار محلي", type="test")
            result = self.test_server_connection(test_server)
            
            if result.status == ServerStatus.ONLINE:
                self.logger.info(f"✅ تم تشغيل سيرفر الاختبار على http://localhost:{port}")
                return True
            else:
                self.logger.error(f"❌ فشل تشغيل سيرفر الاختبار")
                return False
                
        except Exception as e:
            self.logger.error(f"خطأ في إنشاء سيرفر الاختبار: {e}")
            return False
    
    def generate_report(self, results: List[TestResult]) -> Dict[str, Any]:
        """إنشاء تقرير مفصل عن النتائج"""
        online_servers = [r for r in results if r.status == ServerStatus.ONLINE]
        slow_servers = [r for r in results if r.status == ServerStatus.SLOW]
        offline_servers = [r for r in results if r.status == ServerStatus.OFFLINE]
        
        avg_response_time = 0
        if online_servers:
            avg_response_time = sum(r.response_time for r in online_servers) / len(online_servers)
        
        return {
            "summary": {
                "total_tested": len(results),
                "online_servers": len(online_servers),
                "slow_servers": len(slow_servers),
                "offline_servers": len(offline_servers),
                "success_rate": (len(online_servers) + len(slow_servers)) / len(results) * 100,
                "average_response_time_ms": round(avg_response_time, 2)
            },
            "online_servers": [
                {
                    "name": r.server.name,
                    "ip": r.server.ip,
                    "port": r.server.port,
                    "response_time_ms": round(r.response_time, 2),
                    "type": r.server.type
                }
                for r in online_servers
            ],
            "slow_servers": [
                {
                    "name": r.server.name,
                    "ip": r.server.ip,
                    "port": r.server.port,
                    "response_time_ms": round(r.response_time, 2),
                    "type": r.server.type
                }
                for r in slow_servers
            ],
            "timestamp": time.time()
        }
    
    def print_results(self, results: List[TestResult]):
        """طباعة النتائج بشكل منظم"""
        print("\n" + "="*60)
        print("📊 نتائج اختبار السيرفرات")
        print("="*60)
        
        online_servers = [r for r in results if r.status == ServerStatus.ONLINE]
        slow_servers = [r for r in results if r.status == ServerStatus.SLOW]
        offline_servers = [r for r in results if r.status == ServerStatus.OFFLINE]
        
        print(f"\n✅ السيرفرات النشطة ({len(online_servers)}):")
        for result in online_servers:
            print(f"   🌐 {result.server.name}")
            print(f"      📍 {result.server.ip}:{result.server.port}")
            print(f"      ⚡ {result.response_time:.2f}ms")
            if result.data and 'result' in result.data:
                print(f"      🔢 النتيجة: {result.data['result']}")
            print()
        
        if slow_servers:
            print(f"🐌 السيرفرات البطيئة ({len(slow_servers)}):")
            for result in slow_servers:
                print(f"   🌐 {result.server.name} - {result.response_time:.2f}ms")
        
        if offline_servers:
            print(f"❌ السيرفرات غير المتاحة ({len(offline_servers)}):")
            for result in offline_servers:
                print(f"   ❌ {result.server.name} - {result.error}")
    
    def interactive_menu(self):
        """قائمة تفاعلية للمستخدم"""
        while True:
            print("\n" + "="*50)
            print("🚀 نظام اختبار السيرفرات الموزعة")
            print("="*50)
            print(f"📍 عنوان IP المحلي: {self.get_local_ip()}")
            
            print("\n📋 الخيارات المتاحة:")
            print("1. 🔍 اختبار السيرفرات الافتراضية")
            print("2. 🌐 مسح الشبكة المحلية")
            print("3. 🖥️ تشغيل سيرفر اختبار محلي")
            print("4. ➕ إضافة سيرفر مخصص")
            print("5. 📊 عرض الإحصائيات")
            print("6. 🚪 خروج")
            
            choice = input("\nاختر خياراً (1-6): ").strip()
            
            if choice == "1":
                self.run_default_test()
            elif choice == "2":
                self.run_network_scan()
            elif choice == "3":
                self.run_test_server()
            elif choice == "4":
                self.add_custom_server()
            elif choice == "5":
                self.show_statistics()
            elif choice == "6":
                print("👋 مع السلامة!")
                break
            else:
                print("❌ خيار غير صحيح")
    
    def run_default_test(self):
        """اختبار السيرفرات الافتراضية"""
        print("\n🔍 اختبار السيرفرات الافتراضية...")
        results = self.test_servers_concurrent(self.default_servers)
        self.print_results(results)
        
        report = self.generate_report(results)
        print(f"\n📈 الإحصاءات: {report['summary']['online_servers']}/{report['summary']['total_tested']} نشط")
    
    def run_network_scan(self):
        """تشغيل مسح الشبكة"""
        print("\n🌐 مسح الشبكة المحلية...")
        discovered = self.quick_network_scan()
        
        if discovered:
            print(f"\n✅ تم اكتشاف {len(discovered)} سيرفر:")
            for server in discovered:
                print(f"   🌐 {server.ip}:{server.port}")
        else:
            print("❌ لم يتم اكتشاف أي سيرفرات")
    
    def run_test_server(self):
        """تشغيل سيرفر اختبار"""
        port = input("أدخل رقم المنفذ (افتراضي 5000): ").strip()
        port = int(port) if port.isdigit() else 5000
        
        if self.create_test_server(port):
            print(f"✅ تم تشغيل سيرفر الاختبار على المنفذ {port}")
        else:
            print("❌ فشل تشغيل سيرفر الاختبار")
    
    def add_custom_server(self):
        """إضافة سيرفر مخصص"""
        ip = input("أدخل عنوان IP: ").strip()
        port = input("أدخل رقم المنفذ: ").strip()
        name = input("أدخل اسم السيرفر (اختياري): ").strip() or "سيرفر مخصص"
        
        if ip and port.isdigit():
            server = ServerInfo(ip=ip, port=int(port), name=name, type="custom")
            self.default_servers.append(server)
            print("✅ تم إضافة السيرفر الجديد")
            
            # اختبار السيرفر المضاف
            result = self.test_server_connection(server)
            status_icon = "✅" if result.status == ServerStatus.ONLINE else "❌"
            print(f"{status_icon} حالة السيرفر: {result.status.value}")
        else:
            print("❌ بيانات غير صحيحة")
    
    def show_statistics(self):
        """عرض الإحصائيات"""
        network_info = self.get_network_info()
        print(f"\n📊 إحصائيات النظام:")
        print(f"   🖥️  اسم الجهاز: {network_info.get('hostname', 'غير معروف')}")
        print(f"   🌐 IP المحلي: {network_info.get('local_ip', 'غير معروف')}")
        print(f"   📶 الشبكة: {network_info.get('network', 'غير معروف')}")

def main():
    """الدالة الرئيسية"""
    try:
        tester = NetworkTester(timeout=5.0, max_workers=15)
        
        if len(sys.argv) > 1:
            # وضع الأوامر
            if sys.argv[1] == "test":
                tester.run_default_test()
            elif sys.argv[1] == "scan":
                tester.run_network_scan()
            elif sys.argv[1] == "server":
                port = int(sys.argv[2]) if len(sys.argv) > 2 else 5000
                tester.create_test_server(port)
                input("اضغط Enter لإيقاف السيرفر...")
            else:
                print("❌ أمر غير معروف")
        else:
            # الوضع التفاعلي
            tester.interactive_menu()
            
    except KeyboardInterrupt:
        print("\n⏹️ تم إيقاف البرنامج بواسطة المستخدم")
    except Exception as e:
        print(f"❌ خطأ غير متوقع: {e}")
        logging.error(f"خطأ في التنفيذ: {e}")

if __name__ == "__main__":
    main()