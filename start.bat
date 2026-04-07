@echo off
REM NUGUNA Global 시작 스크립트 (Windows용 - 내부망 환경)
REM 한국농어촌공사 글로벌사업처 누구나글로벌 사업관리시스템

chcp 65001 > nul
cls

echo ==========================================
echo 🌏 NUGUNA Global 누구나글로벌 사업관리시스템
echo    Global Business Management System
echo ==========================================
echo.

REM Python 확인
python --version > nul 2>&1
if errorlevel 1 (
    echo ❌ Python을 찾을 수 없습니다.
    echo    Python 3.9 이상을 설치해주세요.
    echo    https://www.python.org/downloads/
    pause
    exit /b 1
)

echo ✓ Python 확인 완료
for /f "tokens=*" %%i in ('python --version') do echo    %%i
echo.

REM 백엔드 확인
if not exist "backend\app.py" (
    echo ❌ backend\app.py를 찾을 수 없습니다.
    echo    프로젝트 루트 디렉토리에서 실행해주세요.
    pause
    exit /b 1
)

REM 데이터베이스 확인
if not exist "backend\database\gbms.db" (
    echo ⚠️  데이터베이스가 없습니다.
    set /p init_db="   데이터베이스를 초기화하시겠습니까? (y/n): "
    if /i "%init_db%"=="y" (
        echo 📦 데이터베이스 초기화 중...
        cd backend
        python init_db.py
        cd ..
        echo ✓ 데이터베이스 초기화 완료
        echo.
    ) else (
        echo ⚠️  데이터베이스 없이 계속 진행합니다.
        echo.
    )
)

REM 서버 시작
echo ==========================================
echo 🚀 서버 시작 중...
echo ==========================================
echo.

cd backend
start /b python app.py
cd ..

echo ⏳ 서버 초기화 대기 중...
timeout /t 3 /nobreak > nul

REM 네트워크 IP 주소 감지
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do (
    set NETWORK_IP=%%a
    goto :found_ip
)
:found_ip
REM 공백 제거
if defined NETWORK_IP set NETWORK_IP=%NETWORK_IP: =%

echo.
echo ==========================================
echo ✅ 시스템이 정상적으로 시작되었습니다!
echo ==========================================
echo.
echo 📱 브라우저에서 다음 주소로 접속하세요:
echo.
echo    로컬 접속:
echo    http://localhost:5001
echo.
if defined NETWORK_IP (
    echo    네트워크 접속 (다른 PC에서도 접속 가능^):
    echo    http://%NETWORK_IP%:5001
    echo.
    echo    ⚠️  방화벽 설정을 확인하세요!
    echo    제어판 ^> Windows Defender 방화벽 ^> 고급 설정
    echo    인바운드 규칙 ^> 새 규칙 ^> 포트 5001 허용
    echo.
)
echo 🔑 기본 로그인 계정:
echo    관리자: admin / admin123
echo    사용자: user1 / user123
echo.
echo ==========================================
echo ⏹️  종료: 이 창을 닫으면 서버가 종료됩니다
echo 📖 도움말: README.md 참고
echo ==========================================
echo.
echo 서버가 실행 중입니다...
echo.

REM 대기 (Ctrl+C 또는 창 닫기로 종료)
pause > nul
