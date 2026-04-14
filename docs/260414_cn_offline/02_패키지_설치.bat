@echo off
chcp 65001 > nul
title CN 분석 앱 패키지 설치 (오프라인)

echo ================================================
echo  CN 분석 앱 패키지 설치 (오프라인 설치)
echo ================================================
echo.

:: packages 폴더 존재 확인
if not exist packages\ (
    echo [오류] packages\ 폴더를 찾을 수 없습니다.
    echo.
    echo  해결 방법:
    echo    - 인터넷 PC에서 01_패키지_다운로드.bat 를 먼저 실행하세요.
    echo    - 다운로드된 packages\ 폴더를 이 폴더에 복사하세요.
    echo      복사 위치: migration\260414\packages\
    echo.
    pause
    exit /b 1
)

:: requirements_cn.txt 존재 확인
if not exist requirements_cn.txt (
    echo [오류] requirements_cn.txt 파일을 찾을 수 없습니다.
    echo        이 배치 파일과 같은 폴더에 있어야 합니다.
    pause
    exit /b 1
)

echo [안내] 오프라인 패키지 설치를 시작합니다...
echo.

pip install ^
    --no-index ^
    --find-links=packages\ ^
    -r requirements_cn.txt

if %ERRORLEVEL% neq 0 (
    echo.
    echo [오류] 패키지 설치 중 오류가 발생했습니다.
    echo.
    echo  확인 사항:
    echo    1. packages\ 폴더에 .whl 파일이 있는지 확인
    echo    2. Python 버전 확인: python --version  (3.11 이어야 함)
    echo    3. pip 버전 확인: pip --version
    pause
    exit /b 1
)

echo.
echo ================================================
echo  [완료] 패키지 설치가 완료되었습니다.
echo.
echo  다음 단계:
echo    1. python 04_CN앱_포트설정_패치.py 실행 (최초 1회)
echo    2. 03_CN앱_실행.bat 실행
echo ================================================
echo.
pause
