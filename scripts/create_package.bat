@echo off
REM ---------------------------------------------------------------------------
REM Create project_backup.zip of this repo.
REM
REM IMPORTANT CHANGE FROM THE OLD VERSION: this now excludes secrets.
REM The previous script excluded node_modules/data/etc but NOT dotfiles, so
REM every zip it produced contained .env (DB password, F95 + LewdCorner account
REM passwords, JWT_SECRET, seed admin password, email password) and the live
REM session cookies in f95_cookies.json / lc_cookies.json. Anyone who received
REM that zip received working credentials.
REM
REM If you deliberately need a zip WITH secrets:
REM     create_package.bat --with-secrets
REM ---------------------------------------------------------------------------
setlocal

cd /d "%~dp0.."

set "OUTPUT=project_backup.zip"
set "WITH_SECRETS=0"
if /i "%~1"=="--with-secrets" set "WITH_SECRETS=1"

if exist "%OUTPUT%" del "%OUTPUT%"

if "%WITH_SECRETS%"=="1" (
    echo *** INCLUDING SECRETS -- do not share this zip. ***
) else (
    echo Excluding .env, cookie jars and key files.
)

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference = 'Stop';" ^
  "$withSecrets = '%WITH_SECRETS%' -eq '1';" ^
  "$root = (Get-Location).Path;" ^
  "$excludeDirs = @('dist','build','node_modules','data','__pycache__','.git','.pytest_cache','.vscode','_archive','_documentation','_reporting','_research','_scripts','_tmp','venv','.venv');" ^
  "$excludeFiles = @('project_backup.zip');" ^
  "$secretFiles = @('.env','f95_cookies.json','lc_cookies.json','deploy.json','dbCredentials.py','config.php');" ^
  "$secretExts = @('.pem','.key','.ppk');" ^
  "$files = Get-ChildItem -Path $root -Recurse -File -Force | Where-Object {" ^
  "  $rel = $_.FullName.Substring($root.Length).TrimStart('\');" ^
  "  $parts = $rel -split '\\';" ^
  "  if ($parts | Where-Object { $excludeDirs -contains $_ }) { return $false }" ^
  "  if ($excludeFiles -contains $_.Name) { return $false }" ^
  "  if (-not $withSecrets) {" ^
  "    if ($secretFiles -contains $_.Name) { return $false }" ^
  "    if ($secretExts -contains $_.Extension) { return $false }" ^
  "    if ($_.Name -like '.env.*' -and $_.Name -ne '.env.example') { return $false }" ^
  "  }" ^
  "  return $true" ^
  "};" ^
  "Add-Type -AssemblyName System.IO.Compression.FileSystem;" ^
  "$zip = [System.IO.Compression.ZipFile]::Open((Join-Path $root '%OUTPUT%'), 'Create');" ^
  "try {" ^
  "  foreach ($f in $files) {" ^
  "    $rel = $f.FullName.Substring($root.Length).TrimStart('\').Replace('\','/');" ^
  "    [void][System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip, $f.FullName, $rel);" ^
  "  }" ^
  "} finally { $zip.Dispose() }" ^
  "Write-Host ('Created %OUTPUT% with ' + $files.Count + ' files.');" ^
  "if (-not $withSecrets) { Write-Host 'Secrets were excluded.' }"

if errorlevel 1 (
    echo.
    echo FAILED to create %OUTPUT%.
    pause
    exit /b 1
)

echo Done.
pause
