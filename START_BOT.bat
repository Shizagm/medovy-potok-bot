@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
set ROY_PYTHON=
py -3 -c "import sys; sys.exit(sys.version_info < (3,11))" >nul 2>&1
if not errorlevel 1 set ROY_PYTHON=py -3
if defined ROY_PYTHON goto run
python -c "import sys; sys.exit(sys.version_info < (3,11))" >nul 2>&1
if not errorlevel 1 set ROY_PYTHON=python
if not defined ROY_PYTHON goto missing
:run
if not exist .env goto setup
echo Рой запускается. Оставьте это окно открытым. Остановка: Ctrl+C.
%ROY_PYTHON% bot.py
pause
exit /b
:setup
echo Сначала запустите CONFIGURE.bat для настройки бота.
pause
exit /b
:missing
echo Установите Python 3.11 или новее с https://www.python.org/downloads/windows/
echo Затем снова откройте START_BOT.bat.
pause
