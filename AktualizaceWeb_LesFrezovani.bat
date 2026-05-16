@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "C:\Users\mspan\Desktop\Projekt_les_frezovani"

echo ============================================
echo   Aktualizace webu - Projekt les frezovani
echo ============================================
echo.

git add .
git status --short
echo.

REM === PRE-FLIGHT: kontrola velkych souboru ve stagingu (^>50 MB) ===
set "LARGE_FOUND=0"
for /f "tokens=*" %%F in ('git diff --cached --name-only') do (
    if exist "%%F" (
        for %%S in ("%%F") do (
            if %%~zS GTR 52428800 (
                echo   VAROVANI: %%F je %%~zS B
                set "LARGE_FOUND=1"
            )
        )
    )
)

if "!LARGE_FOUND!"=="1" (
    echo.
    echo POZOR: Ve stagingu jsou soubory vetsi nez 50 MB.
    echo GitHub odmita soubory nad 100 MB. Doporuceni:
    echo   1^) pridat soubor do .gitignore
    echo   2^) odebrat ze stagingu: git rm --cached "soubor"
    echo.
    set /p POKRACOVAT="Pokracovat presto? (a/N): "
    if /i not "!POKRACOVAT!"=="a" (
        echo Preruseno uzivatelem.
        goto END
    )
)

set /p POPIS="Popis zmeny (Enter = Aktualizace dat): "
if "%POPIS%"=="" set POPIS=Aktualizace dat

git commit -m "%POPIS%"
if errorlevel 1 (
    echo.
    echo CHYBA: commit selhal. Zkontroluj vystup vyse.
    goto END
)

echo.
echo [push] Pushuji na GitHub...
git push origin master
if errorlevel 1 (
    echo.
    echo ============================================
    echo   CHYBA: Push na GitHub SELHAL!
    echo   Vercel se NEDEPLOYNE dokud push neprojde.
    echo.
    echo   Bezne priciny:
    echo     - velke soubory ^(^>100 MB^)
    echo     - chyba autentizace na GitHubu
    echo     - konflikt na remote ^(zkus: git pull --rebase^)
    echo.
    echo   Detail viz vystup vyse.
    echo ============================================
    goto END
)

echo.
echo ============================================
echo   Hotovo! Vercel deployne za 10-15 sekund.
echo   https://projekt-les-frezovani.vercel.app
echo ============================================

:END
echo.
pause
endlocal
