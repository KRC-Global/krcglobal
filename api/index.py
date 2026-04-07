"""
Vercel Serverless Function Entry Point
Flask app을 Vercel serverless로 서빙
"""
import sys
import os

# backend 디렉토리를 Python path에 추가
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from app import app

# Vercel은 'app' 변수를 WSGI handler로 사용
