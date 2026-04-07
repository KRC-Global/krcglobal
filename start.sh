#!/bin/bash

# NUGUNA Global 시작 스크립트 (내부망 환경)
# 한국농어촌공사 글로벌사업처 누구나글로벌 사업관리시스템

echo "=========================================="
echo "🌏 NUGUNA Global 누구나글로벌 사업관리시스템"
echo "   Global Business Management System"
echo "=========================================="
echo ""

# Python 버전 확인
if ! command -v python &> /dev/null && ! command -v python3 &> /dev/null; then
    echo "❌ Python을 찾을 수 없습니다."
    echo "   Python 3.9 이상을 설치해주세요."
    exit 1
fi

PYTHON_CMD="python"
if command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
fi

echo "✓ Python 확인: $($PYTHON_CMD --version)"
echo ""

# 백엔드 디렉토리 확인
if [ ! -f "backend/app.py" ]; then
    echo "❌ backend/app.py를 찾을 수 없습니다."
    echo "   프로젝트 루트 디렉토리에서 실행해주세요."
    exit 1
fi

# 데이터베이스 확인
if [ ! -f "backend/database/gbms.db" ]; then
    echo "⚠️  데이터베이스가 없습니다."
    echo "   데이터베이스를 초기화하시겠습니까? (y/n)"
    read -r response
    if [[ "$response" =~ ^[Yy]$ ]]; then
        echo "📦 데이터베이스 초기화 중..."
        cd backend
        $PYTHON_CMD init_db.py
        cd ..
        echo "✓ 데이터베이스 초기화 완료"
        echo ""
    else
        echo "⚠️  데이터베이스 없이 계속 진행합니다."
        echo ""
    fi
fi

# 서버 시작
echo "=========================================="
echo "🚀 서버 시작 중..."
echo "=========================================="
echo ""

cd backend
$PYTHON_CMD app.py &
BACKEND_PID=$!
cd ..

echo "✓ Flask 서버 시작됨 (PID: $BACKEND_PID)"
echo ""

# 서버 시작 대기
echo "⏳ 서버 초기화 대기 중..."
sleep 3

# 서버 동작 확인
if ps -p $BACKEND_PID > /dev/null; then
    # 네트워크 IP 주소 감지
    if command -v ipconfig &> /dev/null; then
        # macOS
        NETWORK_IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "")
    elif command -v hostname &> /dev/null; then
        # Linux
        NETWORK_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "")
    fi

    echo ""
    echo "=========================================="
    echo "✅ 시스템이 정상적으로 시작되었습니다!"
    echo "=========================================="
    echo ""
    echo "📱 브라우저에서 다음 주소로 접속하세요:"
    echo ""
    echo "   로컬 접속:"
    echo "   http://localhost:5001"
    echo ""
    if [ ! -z "$NETWORK_IP" ]; then
        echo "   네트워크 접속 (다른 PC에서도 접속 가능):"
        echo "   http://$NETWORK_IP:5001"
        echo ""
        echo "   ⚠️  방화벽 설정을 확인하세요!"
        echo "   - Windows: 제어판 > 방화벽 > 5001 포트 허용"
        echo "   - macOS: 시스템 환경설정 > 보안 > 방화벽"
    fi
    echo ""
    echo "🔑 Google 계정으로 로그인하세요."
    echo ""
    echo "=========================================="
    echo "⏹️  종료: Ctrl+C"
    echo "📖 도움말: README.md 참고"
    echo "=========================================="
else
    echo ""
    echo "❌ 서버 시작에 실패했습니다."
    echo "   backend/server.log 파일을 확인해주세요."
    exit 1
fi

# 종료 시 프로세스 정리
trap "echo ''; echo '========================================'; echo '⏹️  서버를 종료합니다...'; echo '========================================'; kill $BACKEND_PID 2>/dev/null; sleep 1; echo '✓ 서버가 종료되었습니다.'; exit" INT TERM

# 대기
wait
