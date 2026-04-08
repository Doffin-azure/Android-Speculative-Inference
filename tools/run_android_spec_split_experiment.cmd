@echo off
setlocal
powershell -ExecutionPolicy Bypass -File "%~dp0run_android_spec_split_experiment.ps1" %*
