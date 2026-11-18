@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PY=python"
if exist "%~dp0runtime\python\python.exe" set "PY=%~dp0runtime\python\python.exe"
if not exist "%~dp0runtime\python\python.exe" echo 내장 파이썬이 없어 시스템 python을 씁니다 — runtime 폴더를 확인하세요
rem 열쇠 없이 녹화(손으로 쓴) 응답으로 시연한다. 실제 LLM은 부르지 않는다. 시연 농가 P1~P5를 입력하세요.
"%PY%" -X utf8 -m app.launch --replay --asof 2026-11-13 %*
