@echo off
setlocal
wsl.exe --cd "%~dp0." --exec ./desktop_target_runtime
