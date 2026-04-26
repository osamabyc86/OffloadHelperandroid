import json
import os
import platform
import sys
import subprocess
from pathlib import Path
from peer_discovery import PORT

class AutoStartManager:
    def __init__(self, app_name="DistributedTaskSystem"):
        self.app_name = app_name
        self.config_file = Path.home() / f".{app_name}_autostart.json"
        self.load_config()
    
    def load_config(self):
        """تحميل إعدادات التشغيل التلقائي"""
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                self.config = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self.config = {
                'enabled': False,
                'startup_script': str(Path(__file__).parent / "startup.py"),
                'startup_arguments': "",
                'start_delay': 0,
                'working_directory': str(Path(__file__).parent)
            }
    
    def save_config(self):
        """حفظ الإعدادات"""
        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, indent=2, ensure_ascii=False)
    
    def is_autostart_enabled(self):
        """التحقق من حالة التشغيل التلقائي"""
        return self.config.get('enabled', False)
    
    def enable_autostart(self):
        """تفعيل التشغيل التلقائي"""
        # التحقق من وجود سكريبت البدء
        if not self._validate_startup_script():
            return False
        
        self.config['enabled'] = True
        success = self._setup_autostart()
        if success:
            self.save_config()
            print(f"✓ تم تفعيل التشغيل التلقائي لـ {self.app_name}")
        else:
            self.config['enabled'] = False
            print("✗ فشل في تفعيل التشغيل التلقائي")
        return success
    
    def disable_autostart(self):
        """تعطيل التشغيل التلقائي"""
        self.config['enabled'] = False
        success = self._remove_autostart()
        if success:
            self.save_config()
            print(f"✓ تم تعطيل التشغيل التلقائي لـ {self.app_name}")
        else:
            print("✗ فشل في تعطيل التشغيل التلقائي")
        return success
    
    def set_startup_arguments(self, arguments):
        """تعيين معلمات إضافية للتشغيل"""
        self.config['startup_arguments'] = arguments
        self.save_config()
    
    def set_start_delay(self, delay_seconds):
        """تعيين تأخير البدء (بالثواني)"""
        self.config['start_delay'] = max(0, delay_seconds)
        self.save_config()
    
    def _validate_startup_script(self):
        """التحقق من وجود سكريبت البدء"""
        script_path = Path(self.config['startup_script'])
        if not script_path.exists():
            print(f"✗ تحذير: ملف البدء غير موجود: {script_path}")
            return False
        return True
    
    def _get_python_executable(self):
        """الحصول على مسار تنفيذ Python الصحيح"""
        if getattr(sys, 'frozen', False):
            # إذا كان التطبيق مجمعاً (مثل pyinstaller)
            return sys.executable
        else:
            return sys.executable
    
    def _build_command(self):
        """بناء أمر التشغيل"""
        python_exe = self._get_python_executable()
        script_path = self.config['startup_script']
        arguments = self.config.get('startup_arguments', '')
        working_dir = self.config.get('working_directory', str(Path(__file__).parent))
        
        command = f'"{python_exe}" "{script_path}"'
        if arguments:
            command += f' {arguments}'
        
        # إضافة تأخير البدء إذا كان موجوداً
        delay = self.config.get('start_delay', 0)
        if delay > 0:
            system = platform.system()
            if system == "Windows":
                command = f'ping -n {delay + 1} 127.0.0.1 >nul && {command}'
            else:  # Linux/Mac
                command = f'sleep {delay} && {command}'
        
        return command, working_dir
    
    def _setup_autostart(self):
        """إعداد التشغيل التلقائي حسب نظام التشغيل"""
        system = platform.system()
        
        try:
            if system == "Windows":
                return self._setup_windows()
            elif system == "Linux":
                return self._setup_linux()
            elif system == "Darwin":
                return self._setup_mac()
            else:
                print(f"✗ نظام التشغيل غير مدعوم: {system}")
                return False
        except Exception as e:
            print(f"✗ خطأ في إعداد التشغيل التلقائي: {e}")
            return False
    
    def _setup_windows(self):
        """إعداد التشغيل التلقائي لـ Windows"""
        import winreg
        
        command, working_dir = self._build_command()
        
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0, winreg.KEY_SET_VALUE | winreg.KEY_READ
            )
            winreg.SetValueEx(
                key, self.app_name, 0, winreg.REG_SZ, command
            )
            winreg.CloseKey(key)
            return True
        except Exception as e:
            print(f"✗ خطأ في إعداد التشغيل التلقائي لـ Windows: {e}")
            return False
    
    def _setup_linux(self):
        """إعداد التشغيل التلقائي لـ Linux"""
        try:
            autostart_dir = Path.home() / ".config/autostart"
            autostart_dir.mkdir(exist_ok=True, parents=True)
            
            command, working_dir = self._build_command()
            
            desktop_file = autostart_dir / f"{self.app_name}.desktop"
            desktop_content = f"""[Desktop Entry]
Type=Application
Name={self.app_name}
Exec={command}
Path={working_dir}
Terminal=false
X-GNOME-Autostart-enabled=true
"""
            desktop_file.write_text(desktop_content, encoding='utf-8')
            
            # جعل الملف قابلاً للتنفيذ
            desktop_file.chmod(0o755)
            return True
        except Exception as e:
            print(f"✗ خطأ في إعداد التشغيل التلقائي لـ Linux: {e}")
            return False
    
    def _setup_mac(self):
        """إعداد التشغيل التلقائي لـ macOS"""
        try:
            plist_dir = Path.home() / "Library/LaunchAgents"
            plist_dir.mkdir(exist_ok=True, parents=True)
            
            command_parts = self._build_command()[0].split()
            
            plist_file = plist_dir / f"com.{self.app_name.lower()}.plist"
            plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.{self.app_name.lower()}</string>
    <key>ProgramArguments</key>
    <array>
        {''.join(f'<string>{part}</string>' for part in command_parts)}
    </array>
    <key>WorkingDirectory</key>
    <string>{self.config.get('working_directory', str(Path(__file__).parent))}</string>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/{self.app_name}.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/{self.app_name}.log</string>
</dict>
</plist>
"""
            plist_file.write_text(plist_content, encoding='utf-8')
            return True
        except Exception as e:
            print(f"✗ خطأ في إعداد التشغيل التلقائي لـ macOS: {e}")
            return False
    
    def _remove_autostart(self):
        """إزالة التشغيل التلقائي"""
        system = platform.system()
        success = True
        
        try:
            if system == "Windows":
                import winreg
                try:
                    key = winreg.OpenKey(
                        winreg.HKEY_CURRENT_USER,
                        r"Software\Microsoft\Windows\CurrentVersion\Run",
                        0, winreg.KEY_SET_VALUE
                    )
                    winreg.DeleteValue(key, self.app_name)
                    winreg.CloseKey(key)
                except WindowsError:
                    success = False
            
            elif system == "Linux":
                autostart_file = Path.home() / f".config/autostart/{self.app_name}.desktop"
                if autostart_file.exists():
                    autostart_file.unlink()
                else:
                    success = False
            
            elif system == "Darwin":
                plist_file = Path.home() / f"Library/LaunchAgents/com.{self.app_name.lower()}.plist"
                if plist_file.exists():
                    plist_file.unlink()
                    # إزالة الملف من launchd إذا كان محملاً
                    try:
                        subprocess.run(['launchctl', 'unload', str(plist_file)], 
                                    capture_output=True, check=False)
                    except:
                        pass
                else:
                    success = False
            
            return success
        except Exception as e:
            print(f"✗ خطأ في إزالة التشغيل التلقائي: {e}")
            return False
    
    def get_status(self):
        """الحصول على حالة التشغيل التلقائي الحالية"""
        system = platform.system()
        enabled = False
        
        try:
            if system == "Windows":
                import winreg
                try:
                    key = winreg.OpenKey(
                        winreg.HKEY_CURRENT_USER,
                        r"Software\Microsoft\Windows\CurrentVersion\Run",
                        0, winreg.KEY_READ
                    )
                    winreg.QueryValueEx(key, self.app_name)
                    winreg.CloseKey(key)
                    enabled = True
                except WindowsError:
                    enabled = False
            
            elif system == "Linux":
                autostart_file = Path.home() / f".config/autostart/{self.app_name}.desktop"
                enabled = autostart_file.exists()
            
            elif system == "Darwin":
                plist_file = Path.home() / f"Library/LaunchAgents/com.{self.app_name.lower()}.plist"
                enabled = plist_file.exists()
        
        except Exception:
            enabled = False
        
        return enabled

# مثال على الاستخدام
if __name__ == "__main__":
    manager = AutoStartManager()
    
    if len(sys.argv) > 1:
        if sys.argv[1] == "enable":
            manager.enable_autostart()
        elif sys.argv[1] == "disable":
            manager.disable_autostart()
        elif sys.argv[1] == "status":
            status = manager.get_status()
            print(f"حالة التشغيل التلقائي: {'مفعل' if status else 'معطل'}")
    else:
        print("الاستخدام:")
        print("  python autostart_config.py enable  - تفعيل التشغيل التلقائي")
        print("  python autostart_config.py disable - تعطيل التشغيل التلقائي")
        print("  python autostart_config.py status  - عرض الحالة")