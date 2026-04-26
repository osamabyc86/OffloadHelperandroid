# remote_executor.py (مُحدَّث: يدعم التشفير والتوقيع واختيار السيرفر ديناميكياً)
# ============================================================
# يرسل المهمّة إلى سيرفر RPC خارجي مع تشفير + توقيع،
# أو يعمل بوضع JSON صافٍ لو لم يكن SecurityManager مفعَّل.
# يستخدم قائمة الأقران المكتشفة من discovery_manager.
# ============================================================

import requests
import json
import os
import socket
from typing import Any

# محاولة استيراد discovery_manager للحصول على الأقران ديناميكياً
try:
    from peer_discovery import discovery_manager
    # الحصول على المنفذ الحالي من discovery_manager
    PORT = discovery_manager.current_discovery_port or 5000
    # الحصول على قائمة الأقران النشطة من discovery_manager
    PEERS = discovery_manager.PEERS if hasattr(discovery_manager, 'PEERS') else set()
    DISCOVERY_AVAILABLE = True
except ImportError:
    # قيم افتراضية إذا لم يتوفر discovery_manager
    PORT = 5000
    PEERS = set()
    DISCOVERY_AVAILABLE = False
    discovery_manager = None

# عناوين سيرفرات احتياطية متعددة
BACKUP_SERVERS = [
    "http://89.111.171.92:5000",
    "http://localhost:5000",
    "http://127.0.0.1:5000",
    "https://offloadhelper.onrender.com",
    "http://cv5303201.regru.cloud",
    "https://amaloffload.onrender.com",
]

# عنوان افتراضي احتياطي (يمكن تغييره بمتغير بيئي REMOTE_SERVER)
FALLBACK_SERVER = os.getenv(
    "REMOTE_SERVER",
    f"http://89.111.171.92:{PORT}"  # بدون /run هنا
)

# محاولة استيراد SecurityManager (اختياري) مع معالجة الأخطاء
SECURITY_ENABLED = False
security = None

try:
    from security_layer import SecurityManager
    try:
        # محاولة إنشاء SecurityManager
        security = SecurityManager(os.getenv("SHARED_SECRET", "my_shared_secret_123"))
        SECURITY_ENABLED = True
        print("✅ نظام الأمان مفعّل بنجاح")
    except Exception as e:
        print(f"⚠️ فشل تهيئة نظام الأمان: {e}")
        print("🔄 الانتقال إلى وضع غير آمن (JSON صريح)")
        security = None
        SECURITY_ENABLED = False
except ImportError:
    print("📋 وحدة الأمان غير متوفرة - استخدام وضع JSON صريح")
    security = None
    SECURITY_ENABLED = False


def check_server_available(url: str, timeout: int = 5) -> bool:
    """فحص إذا كان السيرفر متاحاً"""
    try:
        # إزالة /run إذا كانت موجودة للفحص الأساسي
        base_url = url.replace('/run', '/health') if '/run' in url else url + '/health'
        
        response = requests.get(base_url, timeout=timeout)
        return response.status_code == 200
    except:
        try:
            # محاولة فتح اتصال TCP مباشر
            parsed_url = requests.utils.urlparse(url)
            hostname = parsed_url.hostname
            port = parsed_url.port or (443 if parsed_url.scheme == 'https' else 80)
            
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(timeout)
                result = sock.connect_ex((hostname, port))
                return result == 0
        except:
            return False


def _choose_remote_server() -> str:
    """
    يختار عنوان السيرفر الذي سترسل إليه المهمة:
    1) إذا عُيّن متغير بيئي REMOTE_SERVER، يُستخدم.
    2) وإلا إذا كان discovery_manager متاحاً ونشطاً، نأخذ أول قرين نشط منه.
    3) وإذا لم يكن متاحاً، نستخدم قائمة PEERS الثابتة.
    4) وأخيراً نجرب السيرفرات الاحتياطية.
    """
    # 1) التحقق من متغير البيئة أولاً
    env_url = os.getenv("REMOTE_SERVER")
    if env_url:
        # استبدال PORT في عنوان البيئة إذا كان موجوداً
        if ":PORT" in env_url:
            env_url = env_url.replace(":PORT", f":{PORT}")
        # إضافة /run إذا لم تكن موجودة
        if not env_url.endswith('/run'):
            env_url = env_url.rstrip('/') + '/run'
        print(f"🎯 استخدام عنوان من متغير البيئة: {env_url}")
        return env_url
    
    # 2) استخدام discovery_manager إذا كان متاحاً ونشطاً
    if DISCOVERY_AVAILABLE and discovery_manager:
        try:
            # الحصول على الأقران النشطة مباشرةً
            active_peers = discovery_manager.get_active_peers()
            if active_peers:
                # نأخذ أول قرين نشط
                first_peer = active_peers[0]
                peer_url = first_peer.url
                # إضافة /run إذا لم تكن موجودة
                if not peer_url.endswith('/run'):
                    peer_url = peer_url.rstrip('/') + '/run'
                print(f"🎯 استخدام قرين من discovery_manager: {peer_url}")
                return peer_url
        except Exception as e:
            print(f"⚠️ تحذير: فشل الحصول على الأقران من discovery_manager: {e}")
    
    # 3) استخدام قائمة PEERS الثابتة
    if PEERS:
        # تحويل إلى قائمة إذا كان set
        peers_list = list(PEERS) if isinstance(PEERS, set) else PEERS
        for peer_url in peers_list:
            # إضافة /run إذا لم تكن موجودة
            if not peer_url.endswith('/run'):
                peer_url = peer_url.rstrip('/') + '/run'
            print(f"🎯 اختبار قرين من PEERS: {peer_url}")
            if check_server_available(peer_url.replace('/run', '')):
                return peer_url
    
    # 4) تجربة السيرفرات الاحتياطية
    print("🔍 جاري تجربة السيرفرات الاحتياطية...")
    for server in BACKUP_SERVERS:
        server_url = server.rstrip('/') + '/run'
        print(f"  🔄 اختبار {server_url}")
        if check_server_available(server):
            print(f"  ✅ {server} متاح")
            return server_url
    
    # 5) استخدام الخادم الاحتياطي الافتراضي
    fallback_url = FALLBACK_SERVER.rstrip('/') + '/run'
    print(f"🎯 استخدام الخادم الافتراضي: {fallback_url}")
    return fallback_url


def execute_remotely(
    func_name: str,
    args: list[Any] | None = None,
    kwargs: dict[str, Any] | None = None,
    timeout: int = 10
) -> Any:
    """إرسال استدعاء دالة إلى الخادم البعيد وإرجاع النتيجة."""
    if args is None:
        args = []
    if kwargs is None:
        kwargs = {}

    task = {
        "func": func_name,
        "args": args,
        "kwargs": kwargs,
        "sender_id": "client_node",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
    }

    # اختيار السيرفر الصحيح ديناميكياً
    target_url = _choose_remote_server()
    
    # تسجيل معلومات التصحيح
    print(f"\n🎯 الاتصال بالسيرفر: {target_url}")
    print(f"🔒 الأمان: {'مفعّل' if SECURITY_ENABLED else 'غير مفعّل'}")
    print(f"⏱️  المهلة: {timeout} ثانية")
    
    if DISCOVERY_AVAILABLE and discovery_manager:
        try:
            active_count = len(discovery_manager.get_active_peers())
            print(f"📡 الأقران المكتشفة: {active_count}")
        except:
            pass

    try:
        if SECURITY_ENABLED and security:
            # 1) وقّع المهمة ثم شفّرها
            print("🔐 تشفير وتوقيع المهمة...")
            signed_task = security.sign_task(task)
            encrypted   = security.encrypt_data(json.dumps(signed_task).encode())

            headers = {
                "X-Signature": security.signature_hex,
                "Content-Type": "application/octet-stream"
            }
            payload = encrypted  # خام ثنائي
            resp = requests.post(
                target_url,
                headers=headers,
                data=payload,
                timeout=timeout
            )
        else:
            # وضع التطوير: أرسل JSON صريح
            headers = {"Content-Type": "application/json"}
            print("📤 إرسال مهمة JSON...")
            print(f"📝 المهمة: {func_name} مع {len(args)} وسيط و{len(kwargs)} وسيط اسمي")
            
            resp = requests.post(
                target_url,
                headers=headers,
                json=task,
                timeout=timeout
            )

        print(f"📨 الاستجابة: {resp.status_code}")
        
        if resp.status_code == 200:
            try:
                data = resp.json()
                result = data.get("result", data)
                print(f"✅ تنفيذ ناجح")
                return result
            except json.JSONDecodeError:
                print(f"⚠️ استجابة غير JSON: {resp.text[:100]}...")
                return resp.text
        else:
            print(f"❌ خطأ في السيرفر: {resp.status_code}")
            return f"❌ خطأ {resp.status_code}: {resp.text[:100]}..."

    except requests.exceptions.Timeout:
        print(f"⏰ انتهت مهلة الاتصال ({timeout} ثانية)")
        return f"⏰ انتهت مهلة الاتصال بالسيرفر {target_url}"
    except requests.exceptions.ConnectionError:
        print(f"🔌 فشل الاتصال بالسيرفر")
        return f"🔌 فشل الاتصال بالسيرفر {target_url}"
    except requests.exceptions.HTTPError as e:
        print(f"❌ خطأ HTTP: {e.response.status_code}")
        return f"❌ خطأ HTTP من السيرفر {target_url}: {e.response.status_code}"
    except Exception as e:
        print(f"❌ خطأ غير متوقع: {e}")
        return f"❌ فشل التنفيذ البعيد على {target_url}: {e}"


# دالة مساعدة لعرض حالة النظام
def get_executor_status() -> dict:
    """الحصول على حالة التنفيذ البعيد"""
    return {
        "discovery_available": DISCOVERY_AVAILABLE,
        "security_enabled": SECURITY_ENABLED,
        "port": PORT,
        "peers_count": len(PEERS) if PEERS else 0,
        "fallback_server": FALLBACK_SERVER,
        "current_target": _choose_remote_server()
    }


# دالة لاختبار الاتصال بدون أمان
def test_connection_simple():
    """اختبار اتصال بسيط بدون أمان"""
    test_url = "http://httpbin.org/post"  # خدمة اختبار مجانية
    
    try:
        print(f"\n🧪 اختبار الاتصال بالإنترنت...")
        response = requests.post(
            test_url,
            json={"test": "connection", "message": "hello from OffloadHelper"},
            timeout=10
        )
        
        if response.status_code == 200:
            print("✅ الاتصال بالإنترنت ناجح!")
            return True
        else:
            print(f"❌ فشل الاتصال: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"❌ خطأ في الاتصال بالإنترنت: {e}")
        return False


# دالة لاختبار سيرفرات محلية
def test_local_servers():
    """اختبار السيرفرات المحلية"""
    local_servers = [
        "http://localhost:5000",
        "http://127.0.0.1:5000",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:8080",
        "http://127.0.0.1:8080",
    ]
    
    print("\n🔍 فحص السيرفرات المحلية...")
    available = []
    
    for server in local_servers:
        try:
            # محاولة الاتصال بـ /health أو /
            for endpoint in ['/health', '/', '/run']:
                try:
                    url = server + endpoint
                    response = requests.get(url, timeout=2)
                    if response.status_code < 500:  # أي استجابة غير خطأ سيرفر
                        available.append(url.replace(endpoint, ''))
                        print(f"  ✅ {server} ({endpoint})")
                        break
                except:
                    continue
        except:
            continue
    
    return available


# مثال على الاستخدام
if __name__ == "__main__":
    import time
    
    # اختبار بسيط
    print("🔧 نظام التنفيذ البعيد - OffloadHelper")
    print("=" * 60)
    
    # عرض حالة النظام
    status = get_executor_status()
    print("\n📊 حالة النظام:")
    for key, value in status.items():
        print(f"  {key}: {value}")
    
    # اختبار الاتصال بالإنترنت
    test_connection_simple()
    
    # اختبار السيرفرات المحلية
    local_servers = test_local_servers()
    if local_servers:
        print(f"\n🏠 السيرفرات المحلية المتاحة: {len(local_servers)}")
        for server in local_servers:
            print(f"  • {server}")
    
    print("\n" + "=" * 60)
    print("🎯 بدء التنفيذ البعيد...\n")
    
    # محاولة استدعاء دالة بسيطة
    result = execute_remotely(
        func_name="test_connection",
        args=["ping"],
        kwargs={"test": True, "message": "Hello from client"},
        timeout=8
    )
    
    print(f"\n📦 النتيجة النهائية: {result}")
    
    # اقتراحات لتحسين الاتصال
    print("\n💡 اقتراحات:")
    if "انتهت مهلة" in str(result) or "فشل الاتصال" in str(result):
        print("  1. تأكد من تشغيل السيرفر على المنفذ الصحيح")
        print("  2. جرب سيرفرات مختلفة:")
        print("     - http://localhost:5000/run")
        print("     - http://127.0.0.1:5000/run")
        print("  3. تحقق من جدار الحماية وإعدادات الشبكة")
    
    print("\n" + "=" * 60)
    print("✅ اختبار remote_executor.py مكتمل")
