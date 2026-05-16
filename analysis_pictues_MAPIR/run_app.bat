@echo off
REM ============================================================
REM  MAPIR Survey 3N NIR Analyser - Windows launcher
REM ============================================================

setlocal
cd /d "%~dp0"

set VENV_DIR=.venv
set PY=python

REM --- 1) Vytvor venv pokud neexistuje ---
if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo [setup] Vytvarim virtualni prostredi v %VENV_DIR% ...
    %PY% -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo [chyba] Nepodarilo se vytvorit venv. Mas nainstalovany Python?
        pause
        exit /b 1
    )
)

REM --- 2) Aktivuj venv ---
call "%VENV_DIR%\Scripts\activate.bat"

REM --- 3) Instaluj zavislosti (jen pokud streamlit chybi) ---
python -c "import streamlit" 2>nul
if errorlevel 1 (
    echo [setup] Instaluji zavislosti z requirements.txt ...
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [chyba] Instalace selhala.
        pause
        exit /b 1
    )
)

REM --- 4) Spust Streamlit ---
echo.
echo [start] Spoustim aplikaci na http://localhost:8501
echo.
python -m streamlit run app.py

endlocal
pause
