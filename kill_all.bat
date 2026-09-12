@echo off
echo Barcha python jarayonlari o'chirilmoqda...
taskkill /F /IM python.exe /T
taskkill /F /IM pythonw.exe /T
timeout /t 2 /nobreak >nul
echo.
echo Qolgan python jarayonlari:
tasklist | findstr /I python
echo.
echo Tugadi.
pause
