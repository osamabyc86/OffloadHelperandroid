#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
خدمة العمل في الخلفية - نسخة مدمجة ومحسّنة
- HTTP API آمن بـ Bearer Token
- تحميل تكوين ديناميكي من config/service_config.json
- إدارة عمليات متعددة مع التبعيات وإعادة التشغيل التلقائي
- مراقبة سجلات stdout/stderr لكل خدمة
- فحص صحي دوري
- أوامر لتشغيل/إخفاء واجهة UI (مثلاً npm run dev على 5173)
- CLI أوامر: start | status | stop | restart <service> | restart-all | token | show-ui | hide-ui
"""

import os
import sys
import time
import signal
import logging
import threading
import subprocess
import secrets
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum
import json
from datetime import datetime

from flask import Flask, jsonify, request, abort
from flask_httpauth import HTTPTokenAuth

# اختياري: يمكن إزالة psutil إن لم يلزم
try:
    import psutil  # noqa
except Exception:
    psutil = None  # لن نوقف التنفيذ إن لم تتوفر

# === مسارات أساسية ===
BASE_DIR = Path(__file__).parent.resolve()
CONFIG_DIR = BASE_DIR / "config"
LOG_DIR = BASE_DIR / "logs"
CONFIG_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)

# === حالات الخدمة ===
class ServiceStatus(Enum):
    STOPPED = "stopped"
    RUNNING = "running"
    FAILED = "failed"
    RESTARTING = "restarting"

# === تكوين خدمة واحدة ===
@dataclass
class ServiceConfig:
    name: str
    script: str
    enabled: bool = True
    auto_restart: bool = True
    restart_delay: int = 5
    max_restarts: int = 3
    working_dir: Optional[str] = None
    environment: Dict[str, str] = None
    dependencies: List[str] = None

    def __post_init__(self):
        if self.environment is None:
            self.environment = {}
        if self.dependencies is None:
            self.dependencies = []
        if self.working_dir is None:
            self.working_dir = str(BASE_DIR)

# === معلومات حالة الخدمة أثناء التشغيل ===
@dataclass
class ServiceInfo:
    config: ServiceConfig
    process: Optional[subprocess.Popen] = None
    status: ServiceStatus = ServiceStatus.STOPPED
    pid: Optional[int] = None
    start_time: Optional[datetime] = None
    restarts: int = 0
    last_error: Optional[str] = None
    script: Optional[str] = None  # للتوافق مع إعادة التشغيل السريعة

class BackgroundService:
    def __init__(self, config_file: str = "service_config.json"):
        self.app = Flask(__name__)
        self.auth = HTTPTokenAuth(scheme='Bearer')
        self.is_running = False
        self.services: Dict[str, ServiceInfo] = {}
        self.health_check_thread: Optional[threading.Thread] = None
        self.config_file = CONFIG_DIR / config_file

        self.api_port = 8888
        self.health_check_interval = 30
        self.log_retention_days = 7

        self.setup_logging()
        self.load_config()
        self.setup_auth()
        self.setup_routes()
        self.setup_signal_handlers()

    # === إعداد السجلات ===
    def setup_logging(self):
        # إعدادات ترميز متقدمة
        logging.getLogger().setLevel(logging.INFO)
        
        log_format = '%(asctime)s - %(name)s - %(levelname)s - [%(process)d] - %(message)s'

        # معالجة UTF-8 في الملفات
        main_handler = logging.FileHandler(
            LOG_DIR / 'background_service.log', 
            encoding='utf-8',
            errors='replace'  # مهم للتعامل مع الأحرف الخاصة
        )
        main_handler.setFormatter(logging.Formatter(log_format))

        error_handler = logging.FileHandler(
            LOG_DIR / 'service_errors.log', 
            encoding='utf-8',
            errors='replace'
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(logging.Formatter(log_format))

        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(logging.Formatter(log_format))

        self.logger = logging.getLogger('BackgroundService')
        self.logger.setLevel(logging.INFO)
        self.logger.handlers.clear()
        self.logger.addHandler(main_handler)
        self.logger.addHandler(error_handler)
        self.logger.addHandler(console_handler)
        self.logger.propagate = False

    # === مصادقة API ===
    def setup_auth(self):
        self.token_file = CONFIG_DIR / "api_token.txt"
        if not self.token_file.exists():
            token = secrets.token_urlsafe(32)
            self.token_file.write_text(token, encoding='utf-8')
            self.logger.info(f"تم توليد توكن API جديد وحُفظ في: {self.token_file}")
        else:
            token = self.token_file.read_text(encoding='utf-8').strip()
        self.api_token = token

        @self.auth.verify_token
        def verify_token(token):
            return token == self.api_token

    # === تحميل التكوين ===
    def load_config(self):
        default_config = {
            "services": [
                {
                    "name": "peer_server",
                    "script": "peer_server.py",
                    "enabled": True,
                    "auto_restart": True,
                    "restart_delay": 5,
                    "environment": {"PYTHONPATH": str(BASE_DIR)}
                },
                {
                    "name": "rpc_server",
                    "script": "rpc_server.py",
                    "enabled": True,
                    "auto_restart": True,
                    "dependencies": ["peer_server"]
                },
                {
                    "name": "load_balancer",
                    "script": "load_balancer.py",
                    "enabled": True,
                    "auto_restart": True
                },
                {
                    "name": "distributed_executor",
                    "script": "main.py",
                    "enabled": True,
                    "auto_restart": True,
                    "dependencies": ["peer_server", "rpc_server"]
                }
            ],
            "api_port": 8888,
            "health_check_interval": 30,
            "log_retention_days": 7
        }

        try:
            if self.config_file.exists():
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
            else:
                config = default_config
                with open(self.config_file, 'w', encoding='utf-8') as f:
                    json.dump(config, f, indent=2, ensure_ascii=False)

            # تحميل تكوين الخدمات
            self.services_config: Dict[str, ServiceConfig] = {}
            self.services.clear()
            for service_config in config.get('services', []):
                config_obj = ServiceConfig(**service_config)
                self.services_config[config_obj.name] = config_obj
                self.services[config_obj.name] = ServiceInfo(config=config_obj, script=config_obj.script)

            self.api_port = int(config.get('api_port', 8888))
            self.health_check_interval = int(config.get('health_check_interval', 30))
            self.log_retention_days = int(config.get('log_retention_days', 7))

            self.logger.info("تم تحميل التكوين بنجاح")
        except Exception as e:
            self.logger.error(f"فشل في تحميل التكوين: {e}")
            sys.exit(1)

    # === مسارات HTTP ===
    def setup_routes(self):
        # نقاط نهاية مُحايدة (إبقاء /status و/stop ... الخ أيضاً بدون /api لتوافق الإصدارات)
        @self.app.route('/api/status')
        @self.app.route('/status')
        @self.auth.login_required
        def status():
            services_status = {}
            for name, info in self.services.items():
                services_status[name] = {
                    "status": info.status.value,
                    "pid": info.pid,
                    "uptime": (datetime.now() - info.start_time).total_seconds() if info.start_time else 0,
                    "restarts": info.restarts,
                    "last_error": info.last_error
                }
            return jsonify({
                'status': 'running' if self.is_running else 'stopped',
                'services': services_status,
                'system_uptime': time.time() - self.start_time if hasattr(self, 'start_time') else 0,
                'timestamp': datetime.now().isoformat()
            })

        @self.app.route('/api/start', methods=['POST'])
        @self.app.route('/start', methods=['POST'])
        @self.auth.login_required
        def start_services():
            try:
                self.start_all_services()
                return jsonify({'success': True, 'message': 'تم بدء تشغيل الخدمات بنجاح'})
            except Exception as e:
                self.logger.error(f"فشل في بدء الخدمات: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/stop', methods=['POST'])
        @self.app.route('/stop', methods=['POST'])
        @self.auth.login_required
        def stop_services():
            try:
                self.stop_all_services()
                return jsonify({'success': True, 'message': 'تم إيقاف الخدمات بنجاح'})
            except Exception as e:
                self.logger.error(f"فشل في إيقاف الخدمات: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/restart/<service_name>', methods=['POST'])
        @self.app.route('/restart/<service_name>', methods=['POST'])
        @self.auth.login_required
        def restart_service(service_name):
            if service_name not in self.services:
                abort(404, description="الخدمة غير موجودة")
            try:
                success = self.restart_single_service(service_name)
                if success:
                    return jsonify({'success': True, 'message': f'تم إعادة تشغيل {service_name}'})
                else:
                    return jsonify({'success': False, 'error': f'فشل في إعادة تشغيل {service_name}'}), 500
            except Exception as e:
                self.logger.error(f"فشل في إعادة تشغيل {service_name}: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/restart-all', methods=['POST'])
        @self.app.route('/restart', methods=['POST'])
        @self.auth.login_required
        def restart_all():
            try:
                self.stop_all_services()
                time.sleep(2)
                self.start_all_services()
                return jsonify({'success': True, 'message': 'تمت إعادة تشغيل جميع الخدمات'})
            except Exception as e:
                self.logger.error(f"فشل في إعادة تشغيل الكل: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/service/<service_name>/logs', methods=['GET'])
        @self.auth.login_required
        def get_service_logs(service_name):
            """
            إرجاع نسخة سريعة من آخر أسطر سجلات الخدمة من ملف background_service.log
            (مجرّد فلترة نصية للسطر الذي يحتوي على [service_name])
            """
            try:
                log_path = LOG_DIR / 'background_service.log'
                if not log_path.exists():
                    return jsonify({'success': True, 'logs': []})
                # قراءة آخر ~2000 سطر كحد أقصى ثم فلترتها
                with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                    lines = f.readlines()[-2000:]
                filtered = [ln.rstrip('\n') for ln in lines if f"[{service_name}" in ln]
                return jsonify({'success': True, 'logs': filtered[-200:]})
            except Exception as e:
                return jsonify({'success': False, 'error': str(e)}), 500

        # واجهة UI: تشغيل/إخفاء (من الإصدار الثاني)
        @self.app.route('/api/show-ui', methods=['POST'])
        @self.app.route('/show-ui', methods=['POST'])
        @self.auth.login_required
        def api_show_ui():
            try:
                self.launch_ui()
                return jsonify({'success': True, 'message': 'UI launched'})
            except Exception as e:
                self.logger.error(f"فشل show-ui: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/hide-ui', methods=['POST'])
        @self.app.route('/hide-ui', methods=['POST'])
        @self.auth.login_required
        def api_hide_ui():
            try:
                self.hide_ui_windows()
                return jsonify({'success': True, 'message': 'UI hidden'})
            except Exception as e:
                self.logger.error(f"فشل hide-ui: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/config/reload', methods=['POST'])
        @self.auth.login_required
        def reload_config():
            try:
                self.load_config()
                return jsonify({'success': True, 'message': 'تم إعادة تحميل التكوين بنجاح'})
            except Exception as e:
                self.logger.error(f"فشل في إعادة تحميل التكوين: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

    # === تشغيل خدمة واحدة ===
    def start_single_service(self, service_name: str) -> bool:
        if service_name not in self.services:
            self.logger.error(f"الخدمة {service_name} غير معروفة")
            return False

        service_info = self.services[service_name]
        config = service_info.config

        if not config.enabled:
            self.logger.info(f"تخطي {service_name} (معطّلة)")
            return True

        # تحقق من التبعيات
        for dependency in config.dependencies:
            dep = self.services.get(dependency)
            if not dep or dep.status != ServiceStatus.RUNNING:
                self.logger.warning(f"التبعية {dependency} غير جاهزة لـ {service_name}")
                return False

        try:
            # بيئة التشغيل مع إعدادات UTF-8 شاملة
            env = os.environ.copy()
            env.update(config.environment or {})
            env['PYTHONPATH'] = str(BASE_DIR)
            env['PYTHONIOENCODING'] = 'utf-8'
            env['PYTHONUTF8'] = '1'
            env['LC_ALL'] = 'en_US.UTF-8'
            env['LANG'] = 'en_US.UTF-8'

            # ضمان المسار
            script_path = Path(config.script)
            if not script_path.is_absolute():
                script_path = (Path(config.working_dir or BASE_DIR) / config.script).resolve()

            process = subprocess.Popen(
                [sys.executable, '-X', 'utf8', str(script_path)],  # إضافة flag UTF-8
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=config.working_dir or str(BASE_DIR),
                env=env,
                text=True,
                bufsize=1,
                universal_newlines=True,
                encoding='utf-8',  # الترميز الإلزامي
                errors='replace'   # استبدال الأحرف غير المدعومة
            )

            service_info.process = process
            service_info.pid = process.pid
            service_info.status = ServiceStatus.RUNNING
            service_info.start_time = datetime.now()
            service_info.last_error = None

            self.start_log_monitoring(service_name, process)

            self.logger.info(f"✅ بدء تشغيل {service_name} (PID: {process.pid})")
            return True

        except Exception as e:
            error_msg = f"فشل في بدء تشغيل {service_name}: {e}"
            service_info.last_error = error_msg
            service_info.status = ServiceStatus.FAILED
            self.logger.error(error_msg)
            return False

    # === مراقبة السجلات ===
    def start_log_monitoring(self, service_name: str, process: subprocess.Popen):
        def safe_encode(text):
            """ترميز آمن للنص مع الحفاظ على الرموز التعبيرية"""
            try:
                return text.strip()
            except Exception:
                return text.encode('utf-8', errors='replace').decode('utf-8').strip()

        def monitor_stdout():
            try:
                for line in iter(process.stdout.readline, ''):
                    if line and line.strip():
                        try:
                            cleaned_line = safe_encode(line)
                            # تسجيل فقط إذا لم يكن سطر فارغ أو يحتوي على أخطاء متكررة
                            if cleaned_line and not cleaned_line.startswith('--- Logging error ---'):
                                self.logger.info(f"[{service_name}] {cleaned_line}")
                        except Exception as e:
                            safe_line = line.encode('utf-8', errors='replace').decode('utf-8').strip()
                            if safe_line:
                                self.logger.info(f"[{service_name}-ENCODING] {safe_line}")
            except Exception as e:
                self.logger.error(f"خطأ في مراقبة stdout لـ {service_name}: {e}")

        def monitor_stderr():
            try:
                for line in iter(process.stderr.readline, ''):
                    if line and line.strip():
                        try:
                            cleaned_line = safe_encode(line)
                            # تصفية الرسائل المكررة من stdout - تسجيل فقط الأخطاء الحقيقية
                            if (cleaned_line and 
                                not cleaned_line.startswith('--- Logging error ---') and
                                not any(msg in cleaned_line for msg in [
                                    'INFO -', 'WARNING -', 'DEBUG -',
                                    '📊', '⚠️', '💻', '🔄', '🔍', '✅', '🎯', '📈'
                                ])):
                                self.logger.error(f"[{service_name}-ERROR] {cleaned_line}")
                        except Exception as e:
                            safe_line = line.encode('utf-8', errors='replace').decode('utf-8').strip()
                            if safe_line and not any(msg in safe_line for msg in ['INFO -', 'WARNING -']):
                                self.logger.error(f"[{service_name}-ERROR-ENCODING] {safe_line}")
            except Exception as e:
                self.logger.error(f"خطأ في مراقبة stderr لـ {service_name}: {e}")

        threading.Thread(target=monitor_stdout, daemon=True).start()
        threading.Thread(target=monitor_stderr, daemon=True).start()

    # === بدء جميع الخدمات مع احترام التبعيات ===
    def start_all_services(self):
        self.is_running = True
        self.start_time = time.time()

        started_services = set()
        enabled_services = {n for n, s in self.services.items() if s.config.enabled}
        max_passes = 5

        for _ in range(max_passes):
            progress = False
            for name in list(enabled_services - started_services):
                if self.start_single_service(name):
                    started_services.add(name)
                    progress = True
            if started_services == enabled_services or not progress:
                break
            time.sleep(1)

        self.logger.info(f"بدأ تشغيل {len(started_services)} من أصل {len(enabled_services)} خدمة مُمكّنة")

        # إطلاق حلقة الفحص الصحي إن لم تكن تعمل
        if not self.health_check_thread or not self.health_check_thread.is_alive():
            self.health_check_thread = threading.Thread(target=self.health_check_loop, daemon=True)
            self.health_check_thread.start()

    # === إيقاف خدمة واحدة ===
    def stop_single_service(self, service_name: str, timeout: int = 10) -> bool:
        info = self.services.get(service_name)
        if not info:
            return False

        if not info.process or info.status != ServiceStatus.RUNNING:
            info.status = ServiceStatus.STOPPED
            info.pid = None
            info.process = None
            return True

        try:
            info.process.terminate()
            try:
                info.process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                info.process.kill()
                info.process.wait()

            info.status = ServiceStatus.STOPPED
            info.process = None
            info.pid = None
            self.logger.info(f"🛑 تم إيقاف {service_name}")
            return True

        except Exception as e:
            self.logger.error(f"فشل في إيقاف {service_name}: {e}")
            info.last_error = str(e)
            return False

    # === إيقاف جميع الخدمات (عكسيًا لتجنّب كسر التبعيات) ===
    def stop_all_services(self):
        self.is_running = False
        for service_name in reversed(list(self.services.keys())):
            self.stop_single_service(service_name)
        self.logger.info("تم إيقاف جميع الخدمات")

    # === إعادة تشغيل خدمة واحدة ===
    def restart_single_service(self, service_name: str) -> bool:
        info = self.services.get(service_name)
        if not info:
            return False

        config = info.config
        if info.restarts >= config.max_restarts:
            self.logger.error(f"تجاوز الحد الأقصى لإعادة التشغيل لـ {service_name}")
            info.status = ServiceStatus.FAILED
            return False

        self.logger.info(f"إعادة تشغيل {service_name}...")
        info.status = ServiceStatus.RESTARTING
        self.stop_single_service(service_name)
        time.sleep(config.restart_delay)
        success = self.start_single_service(service_name)
        if success:
            info.restarts += 1
        else:
            info.status = ServiceStatus.FAILED
        return success

    # === فحص صحي دوري ===
    def health_check_loop(self):
        while True:
            if not self.is_running:
                time.sleep(self.health_check_interval)
                continue
            try:
                for name, info in self.services.items():
                    if info.status == ServiceStatus.RUNNING and info.process and info.process.poll() is not None:
                        self.logger.warning(f"الخدمة {name} توقفت بشكل غير متوقع")
                        if info.config.auto_restart:
                            self.restart_single_service(name)
                        else:
                            info.status = ServiceStatus.FAILED
            except Exception as e:
                self.logger.error(f"خطأ في فحص الصحة: {e}")
            time.sleep(self.health_check_interval)

    # === إصلاح مشاكل الترميز للخدمات الحالية ===
    def fix_encoding_issues(self):
        """إصلاح مشاكل الترميز للخدمات الحالية"""
        for service_name, service_info in self.services.items():
            if service_info.status == ServiceStatus.RUNNING and service_info.process:
                try:
                    # إعادة توجيه الترميز للعمليات النشطة
                    if service_info.process.stdout:
                        service_info.process.stdout.reconfigure(errors='replace')
                    if service_info.process.stderr:
                        service_info.process.stderr.reconfigure(errors='replace')
                except Exception as e:
                    self.logger.warning(f"لا يمكن إعادة تكوين ترميز {service_name}: {e}")

    # === إشارات النظام ===
    def setup_signal_handlers(self):
        def signal_handler(signum, frame):
            signame = signal.Signals(signum).name if hasattr(signal, "Signals") else str(signum)
            self.logger.info(f"تلقي إشارة {signame}، إيقاف الخدمات...")
            self.stop_all_services()
            sys.exit(0)

        # بعض الأنظمة (خاصة ويندوز) لا تدعم كل الإشارات، سنتجاهل الفشل بهدوء
        for sig in (getattr(signal, 'SIGTERM', None), getattr(signal, 'SIGINT', None)):
            if sig is not None:
                try:
                    signal.signal(sig, signal_handler)
                except Exception:
                    pass

    # === تشغيل واجهة UI (npm run dev) ===
    def launch_ui(self):
        try:
            # بيئة تشغيل مع إعدادات UTF-8 لواجهة UI
            env = os.environ.copy()
            env['PYTHONIOENCODING'] = 'utf-8'
            env['PYTHONUTF8'] = '1'
            
            ui_process = subprocess.Popen(
                ['npm', 'run', 'dev'],
                cwd=str(BASE_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                text=True,
                bufsize=1,
                universal_newlines=True,
                encoding='utf-8',
                errors='replace'
            )
            # سجّل العملية ضمن services تحت اسم ui_server
            self.services['ui_server'] = ServiceInfo(
                config=ServiceConfig(
                    name='ui_server',
                    script='npm run dev',
                    enabled=True,
                    auto_restart=False
                ),
                process=ui_process,
                status=ServiceStatus.RUNNING,
                pid=ui_process.pid,
                start_time=datetime.now(),
                last_error=None,
            )
            self.start_log_monitoring('ui_server', ui_process)
            self.logger.info("🖥️ تم تشغيل الواجهة التفاعلية (يتوقع افتراضيًا 5173)")

            # فتح المتصفح افتراضيًا بعد ثوانٍ
            try:
                import webbrowser
                time.sleep(3)
                webbrowser.open('http://localhost:5173')
            except Exception:
                pass

        except Exception as e:
            self.logger.error(f"❌ فشل في تشغيل الواجهة التفاعلية: {e}")
            raise

    def hide_ui_windows(self):
        ui = self.services.get('ui_server')
        if ui and ui.process and ui.status == ServiceStatus.RUNNING:
            try:
                ui.process.terminate()
                try:
                    ui.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    ui.process.kill()
                ui.status = ServiceStatus.STOPPED
                ui.pid = None
                ui.process = None
                self.logger.info("🔒 تم إخفاء/إيقاف الواجهة التفاعلية")
            except Exception as e:
                self.logger.error(f"❌ فشل في إخفاء الواجهة التفاعلية: {e}")
                raise
        else:
            self.logger.info("واجهة UI غير قيد التشغيل")

    # === تشغيل كخدمة خلفية ===
    def run_as_daemon(self):
        self.logger.info("🚀 بدء تشغيل خدمة الخلفية...")
        try:
            # إصلاح أي مشاكل ترميز قبل البدء
            self.fix_encoding_issues()
            
            # بدء الخدمات الأساسية
            self.start_all_services()

            # تشغيل خادم API (على localhost فقط لأمان أعلى)
            self.logger.info(f"🌐 تشغيل HTTP API على المنفذ {self.api_port}")
            self.app.run(
                host='127.0.0.1',
                port=self.api_port,
                debug=False,
                use_reloader=False
            )
        except Exception as e:
            self.logger.error(f"فشل في تشغيل الخدمة: {e}")
            self.stop_all_services()
            sys.exit(1)

# === CLI ===
def main():
    service = BackgroundService()

    def _auth_headers():
        token = service.api_token
        return {'Authorization': f'Bearer {token}'}

    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == 'start':
            service.run_as_daemon()

        elif cmd == 'status':
            try:
                import requests
                resp = requests.get(f'http://127.0.0.1:{service.api_port}/api/status', headers=_auth_headers(), timeout=5)
                print(json.dumps(resp.json(), indent=2, ensure_ascii=False))
            except Exception as e:
                print(f"❌ الخدمة غير متاحة: {e}")

        elif cmd == 'stop':
            try:
                import requests
                resp = requests.post(f'http://127.0.0.1:{service.api_port}/api/stop', headers=_auth_headers(), timeout=5)
                print(resp.json().get('message') or resp.text)
            except Exception as e:
                print(f"❌ فشل في إيقاف الخدمة: {e}")

        elif cmd == 'restart-all':
            try:
                import requests
                resp = requests.post(f'http://127.0.0.1:{service.api_port}/api/restart-all', headers=_auth_headers(), timeout=10)
                print(resp.json().get('message') or resp.text)
            except Exception as e:
                print(f"❌ فشل في إعادة تشغيل الكل: {e}")

        elif cmd == 'restart':
            # usage: python background_service.py restart <service_name>
            if len(sys.argv) < 3:
                print("استخدام: restart <service_name>")
                sys.exit(2)
            name = sys.argv[2]
            try:
                import requests
                resp = requests.post(f'http://127.0.0.1:{service.api_port}/api/restart/{name}', headers=_auth_headers(), timeout=10)
                data = resp.json()
                if data.get('success'):
                    print(data.get('message'))
                else:
                    print(f"❌ {data.get('error') or resp.text}")
            except Exception as e:
                print(f"❌ فشل في إعادة تشغيل {name}: {e}")

        elif cmd == 'show-ui':
            try:
                import requests
                resp = requests.post(f'http://127.0.0.1:{service.api_port}/api/show-ui', headers=_auth_headers(), timeout=10)
                print(resp.json().get('message') or resp.text)
            except Exception as e:
                print(f"❌ فشل في إظهار الواجهة التفاعلية: {e}")

        elif cmd == 'hide-ui':
            try:
                import requests
                resp = requests.post(f'http://127.0.0.1:{service.api_port}/api/hide-ui', headers=_auth_headers(), timeout=10)
                print(resp.json().get('message') or resp.text)
            except Exception as e:
                print(f"❌ فشل في إخفاء الواجهة التفاعلية: {e}")

        elif cmd == 'token':
            print(f"API Token: {service.api_token}")

        else:
            print("الأوامر المتاحة: start | status | stop | restart <service> | restart-all | token | show-ui | hide-ui")
    else:
        print("استخدام: python background_service.py [start|status|stop|restart <service>|restart-all|token|show-ui|hide-ui]")

if __name__ == "__main__":
    main()
