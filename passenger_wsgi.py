"""
cPanel "Setup Python App" (Passenger) uchun ishga tushirish fayli.

ARXITEKTURA (yangilangan): bu fayl ENDI faqat admin Web Panel'ni (webapp.py,
Flask) WSGI ilovasi sifatida ishga tushiradi. Telegram bot (main.py, aiogram
long-polling) ENDI bu yerda EMAS - u butunlay ALOHIDA, mustaqil Python
jarayoni sifatida ishlaydi (nohup orqali), cPanel'ning "Cron Jobs" funksiyasi
har daqiqada tekshirib, agar to'xtab qolgan bo'lsa avtomatik qayta ishga
tushiradi (qarang: bot_watchdog.sh va YANGILANISH_QOLLANMA.md).

Sabab: Phusion Passenger so'rov-javob (request/response) turidagi web
ilovalar uchun mo'ljallangan, uzoq muddat davomida cheksiz ishlaydigan fon
jarayonlar (masalan Telegram long-polling) uchun EMAS - shu sababli u
Passenger ichida ba'zan kutilmagan tarzda to'xtab, qayta tiklanmay qolar edi.
Botni mustaqil jarayon sifatida ajratib, Web Panel esa botga to'g'ridan-to'g'ri
bog'lanmasdan (Telegram Bot API'ga oddiy HTTP so'rov orqali) xabar
yuborishi endi ikkalasini ham ancha barqaror qiladi.

Joylashtirish: bu faylni webapp.py, requirements.txt va .env bilan bir xil
papkaga (cPanel'dagi "Application root") qo'ying va Setup Python App'da
"Application startup file" = passenger_wsgi.py,
"Application Entry point" = application qilib belgilang.
"""

import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import webapp as admin_webapp  # noqa: E402

application = admin_webapp.app