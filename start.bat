@echo off
title Mixlumo
cd /d "%~dp0"
echo Starting Mixlumo at http://127.0.0.1:7860 ...
start "" /b cmd /c "timeout /t 4 >nul & start http://127.0.0.1:7860"
"%USERPROFILE%\.audiostudio\venv\Scripts\python.exe" server.py
pause
