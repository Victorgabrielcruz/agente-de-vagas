@echo off
setlocal
pushd "%~dp0.."
if exist ".venv\Scripts\python.exe" (
    set "PYTHON_VAGAS=.venv\Scripts\python.exe"
    goto executar
)
python --version >nul 2>&1
if not errorlevel 1 (
    set "PYTHON_VAGAS=python"
    goto executar
)
for /f "usebackq delims=" %%P in (`powershell.exe -NoProfile -Command "Get-ChildItem ($env:ProgramFiles + '\WindowsApps\OpenAI.CodexPrimaryRuntime.*\dependencies\python\python.exe') -ErrorAction SilentlyContinue ^| Sort-Object FullName -Descending ^| Select-Object -First 1 -ExpandProperty FullName"`) do set "PYTHON_VAGAS=%%P"
if not defined PYTHON_VAGAS (
    echo Python 3.11 ou superior nao encontrado. Consulte README.md.
    popd
    exit /b 1
)
:executar
"%PYTHON_VAGAS%" -m src.cli %*
set "RESULTADO_VAGAS=%ERRORLEVEL%"
popd
exit /b %RESULTADO_VAGAS%
