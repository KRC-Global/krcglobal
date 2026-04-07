@echo off
REM GBMS 프로덕션 서버 시작 (Waitress 사용)
REM 더 빠르고 안정적인 서버 실행

chcp 65001 > nul
cls

echo ==========================================
echo 🚀 GBMS 프로덕션 서버 시작
echo ==========================================
echo.

REM Python 확인
python --version > nul 2>&1
if errorlevel 1 (
    echo ❌ Python을 찾을 수 없습니다.
    pause
    exit /b 1
)

echo ✓ Python 확인 완료
echo.

REM waitress 설치 확인
python -c "import waitress" > nul 2>&1
if errorlevel 1 (
    echo ⚠️  waitress가 설치되지 않았습니다.
    echo    설치 중...
    pip install --no-index --find-links ../preinstall2/02_Python패키지 waitress
    echo.
)

echo ✓ waitress 서버 사용
echo.

echo ==========================================
echo 🌏 서버 시작 중...
echo ==========================================
echo.

REM 환경변수 설정 (프로덕션 모드)
set FLASK_ENV=production

REM Waitress 서버로 실행 (더 빠른 성능)
echo 서버 주소: http://0.0.0.0:5001
echo.
echo ⏹️  종료: Ctrl+C
echo.

waitress-serve --host=0.0.0.0 --port=5001 --threads=4 app:app

pause
