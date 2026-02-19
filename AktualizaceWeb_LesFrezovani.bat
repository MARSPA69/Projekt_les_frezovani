@echo off
chcp 65001 >nul
cd /d "C:\Users\mspan\Desktop\Projekt_les_frezovani"

echo ============================================
echo   Aktualizace webu - Projekt les frezovani
echo ============================================
echo.

git add .
git status --short
echo.

set /p POPIS="Popis zmeny (Enter = Aktualizace dat): "
if "%POPIS%"=="" set POPIS=Aktualizace dat

git commit -m "%POPIS%"
git push origin master

echo.
echo ============================================
echo   Hotovo! Vercel deployne za 10-15 sekund.
echo   https://projekt-les-frezovani.vercel.app
echo ============================================
echo.
pause
