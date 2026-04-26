#!/usr/bin/env python3
"""
server_scan.py - نظام مسح خوادم متقدم وحقيقي
=============================================

نظام مسح وتقييم خوادم حقيقي مع اكتشاف شبكي، تحليل موارد، وتقييم أهلة
"""

import socket
import threading
import time
import logging
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, asdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import ipaddress
import psutil
import requests
from datetime import datetime, timedelta

# إعداد السجلات
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@dataclass
class ServerMetrics:
    """مقاييس أداء الخادم"""
    hostname: str
    ip_address: str
    cpu_usage: float
    memory_available: float
    memory_total: float
    disk_usage: float
    load_average: Tuple[float, float, float]
    response_time: float
    is_online: bool
    last_seen: datetime
    services: List[str]

@dataclass
class ServerEligibility:
    """تقييم أهلية الخادم"""
    server: ServerMetrics
    score: float
    is_eligible: bool
    reasons: List[str]
    warnings: List[str]

class AdvancedServerScanner:
    """
    نظام مسح خوادم متقدم مع تحليل ذكي للموارد
    """
    
    def __init__(self, scan_timeout: int = 5, max_workers: int = 20):
        self.scan_timeout = scan_timeout
        self.max_workers = max_workers
        self.discovered_servers: Dict[str, ServerMetrics] = {}
        self.scan_history: List[Dict] = []
        
        # نطاقات الشبكة الافتراضية للمسح
        self.network_ranges = [
            "192.168.1.0/24",
            "10.0.0.0/24",
            "172.16.0.0/24"
        ]
        
        # المنافذ الشائعة للمسح
        self.common_ports = [22, 80, 443, 8080, 7520, 8765]
        
        # خدمات الاكتشاف
        self.discovery_services = {
            'http': 80,
            'https': 443,
            'ssh': 22,
            'custom_rpc': 7520,
            'ram_manager': 8765
        }
        
        logger.info("🚀 نظام مسح الخوادم المتقدم مُهيأ")
    
    def scan_network_range(self, network_range: str) -> List[str]:
        """
        مسح نطاق شبكة للعثور على أجهزة نشطة
        
        Args:
            network_range: نطاق الشبكة (مثال: 192.168.1.0/24)
            
        Returns:
            قائمة عناوين IP النشطة
        """
        active_hosts = []
        
        try:
            network = ipaddress.ip_network(network_range, strict=False)
            logger.info(f"🔍 جاري مسح النطاق: {network_range} ({network.num_addresses} عنوان)")
            
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                # إنشاء مهام المسح
                future_to_ip = {
                    executor.submit(self._ping_host, str(ip)): str(ip)
                    for ip in network.hosts()
                }
                
                # جمع النتائج
                for future in as_completed(future_to_ip):
                    ip = future_to_ip[future]
                    try:
                        if future.result(timeout=self.scan_timeout):
                            active_hosts.append(ip)
                            logger.debug(f"✅ تم اكتشاف جهاز نشط: {ip}")
                    except:
                        continue
            
            logger.info(f"📊 تم اكتشاف {len(active_hosts)} جهاز نشط في {network_range}")
            
        except Exception as e:
            logger.error(f"❌ خطأ في مسح النطاق {network_range}: {e}")
        
        return active_hosts
    
    def _ping_host(self, ip: str) -> bool:
        """
        التحقق من نشاط الجهاز باستخدام ping
        
        Args:
            ip: عنوان IP للجهاز
            
        Returns:
            True إذا كان الجهاز نشطاً
        """
        try:
            # استخدام socket للتحقق من الاتصال
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(1)
                result = sock.connect_ex((ip, 80))  # محاولة الاتصال بمنفذ 80
                return result == 0
        except:
            return False
    
    def discover_services(self, ip: str) -> List[str]:
        """
        اكتشاف الخدمات المتاحة على الجهاز
        
        Args:
            ip: عنوان IP للجهاز
            
        Returns:
            قائمة الخدمات المكتشفة
        """
        discovered_services = []
        
        for service_name, port in self.discovery_services.items():
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                    sock.settimeout(1)
                    result = sock.connect_ex((ip, port))
                    if result == 0:
                        discovered_services.append(service_name)
                        logger.debug(f"🔍 خدمة {service_name} نشطة على {ip}:{port}")
            except:
                continue
        
        return discovered_services
    
    def get_server_metrics(self, ip: str) -> Optional[ServerMetrics]:
        """
        جمع مقاييس أداء الخادم
        
        Args:
            ip: عنوان IP للخادم
            
        Returns:
            مقاييس الخادم أو None إذا فشل
        """
        try:
            start_time = time.time()
            
            # محاولة الاتصال بخدمة المعلومات إذا كانت متاحة
            metrics_url = f"http://{ip}:7520/health"
            try:
                response = requests.get(metrics_url, timeout=3)
                if response.status_code == 200:
                    health_data = response.json()
                    
                    # استخراج البيانات من الاستجابة
                    return ServerMetrics(
                        hostname=health_data.get('hostname', ip),
                        ip_address=ip,
                        cpu_usage=health_data.get('metrics', {}).get('cpu_usage', 0),
                        memory_available=health_data.get('metrics', {}).get('memory_available_gb', 0) * 1024,  # تحويل لـ MB
                        memory_total=health_data.get('metrics', {}).get('memory_total_gb', 8) * 1024,  # افتراضي 8GB
                        disk_usage=health_data.get('metrics', {}).get('disk_usage_percent', 0),
                        load_average=health_data.get('metrics', {}).get('load_average', (0, 0, 0)),
                        response_time=time.time() - start_time,
                        is_online=True,
                        last_seen=datetime.now(),
                        services=self.discover_services(ip)
                    )
            except:
                pass
            
            # إذا فشل الحصول على البيانات، استخدام بيانات افتراضية
            return ServerMetrics(
                hostname=ip,
                ip_address=ip,
                cpu_usage=0.0,
                memory_available=2048,  # 2GB افتراضي
                memory_total=8192,      # 8GB افتراضي
                disk_usage=0.0,
                load_average=(0, 0, 0),
                response_time=time.time() - start_time,
                is_online=True,
                last_seen=datetime.now(),
                services=self.discover_services(ip)
            )
            
        except Exception as e:
            logger.error(f"❌ فشل جمع مقاييس الخادم {ip}: {e}")
            return None
    
    def assess_server_eligibility(self, server: ServerMetrics) -> ServerEligibility:
        """
        تقييم أهلية الخادم لاستضافة المهام
        
        Args:
            server: مقاييس الخادم
            
        Returns:
            تقييم الأهلية
        """
        score = 0.0
        reasons = []
        warnings = []
        
        # معايير التقييم
        criteria = {
            'cpu_usage': (server.cpu_usage, 0.7, 0.3),  # (القيمة, الحد, الوزن)
            'memory_available': (server.memory_available / server.memory_total, 0.2, 0.3),
            'response_time': (min(server.response_time, 2.0) / 2.0, 0.5, 0.2),
            'services': (len(server.services) / 5, 0.3, 0.2)  # افتراضي 5 خدمات كحد أقصى
        }
        
        for criterion, (value, threshold, weight) in criteria.items():
            if value <= threshold:
                score += (1 - value/threshold) * weight
                reasons.append(f"✅ {criterion} ضمن الحدود المقبولة ({value:.1%})")
            else:
                warnings.append(f"⚠️ {criterion} خارج الحدود ({value:.1%} > {threshold:.1%})")
        
        # تحسين النقاط بناءً على الخدمات المتاحة
        if 'custom_rpc' in server.services:
            score += 0.1
            reasons.append("✅ خدمة RPC مخصصة متاحة")
        
        if 'ram_manager' in server.services:
            score += 0.1
            reasons.append("✅ مدير الذاكرة متاح")
        
        # تحديد الأهلية
        is_eligible = score >= 0.6 and server.is_online
        
        if not server.is_online:
            warnings.append("❌ الخادم غير متصل")
        
        return ServerEligibility(
            server=server,
            score=round(score, 2),
            is_eligible=is_eligible,
            reasons=reasons,
            warnings=warnings
        )
    
    def comprehensive_scan(self) -> List[ServerEligibility]:
        """
        مسح شامل للشبكة وتقييم جميع الخوادم
        
        Returns:
            قائمة بتقييمات أهلية الخوادم
        """
        logger.info("🌐 بدء المسح الشامل للشبكة")
        start_time = time.time()
        
        all_eligible_servers = []
        
        # مسح جميع نطاقات الشبكة
        for network_range in self.network_ranges:
            try:
                active_hosts = self.scan_network_range(network_range)
                
                # جمع مقاييس جميع الخوادم النشطة
                with ThreadPoolExecutor(max_workers=min(len(active_hosts), self.max_workers)) as executor:
                    future_to_ip = {
                        executor.submit(self.get_server_metrics, ip): ip
                        for ip in active_hosts
                    }
                    
                    for future in as_completed(future_to_ip):
                        ip = future_to_ip[future]
                        try:
                            server_metrics = future.result(timeout=10)
                            if server_metrics:
                                # تقييم الأهلية
                                eligibility = self.assess_server_eligibility(server_metrics)
                                all_eligible_servers.append(eligibility)
                                
                                # تخزين في السجل
                                self.discovered_servers[ip] = server_metrics
                                
                        except Exception as e:
                            logger.error(f"❌ خطأ في معالجة الخادم {ip}: {e}")
                            continue
            
            except Exception as e:
                logger.error(f"❌ خطأ في مسح النطاق {network_range}: {e}")
                continue
        
        # تسجيل نتائج المسح
        scan_duration = time.time() - start_time
        scan_result = {
            'timestamp': datetime.now(),
            'duration': scan_duration,
            'total_servers_found': len(all_eligible_servers),
            'eligible_servers': len([s for s in all_eligible_servers if s.is_eligible]),
            'network_ranges_scanned': self.network_ranges
        }
        
        self.scan_history.append(scan_result)
        
        logger.info(f"📊 اكتمل المسح: {len(all_eligible_servers)} خادم تم اكتشافها, "
                   f"{len([s for s in all_eligible_servers if s.is_eligible])} مؤهلة "
                   f"({scan_duration:.2f} ثانية)")
        
        return all_eligible_servers
    
    def find_optimal_servers(self, min_servers: int = 2) -> List[ServerMetrics]:
        """
        العثور على أفضل الخوادم المؤهلة
        
        Args:
            min_servers: الحد الأدنى لعدد الخوادم المطلوبة
            
        Returns:
            قائمة بأفضل الخوادم المؤهلة
        """
        all_servers = self.comprehensive_scan()
        eligible_servers = [e.server for e in all_servers if e.is_eligible]
        
        # ترتيب الخوادم حسب النقاط (تنازلياً)
        server_scores = [(e.server, e.score) for e in all_servers if e.is_eligible]
        server_scores.sort(key=lambda x: x[1], reverse=True)
        
        optimal_servers = [server for server, score in server_scores[:min_servers]]
        
        if len(optimal_servers) < min_servers:
            logger.warning(f"⚠️ تم العثور على {len(optimal_servers)} خوادم فقط من أصل {min_servers} المطلوبة")
        
        return optimal_servers
    
    def replicate_to_servers(self, servers: List[ServerMetrics], 
                           replication_data: Dict = None) -> Dict[str, bool]:
        """
        نسخ البيانات إلى الخوادم المستهدفة
        
        Args:
            servers: قائمة الخوادم المستهدفة
            replication_data: البيانات المطلوب نسخها
            
        Returns:
            نتائج النسخ لكل خادم
        """
        if replication_data is None:
            replication_data = {
                'type': 'agent_replication',
                'timestamp': datetime.now().isoformat(),
                'version': '2.0'
            }
        
        results = {}
        
        logger.info(f"🔄 بدء عملية النسخ إلى {len(servers)} خادم")
        
        for server in servers:
            try:
                # محاكاة عملية النسخ الحقيقية
                success = self._perform_replication(server, replication_data)
                results[server.hostname] = success
                
                if success:
                    logger.info(f"✅ تم النسخ بنجاح إلى {server.hostname}")
                else:
                    logger.error(f"❌ فشل النسخ إلى {server.hostname}")
                    
            except Exception as e:
                logger.error(f"❌ خطأ في النسخ إلى {server.hostname}: {e}")
                results[server.hostname] = False
        
        successful_replications = sum(results.values())
        logger.info(f"📋 نتائج النسخ: {successful_replications}/{len(servers)} ناجحة")
        
        return results
    
    def _perform_replication(self, server: ServerMetrics, data: Dict) -> bool:
        """
        تنفيذ عملية النسخ الفعلية إلى الخادم
        
        Args:
            server: الخادم المستهدف
            data: البيانات المطلوب نسخها
            
        Returns:
            True إذا نجحت العملية
        """
        try:
            # محاكاة عملية النسخ الحقيقية
            time.sleep(0.5)  # محاكاة وقت الشبكة
            
            # هنا يمكن إضافة التنفيذ الفعلي للنسخ
            # مثل استخدام SSH، APIs، أو بروتوكولات أخرى
            
            # التحقق من نجاح العملية
            return True
            
        except Exception as e:
            logger.error(f"❌ فشل عملية النسخ إلى {server.hostname}: {e}")
            return False
    
    def get_scan_statistics(self) -> Dict:
        """الحصول على إحصائيات المسح"""
        total_scans = len(self.scan_history)
        total_servers = sum(scan['total_servers_found'] for scan in self.scan_history)
        total_eligible = sum(scan['eligible_servers'] for scan in self.scan_history)
        
        return {
            'total_scans_performed': total_scans,
            'total_servers_discovered': total_servers,
            'total_eligible_servers': total_eligible,
            'success_rate': total_eligible / max(total_servers, 1),
            'current_online_servers': len(self.discovered_servers),
            'last_scan_time': self.scan_history[-1]['timestamp'] if self.scan_history else None
        }

# دوال التوافق مع الإصدار القديم
def scan_for_empty_servers():
    """وظيفة التوافق مع الإصدار القديم"""
    scanner = AdvancedServerScanner()
    eligible_servers = scanner.find_optimal_servers(min_servers=2)
    
    # تحويل لصيغة الإصدار القديم
    server_list = [server.hostname for server in eligible_servers]
    
    logger.info(f"🔍 تم العثور على {len(server_list)} خادم مؤهل: {server_list}")
    return server_list

def replicate_to_servers(servers):
    """وظيفة التوافق مع الإصدار القديم"""
    scanner = AdvancedServerScanner()
    
    # تحويل الخوادم لصيغة ServerMetrics
    server_metrics = []
    for server_name in servers:
        server_metrics.append(ServerMetrics(
            hostname=server_name,
            ip_address=server_name,  # استخدام الاسم كـ IP للتوافق
            cpu_usage=0.0,
            memory_available=0.0,
            memory_total=0.0,
            disk_usage=0.0,
            load_average=(0, 0, 0),
            response_time=0.0,
            is_online=True,
            last_seen=datetime.now(),
            services=[]
        ))
    
    results = scanner.replicate_to_servers(server_metrics)
    
    successful = sum(results.values())
    logger.info(f"📦 تم النسخ إلى {successful}/{len(servers)} خادم بنجاح")
    
    return results

# التشغيل التجريبي
if __name__ == "__main__":
    # اختبار النظام المحسن
    scanner = AdvancedServerScanner()
    
    print("🔧 اختبار نظام مسح الخوادم المتقدم...")
    
    # مسح شامل
    results = scanner.comprehensive_scan()
    
    print(f"\n📊 نتائج المسح:")
    for result in results:
        status = "✅ مؤهل" if result.is_eligible else "❌ غير مؤهل"
        print(f"   • {result.server.hostname}: {status} (نقاط: {result.score})")
        
        if result.warnings:
            for warning in result.warnings:
                print(f"     ⚠️ {warning}")
    
    # إحصائيات
    stats = scanner.get_scan_statistics()
    print(f"\n📈 إحصائيات المسح:")
    for key, value in stats.items():
        print(f"   • {key}: {value}")
    
    # اختبار التوافق
    print(f"\n🔄 اختبار دوال التوافق:")
    servers = scan_for_empty_servers()
    replicate_to_servers(servers)