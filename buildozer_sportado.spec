[app]

title = ExtraTag SportAdo
package.name = extratagsportado
package.domain = org.extratag

source.dir = .
source.include_exts = py,png,jpg,jpeg,kv,atlas,html,css,js,json,txt,env,xml
source.exclude_dirs = Android Studio, .git, .buildozer, bin, venv, __pycache__, Extratag_Email, Extratag_Vcall, Extratag_Profile, Lbug, .idea, .vscode
version = 0.1
icon.filename = %(source.dir)s/Pic-SportAdo.png

# ===== הוסף דרישה לגרסה ישנה של charset_normalizer =====
requirements = python3==3.14.2,hostpython3==3.14.2,kivy,pyjnius,android,certifi,openssl,charset_normalizer==3.4.4
orientation = portrait
fullscreen = 0
p4a.bootstrap = sdl2

android.permissions = INTERNET, ACCESS_FINE_LOCATION, ACCESS_COARSE_LOCATION, POST_NOTIFICATIONS
android.api = 33
android.minapi = 24
android.ndk_api = 24
android.ndk = 25c
android.archs = arm64-v8a, armeabi-v7a
android.accept_sdk_license = True
android.add_src = java
android.allow_backup = False

[buildozer]

log_level = 2
warn_on_root = 1

build_dir = /home/merch/.buildozer_storage_sportAdo
bin_dir = ./Extratag_SportAdo/bin