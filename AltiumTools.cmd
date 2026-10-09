@echo off
setlocal
set "HERE=%~dp0"
set "PYW=C:\Users\admin\AppData\Local\Programs\Python\Python312\pythonw.exe"
set "PY=C:\Users\admin\AppData\Local\Programs\Python\Python312\python.exe"

if not exist "%HERE%main.py" goto nomain

rem Use pythonw.exe so no console window stays behind the GUI.
if exist "%PYW%" (
    start "" "%PYW%" "%HERE%main.py"
    exit /b 0
)
if exist "%PY%" (
    start "" "%PY%" "%HERE%main.py"
    exit /b 0
)

echo.
echo  [ERROR] Python 3.12 not found.
echo    expected: %PY%
echo.
pause
exit /b 1

:nomain
echo.
echo  [ERROR] main.py not found in:
echo    %HERE%
echo.
pause
exit /b 1
