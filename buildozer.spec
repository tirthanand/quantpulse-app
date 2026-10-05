[app]

# (str) Title of your application
title = QuantPulse

# (str) Package name
package.name = quantpulse

# (str) Package domain (needed for android packaging)
package.domain = org.quantpulse

# (list) Source files to include (let's include py code, kv, spec, db, and your icon!)
source.include_exts = py,png,jpg,kv,db

# (str) Application icon
icon.filename = icon.png

# (list) Application requirements
requirements = python3,kivy,kivymd,requests

# (str) Supported orientations
orientation = portrait

# (list) Permissions
# INTERNET is mandatory because QuantPulse downloads Bhavcopies from NSE!
android.permissions = INTERNET

# (int) Target Android API
android.api = 33

# (int) Minimum API your APK will support
android.minapi = 21

[buildozer]

# (int) Log level (0 = error only, 1 = info, 2 = debug)
log_level = 2

# (int) Display warning if buildozer is run as root (0 = False, 1 = True)
warn_on_root = 1