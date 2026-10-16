@echo off
setlocal
if exist "%~dp0.lori-bin\lori.exe" (
    "%~dp0.lori-bin\lori.exe" %*
) else (
    where py >nul 2>nul
    if errorlevel 1 (
        python "%~dp0tools\lori_entry.py" %*
    ) else (
        py -3 "%~dp0tools\lori_entry.py" %*
    )
)
exit /b %errorlevel%
