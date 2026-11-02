"""발주공고 LLM 보조 — 번역·요약, 항목 추출, 적합도 판정, 관련 공고 연결.

규칙 기반 경로를 대체하지 않고 보강한다. 네 기능 모두 실패하면 None 을
돌려주고, 호출자는 기존 동작을 그대로 수행한다. 수집·발송이 LLM 때문에
멈추는 일이 없어야 한다 — 이 시스템의 반복된 실패 유형이 '조용한 무수집'
이었고, 거기에 외부 의존성을 하나 더 얹는 셈이기 때문이다.

판정 근거가 되는 KRC 사업 프로파일은 data/krc_profile.md 에 있다.
역대 수행사업 174건에서 뽑은 사실이며 scripts/build_krc_profile.py 로
다시 만든다.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from services.claude_client import ClaudeUnavailable, complete_json, is_enabled

DATA_DIR = Path(__file__).resolve().parent.parent / 'data'
PROFILE_PATH = DATA_DIR / 'krc_profile.md'

_profile_cache = {'text': '', 'mtime': 0.0}


def krc_profile() -> str:
    """KRC 사업 프로파일. 파일이 없으면 빈 문자열(판정은 계속 가능)."""
    try:
        stat = PROFILE_PATH.stat()
    except OSError:
        return ''
    if _profile_cache['mtime'] != stat.st_mtime:
        _profile_cache['text'] = PROFILE_PATH.read_text(encoding='utf-8')
        _profile_cache['mtime'] = stat.st_mtime
    return _profile_cache['text']


def _notice_block(notice: dict, *, excerpt_chars: int = 2500,
                  for_extraction: bool = False) -> str:
    """판정·요약에 쓰는 공고 원문 블록.

    for_extraction 이면 이미 수집된 마감일·금액·발주처를 빼고 넘긴다.
    넣어 두면 모델이 '원문에서 뽑은 값'이 아니라 우리가 준 값을 그대로
    돌려주고, 근거 검증도 그 줄 때문에 통과해 버린다(실측: #433 에서
    마감일이 본문에 없는데도 추출된 것처럼 보였다). 추출은 원문이
    새로 알려주는 것만 가져와야 의미가 있다.
    """
    # to_dict() 는 소스별 *_details 를 평평하게 펴서 'details' 로 내보낸다.
    # DB 객체를 그대로 받는 경우에 대비해 raw_data 경로도 함께 본다.
    details = notice.get('details')
    if not isinstance(details, dict):
        details = {}
    if not details:
        raw = notice.get('rawData') or notice.get('raw_data') or {}
        if isinstance(raw, dict):
            for key in ('adb_details', 'afdb_details', 'wb_details'):
                if isinstance(raw.get(key), dict):
                    details = raw[key]
                    break
    excerpt = (details.get('text_excerpt')
               or notice.get('textExcerpt') or notice.get('text_excerpt') or '')
    fields = [
        f"제목: {notice.get('title') or ''}",
        f"발주기관(수집원): {notice.get('source') or ''}",
        f"국가: {notice.get('country') or ''}",
        f"원문 주소: {notice.get('sourceUrl') or notice.get('source_url') or ''}",
    ]
    if not for_extraction:
        fields[2:2] = [
            f"발주처: {notice.get('client') or ''}",
            f"분야: {notice.get('sector') or ''}",
            f"마감일(수집값): {notice.get('deadline') or '없음'}",
            f"계약규모(수집값): "
            f"{notice.get('contractValue') or notice.get('contract_value') or '없음'}",
        ]
    if details.get('attachment_url'):
        fields.append(f"첨부 문서: {details['attachment_url']}")
    if excerpt:
        fields.append(f"\n[원문 발췌]\n{str(excerpt)[:excerpt_chars]}")
    return '\n'.join(fields)


# ── A. 번역·요약 ────────────────────────────────────────────────────────────

_SUMMARY_SYSTEM = """너는 한국농어촌공사(KRC) 글로벌사업처의 공고 분석 담당이다.
해외 발주공고를 받아 국문 제목과 카드용 요약을 만든다.

{profile}

## 출력 형식

JSON 만 출력한다. 설명을 덧붙이지 않는다.

{{
  "title_ko": "국문 제목",
  "overview": ["개요 1", "개요 2"],
  "check": ["확인 필요 1", "확인 필요 2"],
  "review": ["KRC 검토 1"]
}}

## 작성 규칙

- title_ko: 공고 유형을 앞에 두고 국가·사업명을 담는다. 원문에 없는 말을
  만들지 않는다. 80자 이내.
- overview(2줄): 무슨 사업이고 이번 공고로 무엇을 발주하는지. 재원과
  발주기관을 밝힌다.
- check(2줄): 자료에서 확인되지 않는 항목(마감일·금액·참가자격 등)과,
  KRC 가 참여를 판단할 때 걸리는 지점. "원문을 확인하세요" 같은 빈말
  대신 무엇이 비어 있는지 구체적으로 적는다.
- review(1~2줄): KRC 관점의 검토 방향. 과거 수행사업과 닮은 점이 있으면
  그 사업 성격을 근거로 든다.
- 각 줄은 한 문장, 60~100자. 문장 끝을 '…' 로 흐리지 않는다.
- **원문에 없는 수치·날짜·기관명을 지어내지 않는다.** 모르면 모른다고 쓴다.
- 평서체('~이다', '~한다')로 통일한다."""


def translate_and_summarize(notice: dict) -> dict | None:
    """국문 제목 + 6줄 요약. 실패하면 None → 호출자가 기존 경로 사용."""
    if not is_enabled():
        return None
    try:
        data = complete_json(
            _SUMMARY_SYSTEM.format(profile=krc_profile()),
            f'다음 공고를 처리하라.\n\n{_notice_block(notice)}',
            max_tokens=1600,
        )
    except ClaudeUnavailable as e:
        print(f'[notice-ai] 요약 실패 #{notice.get("id")}: {str(e)[:120]}')
        return None

    title = _clean_line(data.get('title_ko'))
    lines = []
    for key in ('overview', 'check', 'review'):
        vals = data.get(key)
        if isinstance(vals, str):
            vals = [vals]
        for v in (vals or [])[:2]:
            cleaned = _clean_line(v)
            if cleaned:
                lines.append(cleaned)
    if not title or len(lines) < 3:
        print(f'[notice-ai] 요약 형식 미달 #{notice.get("id")}: {len(lines)}줄')
        return None
    return {'title_ko': title[:500], 'summary_ko': '\n'.join(lines)}


def _clean_line(value) -> str:
    line = ' '.join(str(value or '').split())
    # 모델이 붙이는 머리 기호·번호를 떼어 콜아웃 불릿과 겹치지 않게 한다
    line = re.sub(r'^[-•*]\s*', '', line)
    line = re.sub(r'^[①-⑳\d]+[.)]\s*', '', line)
    return line


# ── B. 항목 추출 ────────────────────────────────────────────────────────────

_EXTRACT_SYSTEM = """너는 발주공고 원문에서 사실만 뽑아내는 추출기다.

JSON 만 출력한다.

{
  "deadline": "YYYY-MM-DD 또는 null",
  "contract_value": "통화와 금액을 원문 표기대로, 없으면 null",
  "client": "실제 발주처(차주·집행기관), 없으면 null",
  "eligibility": "참가자격 한 문장 요약, 없으면 null",
  "evidence": {"deadline": "근거가 된 원문 구절", "contract_value": "...", "client": "..."}
}

규칙:
- **원문에 적혀 있지 않으면 반드시 null 이다.** 추정·계산·상식으로 채우지 않는다.
- 뽑은 값마다 evidence 에 근거 구절을 원문 그대로 넣는다. 근거를 쓸 수
  없으면 그 항목은 null 이다.
- 마감일은 '입찰서·관심표명서 제출 마감'이다. 공고일·개찰일·사업기간이
  아니다. 시각은 버리고 날짜만 쓴다.
- 차관번호·참조번호는 금액이 아니다.
- 자금을 빌려준 다자개발은행(ADB·AfDB·World Bank 등)은 client 가 아니다.
  돈을 받아 사업을 발주하는 쪽(부처·청·정부)이 client 다."""


def extract_fields(notice: dict) -> dict | None:
    """마감일·금액·발주처·참가자격 추출. 근거가 원문에 없으면 버린다."""
    if not is_enabled():
        return None
    block = _notice_block(notice, excerpt_chars=6000, for_extraction=True)
    if '[원문 발췌]' not in block:
        # 본문이 없으면 뽑을 근거 자체가 없다. 호출도 하지 않는다(비용·오탐 방지).
        return None
    try:
        data = complete_json(
            _EXTRACT_SYSTEM,
            f'다음 공고에서 항목을 추출하라.\n\n{block}',
            max_tokens=1200,
        )
    except ClaudeUnavailable as e:
        print(f'[notice-ai] 추출 실패 #{notice.get("id")}: {str(e)[:120]}')
        return None

    evidence = data.get('evidence') if isinstance(data.get('evidence'), dict) else {}
    haystack = _norm_for_match(block)
    out = {}

    deadline = _clean_line(data.get('deadline'))
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', deadline or ''):
        if _evidence_ok(evidence.get('deadline'), haystack):
            out['deadline'] = deadline
    for key in ('contract_value', 'client', 'eligibility'):
        val = _clean_line(data.get(key))
        if not val or val.lower() in ('null', 'none', '없음'):
            continue
        # eligibility 는 요약문이라 원문 대조가 어렵다 — 근거 검증 대상에서 뺀다
        if key != 'eligibility' and not _evidence_ok(evidence.get(key), haystack):
            print(f'[notice-ai] 근거 없는 {key} 폐기 #{notice.get("id")}: {val[:50]}')
            continue
        out[key] = val[:200]
    return out or None


def _norm_for_match(text: str) -> str:
    """대조용 정규화 — 공백·대소문자·구두점 차이를 무시한다."""
    return re.sub(r'[^0-9a-z가-힣]', '', (text or '').lower())


def _evidence_ok(evidence, haystack: str) -> bool:
    """근거 구절이 실제 원문에 있는지. 모델이 지어낸 값을 막는 마지막 관문."""
    needle = _norm_for_match(evidence)
    if len(needle) < 8:
        return False
    return needle in haystack


# ── C. 적합도 판정 ──────────────────────────────────────────────────────────

_FIT_SYSTEM = """너는 한국농어촌공사(KRC)가 해외 발주공고에 참여할지
가려내는 심사자다.

{profile}

## 출력

JSON 만 출력한다.

{{
  "grade": "상" | "중" | "하",
  "reason": "20자 이내 분류 사유",
  "rationale": "한 문장 근거",
  "confidence": 0.0~1.0
}}

## 판정 기준

- 상: KRC 본업. 관개·농업용수·배수·경지정리·간척, 농업 맥락의 댐·저수지·
  용수로.
- 중: 연관 분야. 농촌종합개발, 식량안보, 농업 가치사슬, 농촌 기반시설,
  홍수 조절·재난위험 경감, 물관리 정보화.
- 하: 위 제외 목록에 해당하거나 KRC 업무와 무관한 사업.

## 반드시 지킬 것

- **사업의 목적으로 판정한다.** 본문에 한 번 스친 단어로 판정하지 않는다.
  예: 철도 사업 설명문에 'irrigation' 이 한 번 나와도 그것은 철도 사업이다.
- 수단과 목적을 구분한다. 태양광으로 돌리는 관개설비는 관개 사업이고,
  전력 공급 자체가 목적이면 전력 사업이다.
- 영어·프랑스어 공고가 많다. 표현이 달라도 내용으로 판단한다.
- 애매하면 confidence 를 낮게 준다. 억지로 확신하지 않는다."""


def judge_fit(notice: dict) -> dict | None:
    """적합도 재판정. {'grade','reason','rationale','confidence'} 또는 None."""
    if not is_enabled():
        return None
    try:
        data = complete_json(
            _FIT_SYSTEM.format(profile=krc_profile()),
            f'다음 공고를 판정하라.\n\n{_notice_block(notice)}',
            max_tokens=700,
        )
    except ClaudeUnavailable as e:
        print(f'[notice-ai] 판정 실패 #{notice.get("id")}: {str(e)[:120]}')
        return None

    grade = _clean_line(data.get('grade'))
    if grade not in ('상', '중', '하'):
        return None
    try:
        confidence = float(data.get('confidence'))
    except (TypeError, ValueError):
        confidence = 0.0
    return {
        'grade': grade,
        'reason': (_clean_line(data.get('reason')) or 'LLM 판정')[:40],
        'rationale': _clean_line(data.get('rationale'))[:300],
        'confidence': max(0.0, min(1.0, confidence)),
    }


# ── E. 관련 공고 연결 ───────────────────────────────────────────────────────

_LINK_SYSTEM = """너는 발주공고끼리 같은 사업인지 가려내는 판별기다.

같은 사업이 기관·언어·단계를 달리해 여러 번 공고된다. 예:
  - World Bank 와 AfDB 가 같은 사업을 각자 공고
  - 같은 사업의 일반조달공고(GPN) → 입찰공고(SPN)
  - 1단계 공고 뒤의 2단계 공고

JSON 만 출력한다.

{
  "matches": [
    {"id": 123, "relation": "동일|후속|관련", "why": "한 문장 근거"}
  ]
}

규칙:
- 사업명·차주·지역·사업약어(DRSLP, SIMURP 등)가 겹칠 때만 연결한다.
- 분야가 같다는 이유만으로 연결하지 않는다. '캄보디아 관개사업' 둘이
  서로 다른 사업일 수 있다.
- 확실하지 않으면 matches 를 비운다. 틀린 연결이 빈 결과보다 나쁘다."""


def link_related(notice: dict, candidates: list[dict]) -> list[dict]:
    """후보 중 같은/후속 사업을 찾는다. 실패하거나 없으면 빈 리스트."""
    if not is_enabled() or not candidates:
        return []
    lines = []
    for c in candidates[:40]:
        lines.append(
            f"- id={c.get('id')} | {c.get('source')} | {c.get('country') or ''} | "
            f"{(c.get('title') or '')[:150]}"
        )
    try:
        data = complete_json(
            _LINK_SYSTEM,
            '기준 공고:\n' + _notice_block(notice, excerpt_chars=900)
            + '\n\n후보 목록:\n' + '\n'.join(lines),
            max_tokens=900,
        )
    except ClaudeUnavailable as e:
        print(f'[notice-ai] 연결 실패 #{notice.get("id")}: {str(e)[:120]}')
        return []

    valid_ids = {c.get('id') for c in candidates}
    out = []
    for m in (data.get('matches') or [])[:5]:
        try:
            mid = int(m.get('id'))
        except (TypeError, ValueError):
            continue
        if mid not in valid_ids or mid == notice.get('id'):
            continue
        relation = _clean_line(m.get('relation'))
        if relation not in ('동일', '후속', '관련'):
            continue
        out.append({'id': mid, 'relation': relation,
                    'why': _clean_line(m.get('why'))[:200]})
    return out
