#!/usr/bin/env python3
"""역대 수행사업(PDS) 목록에서 KRC 사업 프로파일을 만든다.

공고 적합도를 키워드로만 판정하면 표현이 조금만 달라져도 뚫린다.
Claude 에게 '이 회사가 실제로 무슨 일을 해왔는지'를 사실로 보여 주면
처음 보는 표현도 맥락으로 판단할 수 있다. 그 근거가 이 프로파일이다.

출력: backend/data/krc_profile.md  (커밋해서 서버에서도 읽는다)

사용:
  python3 scripts/build_krc_profile.py
  python3 scripts/build_krc_profile.py --source '/path/PDS_연번별/000. PDS 정리결과.xlsx'
"""
from __future__ import annotations

import argparse
import re
from collections import Counter
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = (BACKEND_DIR.parent / 'PDS_연번별' / '000. PDS 정리결과.xlsx')
OUT_PATH = BACKEND_DIR / 'data' / 'krc_profile.md'

# 사업명 → 업무 유형. 위에서부터 먼저 걸리는 것을 택한다(구체적인 것이 위).
_TYPES = (
    ('관개 개발·현대화', ('관개', '개답', '용수로', '경지정리')),
    ('댐·저수지', ('댐', '저수지', '제방', '방조제', '대방조제')),
    ('홍수·재난 대응', ('홍수', '재난', '배수갑문', '복구', '기후변화대응', '위험관리')),
    ('수자원 관리·정보화', ('수자원', '물관리', '수문', '정보화', '스마트', 'ICT', '원격관측')),
    ('농촌종합개발', ('농촌', '농업개발', '농장', '농업현대화', '미곡', '기계화', '정착')),
    ('식수·상수', ('식수', '상수', '급수')),
    ('수산·어업', ('수산', '어업')),
)
# 사업 단계(용역 성격)
_STAGES = (
    ('타당성조사', ('타당성조사', '심층기획조사', '기획조사', 'F/S')),
    ('마스터플랜', ('마스터플랜', '기본계획')),
    ('설계', ('실시설계', '설계', '기본설계')),
    ('시공감리', ('감리', '시공관리')),
    ('사업관리(PMC)', ('PMC', '사업관리', '컨설팅')),
    ('건설·시공', ('건설사업', '시공', '설치사업', '복구사업')),
)


def _classify(name: str, table) -> str:
    for label, keys in table:
        if any(k.lower() in name.lower() for k in keys):
            return label
    return ''


def load_rows(source: Path) -> list[dict]:
    import openpyxl
    wb = openpyxl.load_workbook(source, data_only=True)
    ws = wb.worksheets[0]
    rows = []
    for r in ws.iter_rows(min_row=2, values_only=True):
        name = (r[1] or '').strip() if len(r) > 1 and r[1] else ''
        if not name:
            continue
        rows.append({
            'no': r[0],
            'name': ' '.join(name.split()),
            'funder': ((r[2] or '').strip() if len(r) > 2 and r[2] else '미상'),
        })
    return rows


def build_markdown(rows: list[dict]) -> str:
    funders = Counter(r['funder'] for r in rows)
    types = Counter(_classify(r['name'], _TYPES) or '기타' for r in rows)
    stages = Counter(_classify(r['name'], _STAGES) or '' for r in rows)
    stages.pop('', None)

    # 국가명은 사업명 앞머리에 자주 나온다 — 지역 감각을 주기 위해 모은다
    countries = Counter()
    for r in rows:
        for c in ('캄보디아', '필리핀', '인니', '인도네시아', '라오스', '베트남', '방글라데시',
                  '네팔', '미얀마', '태국', '스리랑카', '파키스탄', '말라위', '탄자니아',
                  '잔지바르', '에티오피아', '케냐', '우간다', '모잠비크', '이란', '브루나이',
                  '자카르타', '메콩'):
            if c in r['name']:
                countries[c] += 1

    recent = rows[-40:]

    out = []
    out.append('# 한국농어촌공사(KRC) 해외사업 프로파일')
    out.append('')
    out.append('발주공고 적합도 판정에 쓰는 참고 자료다. 아래는 모두 KRC 가 실제로')
    out.append(f'수행한 사업 {len(rows)}건에서 뽑은 사실이며, 추정이 아니다.')
    out.append('(출처: 역대 수행사업 정리자료 PDS)')
    out.append('')

    out.append('## 한 줄 정의')
    out.append('')
    out.append('KRC 는 **농업생산기반 조성** 기관이다. 관개·농업용수·배수·경지정리를')
    out.append('본업으로 하고, 그 기반이 되는 댐·저수지·제방과 홍수 대응, 그리고')
    out.append('물관리 정보화까지를 함께 다룬다. 토목 시공사가 아니라 조사·설계·감리·')
    out.append('사업관리를 수행하는 공공 엔지니어링 기관이다.')
    out.append('')

    out.append('## 업무 유형별 수행 건수')
    out.append('')
    for label, cnt in types.most_common():
        out.append(f'- {label}: {cnt}건')
    out.append('')

    out.append('## 용역 단계별 수행 건수')
    out.append('')
    for label, cnt in stages.most_common():
        out.append(f'- {label}: {cnt}건')
    out.append('')
    out.append('조사·설계·감리·사업관리가 주력이다. 단순 물품 납품이나 개인')
    out.append('컨설턴트 파견은 기관으로 수주하는 형태가 아니다.')
    out.append('')

    out.append('## 재원(발주처)별 수행 건수')
    out.append('')
    for label, cnt in funders.most_common(14):
        out.append(f'- {label}: {cnt}건')
    out.append('')
    out.append('지금 수집 중인 ADB·World Bank·AfDB·EDCF·KOICA·IsDB·AIIB 는')
    out.append('모두 실제 수주 이력이 있거나 같은 성격의 다자개발은행이다.')
    out.append('')

    if countries:
        out.append('## 주요 수행 지역')
        out.append('')
        out.append(', '.join(f'{k}({v})' for k, v in countries.most_common(16)))
        out.append('')
        out.append('동남아시아·남아시아가 중심이고, 아프리카(말라위·탄자니아·')
        out.append('에티오피아 등)로 넓혀 왔다.')
        out.append('')

    out.append('## 최근 수행사업 40건')
    out.append('')
    out.append('가장 최근의 사업 성격을 보여 준다. 처음 보는 공고가 이 목록의')
    out.append('어느 것과 닮았는지가 판단의 기준이 된다.')
    out.append('')
    for r in recent:
        out.append(f'- [{r["funder"]}] {r["name"]}')
    out.append('')

    out.append('## 판정에 쓰는 경계')
    out.append('')
    out.append('위 이력에서 직접 도출되는 기준이다.')
    out.append('')
    out.append('**본업(상)** — 관개·농업용수·배수·경지정리·간척, 그리고 농업')
    out.append('맥락의 댐·저수지·보·용수로.')
    out.append('')
    out.append('**연관(중)** — 농촌종합개발, 식량안보, 농업 가치사슬, 농촌')
    out.append('기반시설, 홍수 조절·재난위험 경감, 물관리 정보화.')
    out.append('수행 이력이 있으므로 버리지 않는다.')
    out.append('')
    out.append('**제외(하)**')
    out.append('')
    out.append('- 단순 물품 구매·납품, 개인 컨설턴트 모집(기관 수주가 아니다)')
    out.append('- 하수처리·도시위생')
    out.append('- 도로·교량·철도·공항 등 농촌과 무관한 토목')
    out.append('- 축산·낙농·양계 (농업이지만 생산기반 조성이 아니다)')
    out.append('- 전력·전기화·송배전 (에너지 사업이다)')
    out.append('- 수문관측소 건설 단독')
    out.append('')
    out.append('마지막 셋은 2026-10 운영 지침으로 추가된 제외 항목이다.')
    out.append('유의할 점: 과거에 "원격관측 물관리시스템 설치사업"(태국)처럼')
    out.append('관측을 포함한 물관리 체계 구축은 수행했다. 제외 대상은')
    out.append('관측소 구조물 건설이 사업의 목적인 경우다.')
    out.append('')
    out.append('태양광으로 구동되는 관개 설비처럼 **에너지가 수단이고 관개가')
    out.append('목적인 사업은 본업**이다. 전력 공급 자체가 목적인 사업과 구분한다.')
    out.append('')
    return '\n'.join(out) + '\n'


def main() -> int:
    ap = argparse.ArgumentParser(description='KRC 사업 프로파일 생성')
    ap.add_argument('--source', type=Path, default=DEFAULT_SOURCE)
    ap.add_argument('--out', type=Path, default=OUT_PATH)
    args = ap.parse_args()

    if not args.source.is_file():
        raise SystemExit(f'PDS 정리자료를 찾을 수 없습니다: {args.source}')
    rows = load_rows(args.source)
    if not rows:
        raise SystemExit('사업 행을 읽지 못했습니다.')
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(build_markdown(rows), encoding='utf-8')
    print(f'사업 {len(rows)}건 → {args.out}')
    print(f'{args.out.stat().st_size:,} bytes')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
