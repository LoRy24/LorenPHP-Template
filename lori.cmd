@echo off
setlocal
py -3 "%~dp0lori" %*
if errorlevel 9009 python "%~dp0lori" %*
endlocal
