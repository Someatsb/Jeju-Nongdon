@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PY=python"
if exist "%~dp0runtime\python\python.exe" set "PY=%~dp0runtime\python\python.exe"
if not exist "%~dp0runtime\python\python.exe" echo 내장 파이썬이 없어 시스템 python을 씁니다 — runtime 폴더를 확인하세요
if /i "%~1"=="--replay" (
  if "%~2"=="" (
    echo 사용법: notice.bat --replay N1
    exit /b 2
  )
  "%PY%" -X utf8 -m app.replay_cli "%~2"
  exit /b %errorlevel%
)
if /i "%~1"=="--scout" (
  "%PY%" -X utf8 -m app.cli notice %*
  exit /b %errorlevel%
)
if /i "%~1"=="--url" (
  if "%~2"=="" (
    echo 사용법: notice.bat --url 공고주소   ^(서귀포시·제주시·제주도청 공고 주소^)
    exit /b 2
  )
  "%PY%" -X utf8 -m app.cli notice --url "%~2"
  exit /b %errorlevel%
)
if "%~1"=="" (
  echo 사용법: notice.bat 공고파일.pdf   또는   notice.bat --url 공고주소   또는   notice.bat --scout   또는   notice.bat --replay N1
  exit /b 2
)
"%PY%" -X utf8 -m app.cli notice "%~1"
