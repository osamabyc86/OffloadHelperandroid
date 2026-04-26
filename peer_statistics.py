#!/usr/bin/env python3
"""
نظام إحصاءات الأقران المحسن - الإصدار 2.0
تحليلات متقدمة للأجهزة المكتشفة مع تقارير شاملة
"""

from collections import Counter, defaultdict
import ipaddress
import json
import logging
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime
import statistics
import socket

# إعداد السجلات
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class NetworkStats:
    """إحصائيات الشبكة"""
    total_peers: int
    local_peers: int
    private_peers: int
    public_peers: int
    unique_ips: int
    subnets: Dict[str, int]
    ip_versions: Dict[str, int]
    countries: Dict[str, int]  # للمستقبل - تكامل مع GeoIP

@dataclass
class PeerAnalysis:
    """تحليل شامل للأقران"""
    network_stats: NetworkStats
    common_networks: List[Tuple[str, int]]
    risk_assessment: Dict[str, Any]
    recommendations: List[str]

class EnhancedPeerStatistics:
    """نظام إحصاءات أقران محسن"""
    
    def __init__(self):
        self.analysis_history = []
    
    def analyze_peers(self, discovered_peers: List[Dict]) -> PeerAnalysis:
        """
        تحليل شامل لقائمة الأقران المكتشفة
        
        Args:
            discovered_peers: قائمة الأقران المكتشفة
            
        Returns:
            PeerAnalysis: تحليل شامل مع التوصيات
        """
        if not discovered_peers:
            return self._empty_analysis()
        
        # استخراج وتصنيف البيانات
        ips = [peer.get('ip', 'unknown') for peer in discovered_peers]
        ip_counts = Counter(ips)
        
        # التحليل المتقدم
        network_stats = self._calculate_network_stats(discovered_peers, ip_counts)
        common_networks = self._find_common_networks(ip_counts)
        risk_assessment = self._assess_network_risks(discovered_peers)
        recommendations = self._generate_recommendations(network_stats, risk_assessment)
        
        analysis = PeerAnalysis(
            network_stats=network_stats,
            common_networks=common_networks,
            risk_assessment=risk_assessment,
            recommendations=recommendations
        )
        
        # حفظ في السجل
        self.analysis_history.append({
            'timestamp': datetime.now(),
            'analysis': analysis
        })
        
        return analysis
    
    def _calculate_network_stats(self, peers: List[Dict], ip_counts: Counter) -> NetworkStats:
        """حساب إحصائيات الشبكة المتقدمة"""
        local_count = 0
        private_count = 0
        public_count = 0
        subnets = defaultdict(int)
        ip_versions = defaultdict(int)
        
        for ip in ip_counts.keys():
            if ip == 'unknown':
                continue
                
            try:
                ip_obj = ipaddress.ip_address(ip)
                
                # تصنيف IP
                if ip_obj.is_loopback or ip == '127.0.0.1' or ip == 'localhost':
                    local_count += ip_counts[ip]
                    category = 'loopback'
                elif ip_obj.is_private:
                    private_count += ip_counts[ip]
                    category = 'private'
                    
                    # تحليل الشبكة الفرعية
                    if ip_obj.version == 4:
                        if ip.startswith('192.168.'):
                            subnet = '192.168.0.0/16'
                        elif ip.startswith('10.'):
                            subnet = '10.0.0.0/8'
                        elif ip.startswith('172.16.'):
                            subnet = '172.16.0.0/12'
                        else:
                            subnet = 'other_private'
                        subnets[subnet] += ip_counts[ip]
                    
                else:
                    public_count += ip_counts[ip]
                    category = 'public'
                
                # إصدار IP
                ip_versions[f'IPv{ip_obj.version}'] += ip_counts[ip]
                
            except ValueError as e:
                logger.warning(f"عنوان IP غير صالح: {ip} - {e}")
                continue
        
        return NetworkStats(
            total_peers=sum(ip_counts.values()),
            local_peers=local_count,
            private_peers=private_count,
            public_peers=public_count,
            unique_ips=len(ip_counts),
            subnets=dict(subnets),
            ip_versions=dict(ip_versions),
            countries={}  # يمكن إضافة تكامل GeoIP لاحقاً
        )
    
    def _find_common_networks(self, ip_counts: Counter) -> List[Tuple[str, int]]:
        """العثور على الشبكات الأكثر شيوعاً"""
        network_counts = defaultdict(int)
        
        for ip, count in ip_counts.items():
            if ip == 'unknown':
                continue
                
            try:
                ip_obj = ipaddress.ip_address(ip)
                if ip_obj.version == 4 and ip_obj.is_private:
                    # تجميع حسب الشبكة /24
                    network = ipaddress.IPv4Network(f"{ip}/24", strict=False)
                    network_counts[str(network)] += count
            except ValueError:
                continue
        
        return sorted(network_counts.items(), key=lambda x: x[1], reverse=True)[:10]
    
    def _assess_network_risks(self, peers: List[Dict]) -> Dict[str, Any]:
        """تقييم مخاطر الشبكة"""
        risks = {
            'public_peer_ratio': 0,
            'high_concentration_networks': [],
            'risk_level': 'low',
            'concerns': []
        }
        
        if not peers:
            return risks
        
        total_peers = len(peers)
        public_peers = sum(1 for peer in peers 
                          if not self._is_private_ip(peer.get('ip', '')))
        
        public_ratio = public_peers / total_peers
        risks['public_peer_ratio'] = public_ratio
        
        # تقييم مستوى المخاطرة
        if public_ratio > 0.5:
            risks['risk_level'] = 'high'
            risks['concerns'].append("نسبة عالية من الأقران العامة - مخاطر أمنية محتملة")
        elif public_ratio > 0.2:
            risks['risk_level'] = 'medium'
            risks['concerns'].append("نسبة متوسطة من الأقران العامة - مراقبة مستمرة مطلوبة")
        else:
            risks['risk_level'] = 'low'
        
        # اكتشاف التركيز العالي في شبكات معينة
        ip_counts = Counter(peer.get('ip', 'unknown') for peer in peers)
        for ip, count in ip_counts.items():
            if count > 5:  # أكثر من 5 أقران من نفس IP
                risks['high_concentration_networks'].append({
                    'ip': ip,
                    'count': count,
                    'type': 'public' if not self._is_private_ip(ip) else 'private'
                })
                risks['concerns'].append(f"تركيز عالي من الأقران من {ip} ({count} جهاز)")
        
        return risks
    
    def _generate_recommendations(self, stats: NetworkStats, risks: Dict) -> List[str]:
        """توليد توصيات بناءً على التحليل"""
        recommendations = []
        
        # توصيات بناءً على الإحصائيات
        if stats.public_peers > stats.private_peers:
            recommendations.append("🔒 زيادة عدد الأقران الخاصة لتقليل الاعتماد على الشبكات العامة")
        
        if stats.local_peers == 0 and stats.private_peers > 0:
            recommendations.append("🌐 النظر في إضافة أقران محلية لتحسين الأداء")
        
        if len(stats.subnets) > 3:
            recommendations.append("📈 تنوع جيد في الشبكات - استمر في اكتشاف شبكات جديدة")
        
        # توصيات بناءً على المخاطر
        if risks['risk_level'] == 'high':
            recommendations.append("⚠️ مراجعة سياسة الأمان للحد من الأقران العامة")
        
        if risks['high_concentration_networks']:
            recommendations.append("🔍 مراقبة الشبكات ذات التركيز العالي للأقران")
        
        if not recommendations:
            recommendations.append("✅ توزيع صحي للأقران - لا توجد توصيات عاجلة")
        
        return recommendations
    
    def _is_private_ip(self, ip: str) -> bool:
        """فحص إذا كان IP خاص"""
        try:
            ip_obj = ipaddress.ip_address(ip)
            return ip_obj.is_private
        except ValueError:
            return False
    
    def _empty_analysis(self) -> PeerAnalysis:
        """تحليل فارغ عندما لا توجد أقران"""
        return PeerAnalysis(
            network_stats=NetworkStats(0, 0, 0, 0, 0, {}, {}, {}),
            common_networks=[],
            risk_assessment={'risk_level': 'unknown', 'concerns': []},
            recommendations=["🔍 لم يتم اكتشاف أي أقران - تحقق من إعدادات الشبكة"]
        )
    
    def print_statistics(self, discovered_peers: List[Dict], detailed: bool = False):
        """
        طباعة إحصاءات الأقران بتنسيق منظم
        
        Args:
            discovered_peers: قائمة الأقران المكتشفة
            detailed: عرض تحليل مفصل
        """
        analysis = self.analyze_peers(discovered_peers)
        stats = analysis.network_stats
        
        print("\n" + "="*60)
        print("📊 إحصاءات الأقران المتقدمة")
        print("="*60)
        
        # الإحصائيات الأساسية
        print(f"\n🔢 الإحصائيات الأساسية:")
        print(f"   • إجمالي الأقران: {stats.total_peers}")
        print(f"   • العناوين الفريدة: {stats.unique_ips}")
        print(f"   • الأقران المحلية: {stats.local_peers}")
        print(f"   • الأقران الخاصة: {stats.private_peers}")
        print(f"   • الأقران العامة: {stats.public_peers}")
        
        # توزيع إصدارات IP
        if stats.ip_versions:
            print(f"\n🌐 توزيع إصدارات IP:")
            for version, count in stats.ip_versions.items():
                percentage = (count / stats.total_peers) * 100
                print(f"   • {version}: {count} ({percentage:.1f}%)")
        
        # الشبكات الفرعية
        if stats.subnets:
            print(f"\n🕸️  الشبكات الفرعية:")
            for subnet, count in stats.subnets.items():
                print(f"   • {subnet}: {count} جهاز")
        
        # الشبكات الشائعة
        if analysis.common_networks:
            print(f"\n📈 الشبكات الأكثر شيوعاً:")
            for network, count in analysis.common_networks[:5]:
                print(f"   • {network}: {count} جهاز")
        
        # تقييم المخاطر
        print(f"\n⚠️  تقييم المخاطر:")
        print(f"   • مستوى المخاطرة: {analysis.risk_assessment['risk_level'].upper()}")
        print(f"   • نسبة الأقران العامة: {analysis.risk_assessment['public_peer_ratio']:.1%}")
        
        if analysis.risk_assessment['concerns']:
            print(f"   • المخاوف:")
            for concern in analysis.risk_assessment['concerns']:
                print(f"     - {concern}")
        
        # التوصيات
        print(f"\n💡 التوصيات:")
        for recommendation in analysis.recommendations:
            print(f"   • {recommendation}")
        
        # التحليل المفصل
        if detailed:
            self._print_detailed_analysis(discovered_peers, analysis)
        
        print("\n" + "="*60)
    
    def _print_detailed_analysis(self, peers: List[Dict], analysis: PeerAnalysis):
        """طباعة التحليل المفصل"""
        print(f"\n🔍 التحليل المفصل:")
        
        # توزيع الأقران حسب IP
        ip_counts = Counter(peer.get('ip', 'unknown') for peer in peers)
        print(f"   • توزيع الأقران حسب IP:")
        for ip, count in ip_counts.most_common(10):
            category = "داخلي" if self._is_private_ip(ip) else "خارجي"
            if ip == '127.0.0.1' or ip == 'localhost':
                category = "محلي"
            print(f"     - {ip} ({category}): {count} جهاز")
        
        # معلومات إضافية
        if len(peers) > 0:
            avg_peers_per_ip = len(peers) / len(ip_counts)
            print(f"   • متوسط الأقران لكل IP: {avg_peers_per_ip:.2f}")
    
    def export_statistics(self, discovered_peers: List[Dict], 
                         format: str = 'json') -> Optional[str]:
        """
        تصدير الإحصاءات بتنسيقات مختلفة
        
        Args:
            discovered_peers: قائمة الأقران المكتشفة
            format: تنسيق التصدير ('json', 'text')
            
        Returns:
            البيانات المصدرة كنص
        """
        analysis = self.analyze_peers(discovered_peers)
        
        if format == 'json':
            export_data = {
                'timestamp': datetime.now().isoformat(),
                'analysis': {
                    'network_stats': {
                        'total_peers': analysis.network_stats.total_peers,
                        'local_peers': analysis.network_stats.local_peers,
                        'private_peers': analysis.network_stats.private_peers,
                        'public_peers': analysis.network_stats.public_peers,
                        'unique_ips': analysis.network_stats.unique_ips,
                        'subnets': analysis.network_stats.subnets,
                        'ip_versions': analysis.network_stats.ip_versions
                    },
                    'risk_assessment': analysis.risk_assessment,
                    'recommendations': analysis.recommendations
                }
            }
            return json.dumps(export_data, indent=2, ensure_ascii=False)
        
        elif format == 'text':
            output = []
            output.append("إحصاءات الأقران - تقرير مصدر")
            output.append(f"الوقت: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            output.append(f"إجمالي الأقران: {analysis.network_stats.total_peers}")
            output.append(f"مستوى المخاطرة: {analysis.risk_assessment['risk_level']}")
            output.append("التوصيات:")
            for rec in analysis.recommendations:
                output.append(f"  - {rec}")
            
            return "\n".join(output)
        
        return None

# دوال التوافق مع الإصدار القديم
def print_peer_statistics(discovered_peers, detailed=False):
    """
    دالة التوافق مع الإصدار القديم
    
    Args:
        discovered_peers: قائمة الأقران المكتشفة
        detailed: عرض تحليل مفصل
    """
    stats_engine = EnhancedPeerStatistics()
    stats_engine.print_statistics(discovered_peers, detailed)

# مثال على الاستخدام
if __name__ == "__main__":
    # بيانات تجريبية للاختبار
    sample_peers = [
        {'ip': '192.168.1.10', 'port': 8080},
        {'ip': '192.168.1.11', 'port': 8080},
        {'ip': '192.168.1.10', 'port': 8081},  # نفس IP، منفذ مختلف
        {'ip': '10.0.0.5', 'port': 8080},
        {'ip': '172.16.0.20', 'port': 8080},
        {'ip': '8.8.8.8', 'port': 8080},  # عام
        {'ip': '203.0.113.5', 'port': 8080},  # عام
        {'ip': '127.0.0.1', 'port': 8080},  # محلي
    ]
    
    # استخدام النظام المحسن
    stats_engine = EnhancedPeerStatistics()
    
    # طباعة الإحصاءات الأساسية
    stats_engine.print_statistics(sample_peers)
    
    print("\n" + "🔧 التحليل المفصل:")
    stats_engine.print_statistics(sample_peers, detailed=True)
    
    # تصدير البيانات
    json_export = stats_engine.export_statistics(sample_peers, 'json')
    print(f"\n📤 التصدير JSON:\n{json_export}")
    
    # استخدام دالة التوافق
    print("\n" + "🔄 استخدام دالة التوافق:")
    print_peer_statistics(sample_peers)