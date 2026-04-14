"""
SQLite(내부망) → Supabase(외부망) 라이프사이클 날짜 마이그레이션
- backend_ex/database/gbms.db 의 project_lifecycles 데이터를 Supabase로 업데이트
- '없음', 빈 문자열은 건너뜀 (None 처리)
- 쉼표 오타 날짜 자동 수정 (예: '22.08,01 → '22.08.01)
"""

import sqlite3
import os
import sys

# 경로 설정
SQLITE_DB = os.path.expanduser("~/Downloads/backend_ex/database/gbms.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ['DATABASE_URL'] = (
    'postgresql://postgres.zzypdvwdwgwocczpaaiu:'
    'KrcGlobal2026!DB@aws-1-ap-northeast-1.pooler.supabase.com:5432/postgres'
)

from app import app
from models import db, ConsultingProject, ProjectLifecycle


def clean_date(val):
    """날짜 값 정리: None/빈값 → None, '없음'은 그대로 보존, 쉼표→점 수정"""
    if not val or str(val).strip() in ('', 'None'):
        return None
    s = str(val).strip()
    if s == '없음':
        return '없음'
    return s.replace(',', '.')


def migrate():
    conn = sqlite3.connect(SQLITE_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT pl.consulting_project_id, cp.title_kr,
               pl.eoi_date, pl.eoi_completed, pl.eoi_progress,
               pl.shortlist_date, pl.shortlist_completed, pl.shortlist_progress,
               pl.proposal_date, pl.proposal_completed, pl.proposal_progress,
               pl.contract_date, pl.contract_completed, pl.contract_progress,
               pl.kickoff_date, pl.kickoff_completed, pl.kickoff_progress,
               pl.design_date, pl.design_completed, pl.design_progress,
               pl.construction_date, pl.construction_completed, pl.construction_progress,
               pl.completion_date, pl.completion_completed, pl.completion_progress
        FROM project_lifecycles pl
        JOIN consulting_projects cp ON pl.consulting_project_id = cp.id
        ORDER BY pl.consulting_project_id
    """)
    rows = cur.fetchall()
    conn.close()

    print(f"SQLite에서 {len(rows)}개 라이프사이클 레코드 로드")

    updated = 0
    created = 0
    skipped = 0

    with app.app_context():
        # Supabase의 프로젝트 제목→ID 매핑
        supabase_projects = {p.title_kr: p.id for p in ConsultingProject.query.all()}
        supabase_lc = {lc.consulting_project_id: lc for lc in ProjectLifecycle.query.all()}

        for row in rows:
            sqlite_project_id = row['consulting_project_id']
            title_kr = row['title_kr']

            # Supabase 프로젝트 ID 찾기 (제목 기준, 없으면 SQLite ID 그대로 사용)
            supabase_pid = supabase_projects.get(title_kr, sqlite_project_id)

            # 프로젝트가 Supabase에 없으면 건너뜀
            if supabase_pid not in {p.id for p in ConsultingProject.query.all()}:
                print(f"  [SKIP] id={sqlite_project_id} '{title_kr}' — Supabase에 없음")
                skipped += 1
                continue

            # 날짜 정리
            fields = {
                'eoi_date':          clean_date(row['eoi_date']),
                'eoi_completed':     bool(row['eoi_completed']),
                'eoi_progress':      bool(row['eoi_progress']),
                'shortlist_date':    clean_date(row['shortlist_date']),
                'shortlist_completed': bool(row['shortlist_completed']),
                'shortlist_progress':  bool(row['shortlist_progress']),
                'proposal_date':     clean_date(row['proposal_date']),
                'proposal_completed': bool(row['proposal_completed']),
                'proposal_progress':  bool(row['proposal_progress']),
                'contract_date':     clean_date(row['contract_date']),
                'contract_completed': bool(row['contract_completed']),
                'contract_progress':  bool(row['contract_progress']),
                'kickoff_date':      clean_date(row['kickoff_date']),
                'kickoff_completed': bool(row['kickoff_completed']),
                'kickoff_progress':  bool(row['kickoff_progress']),
                'design_date':       clean_date(row['design_date']),
                'design_completed':  bool(row['design_completed']),
                'design_progress':   bool(row['design_progress']),
                'construction_date': clean_date(row['construction_date']),
                'construction_completed': bool(row['construction_completed']),
                'construction_progress':  bool(row['construction_progress']),
                'completion_date':   clean_date(row['completion_date']),
                'completion_completed': bool(row['completion_completed']),
                'completion_progress':  bool(row['completion_progress']),
            }

            # Supabase lifecycle 레코드 찾기 or 생성
            lc = supabase_lc.get(supabase_pid)
            if not lc:
                lc = ProjectLifecycle(consulting_project_id=supabase_pid)
                db.session.add(lc)
                created += 1
                action = 'CREATE'
            else:
                updated += 1
                action = 'UPDATE'

            # 필드 업데이트 (None인 경우 기존값 유지)
            for field, value in fields.items():
                if value is None and 'date' in field:
                    # 날짜 필드: None이면 기존 Supabase 값 유지
                    pass
                else:
                    setattr(lc, field, value)

            print(f"  [{action}] id={supabase_pid} '{title_kr[:35]}'")
            print(f"          eoi={fields['eoi_date'] or '-'!r} "
                  f"prop={fields['proposal_date'] or '-'!r} "
                  f"cont={fields['contract_date'] or '-'!r} "
                  f"comp={fields['completion_date'] or '-'!r}")

        try:
            db.session.commit()
            print(f"\n완료: 생성={created}, 업데이트={updated}, 건너뜀={skipped}")
        except Exception as e:
            db.session.rollback()
            print(f"\n오류 발생: {e}")
            import traceback
            traceback.print_exc()


if __name__ == '__main__':
    migrate()
