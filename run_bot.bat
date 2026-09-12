@echo off
cd /d "%~dp0"

echo Eski bot jarayonlari tozalanmoqda...
taskkill /F /IM python.exe /T >nul 2>&1
taskkill /F /IM pythonw.exe /T >nul 2>&1
timeout /t 2 /nobreak >nul

set BOT_TOKEN=8785180799:AAHwZuLUcu4Tu667jHxKBQM91N-TknyELsE
set ADMIN_IDS=1462539043

echo Ishlatilayotgan papka: %CD%

echo Kutubxonalar tekshirilmoqda...
pip install -r requirements.txt

echo.
echo Bot ishga tushmoqda...
python main.py
pause
