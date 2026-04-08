@echo off
setlocal
powershell -ExecutionPolicy Bypass -File "%~dp0run_split_parity_experiment.ps1" %*
