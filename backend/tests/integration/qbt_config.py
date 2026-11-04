"""Print a qBittorrent.conf with a known WebUI login (admin / magarr-test) for the test container."""

import base64
import hashlib
import os

USERNAME, PASSWORD = "admin", "magarr-test"

salt = os.urandom(16)
key = hashlib.pbkdf2_hmac("sha512", PASSWORD.encode(), salt, 100_000, dklen=64)
print(f"""[LegalNotice]
Accepted=true

[BitTorrent]
Session\\DefaultSavePath=/downloads/
Session\\TempPathEnabled=false
Session\\DHTEnabled=false
Session\\PeXEnabled=false
Session\\LSDEnabled=false

[Preferences]
WebUI\\Username={USERNAME}
WebUI\\Password_PBKDF2="@ByteArray({base64.b64encode(salt).decode()}:{base64.b64encode(key).decode()})"
WebUI\\Port=8085
WebUI\\HostHeaderValidation=false
WebUI\\LocalHostAuth=true
Downloads\\SavePath=/downloads/
""")
