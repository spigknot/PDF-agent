@echo off
rem CompressPDF - duplo clique aqui para abrir a interface grafica.
rem (este .bat fica na raiz do projeto e funciona em qualquer pasta)
cd /d "%~dp0"

set "PY=C:\Users\Gustavo\AppData\Local\Programs\Python\Python311\python.exe"
set "PYW=C:\Users\Gustavo\AppData\Local\Programs\Python\Python311\pythonw.exe"

if not exist "%PY%" (
  set "PY=python"
  set "PYW=pythonw"
)

"%PY%" -c "import pikepdf, PIL, fontTools" 2>nul
if errorlevel 1 (
  echo Instalando dependencias - uma vez so...
  "%PY%" -m pip install -r requirements.txt
  if errorlevel 1 (
    echo Falhou a instalacao das dependencias.
    pause
    exit /b 1
  )
)

start "" "%PYW%" app.py
