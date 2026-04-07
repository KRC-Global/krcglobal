"""
해외사무소 데이터 업데이트 스크립트
현재 ODA 데스크 8개국으로 업데이트
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app
from models import db, Office

def update_offices():
    """기존 사무소 삭제 후 ODA 데스크 생성"""

    with app.app_context():
        # 기존 사무소 모두 삭제
        Office.query.delete()
        db.session.commit()
        print("✓ 기존 해외사무소 데이터 삭제 완료")

        # 새로운 ODA 데스크 정보
        oda_desks = [
            {
                'name': '가나 ODA데스크',
                'country': '가나',
                'country_code': 'GH',
                'region': '아프리카',
                'city': '아크라',
                'office_type': 'oda_desk',
                'status': 'active',
                'contact_person': '김아프리카',
                'contact_email': 'ghana@krc.co.kr',
                'contact_phone': '+233-20-123-4567',
                'established_date': date(2020, 3, 1),
                'annual_budget': 150000000,
                'address': 'Accra, Ghana'
            },
            {
                'name': '케냐 ODA데스크',
                'country': '케냐',
                'country_code': 'KE',
                'region': '아프리카',
                'city': '나이로비',
                'office_type': 'oda_desk',
                'status': 'active',
                'contact_person': '이동부',
                'contact_email': 'kenya@krc.co.kr',
                'contact_phone': '+254-20-234-5678',
                'established_date': date(2019, 6, 1),
                'annual_budget': 180000000,
                'address': 'Nairobi, Kenya'
            },
            {
                'name': '우즈베키스탄 ODA데스크',
                'country': '우즈베키스탄',
                'country_code': 'UZ',
                'region': '중앙아시아',
                'city': '타슈켄트',
                'office_type': 'oda_desk',
                'status': 'active',
                'contact_person': '박중앙',
                'contact_email': 'uzbekistan@krc.co.kr',
                'contact_phone': '+998-71-345-6789',
                'established_date': date(2018, 9, 1),
                'annual_budget': 200000000,
                'address': 'Tashkent, Uzbekistan'
            },
            {
                'name': '베트남 ODA데스크',
                'country': '베트남',
                'country_code': 'VN',
                'region': '아시아',
                'city': '하노이',
                'office_type': 'oda_desk',
                'status': 'active',
                'contact_person': '최동남',
                'contact_email': 'vietnam@krc.co.kr',
                'contact_phone': '+84-24-456-7890',
                'established_date': date(2017, 4, 1),
                'annual_budget': 250000000,
                'address': 'Hanoi, Vietnam'
            },
            {
                'name': '라오스 ODA데스크',
                'country': '라오스',
                'country_code': 'LA',
                'region': '아시아',
                'city': '비엔티안',
                'office_type': 'oda_desk',
                'status': 'active',
                'contact_person': '정메콩',
                'contact_email': 'laos@krc.co.kr',
                'contact_phone': '+856-21-567-8901',
                'established_date': date(2019, 11, 1),
                'annual_budget': 160000000,
                'address': 'Vientiane, Laos'
            },
            {
                'name': '캄보디아 ODA데스크',
                'country': '캄보디아',
                'country_code': 'KH',
                'region': '아시아',
                'city': '프놈펜',
                'office_type': 'oda_desk',
                'status': 'active',
                'contact_person': '한앙코르',
                'contact_email': 'cambodia@krc.co.kr',
                'contact_phone': '+855-23-678-9012',
                'established_date': date(2018, 2, 1),
                'annual_budget': 170000000,
                'address': 'Phnom Penh, Cambodia'
            },
            {
                'name': '세네갈 ODA데스크',
                'country': '세네갈',
                'country_code': 'SN',
                'region': '아프리카',
                'city': '다카르',
                'office_type': 'oda_desk',
                'status': 'active',
                'contact_person': '송서부',
                'contact_email': 'senegal@krc.co.kr',
                'contact_phone': '+221-33-789-0123',
                'established_date': date(2021, 1, 1),
                'annual_budget': 140000000,
                'address': 'Dakar, Senegal'
            },
            {
                'name': '키리바시 ODA데스크',
                'country': '키리바시',
                'country_code': 'KI',
                'region': '오세아니아',
                'city': '타라와',
                'office_type': 'oda_desk',
                'status': 'active',
                'contact_person': '윤태평',
                'contact_email': 'kiribati@krc.co.kr',
                'contact_phone': '+686-890-1234',
                'established_date': date(2022, 5, 1),
                'annual_budget': 120000000,
                'address': 'Tarawa, Kiribati'
            }
        ]

        # ODA 데스크 생성
        for desk_data in oda_desks:
            desk = Office(**desk_data)
            db.session.add(desk)

        db.session.commit()
        print(f"✓ {len(oda_desks)}개 ODA 데스크 생성 완료")

        # 생성된 데스크 목록 출력
        print("\n생성된 ODA 데스크:")
        for desk in oda_desks:
            print(f"  - {desk['name']} ({desk['city']}, {desk['country']})")

        print("\n🎉 해외사무소 데이터 업데이트 완료!")

if __name__ == '__main__':
    update_offices()
