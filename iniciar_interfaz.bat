@echo off
cd /d "%~dp0"
echo Iniciando interfaz grafica de LawamyRacing...
".\.venv\Scripts\python.exe" gui.py
if errorlevel 1 pause
