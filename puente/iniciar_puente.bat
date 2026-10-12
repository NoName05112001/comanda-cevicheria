@echo off
chcp 65001 >nul
title Puente Comanda Cevicheria (se reinicia solo si se cae)
cd /d "%~dp0"
:inicio
echo [%date% %time%] Iniciando el puente...
puente-comanda-cevicheria.exe
echo.
echo [%date% %time%] El puente se cerro. Se vuelve a abrir en 5 segundos. Cierra ESTA ventana para detenerlo del todo.
timeout /t 5 /nobreak >nul
goto inicio
