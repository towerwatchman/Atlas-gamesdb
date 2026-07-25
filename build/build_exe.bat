@echo off
REM ---------------------------------------------------------------------------
REM Build AtlasTools.exe   --   run this from anywhere; it cd's to the repo root.
REM
REM Produces:  dist\AtlasTools\AtlasTools.exe   (plus its _internal folder)
REM
REM The exe reads .env and deploy.json from the folder it sits in, so both are
REM copied next to it at the end. Edit those, not the ones in the repo.
REM ---------------------------------------------------------------------------
setlocal

cd /d "%~dp0.."
echo Project root: %CD%
echo.

REM --- python present? ---
where python >nul 2>nul
if errorlevel 1 (
    echo ERROR: python is not on PATH.
    echo Install Python 3.10+ and tick "Add python.exe to PATH".
    pause
    exit /b 1
)

REM --- dependencies ---
echo [1/4] Installing dependencies...
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt -r requirements-desktop.txt
if errorlevel 1 goto :failed

REM --- tests, so a broken build is caught before it is packaged ---
echo [2/4] Running tests...
python tests\test_atlas_tools.py
if errorlevel 1 (
    echo.
    echo Tests FAILED. Fix them before shipping a build.
    echo Press any key to build anyway, or close this window to stop.
    pause >nul
)
python tests\test_pipe.py
if errorlevel 1 (
    echo.
    echo Pipe tests FAILED -- the prompt relay is broken. Not building.
    goto :failed
)

REM --- build ---
echo [3/4] Building...
if exist "dist\AtlasTools" rmdir /s /q "dist\AtlasTools"
REM --workpath is important: PyInstaller defaults its scratch dir to .\build,
REM which is THIS folder (where the spec lives). Without redirecting it, the
REM build litters intermediates in among the source files.
python -m PyInstaller build\atlas_tools.spec --noconfirm --clean --workpath .pyibuild --distpath dist
if errorlevel 1 goto :failed

REM --- seed the runtime files next to the exe ---
echo [4/4] Copying runtime config...
if not exist "dist\AtlasTools\AtlasTools.exe" (
    echo ERROR: exe was not produced.
    goto :failed
)
if exist ".env" (
    copy /y ".env" "dist\AtlasTools\.env" >nul
    echo   copied your .env next to the exe
) else (
    copy /y ".env.example" "dist\AtlasTools\.env" >nul
    echo   NOTE: no .env found, copied .env.example as a starting point.
    echo         Edit dist\AtlasTools\.env before running anything.
)
if exist "deploy.json" (
    copy /y "deploy.json" "dist\AtlasTools\deploy.json" >nul
) else (
    copy /y "deploy\deploy.example.json" "dist\AtlasTools\deploy.json" >nul
    echo   NOTE: copied deploy.example.json as deploy.json.
    echo         Set your host and paths on the Settings tab.
)

echo.
echo ============================================================
echo  Built: dist\AtlasTools\AtlasTools.exe
echo.
echo  That whole AtlasTools FOLDER is the app -- copy the folder,
echo  not just the .exe, or it will not start.
echo ============================================================
echo.
pause
exit /b 0

:failed
echo.
echo BUILD FAILED -- see the output above.
pause
exit /b 1
