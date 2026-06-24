@echo off
title Workup Search

:: ── Run from this script's own folder so the project is fully relocatable ────
cd /d "%~dp0"

:: ── Kill any existing server instance to ensure a clean start ────────────────
taskkill /f /im pythonw.exe >nul 2>&1
taskkill /f /im python.exe /fi "WINDOWTITLE eq Workup Search*" >nul 2>&1
timeout /t 1 /nobreak >nul

:: ── Start server silently with pythonw (no window) ───────────────────────────
echo Starting Workup Search...
start "" pythonw "%~dp0app.py"

:: ── Wait for server to be ready (up to 15 seconds) ──────────────────────────
set /a attempts=0
:wait_loop
timeout /t 1 /nobreak >nul
curl -s http://localhost:54321/ping >nul 2>&1
if %errorlevel% == 0 goto open_browser
set /a attempts+=1
if %attempts% lss 15 goto wait_loop

:: ── Fallback: try regular python if pythonw failed ───────────────────────────
curl -s http://localhost:54321/ping >nul 2>&1
if %errorlevel% neq 0 (
    start /min "" python "%~dp0app.py"
    timeout /t 3 /nobreak >nul
)

:: ── Final check ──────────────────────────────────────────────────────────────
curl -s http://localhost:54321/ping >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo ERROR: Server did not start. Make sure Python is installed
    echo and that index.py has been run at least once.
    echo.
    pause
    exit /b 1
)

:open_browser
start "" "%~dp0workups.html"
exit /b 0
