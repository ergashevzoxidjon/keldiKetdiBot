#!/bin/bash
# Telegram bot (main.py) ni "to'xtovsiz" ishlash rejimida ushlab turadigan
# soqchi (watchdog) skript.
#
# Ishlash tartibi: agar bot allaqachon ishlab turgan bo'lsa (PID fayldagi
# jarayon hali tirik bo'lsa) - hech narsa qilmaydi. Aks holda (birinchi marta
# ishga tushirilganda yoki bot biror sababdan to'xtab qolganda) botni nohup
# orqali fonda qayta ishga tushiradi.
#
# cPanel'ning "Cron Jobs" bo'limida HAR DAQIQADA ishga tushiladigan qilib
# sozlanadi (pastdagi YANGILANISH_QOLLANMA.md'dagi ko'rsatmaga qarang):
#   * * * * * /bin/bash /home/mylogo/came.mylogo.uz/bot_watchdog.sh >> /home/mylogo/came.mylogo.uz/bot_watchdog.log 2>&1

set -u

APP_DIR="/home/mylogo/came.mylogo.uz"
VENV_ACTIVATE="/home/mylogo/virtualenv/came.mylogo.uz/3.11/bin/activate"
PIDFILE="$APP_DIR/bot.pid"
STDOUT_LOG="$APP_DIR/bot_stdout.log"

cd "$APP_DIR" || exit 1

if [ -f "$PIDFILE" ]; then
    OLD_PID="$(cat "$PIDFILE" 2>/dev/null)"
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        # Bot hali tirik - hech narsa qilmaymiz.
        exit 0
    fi
fi

# Bot yo'q yoki o'lgan - venv'ni yoqib, qayta ishga tushiramiz.
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Bot topilmadi/o'lgan, qayta ishga tushirilmoqda..." >> "$STDOUT_LOG"

# shellcheck disable=SC1090
source "$VENV_ACTIVATE"
nohup python main.py >> "$STDOUT_LOG" 2>&1 &
echo $! > "$PIDFILE"