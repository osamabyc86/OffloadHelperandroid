#!/usr/bin/env python3
"""
مشغل موحد لنظام توزيع المهام
يوفر خيارات متعددة للتشغيل
"""

import sys
import os
import subprocess
import argparse
import time
import logging
from pathlib import Path

# إعداد التسجيل
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

def check_requirements():
    """فحص المتطلبات والاعتماديات"""
    required_files = [
        'background_service.py',
        'main.py',
        'peer_server.py',
        'rpc_server.py',
        'load_balancer.py'
    ]
    
    missing_files = []
    for file in required_files:
        if not Path(file).exists():
            missing_files.append(file)
            
    if missing_files:
        logger.error(f"❌ ملفات مفقودة: {', '.join(missing_files)}")
        return False
        
    return True

def install_tray_dependencies():
    """تثبيت اعتماديات أيقونة شريط النظام"""
    try:
        subprocess.check_call(
            [sys.executable, '-m', 'pip', 'install', 'pystray', 'Pillow'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        logger.info("✅ تم تثبيت اعتماديات أيقونة شريط النظام")
        return True
    except subprocess.CalledProcessError:
        logger.error("❌ فشل في تثبيت اعتماديات أيقونة شريط النظام")
        return False

def start_background_service():
    """بدء تشغيل الخدمة في الخلفية"""
    logger.info("🚀 بدء تشغيل الخدمة في الخلفية...")
    
    try:
        # تشغيل الخدمة الخلفية
        process = subprocess.Popen(
            [sys.executable, 'background_service.py', 'start'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            universal_newlines=True
        )
        
        # قراءة الإخراج بشكل غير متزامن
        def read_output(pipe, pipe_name):
            for line in pipe:
                if line.strip():
                    logger.debug(f"[{pipe_name}] {line.strip()}")
        
        # خيوط لقراءة الإخراج
        import threading
        stdout_thread = threading.Thread(target=read_output, args=(process.stdout, "stdout"))
        stderr_thread = threading.Thread(target=read_output, args=(process.stderr, "stderr"))
        stdout_thread.daemon = True
        stderr_thread.daemon = True
        stdout_thread.start()
        stderr_thread.start()
        
        # انتظار قليل للتأكد من بدء التشغيل
        time.sleep(3)
        
        if process.poll() is None:
            logger.info("✅ تم بدء تشغيل الخدمة الخلفية بنجاح")
            return process
        else:
            logger.error("❌ فشل في بدء تشغيل الخدمة الخلفية")
            return None
            
    except Exception as e:
        logger.error(f"❌ خطأ في بدء الخدمة: {e}")
        return None

def start_with_tray():
    """تشغيل النظام مع أيقونة شريط النظام"""
    logger.info("🖱️ تشغيل النظام مع أيقونة شريط النظام...")
    
    # بدء الخدمة الخلفية أولاً
    bg_process = start_background_service()
    if not bg_process:
        return False
        
    time.sleep(3)  # انتظار حتى تصبح الخدمة جاهزة
    
    try:
        # تحقق من وجود ملف system_tray.py
        if not Path('system_tray.py').exists():
            logger.error("❌ ملف system_tray.py غير موجود")
            return False
            
        # تشغيل أيقونة شريط النظام
        logger.info("🚀 بدء تشغيل أيقونة شريط النظام...")
        tray_process = subprocess.Popen(
            [sys.executable, 'system_tray.py'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        logger.info("✅ النظام يعمل مع أيقونة شريط النظام")
        logger.info("📌 يمكنك الوصول للنظام من أيقونة شريط النظام")
        
        # انتظار إنهاء عملية الأيقونة
        tray_process.wait()
        
    except KeyboardInterrupt:
        logger.info("\n🛑 إيقاف النظام...")
    except FileNotFoundError:
        logger.error("❌ ملف system_tray.py غير موجود")
        return False
    except Exception as e:
        logger.error(f"❌ خطأ في تشغيل أيقونة شريط النظام: {e}")
        return False
    finally:
        # إيقاف الخدمة الخلفية
        try:
            if bg_process and bg_process.poll() is None:
                logger.info("⏹️ إيقاف الخدمة الخلفية...")
                bg_process.terminate()
                bg_process.wait(timeout=5)
        except:
            pass
            
    return True

def start_interactive():
    """تشغيل النظام في الوضع التفاعلي"""
    logger.info("🖥️ تشغيل النظام في الوضع التفاعلي...")
    
    # بدء الخدمة الخلفية
    bg_process = start_background_service()
    if not bg_process:
        return False
        
    time.sleep(3)
    
    try:
        # محاولة تشغيل الواجهة التفاعلية
        try:
            import requests
            try:
                response = requests.post('http://localhost:8888/show-ui', timeout=5)
                if response.status_code == 200:
                    logger.info("✅ تم تشغيل الواجهة التفاعلية")
                else:
                    logger.warning(f"⚠️  استجابة غير متوقعة من الخدمة: {response.status_code}")
            except requests.ConnectionError:
                logger.info("⚠️  الخدمة تعمل ولكن لا تستجيب لواجهة UI")
        except ImportError:
            logger.info("ℹ️  حزمة requests غير مثبتة، تخطي تفعيل الواجهة")
        
        # فتح المتصفح إذا أمكن
        try:
            import webbrowser
            time.sleep(2)
            webbrowser.open('http://localhost:5173')
            logger.info("🌐 تم فتح المتصفح مع الواجهة")
        except:
            logger.info("📋 يمكنك الوصول للواجهة عبر: http://localhost:5173")
        
        logger.info("\n" + "="*50)
        logger.info("📢 النظام يعمل الآن!")
        logger.info("• الواجهة: http://localhost:5173")
        logger.info("• إدارة النظام: http://localhost:8888")
        logger.info("• لإيقاف النظام: اضغط Ctrl+C")
        logger.info("="*50 + "\n")
        
        # انتظار إنهاء المستخدم
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("\n🛑 تلقي إشارة الإيقاف...")
            
    except Exception as e:
        logger.error(f"❌ خطأ في تشغيل الوضع التفاعلي: {e}")
    finally:
        logger.info("⏹️ إيقاف النظام...")
        try:
            import requests
            try:
                requests.post('http://localhost:8888/stop', timeout=5)
                logger.info("✅ تم إرسال أمر الإيقاف للخدمة")
            except:
                pass
        except ImportError:
            pass
        finally:
            if bg_process and bg_process.poll() is None:
                bg_process.terminate()
                try:
                    bg_process.wait(timeout=5)
                except:
                    pass
                logger.info("✅ تم إيقاف الخدمة الخلفية")
            
    return True

def start_headless():
    """تشغيل النظام بدون واجهة (للخوادم)"""
    logger.info("⚙️ تشغيل النظام بدون واجهة...")
    
    try:
        # تشغيل الخدمة الخلفية والانتظار
        process = subprocess.Popen(
            [sys.executable, 'background_service.py', 'start'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        logger.info("✅ النظام يعمل في وضع بدون واجهة")
        logger.info("📡 في انتظار المهام...")
        logger.info("🛑 اضغط Ctrl+C لإيقاف النظام")
        
        # عرض الإخراج في الوقت الحقيقي
        try:
            for line in process.stdout:
                if line.strip():
                    print(line.strip())
        except KeyboardInterrupt:
            logger.info("\n🛑 إيقاف النظام...")
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait()
                
    except FileNotFoundError:
        logger.error("❌ ملف background_service.py غير موجود")
        return False
    except Exception as e:
        logger.error(f"❌ خطأ في التشغيل بدون واجهة: {e}")
        return False
        
    return True

def show_status():
    """عرض حالة النظام"""
    try:
        result = subprocess.run(
            [sys.executable, 'background_service.py', 'status'],
            text=True,
            capture_output=True,
            timeout=10
        )
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
    except FileNotFoundError:
        logger.error("❌ ملف background_service.py غير موجود")
    except subprocess.TimeoutExpired:
        logger.error("⏱️  انتهت المهلة أثناء فحص الحالة")
    except Exception as e:
        logger.error(f"❌ خطأ في عرض الحالة: {e}")

def stop_system():
    """إيقاف النظام"""
    logger.info("🛑 إيقاف النظام...")
    try:
        result = subprocess.run(
            [sys.executable, 'background_service.py', 'stop'],
            text=True,
            capture_output=True,
            timeout=10
        )
        if result.stdout:
            print(result.stdout)
        if result.returncode == 0:
            logger.info("✅ تم إيقاف النظام بنجاح")
        else:
            logger.error("❌ فشل في إيقاف النظام")
            if result.stderr:
                print(result.stderr, file=sys.stderr)
    except FileNotFoundError:
        logger.error("❌ ملف background_service.py غير موجود")
    except subprocess.TimeoutExpired:
        logger.error("⏱️  انتهت المهلة أثناء محاولة الإيقاف")
    except Exception as e:
        logger.error(f"❌ خطأ في إيقاف النظام: {e}")

def main():
    parser = argparse.ArgumentParser(
        description="مشغل نظام توزيع المهام الذكي",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
أمثلة الاستخدام:
  python launcher.py --tray           # تشغيل مع أيقونة شريط النظام
  python launcher.py --interactive    # تشغيل تفاعلي مع واجهة
  python launcher.py --headless       # تشغيل بدون واجهة (للخوادم)
  python launcher.py --status         # عرض حالة النظام
  python launcher.py --stop           # إيقاف النظام
  
  python launcher.py --tray --debug   # تشغيل مع تفعيل وضع التصحيح
  python launcher.py --install-deps   # تثبيت الاعتماديات فقط
        """
    )
    
    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument('--tray', action='store_true', 
                      help='تشغيل مع أيقونة شريط النظام')
    group.add_argument('--interactive', action='store_true',
                      help='تشغيل تفاعلي مع واجهة')
    group.add_argument('--headless', action='store_true',
                      help='تشغيل بدون واجهة (للخوادم)')
    group.add_argument('--status', action='store_true',
                      help='عرض حالة النظام')
    group.add_argument('--stop', action='store_true',
                      help='إيقاف النظام')
    
    parser.add_argument('--install-deps', action='store_true',
                       help='تثبيت الاعتماديات المطلوبة')
    parser.add_argument('--debug', action='store_true',
                       help='تمكين وضع التصحيح')
    
    args = parser.parse_args()
    
    # ضبط مستوى التسجيل
    if args.debug:
        logger.setLevel(logging.DEBUG)
        logger.debug("🔍 تم تفعيل وضع التصحيح")
    
    # فحص إذا لم يتم تمرير أي وسيطة
    if not any([args.tray, args.interactive, args.headless, args.status, args.stop, args.install_deps]):
        logger.info("🤔 لم يتم تحديد وضع التشغيل")
        logger.info("🔍 استخدام --help لعرض خيارات المساعدة")
        parser.print_help()
        return 1
    
    # فحص المتطلبات
    if not check_requirements():
        return 1
        
    # تثبيت الاعتماديات إذا طُلب ذلك
    if args.install_deps:
        install_tray_dependencies()
        return 0
        
    # تنفيذ الأمر المطلوب
    success = False
    if args.status:
        show_status()
        success = True
    elif args.stop:
        stop_system()
        success = True
    elif args.headless:
        success = start_headless()
    elif args.interactive:
        success = start_interactive()
    elif args.tray:
        # تثبيت اعتماديات أيقونة شريط النظام إذا لم تكن موجودة
        try:
            import pystray
            import PIL.Image
        except ImportError:
            logger.info("📦 تثبيت اعتماديات أيقونة شريط النظام...")
            if not install_tray_dependencies():
                logger.error("❌ فشل في تثبيت الاعتماديات، التشغيل في الوضع التفاعلي...")
                success = start_interactive()
            else:
                success = start_with_tray()
        else:
            success = start_with_tray()
    
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())
