"""
발주공고 작업 큐 API — ddkkbot(외부 워커)와 krcglobal 사이의 계약.

흐름
----
1) /api/notices/collect 가 신규 BidNotice 를 INSERT 하면 services.notice_pipeline.
   post_collect_hook() 이 NoticeTask(translate, slides) 를 enqueue 한다.
2) ddkkbot 워커가 GET /api/notices/tasks?status=pending 으로 큐를 폴링.
3) POST /api/notices/tasks/<id>/claim 으로 작업을 잡고 (status=claimed),
4) translate 면 JSON 결과(title_ko 등)를, slides 면 multipart PPT 를
   POST /api/notices/tasks/<id>/complete 로 업로드.
5) 실패 시 POST /api/notices/tasks/<id>/fail. attempts 가 max_attempts 미만이면
   pending 으로 되돌리고, 한도 도달 시 failed 로 종료.

인증
----
워커 엔드포인트(claim/complete/fail/list)는 두 경로 중 하나면 통과:
  - Authorization: Bearer $WORKER_SECRET
  - Authorization: Bearer <admin JWT>
WORKER_SECRET 미설정 시 admin JWT 만 허용한다 (개발 편의용 자동 통과는 없음).
관리 엔드포인트(재큐잉/PATCH)는 admin JWT 만 허용.
"""
from __future__ import annotations

import os
import json
from datetime import datetime
from functools import wraps

from flask import Blueprint, request, jsonify, send_file, current_app
from sqlalchemy import asc
from werkzeug.utils import secure_filename

from models import db, BidNotice, NoticeTask
from routes.auth import token_required, admin_required, verify_token
from services.notice_pipeline import notify_task_done, notify_task_failed


notice_tasks_bp = Blueprint('notice_tasks', __name__)


# ── 인증 ─────────────────────────────────────────────────────────────────────
def _check_worker_auth() -> tuple[bool, str]:
    """워커 엔드포인트 이중 인증.

    - WORKER_SECRET (환경변수) 와 일치하는 Bearer 토큰 → 'worker'
    - admin role 의 JWT → 'admin'
    그 외 → 'denied'
    """
    worker_secret = os.environ.get('WORKER_SECRET', '').strip()
    auth_header = request.headers.get('Authorization', '')
    token = auth_header[7:] if auth_header.startswith('Bearer ') else ''

    if worker_secret and token and token == worker_secret:
        return True, 'worker'

    if token:
        try:
            user = verify_token(token)
            if user and getattr(user, 'role', None) == 'admin':
                return True, 'admin'
        except Exception as e:
            print(f'[worker-auth] JWT 검증 예외: {e}')

    return False, 'denied'


def worker_required(f):
    """워커 엔드포인트용 데코레이터."""
    @wraps(f)
    def decorated(*args, **kwargs):
        ok, _mode = _check_worker_auth()
        if not ok:
            return jsonify({'success': False, 'message': '인증 실패'}), 401
        return f(*args, **kwargs)
    return decorated


# ── 헬퍼 ─────────────────────────────────────────────────────────────────────
ALLOWED_TASK_TYPES = {'translate', 'slides', 'infographic', 'summary', 'review'}
ALLOWED_TRANSLATE_FIELDS = {'title_ko', 'text_excerpt_ko', 'summary_ko'}
ALLOWED_SLIDES_EXTENSIONS = {'pptx', 'pdf'}
ALLOWED_INFOGRAPHIC_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

# 수동 재큐잉 시 task_type → priority 매핑
TASK_PRIORITY = {'translate': 0, 'infographic': 5, 'slides': 10}


def _slides_dir() -> str:
    upload_root = current_app.config.get('UPLOAD_FOLDER') or 'uploads'
    path = os.path.join(upload_root, 'slides')
    os.makedirs(path, exist_ok=True)
    return path


def _infographic_dir() -> str:
    upload_root = current_app.config.get('UPLOAD_FOLDER') or 'uploads'
    path = os.path.join(upload_root, 'infographics')
    os.makedirs(path, exist_ok=True)
    return path


def _safe_ext(filename: str) -> str | None:
    if '.' not in filename:
        return None
    ext = filename.rsplit('.', 1)[-1].lower()
    return ext if ext in ALLOWED_SLIDES_EXTENSIONS else None


def _safe_infographic_ext(filename: str) -> str | None:
    if '.' not in filename:
        return None
    ext = filename.rsplit('.', 1)[-1].lower()
    return ext if ext in ALLOWED_INFOGRAPHIC_EXTENSIONS else None


# ── 1. 작업 목록 (워커 폴링용) ───────────────────────────────────────────────
@notice_tasks_bp.route('/tasks', methods=['GET'])
@worker_required
def list_tasks():
    """큐에서 가져갈 작업 목록.
    쿼리: status=pending|claimed|done|failed (기본 pending),
          type=translate|slides 등, limit (기본 20, 최대 100)
    """
    status = (request.args.get('status') or 'pending').strip()
    task_type = (request.args.get('type') or '').strip()
    try:
        limit = max(1, min(100, int(request.args.get('limit', 20))))
    except (TypeError, ValueError):
        limit = 20

    query = NoticeTask.query
    if status:
        query = query.filter(NoticeTask.status == status)
    if task_type:
        if task_type not in ALLOWED_TASK_TYPES:
            return jsonify({'success': False, 'message': f'허용되지 않은 task_type: {task_type}'}), 400
        query = query.filter(NoticeTask.task_type == task_type)

    rows = (query
            .order_by(asc(NoticeTask.priority), asc(NoticeTask.created_at))
            .limit(limit)
            .all())

    return jsonify({
        'success': True,
        'data': [r.to_dict() for r in rows],
        'count': len(rows),
    })


# ── 2. 단건 조회 ─────────────────────────────────────────────────────────────
@notice_tasks_bp.route('/tasks/<int:tid>', methods=['GET'])
@worker_required
def get_task(tid: int):
    task = NoticeTask.query.get(tid)
    if not task:
        return jsonify({'success': False, 'message': '작업을 찾을 수 없습니다.'}), 404
    return jsonify({'success': True, 'data': task.to_dict()})


# ── 3. claim ─────────────────────────────────────────────────────────────────
@notice_tasks_bp.route('/tasks/<int:tid>/claim', methods=['POST'])
@worker_required
def claim_task(tid: int):
    """status=pending → claimed, attempts+=1, claimed_at=now."""
    body = request.get_json(silent=True) or {}
    worker_id = (body.get('worker_id') or body.get('workerId') or '')[:100]

    task = NoticeTask.query.get(tid)
    if not task:
        return jsonify({'success': False, 'message': '작업을 찾을 수 없습니다.'}), 404

    if task.status != 'pending':
        return jsonify({
            'success': False,
            'message': f'pending 상태가 아닙니다 (현재: {task.status})',
            'data': task.to_dict(),
        }), 409

    task.status = 'claimed'
    task.worker_id = worker_id or task.worker_id
    task.claimed_at = datetime.utcnow()
    task.attempts = (task.attempts or 0) + 1
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'claim 실패: {e}'}), 500

    return jsonify({'success': True, 'data': task.to_dict()})


# ── 4. complete ──────────────────────────────────────────────────────────────
def _complete_translate(task: NoticeTask, notice: BidNotice, body: dict, result: dict):
    """JSON body 의 fields_to_update 화이트리스트만 BidNotice 에 반영."""
    fields = body.get('fields_to_update') or body.get('fieldsToUpdate') or {}
    if not isinstance(fields, dict):
        return False, 'fields_to_update 가 dict 가 아닙니다.'

    applied = {}
    for k, v in fields.items():
        # camelCase 도 허용
        snake = {'titleKo': 'title_ko', 'textExcerptKo': 'text_excerpt_ko',
                 'summaryKo': 'summary_ko'}.get(k, k)
        if snake not in ALLOWED_TRANSLATE_FIELDS:
            continue
        if v is None or v == '':
            continue
        setattr(notice, snake, str(v))
        applied[snake] = True

    if not applied:
        return False, '업데이트할 허용된 필드가 없습니다.'

    task.result = {**(result or {}), 'updated': sorted(applied.keys())}
    return True, None


def _complete_slides(task: NoticeTask, notice: BidNotice, body: dict,
                     result: dict, multipart: bool):
    """슬라이드 작업 완료 처리 — 두 가지 모드.

    1) multipart 모드: 'file' 필드로 PPTX/PDF 파일 업로드 → slides_path 저장
       slides_url 은 우리 시스템 다운로드 경로(/api/notices/<id>/slides) 로 자동 설정.

    2) JSON 모드 (1차 권장 — NotebookLM Google Slides 링크 첨부):
       result.slides_url (또는 fields_to_update.slides_url) 의 외부 URL 을
       그대로 BidNotice.slides_url 에 저장. 파일은 없음.
    """
    if multipart:
        if 'file' not in request.files:
            return False, "multipart 의 'file' 필드가 필요합니다."
        f = request.files['file']
        if not f or not f.filename:
            return False, '빈 파일입니다.'

        ext = _safe_ext(f.filename)
        if not ext:
            return False, (f'허용되지 않은 확장자입니다 '
                           f'(허용: {", ".join(ALLOWED_SLIDES_EXTENSIONS)}).')

        safe_name = secure_filename(f.filename) or f'slides.{ext}'
        target_name = f'{notice.id}_{safe_name}'
        target_dir = _slides_dir()
        target_path = os.path.join(target_dir, target_name)
        f.save(target_path)

        notice.slides_path = target_path
        notice.slides_url = f'/api/notices/{notice.id}/slides'

        task.result = {
            **(result or {}),
            'mode': 'file',
            'filename': target_name,
            'size': os.path.getsize(target_path),
        }
        return True, None

    # JSON 모드 — 외부 슬라이드 URL 등록
    fields = body.get('fields_to_update') or body.get('fieldsToUpdate') or {}
    candidate_url = (
        (result or {}).get('slides_url')
        or (result or {}).get('slidesUrl')
        or (result or {}).get('url')
        or (fields or {}).get('slides_url')
        or (fields or {}).get('slidesUrl')
    )
    if not candidate_url or not isinstance(candidate_url, str):
        return False, "slides_url 이 비어있거나 문자열이 아닙니다."
    if not (candidate_url.startswith('http://') or candidate_url.startswith('https://')):
        return False, 'slides_url 은 http(s) 절대 URL 이어야 합니다.'

    notice.slides_url = candidate_url[:500]
    notice.slides_path = None  # 외부 링크 모드에서는 로컬 파일 없음
    task.result = {
        **(result or {}),
        'mode': 'link',
        'slides_url': notice.slides_url,
    }
    return True, None


def _complete_infographic(task: NoticeTask, notice: BidNotice, body: dict,
                           result: dict, multipart: bool):
    """인포그래픽 작업 완료 처리.

    ddkkbot 이 $imggen 스킬로 생성한 이미지 파일을 multipart 로 업로드한다.
    링크 모드(JSON)도 열어두어 외부 URL 만 보낼 수도 있다.

    허용 확장자: png, jpg, jpeg, gif, webp
    """
    if multipart:
        if 'file' not in request.files:
            return False, "multipart 의 'file' 필드가 필요합니다."
        f = request.files['file']
        if not f or not f.filename:
            return False, '빈 파일입니다.'

        ext = _safe_infographic_ext(f.filename)
        if not ext:
            return False, (f'허용되지 않은 확장자입니다 '
                           f'(허용: {", ".join(sorted(ALLOWED_INFOGRAPHIC_EXTENSIONS))}).')

        safe_name = secure_filename(f.filename) or f'infographic.{ext}'
        target_name = f'{notice.id}_{safe_name}'
        target_dir = _infographic_dir()
        target_path = os.path.join(target_dir, target_name)
        f.save(target_path)

        notice.infographic_path = target_path
        notice.infographic_url = f'/api/notices/{notice.id}/infographic'

        task.result = {
            **(result or {}),
            'mode': 'file',
            'filename': target_name,
            'size': os.path.getsize(target_path),
        }
        return True, None

    # JSON 모드 — R2 key 또는 외부 URL 등록
    r2_key = (result or {}).get('r2_key') or (result or {}).get('r2Key')
    fields = body.get('fields_to_update') or body.get('fieldsToUpdate') or {}
    candidate_url = (
        (result or {}).get('infographic_url')
        or (result or {}).get('infographicUrl')
        or (result or {}).get('url')
        or (fields or {}).get('infographic_url')
        or (fields or {}).get('infographicUrl')
    )
    if not candidate_url or not isinstance(candidate_url, str):
        return False, "infographic_url 이 비어있거나 문자열이 아닙니다."
    # /api/... 내부 경로 또는 http(s) 외부 URL 모두 허용
    if not (candidate_url.startswith('/') or candidate_url.startswith('http')):
        return False, 'infographic_url 은 /api/... 경로 또는 http(s) URL 이어야 합니다.'

    notice.infographic_url  = candidate_url[:500]
    notice.infographic_path = r2_key[:500] if r2_key else None  # R2 key 저장
    task.result = {
        **(result or {}),
        'mode': 'r2' if r2_key else 'link',
        'infographic_url': notice.infographic_url,
    }
    return True, None


@notice_tasks_bp.route('/tasks/<int:tid>/complete', methods=['POST'])
@worker_required
def complete_task(tid: int):
    """작업 완료 보고. translate=JSON, slides=multipart(file=...)."""
    task = NoticeTask.query.get(tid)
    if not task:
        return jsonify({'success': False, 'message': '작업을 찾을 수 없습니다.'}), 404
    if task.status not in ('claimed', 'pending'):
        return jsonify({
            'success': False,
            'message': f'완료 처리할 수 없는 상태입니다 (현재: {task.status})',
        }), 409

    notice = BidNotice.query.get(task.notice_id)
    if not notice:
        return jsonify({'success': False, 'message': '관련 발주공고가 존재하지 않습니다.'}), 404

    # multipart 인지 JSON 인지 분기
    is_multipart = (request.content_type or '').lower().startswith('multipart/')
    if is_multipart:
        # form 의 'result' 필드(JSON 문자열) 도 함께 받음
        result_raw = request.form.get('result') or '{}'
        try:
            result = json.loads(result_raw) if isinstance(result_raw, str) else (result_raw or {})
        except json.JSONDecodeError:
            result = {}
        body = {}  # multipart 에서는 body 별도 필요 없음
    else:
        body = request.get_json(silent=True) or {}
        result = body.get('result') or {}

    if task.task_type == 'translate':
        ok, err = _complete_translate(task, notice, body, result)
    elif task.task_type == 'slides':
        ok, err = _complete_slides(task, notice, body, result, is_multipart)
    elif task.task_type == 'infographic':
        ok, err = _complete_infographic(task, notice, body, result, is_multipart)
    elif task.task_type in ('summary', 'review'):
        # 1차에서는 단순 결과 메타만 저장, BidNotice 변경 없음
        task.result = result or {}
        ok, err = True, None
    else:
        return jsonify({'success': False, 'message': f'지원하지 않는 task_type: {task.task_type}'}), 400

    if not ok:
        return jsonify({'success': False, 'message': err}), 400

    now = datetime.utcnow()
    task.status = 'done'
    task.completed_at = now
    task.error = None
    notice.last_task_at = now

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'완료 처리 중 오류: {e}'}), 500

    notify_task_done(task, notice)
    return jsonify({'success': True, 'data': task.to_dict()})


# ── 5. fail ──────────────────────────────────────────────────────────────────
@notice_tasks_bp.route('/tasks/<int:tid>/fail', methods=['POST'])
@worker_required
def fail_task(tid: int):
    """실패 보고. attempts < max_attempts 면 다시 pending, 그 외 failed."""
    body = request.get_json(silent=True) or {}
    err_msg = (body.get('error') or '')[:2000]

    task = NoticeTask.query.get(tid)
    if not task:
        return jsonify({'success': False, 'message': '작업을 찾을 수 없습니다.'}), 404

    task.error = err_msg
    if (task.attempts or 0) < (task.max_attempts or 3):
        task.status = 'pending'
        task.claimed_at = None
        # 다음 시도를 위해 worker_id 는 유지 (디버깅 용이성)
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'message': f'fail 처리 중 오류: {e}'}), 500
        return jsonify({
            'success': True,
            'data': task.to_dict(),
            'requeued': True,
        })

    # 최종 실패
    task.status = 'failed'
    task.completed_at = datetime.utcnow()
    notice = BidNotice.query.get(task.notice_id)
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'fail 처리 중 오류: {e}'}), 500

    if notice:
        notify_task_failed(task, notice, err_msg)
    return jsonify({
        'success': True,
        'data': task.to_dict(),
        'requeued': False,
    })


# ── 6. 공고 단건 조회 — 로그인 사용자(UI 팝업)·워커(krc_worker) 모두 허용
@notice_tasks_bp.route('/<int:nid>', methods=['GET'])
def get_notice(nid: int):
    # worker 인증 먼저 시도, 실패 시 JWT 인증
    ok, _ = _check_worker_auth()
    if not ok:
        from routes.auth import verify_token
        auth_header = request.headers.get('Authorization', '')
        token = auth_header[7:] if auth_header.startswith('Bearer ') else ''
        if not token or not verify_token(token):
            return jsonify({'success': False, 'message': '인증 실패'}), 401
    notice = BidNotice.query.get(nid)
    if not notice:
        return jsonify({'success': False, 'message': '발주공고를 찾을 수 없습니다.'}), 404
    return jsonify({'success': True, 'data': notice.to_dict()})


# ── 7. 공고별 작업 목록 (UI 진행 상태용) ─────────────────────────────────────
@notice_tasks_bp.route('/<int:nid>/tasks', methods=['GET'])
@token_required
def list_tasks_for_notice(current_user, nid: int):
    rows = (NoticeTask.query
            .filter_by(notice_id=nid)
            .order_by(asc(NoticeTask.priority), asc(NoticeTask.created_at))
            .all())
    return jsonify({'success': True, 'data': [r.to_dict() for r in rows]})


# ── 7. 수동 재큐잉 (관리자) ──────────────────────────────────────────────────
@notice_tasks_bp.route('/<int:nid>/tasks', methods=['POST'])
@admin_required
def enqueue_task(current_user, nid: int):
    """body: {"task_type": "translate"|"slides"|...}.
    이미 같은 (nid, task_type) 이 존재하면 status 를 pending 으로 리셋.
    """
    body = request.get_json(silent=True) or {}
    task_type = (body.get('task_type') or body.get('taskType') or '').strip()
    if task_type not in ALLOWED_TASK_TYPES:
        return jsonify({'success': False, 'message': f'허용되지 않은 task_type: {task_type}'}), 400

    notice = BidNotice.query.get(nid)
    if not notice:
        return jsonify({'success': False, 'message': '발주공고를 찾을 수 없습니다.'}), 404

    existing = NoticeTask.query.filter_by(notice_id=nid, task_type=task_type).first()
    if existing:
        existing.status = 'pending'
        existing.error = None
        existing.claimed_at = None
        existing.completed_at = None
        existing.worker_id = None
        # attempts 는 유지 — 운영자 의도 파악용
        task = existing
    else:
        priority = TASK_PRIORITY.get(task_type, 20)
        task = NoticeTask(
            notice_id=nid,
            task_type=task_type,
            status='pending',
            priority=priority,
        )
        db.session.add(task)

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'재큐잉 실패: {e}'}), 500

    return jsonify({'success': True, 'data': task.to_dict()})


# ── 8. 단건 PATCH (실패 작업 수동 재시도) ────────────────────────────────────
@notice_tasks_bp.route('/tasks/<int:tid>', methods=['PATCH'])
@admin_required
def patch_task(current_user, tid: int):
    body = request.get_json(silent=True) or {}
    task = NoticeTask.query.get(tid)
    if not task:
        return jsonify({'success': False, 'message': '작업을 찾을 수 없습니다.'}), 404

    new_status = (body.get('status') or '').strip()
    if new_status and new_status in ('pending', 'failed'):
        task.status = new_status
        if new_status == 'pending':
            task.error = None
            task.claimed_at = None
            task.completed_at = None

    if 'priority' in body:
        try:
            task.priority = int(body['priority'])
        except (TypeError, ValueError):
            pass

    if 'maxAttempts' in body or 'max_attempts' in body:
        try:
            task.max_attempts = int(body.get('maxAttempts') or body.get('max_attempts'))
        except (TypeError, ValueError):
            pass

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'PATCH 실패: {e}'}), 500
    return jsonify({'success': True, 'data': task.to_dict()})


# ── 9. 슬라이드 다운로드 ─────────────────────────────────────────────────────
@notice_tasks_bp.route('/<int:nid>/slides', methods=['GET'])
@token_required
def download_slides(current_user, nid: int):
    notice = BidNotice.query.get(nid)
    if not notice or not notice.slides_path:
        return jsonify({'success': False, 'message': '슬라이드 파일이 없습니다.'}), 404

    # 절대경로 직접 검증 — 다른 경로로 leak 방지를 위해 slides 디렉토리 prefix 확인
    target = notice.slides_path
    expected_dir = _slides_dir()
    if not os.path.commonpath([os.path.abspath(target), os.path.abspath(expected_dir)]) == os.path.abspath(expected_dir):
        return jsonify({'success': False, 'message': '잘못된 파일 경로입니다.'}), 400
    if not os.path.isfile(target):
        return jsonify({'success': False, 'message': '파일을 찾을 수 없습니다.'}), 404

    return send_file(target, as_attachment=True,
                     download_name=os.path.basename(target))


# ── 10. 인포그래픽 다운로드 ──────────────────────────────────────────────────
@notice_tasks_bp.route('/<int:nid>/infographic', methods=['GET'])
@token_required
def download_infographic(current_user, nid: int):
    notice = BidNotice.query.get(nid)
    if not notice or not notice.infographic_path:
        return jsonify({'success': False, 'message': '인포그래픽 파일이 없습니다.'}), 404

    target = notice.infographic_path

    # R2 key 방식 (Vercel 배포 — 로컬 절대경로가 아닌 경우)
    if not target.startswith('/'):
        try:
            from utils.r2_storage import stream_from_r2
            return stream_from_r2(target, content_type='image/png', inline=True)
        except Exception as e:
            return jsonify({'success': False, 'message': f'R2 로드 실패: {e}'}), 500

    # 로컬 파일 방식 (개발 환경 fallback)
    expected_dir = _infographic_dir()
    if not os.path.commonpath(
            [os.path.abspath(target), os.path.abspath(expected_dir)]
    ) == os.path.abspath(expected_dir):
        return jsonify({'success': False, 'message': '잘못된 파일 경로입니다.'}), 400
    if not os.path.isfile(target):
        return jsonify({'success': False, 'message': '파일을 찾을 수 없습니다.'}), 404

    return send_file(target, as_attachment=False,
                     download_name=os.path.basename(target))
