#!/usr/bin/env python3
# run_safe.py - سكريبت تشغيل آمن مع معالجة جميع الأخطاء

import os
import sys
import time

def main():
    print("🛡️  تشغيل النظام بشكل آمن...")
    
    # تشغيل مدقق الاعتماديات أولاً
    try:
        from dependency_checker import checker
        if not checker.check_and_install_dependencies():
            print("❌ فشل في تحضير الاعتماديات")
            return
    except Exception as e:
        print(f"⚠️ تحذير في مدقق الاعتماديات: {e}")
    
    # تشغيل النظام الرئيسي
    try:
        import main
        main.main()
    except KeyboardInterrupt:
        print("\n🛑 تم إيقاف التشغيل")
    except Exception as e:
        print(f"❌ خطأ في التشغيل: {e}")
        print("💡 حاول تشغيل: python3 dependency_checker.py أولاً")

if __name__ == "__main__":
    main()