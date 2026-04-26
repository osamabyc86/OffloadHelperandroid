[app]
title = OffloadHelper
package.name = offloadhelper
package.domain = com.offload
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,json,txt,env
version = 4.0.0

requirements = python3,flask==2.3.0,flask-cors==4.0.0,requests==2.31.0,python-dotenv==1.0.0
orientation = portrait
fullscreen = 0

android.permissions = INTERNET,ACCESS_NETWORK_STATE,ACCESS_WIFI_STATE,FOREGROUND_SERVICE
android.api = 33
android.minapi = 21
android.ndk = 25.2.9519653
android.sdk = 33
android.arch = armeabi-v7a,arm64-v8a
android.allow_backup = True

[buildozer]
log_level = 2
warn_on_root = 1
