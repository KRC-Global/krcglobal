#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
간단한 프로젝트 API 엔드포인트
GIS 지도에서 사용
"""

import json
import sqlite3
import os

# DB 경로
DB_PATH = os.path.join(os.path.dirname(__file__), 'database', 'gbms.db')

def get_all_projects():
    """모든 프로젝트 데이터 조회"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT 
            id, code, title, title_en, project_type, country, 
            latitude, longitude, start_date, end_date, budget_total, 
            client, status, description, region
        FROM projects
        WHERE latitude IS NOT NULL AND longitude IS NOT NULL
        ORDER BY id DESC
    ''')
    
    projects = []
    for row in cursor.fetchall():
        projects.append({
            'id': row['id'],
            'code': row['code'],
            'title': row['title'],
            'titleEn': row['title_en'],
            'projectType': row['project_type'],
            'country': row['country'],
            'latitude': float(row['latitude']) if row['latitude'] else None,
            'longitude': float(row['longitude']) if row['longitude'] else None,
            'startDate': row['start_date'],
            'endDate': row['end_date'],
            'budgetTotal': float(row['budget_total']) if row['budget_total'] else 0,
            'client': row['client'],
            'status': row['status'],
            'description': row['description'],
            'region': row['region']
        })
    
    conn.close()
    
    return {
        'success': True,
        'data': projects,
        'count': len(projects)
    }

if __name__ == '__main__':
    # 테스트
    result = get_all_projects()
    print(json.dumps(result, ensure_ascii=False, indent=2))
