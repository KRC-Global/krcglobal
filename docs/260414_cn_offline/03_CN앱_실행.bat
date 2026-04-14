@echo off
chcp 65001 > nul
title CN 분석 앱 실행 (포트 5002)

echo ================================================
echo  CN 분석 앱 실행 (포트 5002)
echo ================================================
echo.
echo [안내] 이 창을 닫으면 CN 분석 앱이 종료됩니다.
echo [안내] 운영 중에는 이 창을 유지하세요.
echo.

:: CN_web/cn_web/ 디렉토리로 이동
:: 이 배치 파일은 migration\260414\ 에 위치하므로
:: ..\..\CN_web\cn_web\ 이 CN_web 앱 경로
set CN_APP_DIR=%~dp0..\..\CN_web\cn_web

if not exist "%CN_APP_DIR%\app.py" (
    echo [오류] CN_web app.py 를 찾을 수 없습니다.
    echo        찾은 경로: %CN_APP_DIR%\app.py
    echo.
    echo  확인 사항:
    echo    - CN_web\ 폴더가 올바른 위치에 있는지 확인하세요.
    echo    - 예상 폴더 구조:
    echo        [루트]\CN_web\cn_web\app.py
    echo        [루트]\migration\260414\03_CN앱_실행.bat  (이 파일)
    echo.
    pause
    exit /b 1
)

cd /d "%CN_APP_DIR%"
echo [경로] %CD%
echo.

:: 포트 5002로 실행
:: 04_CN앱_포트설정_패치.py 를 먼저 실행했다면 app.py에 포트 5002가 설정되어 있음
:: 패치를 실행하지 않은 경우를 대비해 환경변수로도 포트 전달
set FLASK_PORT=5002

echo [시작] CN 분석 앱을 포트 5002로 실행합니다...
echo        접속 주소: http://localhost:5002
echo.
echo ------------------------------------------------

python app.py

echo.
echo ------------------------------------------------
echo [종료] CN 분석 앱이 종료되었습니다.
pause
