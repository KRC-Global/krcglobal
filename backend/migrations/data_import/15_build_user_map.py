"""Stage 3: 내부망 sqlite users.id → 외부망 supabase users.id 매핑 생성.

매칭 키: User.user_id (string). 외부망 [models.User.user_id] 가 unique.

사용법:
    python backend/migrations/data_import/15_build_user_map.py
      [--fallback-user-id <int>]

산출물:
  - manifests/user_map.json    { "<sqlite_id_int>": <supabase_id_or_null> }
  - reports/user_map_summary.md
"""
import argparse
import json
import os
import sys

from _bootstrap import app, db, EXPORTS_DIR, MANIFESTS_DIR, REPORTS_DIR  # noqa
from sqlalchemy import text


def load_sqlite_users():
    path = os.path.join(EXPORTS_DIR, 'users.jsonl')
    if not os.path.exists(path):
        print(f'ERROR: {path} 없음. 먼저 10_export_sqlite.py 실행.', file=sys.stderr)
        sys.exit(2)
    users = []
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            users.append(json.loads(line))
    return users


def load_supabase_users():
    rows = db.session.execute(text(
        'SELECT id, user_id, name, employee_number FROM users'
    )).fetchall()
    by_user_id = {}
    for r in rows:
        if r.user_id:
            by_user_id[r.user_id] = {
                'id': r.id, 'user_id': r.user_id,
                'name': r.name, 'employee_number': r.employee_number,
            }
    return by_user_id


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--fallback-user-id', type=int, default=None,
                        help='미매칭 사용자가 created_by/updated_by 였을 때 폴백할 외부망 users.id')
    parser.add_argument('--out', default=os.path.join(MANIFESTS_DIR, 'user_map.json'))
    parser.add_argument('--report', default=os.path.join(REPORTS_DIR, 'user_map_summary.md'))
    args = parser.parse_args()

    sl_users = load_sqlite_users()

    with app.app_context():
        sb_by_uid = load_supabase_users()

    mapping = {}  # sqlite_id (str) -> supabase_id (int) | None
    matched = []
    unmatched = []
    for u in sl_users:
        sl_id = u.get('id')
        sl_uid = u.get('user_id')
        match = sb_by_uid.get(sl_uid)
        if match:
            mapping[str(sl_id)] = match['id']
            matched.append({'sl': u, 'sb_id': match['id']})
        else:
            mapping[str(sl_id)] = args.fallback_user_id  # None 또는 int
            unmatched.append(u)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump({
            'fallback_user_id': args.fallback_user_id,
            'map': mapping,
        }, f, ensure_ascii=False, indent=2)

    lines = [
        '# User 매핑 보고서',
        '',
        f'- 매칭 키: `user_id` (string)',
        f'- 내부망 users: {len(sl_users)}',
        f'- 외부망 users: {len(sb_by_uid)}',
        f'- 매칭: **{len(matched)}**',
        f'- 미매칭: **{len(unmatched)}** (fallback: `{args.fallback_user_id}`)',
        '',
        '## 매칭 결과',
        '',
        '| sqlite_id | user_id | name | → supabase_id |',
        '|-----------|---------|------|----------------|',
    ]
    for m in matched:
        u = m['sl']
        lines.append(f"| {u.get('id')} | `{u.get('user_id')}` | {u.get('name') or ''} | {m['sb_id']} |")

    lines.append('')
    lines.append('## 미매칭 (수동 처리 필요)')
    lines.append('')
    if unmatched:
        lines.append('| sqlite_id | user_id | name | employee_number | email |')
        lines.append('|-----------|---------|------|------------------|-------|')
        for u in unmatched:
            lines.append(
                f"| {u.get('id')} | `{u.get('user_id') or ''}` | {u.get('name') or ''} "
                f"| {u.get('employee_number') or ''} | {u.get('email') or ''} |"
            )
        lines.append('')
        lines.append('**조치 옵션**:')
        lines.append('1. 외부망 관리자 페이지에서 위 사용자들을 신규 생성한 뒤 본 스크립트 재실행')
        lines.append('2. `--fallback-user-id <admin_id>` 인자로 일괄 폴백')
        lines.append('3. 미매칭이 있어도 무방하면 그대로 진행 (created_by NULL 허용)')
    else:
        lines.append('없음 ✅')

    with open(args.report, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    print(f'user_map.json: {args.out}')
    print(f'report:        {args.report}')
    print(f'matched={len(matched)}  unmatched={len(unmatched)}  fallback={args.fallback_user_id}')
    return 0 if len(unmatched) == 0 or args.fallback_user_id is not None else 1


if __name__ == '__main__':
    sys.exit(main())
