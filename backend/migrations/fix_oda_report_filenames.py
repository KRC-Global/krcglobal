"""
기존 ODA 보고서 file_name을 표준 네이밍으로 일괄 수정
secure_filename이 한글을 제거해서 의미없는 이름으로 저장된 것을 수정
예: '1543000_2024_010_______.pdf' → '2024_세네갈_중고_농기계_지원_및_수리센터_지원_FS.pdf'
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
from models import OdaReport, OdaProject
from utils.file_naming import make_oda_report_filename


def migrate():
    with app.app_context():
        reports = OdaReport.query.all()
        updated = 0
        skipped = 0

        for r in reports:
            project = OdaProject.query.get(r.oda_project_id)
            if not project:
                print(f"  [SKIP] id={r.id}: 프로젝트 없음 (oda_project_id={r.oda_project_id})")
                skipped += 1
                continue

            ext = r.file_type or 'pdf'
            new_name = make_oda_report_filename(r.report_type, ext, project)

            old_name = r.file_name
            if old_name != new_name:
                r.file_name = new_name
                updated += 1
                print(f"  [FIX] id={r.id}: '{old_name}' → '{new_name}'")
            else:
                skipped += 1

        if updated > 0:
            db.session.commit()

        print(f"\n완료: {updated}건 수정, {skipped}건 변경 없음 (총 {len(reports)}건)")


if __name__ == '__main__':
    migrate()
