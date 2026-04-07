#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
KRC 데이터 Import 스크립트
KRC/data 폴더의 JSON 파일들을 데이터베이스에 import합니다.
"""

import json
import sqlite3
import os
import sys
from datetime import datetime

# 프로젝트 루트 경로 설정
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
KRC_DATA_DIR = os.path.join(PROJECT_ROOT, 'KRC', 'data')
DB_PATH = os.path.join(SCRIPT_DIR, 'database', 'gbms.db')

def parse_date(date_str):
    """날짜 문자열을 YYYY-MM-DD 형식으로 변환"""
    if not date_str or date_str.strip() == '':
        return None
    
    # '24-02 형식 처리
    if '-' in date_str:
        parts = date_str.replace("'", "").split('-')
        if len(parts) == 2:
            year = parts[0]
            month = parts[1]
            # 2자리 연도를 4자리로 변환
            if len(year) == 2:
                year_int = int(year)
                if year_int >= 72:  # 1972년부터
                    year = f"19{year}"
                else:
                    year = f"20{year}"
            return f"{year}-{month.zfill(2)}-01"
    
    return None

def import_consulting_data(conn):
    """해외기술용역 데이터 import"""
    json_path = os.path.join(KRC_DATA_DIR, 'global_consulting.json')
    
    if not os.path.exists(json_path):
        print(f"❌ 파일을 찾을 수 없습니다: {json_path}")
        return 0
    
    with open(json_path, 'r', encoding='utf-8') as f:
        projects = json.load(f)
    
    cursor = conn.cursor()
    imported = 0
    
    for project in projects:
        try:
            # 날짜 파싱
            start_date = parse_date(project.get('startDate'))
            end_date = parse_date(project.get('endDate'))
            
            # 상태 매핑
            status_map = {
                '준공': 'completed',
                '시행중': 'in_progress',
                '제안중': 'planning'
            }
            status = status_map.get(project.get('status'), 'planning')
            
            # 프로젝트 삽입
            cursor.execute('''
                INSERT OR REPLACE INTO projects (
                    code, title, project_type, country, latitude, longitude,
                    start_date, end_date, budget_total, client, status,
                    description, title_en, department
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                project.get('__id', f"CONS-{imported}"),
                project.get('description', ''),
                'consulting',  # project_type
                project.get('name', ''),
                project.get('lat'),
                project.get('lng'),
                start_date,
                end_date,
                project.get('budget', 0) * 1000000 if project.get('budget') else 0,  # 백만원 -> 원
                project.get('client', ''),
                status,
                project.get('projectType', ''),  # description에 사업형태 저장
                project.get('englishName', ''),
                'gb'  # 글로벌사업부
            ))
            
            imported += 1
            
        except Exception as e:
            print(f"⚠️  프로젝트 import 실패: {project.get('description', 'Unknown')} - {e}")
            continue
    
    conn.commit()
    return imported

def import_oda_data(conn):
    """ODA 데이터 import"""
    json_path = os.path.join(KRC_DATA_DIR, 'global_oda.json')
    
    if not os.path.exists(json_path):
        print(f"❌ 파일을 찾을 수 없습니다: {json_path}")
        return 0
    
    with open(json_path, 'r', encoding='utf-8') as f:
        projects = json.load(f)
    
    cursor = conn.cursor()
    imported = 0
    
    for project in projects:
        try:
            # 기간 파싱 ('23-'28 형식)
            period = project.get('period', '')
            start_date = None
            end_date = None
            
            if period and '-' in period:
                parts = period.replace("'", "").split('-')
                if len(parts) == 2:
                    start_year = parts[0]
                    end_year = parts[1]
                    
                    # 2자리 연도를 4자리로 변환
                    if len(start_year) == 2:
                        start_year_int = int(start_year)
                        start_year = f"20{start_year}" if start_year_int < 72 else f"19{start_year}"
                    
                    if len(end_year) == 2:
                        end_year_int = int(end_year)
                        end_year = f"20{end_year}" if end_year_int < 72 else f"19{end_year}"
                    
                    start_date = f"{start_year}-01-01"
                    end_date = f"{end_year}-12-31"
            
            # 프로젝트 삽입
            cursor.execute('''
                INSERT OR REPLACE INTO projects (
                    code, title, project_type, country, latitude, longitude,
                    start_date, end_date, budget_total, client, status,
                    description, region, department
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                project.get('__id', f"ODA-{imported}"),
                project.get('description', ''),
                'oda_bilateral',  # project_type
                project.get('name', ''),
                project.get('lat'),
                project.get('lng'),
                start_date,
                end_date,
                project.get('budget', 0) * 1000000 if project.get('budget') else 0,  # 백만원 -> 원
                project.get('type', ''),  # ODA는 type 필드 사용
                'in_progress',  # ODA는 대부분 진행중
                project.get('content', ''),
                project.get('continent', ''),
                'aidc'  # 농식품국제개발협력센터
            ))
            
            imported += 1
            
        except Exception as e:
            print(f"⚠️  프로젝트 import 실패: {project.get('description', 'Unknown')} - {e}")
            continue
    
    conn.commit()
    return imported

def main():
    """메인 함수"""
    print("=" * 60)
    print("KRC 데이터 Import 시작")
    print("=" * 60)
    
    # DB 연결
    if not os.path.exists(DB_PATH):
        print(f"❌ 데이터베이스를 찾을 수 없습니다: {DB_PATH}")
        print("먼저 init_db.py를 실행하여 데이터베이스를 생성하세요.")
        return
    
    conn = sqlite3.connect(DB_PATH)
    
    try:
        # 기존 프로젝트 데이터 삭제 (선택사항)
        print("\n🗑️  기존 프로젝트 데이터 삭제 중...")
        cursor = conn.cursor()
        cursor.execute('DELETE FROM projects')
        conn.commit()
        print("✅ 기존 데이터 삭제 완료")
        
        # Consulting 데이터 import
        print("\n📊 해외기술용역 데이터 import 중...")
        consulting_count = import_consulting_data(conn)
        print(f"✅ 해외기술용역: {consulting_count}개 프로젝트 import 완료")
        
        # ODA 데이터 import
        print("\n📊 ODA 데이터 import 중...")
        oda_count = import_oda_data(conn)
        print(f"✅ ODA: {oda_count}개 프로젝트 import 완료")
        
        # 통계 출력
        print("\n" + "=" * 60)
        print("Import 완료!")
        print("=" * 60)
        print(f"총 {consulting_count + oda_count}개 프로젝트 import 완료")
        print(f"  - 해외기술용역 (Consulting): {consulting_count}개")
        print(f"  - ODA: {oda_count}개")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        conn.close()

if __name__ == '__main__':
    main()
