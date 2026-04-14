@echo off
chcp 65001 > nul
title CN 분석 앱 패키지 다운로드

echo ================================================
echo  CN 분석 앱 패키지 다운로드 (인터넷 연결 필요)
echo ================================================
echo.
echo [안내] 이 스크립트는 인터넷이 연결된 PC에서 실행하세요.
echo [안내] 다운로드된 packages\ 폴더를 내부망 서버로 복사하세요.
echo.

:: packages 폴더 생성
if not exist packages\ (
    mkdir packages
    echo [OK] packages\ 폴더를 생성했습니다.
) else (
    echo [OK] packages\ 폴더가 이미 존재합니다.
)

echo.
echo [진행중] 패키지 다운로드를 시작합니다...
echo         (시간이 다소 걸릴 수 있습니다)
echo.

pip download ^
    --destination packages\ ^
    --platform win_amd64 ^
    --python-version 311 ^
    --only-binary=:all: ^
    -r requirements_cn.txt

if %ERRORLEVEL% neq 0 (
    echo.
    echo [오류] 패키지 다운로드 중 오류가 발생했습니다.
    echo        인터넷 연결 상태와 pip 버전을 확인하세요.
    echo        pip upgrade: python -m pip install --upgrade pip
    pause
    exit /b 1
)

echo.
echo ================================================
echo  [완료] 패키지 다운로드가 완료되었습니다.
echo.
echo  다음 단계:
echo    1. packages\ 폴더를 USB 등에 복사
echo    2. 내부망 서버의 migration\260414\ 에 붙여넣기
echo    3. 내부망 서버에서 02_패키지_설치.bat 실행
echo ================================================
echo.
pause
