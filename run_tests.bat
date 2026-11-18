@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PY=python"
if exist "%~dp0runtime\python\python.exe" set "PY=%~dp0runtime\python\python.exe"
if not exist "%~dp0runtime\python\python.exe" echo 내장 파이썬이 없어 시스템 python을 씁니다 — runtime 폴더를 확인하세요
"%PY%" -X utf8 scripts\run_tests_report.py %*
