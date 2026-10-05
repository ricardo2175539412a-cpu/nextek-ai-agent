@echo off
title NexTek AI Agent
cd /d "%~dp0"

echo ==========================================
echo       Iniciando NexTek AI Agent...
echo ==========================================

:: Activa el entorno virtual e inicia la aplicacion
call venv\Scripts\activate.bat
python app.py

:: Si ocurre un error o se detiene, la ventana no se cerrara de golpe
if %errorlevel% neq 0 (
    echo.
    echo Ocurrio un problema al ejecutar la aplicacion.
    pause
)