"""Stage 6: 마이그레이션 검증 (read-only).

확인 항목:
1) 테이블별 export 행수 vs (INSERT + SKIP) 일치
2) id_mapping 의 신규 INSERT id 가 실제 DB에 존재
3) R2 객체 head_object 샘플 검증
4) FK 무결성 — 자식 → 부모 존재
5) Stage 0의 r2_objects_before.txt 와 현재 사용량 비교

사용법:
    python backend/migrations/data_import/40_verify.py
"""
import argparse
import json
import os
import random
import sys
from collections import defaultdict

from _bootstrap import app, db, EXPORTS_DIR, MANIFESTS_DIR, REPORTS_DIR  # noqa
from _tables import TABLES, by_name  # noqa
from sqlalchemy import text


def count_export(name):
    p = os.path.join(EXPORTS_DIR, f'{name}.jsonl')
    if not os.path.exists(p):
        return 0
    n = 0
    with open(p, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                n += 1
    return n


def load_id_mapping():
    p = os.path.join(MANIFESTS_DIR, 'id_mapping.json')
    if not os.path.exists(p):
        return {}
    with open(p, 'r', encoding='utf-8') as f:
        return json.load(f)


def load_manifest():
    p = os.path.join(MANIFESTS_DIR, 'uploaded_manifest.jsonl')
    out = []
    if not os.path.exists(p):
        return out
    with open(p, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def verify_counts(report, id_mapping):
    report.append('## 1. 테이블별 카운트')
    report.append('')
    report.append('| 테이블 | export | id_mapping | DB COUNT | 비고 |')
    report.append('|--------|--------|------------|----------|------|')
    for entry in TABLES:
        name = entry['name']
        exp = count_export(name)
        mp = id_mapping.get(name, {})
        in_db = 0
        try:
            row = db.session.execute(text(f'SELECT COUNT(*) FROM "{name}"')).scalar()
            in_db = row
        except Exception as e:
            in_db = f'ERR: {str(e)[:50]}'
        note = '✅' if exp == len(mp) else ('mapping<export' if len(mp) < exp else '')
        report.append(f'| {name} | {exp} | {len(mp)} | {in_db} | {note} |')
    report.append('')


def verify_mapped_records_exist(report, id_mapping):
    report.append('## 2. id_mapping 의 신규 id 가 DB에 실제 존재하는지')
    report.append('')
    missing = []
    for name, m in id_mapping.items():
        for sl_id, sb_id in m.items():
            if not isinstance(sb_id, int):
                continue
            row = db.session.execute(
                text(f'SELECT 1 FROM "{name}" WHERE id = :id'), {'id': sb_id}
            ).fetchone()
            if not row:
                missing.append((name, sl_id, sb_id))
    if missing:
        report.append(f'❌ {len(missing)} 건 누락')
        for name, sl, sb in missing[:20]:
            report.append(f'  - {name} sl={sl} sb={sb}')
        if len(missing) > 20:
            report.append(f'  - ... 외 {len(missing) - 20} 건')
    else:
        report.append('✅ 모두 존재')
    report.append('')


def verify_r2(report):
    report.append('## 3. R2 객체 샘플 검증')
    report.append('')
    manifest = load_manifest()
    if not manifest:
        report.append('manifest 비어있음 — 검증 생략')
        report.append('')
        return

    from utils.r2_storage import get_r2_client, get_bucket_usage
    client = get_r2_client()
    bucket = app.config['R2_BUCKET_NAME']

    # prefix 별로 그룹화
    by_prefix = defaultdict(list)
    for rec in manifest:
        prefix = rec.get('r2_key', '').split('/', 1)[0]
        by_prefix[prefix].append(rec)

    report.append('| prefix | 업로드수 | 샘플(3건) head 결과 |')
    report.append('|--------|----------|---------------------|')
    for prefix, items in sorted(by_prefix.items()):
        samples = random.sample(items, min(3, len(items)))
        results = []
        for s in samples:
            try:
                client.head_object(Bucket=bucket, Key=s['r2_key'])
                results.append('OK')
            except Exception as e:
                results.append(f'FAIL({str(e)[:30]})')
        report.append(f'| {prefix}/ | {len(items)} | {" / ".join(results)} |')

    try:
        usage = get_bucket_usage()
        max_bytes = app.config['R2_MAX_STORAGE_BYTES']
        report.append('')
        report.append(f'**R2 현재 사용량**: {usage:,} / {max_bytes:,} bytes '
                      f'({usage / max_bytes * 100:.1f}%)')
    except Exception as e:
        report.append(f'\n사용량 조회 실패: {e}')
    report.append('')


def verify_fk_integrity(report, id_mapping):
    report.append('## 4. FK 무결성 (자식 → 부모)')
    report.append('')
    issues = []
    for entry in TABLES:
        for fk_col, parent_table in entry.get('parent_fks', {}).items():
            if parent_table == 'users':
                continue  # nullable 허용
            new_ids = [v for v in id_mapping.get(entry['name'], {}).values()
                       if isinstance(v, int)]
            if not new_ids:
                continue
            # 신규 자식 행에 대해 FK 검사
            sample = new_ids[:50]  # 너무 많으면 샘플링
            placeholders = ', '.join(f':id{i}' for i in range(len(sample)))
            params = {f'id{i}': v for i, v in enumerate(sample)}
            sql = text(
                f'SELECT id, "{fk_col}" FROM "{entry["name"]}" '
                f'WHERE id IN ({placeholders}) AND "{fk_col}" IS NOT NULL'
            )
            rows = db.session.execute(sql, params).fetchall()
            for row in rows:
                parent_id = row[1]
                exists = db.session.execute(
                    text(f'SELECT 1 FROM "{parent_table}" WHERE id = :id'),
                    {'id': parent_id}
                ).fetchone()
                if not exists:
                    issues.append((entry['name'], row[0], fk_col, parent_id, parent_table))
    if issues:
        report.append(f'❌ FK 깨짐 {len(issues)} 건')
        for r in issues[:20]:
            report.append(f'  - {r[0]}#{r[1]} {r[2]}={r[3]} → {r[4]} 없음')
    else:
        report.append('✅ 샘플 검사 통과')
    report.append('')


def verify_r2_delta(report):
    report.append('## 5. R2 사용량 변화 (Stage 0 스냅샷과 비교)')
    report.append('')
    before_path = os.path.join(REPORTS_DIR, 'r2_objects_before.txt')
    if not os.path.exists(before_path):
        report.append('r2_objects_before.txt 없음 — 스킵')
        report.append('')
        return
    before_count = 0
    before_size = 0
    with open(before_path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.startswith('#') or not line.strip():
                continue
            parts = line.rstrip('\n').split('\t')
            if len(parts) >= 2:
                try:
                    before_size += int(parts[1])
                    before_count += 1
                except ValueError:
                    continue

    try:
        from utils.r2_storage import get_r2_client
        client = get_r2_client()
        bucket = app.config['R2_BUCKET_NAME']
        after_count = 0
        after_size = 0
        paginator = client.get_paginator('list_objects_v2')
        for page in paginator.paginate(Bucket=bucket):
            for obj in page.get('Contents', []):
                after_count += 1
                after_size += obj['Size']
        report.append(f'- before: {before_count:>6} 객체, {before_size:>15,} bytes')
        report.append(f'- after:  {after_count:>6} 객체, {after_size:>15,} bytes')
        report.append(f'- delta:  {after_count - before_count:>+6} 객체, {after_size - before_size:>+15,} bytes')
    except Exception as e:
        report.append(f'after 조회 실패: {e}')
    report.append('')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', default=os.path.join(REPORTS_DIR, 'migration_report.md'))
    args = parser.parse_args()

    id_mapping = load_id_mapping()
    report = ['# Migration Verification Report', '']

    with app.app_context():
        try:
            from models import expansion  # noqa
        except ImportError:
            pass

        verify_counts(report, id_mapping)
        verify_mapped_records_exist(report, id_mapping)
        verify_r2(report)
        verify_fk_integrity(report, id_mapping)
        verify_r2_delta(report)

    os.makedirs(os.path.dirname(args.report), exist_ok=True)
    with open(args.report, 'w', encoding='utf-8') as f:
        f.write('\n'.join(report))

    print(f'Report: {args.report}')
    print()
    print('\n'.join(report[:60]))
    if len(report) > 60:
        print('... (보고서 파일에서 전체 확인)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
