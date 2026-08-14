@echo off
setlocal
cd /d "%~dp0"

".venv\Scripts\python.exe" -m PyInstaller --clean --noconfirm study_assistant.spec
if errorlevel 1 (
    echo Build failed.
    exit /b 1
)

echo.
echo Build succeeded: %~dp0dist\StudyAssistant.exe
endlocal
