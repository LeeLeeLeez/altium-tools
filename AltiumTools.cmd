@echo off
setlocal
set "HERE=%~dp0"
set "PYW=C:\Users\admin\AppData\Local\Programs\Python\Python312\pythonw.exe"
set "PY=C:\Users\admin\AppData\Local\Programs\Python\Python312\python.exe"
set "EXE=%HERE%web\src-tauri\target\release\altium-tools.exe"

rem ---------------------------------------------------------------
rem  Altium 工具集启动器
rem  1) 有桌面版 exe（Tauri）→ 直接开原生窗口
rem  2) 否则 → 起本地服务，用浏览器打开
rem  桌面版没打包时执行：cd web && npm run tauri:build
rem ---------------------------------------------------------------

if exist "%EXE%" (
    start "" "%EXE%"
    exit /b 0
)

if not exist "%HERE%server.py" goto noserver
if not exist "%HERE%web\dist\index.html" goto nodist

rem Use pythonw.exe so no console window stays behind the app.
if exist "%PYW%" (
    start "" "%PYW%" "%HERE%server.py"
    exit /b 0
)
if exist "%PY%" (
    start "" "%PY%" "%HERE%server.py"
    exit /b 0
)

echo.
echo  [ERROR] Python 3.12 not found.
echo    expected: %PY%
echo.
pause
exit /b 1

:noserver
echo.
echo  [ERROR] server.py not found in:
echo    %HERE%
echo.
pause
exit /b 1

:nodist
echo.
echo  [ERROR] Frontend not built.
echo    please run:
echo      cd "%HERE%web"
echo      npm install
echo      npm run build
echo.
pause
exit /b 1
