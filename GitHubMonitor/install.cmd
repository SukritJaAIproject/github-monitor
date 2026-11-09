@echo off
rem GitHub Monitor - install
rem Finds Python 3 on this computer (Anaconda first), then runs: python github_monitor.py --install
rem The script copies itself to %LOCALAPPDATA%\Programs\GitHub Monitor and creates Desktop / Start Menu shortcuts.
setlocal
title GitHub Monitor - install
cd /d "%~dp0"
set "PY="
call :try "%USERPROFILE%\anaconda3\python.exe"
call :try "%USERPROFILE%\Anaconda3\python.exe"
call :try "%USERPROFILE%\miniconda3\python.exe"
call :try "%LOCALAPPDATA%\anaconda3\python.exe"
call :try "%LOCALAPPDATA%\miniconda3\python.exe"
call :try "%ProgramData%\anaconda3\python.exe"
call :try "%ProgramData%\Anaconda3\python.exe"
call :try "%ProgramData%\miniconda3\python.exe"
if not defined PY for /f "delims=" %%P in ('where python 2^>nul ^| findstr /v /i "WindowsApps"') do call :try "%%P"
if not defined PY for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do call :try "%%D\python.exe"
if not defined PY goto nopython
echo Using Python: %PY%
"%PY%" "%~dp0github_monitor.py" --install
if errorlevel 1 goto failed
timeout /t 3 >nul
exit /b 0

:try
if defined PY exit /b 0
if exist "%~1" set "PY=%~1"
exit /b 0

:nopython
echo Python 3 was not found on this computer.
echo Install Anaconda or Python 3, then run this file again.
pause
exit /b 1

:failed
echo.
echo The install did not finish. See the message above.
pause
exit /b 1
