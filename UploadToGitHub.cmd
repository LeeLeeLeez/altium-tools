@echo off
setlocal
set "HERE=%~dp0"
set "APP=%HERE%upload_gui.py"
if not exist "%APP%" goto nomain

rem ---------------------------------------------------------------
rem  Pick a Python that actually HAS tkinter (the isolated 3.13 venv
rem  does not, and would die with ModuleNotFoundError at import time).
rem  Probe with python.exe (console), launch with pythonw.exe (silent).
rem ---------------------------------------------------------------
set "PW="
set "PC="

call :pick "%LOCALAPPDATA%\Programs\Python\Python312"
call :pick "C:\Python312"
call :pick "%ProgramFiles%\Python312"
if defined PW goto run

rem fallback: pythonw on PATH
where pythonw >nul 2>nul && for /f "delims=" %%i in ('where pythonw') do (
    set "PW=%%i"
    set "PC=%%~dpi..\python.exe"
    goto run
)
goto nopy

:pick
if defined PW exit /b 0
if not exist "%~1\pythonw.exe" exit /b 0
if not exist "%~1\python.exe" exit /b 0
"%~1\python.exe" -c "import tkinter" >nul 2>nul
if errorlevel 1 exit /b 0
set "PW=%~1\pythonw.exe"
set "PC=%~1\python.exe"
exit /b 0

:run
echo   python : %PC%
echo   launch : %APP%
start "" "%PW%" "%APP%"
exit /b 0

:nopy
echo.
echo  [ERROR] No Python 3.12 with tkinter found.
echo.
echo    upload_gui.py needs tkinter. The isolated venv (Python 3.13)
echo    does NOT ship tkinter -- use the system Python 3.12 instead.
echo.
echo    Checked:
echo      %%LOCALAPPDATA%%\Programs\Python\Python312
echo      C:\Python312
echo      %%ProgramFiles%%\Python312
echo      pythonw on PATH
echo.
echo    Fix: install Python 3.12 for Windows, then re-run this file.
echo.
pause
exit /b 1

:nomain
echo.
echo  [ERROR] upload_gui.py not found in:
echo    %HERE%
echo.
pause
exit /b 1
