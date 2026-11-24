[app]
title = PhoneGene
package.name = phonegene
package.domain = org.venice
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,json
version = 1.0
requirements = python3,kivy,requests,urllib3,chardet,idna,certifi,phonenumbers
orientation = portrait
android.permissions = INTERNET,ACCESS_NETWORK_STATE
android.api = 33
android.minapi = 24
android.archs = arm64-v8a, armeabi-v7a
android.accept_sdk_license = True
p4a.branch = master

[buildozer]
log_level = 2
