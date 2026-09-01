@echo off
REM ============================================================
REM  MAPIR Survey 3N - casosber a report o biotopu
REM  (bezi vedle run_app.bat, ktery spousti analyzu jednoho snimku)
REM ============================================================

REM UTF-8 kvuli ceske diakritice ve vypisech
chcp 65001 >nul

setlocal
cd /d "%~dp0"

set VENV_DIR=.venv
set PY=python

if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo [setup] Vytvarim virtualni prostredi v %VENV_DIR% ...
    %PY% -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo [chyba] Nepodarilo se vytvorit venv. Mas nainstalovany Python?
        pause
        exit /b 1
    )
)

call "%VENV_DIR%\Scripts\activate.bat"

REM --trusted-host je nutny: sitovy proxy podepisuje HTTPS vlastnim
REM certifikatem a pip by jinak skoncil na CERTIFICATE_VERIFY_FAILED.
python -c "import streamlit" 2>nul
if errorlevel 1 (
    echo [setup] Instaluji zavislosti z requirements.txt ...
    python -m pip install --upgrade pip ^
        --trusted-host pypi.org --trusted-host files.pythonhosted.org
    python -m pip install -r requirements.txt ^
        --trusted-host pypi.org --trusted-host files.pythonhosted.org
    if errorlevel 1 (
        echo [chyba] Instalace selhala.
        pause
        exit /b 1
    )
)

where ffmpeg >nul 2>nul
if errorlevel 1 (
    echo [chyba] ffmpeg neni v PATH. Bez nej nelze zapsat mp4.
    echo         Nainstaluj napr. prikazem:  winget install Gyan.FFmpeg
    pause
    exit /b 1
)

echo.
echo [start] Spoustim aplikaci na http://localhost:8503
echo.
python -m streamlit run timelapse_app.py --server.port 8503

endlocal
pause
