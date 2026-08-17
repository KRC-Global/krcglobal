#!/usr/bin/env python3
"""KRC 발주공고를 Mac 카카오톡 채팅방으로 전달하는 상시 릴레이.

백엔드의 kakao_deliveries 큐를 폴링하고, kmsg(macOS Accessibility)를 통해
인포그래픽 이미지와 원문 source_url을 순서대로 전송한다.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import logging
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests


LOG = logging.getLogger('kakao-relay')
STOP_REQUESTED = False
MAX_IMAGE_BYTES = 25 * 1024 * 1024


def _truthy(value: str | None) -> bool:
    return (value or '').strip().lower() in {'1', 'true', 'yes', 'on'}


def _load_env_file(path: Path) -> None:
    """간단한 KEY=VALUE 파일을 읽는다. 셸 확장이나 명령 실행은 하지 않는다."""
    if not path.is_file():
        raise RuntimeError(f'환경설정 파일을 찾을 수 없습니다: {path}')
    for lineno, raw in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        if '=' not in line:
            raise RuntimeError(f'{path}:{lineno}: KEY=VALUE 형식이 아닙니다.')
        key, value = line.split('=', 1)
        key = key.strip()
        value = value.strip()
        if value[:1] == value[-1:] and value[:1] in {'"', "'"}:
            value = value[1:-1]
        if not key or not key.replace('_', '').isalnum():
            raise RuntimeError(f'{path}:{lineno}: 환경변수 이름이 올바르지 않습니다.')
        os.environ.setdefault(key, value)


@dataclass(frozen=True)
class RelayConfig:
    api_base_url: str
    worker_secret: str
    room_name: str
    worker_id: str
    poll_seconds: float
    request_timeout: float
    kmsg_bin: str
    receipt_dir: Path
    dry_run: bool
    once: bool
    local_db: bool
    min_notice_id: int

    @classmethod
    def from_env(cls, *, once: bool = False) -> 'RelayConfig':
        api_base_url = os.environ.get('KRC_API_BASE_URL', '').strip().rstrip('/')
        worker_secret = os.environ.get('WORKER_SECRET', '').strip()
        room_name = os.environ.get('KAKAO_ROOM_NAME', '').strip()
        kmsg_bin = os.environ.get('KMSG_BIN', '').strip() or (shutil.which('kmsg') or '')
        worker_id = os.environ.get('KAKAO_RELAY_WORKER_ID', '').strip()
        if not worker_id:
            worker_id = f'mac-{socket.gethostname().split(".")[0]}'[:100]

        missing = [
            name for name, value in (
                ('KRC_API_BASE_URL', api_base_url),
                ('WORKER_SECRET', worker_secret),
                ('KAKAO_ROOM_NAME', room_name),
                ('KMSG_BIN', kmsg_bin),
            ) if not value
        ]
        if missing:
            raise RuntimeError('필수 설정 누락: ' + ', '.join(missing))
        if urlparse(api_base_url).scheme not in {'http', 'https'}:
            raise RuntimeError('KRC_API_BASE_URL은 http(s) URL이어야 합니다.')
        if not Path(kmsg_bin).is_file():
            raise RuntimeError(f'kmsg 실행 파일을 찾을 수 없습니다: {kmsg_bin}')

        try:
            poll_seconds = max(5.0, float(os.environ.get('KAKAO_RELAY_POLL_SECONDS', '30')))
            request_timeout = max(5.0, float(os.environ.get('KAKAO_RELAY_HTTP_TIMEOUT', '30')))
            min_notice_id = max(0, int(os.environ.get('KAKAO_RELAY_MIN_NOTICE_ID', '0')))
        except ValueError as exc:
            raise RuntimeError('폴링/HTTP timeout/최소 공고 ID 설정은 숫자여야 합니다.') from exc

        local_db = _truthy(os.environ.get('KAKAO_RELAY_USE_LOCAL_DB'))
        if local_db and min_notice_id < 1:
            raise RuntimeError(
                '로컬 DB 모드에서는 기존 공고 재전송 방지를 위해 '
                'KAKAO_RELAY_MIN_NOTICE_ID가 필요합니다.'
            )

        default_receipts = (
            Path.home() / 'Library' / 'Application Support' /
            'KRCGlobal' / 'kakao-relay' / 'receipts'
        )
        receipt_dir = Path(
            os.environ.get('KAKAO_RELAY_RECEIPT_DIR', str(default_receipts))
        ).expanduser().resolve()
        return cls(
            api_base_url=api_base_url,
            worker_secret=worker_secret,
            room_name=room_name,
            worker_id=worker_id,
            poll_seconds=poll_seconds,
            request_timeout=request_timeout,
            kmsg_bin=kmsg_bin,
            receipt_dir=receipt_dir,
            dry_run=_truthy(os.environ.get('KAKAO_RELAY_DRY_RUN')),
            once=once or _truthy(os.environ.get('KAKAO_RELAY_ONCE')),
            local_db=local_db,
            min_notice_id=min_notice_id,
        )


class RelayAPI:
    def __init__(self, config: RelayConfig):
        self.config = config
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f'Bearer {config.worker_secret}',
            'User-Agent': f'krcglobal-kakao-relay/{config.worker_id}',
        })

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        response = self.session.request(
            method,
            f'{self.config.api_base_url}{path}',
            timeout=self.config.request_timeout,
            **kwargs,
        )
        response.raise_for_status()
        return response

    def list(self, status: str, *, worker_id: str | None = None, limit: int = 10) -> list[dict]:
        params: dict[str, Any] = {'status': status, 'limit': limit}
        if worker_id:
            params['worker_id'] = worker_id
        payload = self._request('GET', '/api/notices/kakao-deliveries', params=params).json()
        return payload.get('data') or []

    def claim(self, delivery_id: int) -> dict:
        payload = self._request(
            'POST',
            f'/api/notices/kakao-deliveries/{delivery_id}/claim',
            json={'worker_id': self.config.worker_id},
        ).json()
        return payload['data']

    def complete(self, delivery_id: int, result: dict) -> None:
        self._request(
            'POST',
            f'/api/notices/kakao-deliveries/{delivery_id}/complete',
            json={'result': result},
        )

    def fail(self, delivery_id: int, error: str, *, retryable: bool) -> None:
        self._request(
            'POST',
            f'/api/notices/kakao-deliveries/{delivery_id}/fail',
            json={'error': error[:2000], 'retryable': retryable},
        )

    def download_image(self, notice: dict, destination: Path) -> None:
        external_url = str(notice.get('infographicUrl') or '').strip()
        path = notice.get('imageDownloadPath')
        response = None
        if path and str(path).startswith('/'):
            try:
                response = self._request('GET', str(path), stream=True)
            except requests.HTTPError as exc:
                # 외부 URL만 저장된 레코드는 백엔드 파일 엔드포인트가 404일 수 있다.
                if exc.response is None or exc.response.status_code != 404:
                    raise
        if response is None:
            if urlparse(external_url).scheme not in {'http', 'https'}:
                raise RuntimeError('다운로드 가능한 인포그래픽 경로가 없습니다.')
            # 외부 이미지 호스트에 WORKER_SECRET이 전달되지 않도록 별도 요청을 쓴다.
            response = requests.get(
                external_url,
                timeout=self.config.request_timeout,
                stream=True,
                headers={'User-Agent': f'krcglobal-kakao-relay/{self.config.worker_id}'},
            )
            response.raise_for_status()
        try:
            total = 0
            with destination.open('wb') as output:
                for chunk in response.iter_content(chunk_size=128 * 1024):
                    if chunk:
                        output.write(chunk)
                        total += len(chunk)
                        if total > MAX_IMAGE_BYTES:
                            raise RuntimeError('인포그래픽이 허용 크기(25MB)를 초과했습니다.')
            if total == 0:
                raise RuntimeError('다운로드한 인포그래픽이 비어 있습니다.')
        finally:
            response.close()


class LocalDBRelayAPI:
    """운영 배포 없이 공용 Supabase/R2를 직접 사용하는 Mac 전용 큐.

    설치 시점의 마지막 공고 ID보다 큰 공고만 큐에 넣어 기존 공고가 한꺼번에
    재전송되는 것을 막는다. 큐 상태 자체는 공용 DB에 남아 프로세스 재시작에도
    이미지/링크 단계의 중복 방지가 유지된다.
    """

    def __init__(self, config: RelayConfig):
        self.config = config
        backend_dir = Path(__file__).resolve().parents[1]
        if str(backend_dir) not in sys.path:
            sys.path.insert(0, str(backend_dir))
        from app import app as flask_app
        from models import BidNotice, KakaoDelivery, db

        self.app = flask_app
        self.BidNotice = BidNotice
        self.KakaoDelivery = KakaoDelivery
        self.db = db
        with self.app.app_context():
            self.db.create_all()

    def _sync_new_notices(self) -> None:
        from sqlalchemy import or_

        with self.app.app_context():
            candidates = (
                self.BidNotice.query
                .filter(self.BidNotice.id > self.config.min_notice_id)
                .filter(self.BidNotice.source_url.isnot(None))
                .filter(or_(
                    self.BidNotice.infographic_path.isnot(None),
                    self.BidNotice.infographic_url.isnot(None),
                ))
                .order_by(self.BidNotice.id.asc())
                .limit(100)
                .all()
            )
            created = 0
            for notice in candidates:
                exists = self.KakaoDelivery.query.filter_by(
                    notice_id=notice.id, kind='image',
                ).first()
                if exists:
                    continue
                self.db.session.add(self.KakaoDelivery(
                    notice_id=notice.id,
                    kind='image',
                    status='pending',
                    max_attempts=3,
                ))
                created += 1
            if created:
                self.db.session.commit()
                LOG.info('신규 인포그래픽 로컬 큐 등록: %s건', created)

    def list(self, status: str, *, worker_id: str | None = None, limit: int = 10) -> list[dict]:
        if status == 'pending':
            self._sync_new_notices()
        with self.app.app_context():
            query = self.KakaoDelivery.query.filter_by(status=status)
            if worker_id:
                query = query.filter_by(worker_id=worker_id)
            rows = query.order_by(self.KakaoDelivery.created_at.asc()).limit(limit).all()
            return [row.to_dict(include_notice=True) for row in rows]

    def claim(self, delivery_id: int) -> dict:
        with self.app.app_context():
            delivery = self.db.session.get(self.KakaoDelivery, delivery_id)
            if not delivery or delivery.status != 'pending':
                state = delivery.status if delivery else 'missing'
                raise RuntimeError(f'pending 상태가 아닌 카카오 작업입니다: {state}')
            delivery.status = 'claimed'
            delivery.worker_id = self.config.worker_id
            delivery.claimed_at = datetime.utcnow()
            delivery.attempts = (delivery.attempts or 0) + 1
            self.db.session.commit()
            return delivery.to_dict(include_notice=True)

    def complete(self, delivery_id: int, result: dict) -> None:
        with self.app.app_context():
            delivery = self.db.session.get(self.KakaoDelivery, delivery_id)
            if not delivery:
                raise RuntimeError('카카오 전송 작업을 찾을 수 없습니다.')
            if delivery.status == 'done':
                return
            if delivery.status != 'claimed':
                raise RuntimeError(f'claimed 상태가 아닌 카카오 작업입니다: {delivery.status}')
            delivery.status = 'done'
            delivery.completed_at = datetime.utcnow()
            delivery.error = None
            delivery.result = result
            if delivery.kind == 'image':
                link = self.KakaoDelivery.query.filter_by(
                    notice_id=delivery.notice_id, kind='link',
                ).first()
                if not link:
                    self.db.session.add(self.KakaoDelivery(
                        notice_id=delivery.notice_id,
                        kind='link',
                        status='pending',
                        max_attempts=3,
                    ))
            self.db.session.commit()

    def fail(self, delivery_id: int, error: str, *, retryable: bool) -> None:
        with self.app.app_context():
            delivery = self.db.session.get(self.KakaoDelivery, delivery_id)
            if not delivery:
                raise RuntimeError('카카오 전송 작업을 찾을 수 없습니다.')
            if delivery.status == 'done':
                raise RuntimeError('이미 완료된 작업은 실패 처리할 수 없습니다.')
            delivery.error = error[:2000]
            if retryable and (delivery.attempts or 0) < (delivery.max_attempts or 3):
                delivery.status = 'pending'
                delivery.claimed_at = None
            else:
                delivery.status = 'failed'
                delivery.completed_at = datetime.utcnow()
            self.db.session.commit()

    def download_image(self, notice: dict, destination: Path) -> None:
        notice_id = int(notice.get('id') or 0)
        with self.app.app_context():
            row = self.db.session.get(self.BidNotice, notice_id)
            if not row:
                raise RuntimeError('인포그래픽 공고를 찾을 수 없습니다.')
            stored_path = (row.infographic_path or '').strip()
            external_url = (row.infographic_url or '').strip()

            if stored_path and not stored_path.startswith('/'):
                from utils.r2_storage import download_file

                obj = download_file(stored_path)
                body = obj['Body']
                try:
                    self._write_stream(body, destination)
                finally:
                    body.close()
                return

            if stored_path and Path(stored_path).is_file():
                with Path(stored_path).open('rb') as source:
                    self._write_stream(source, destination)
                return

        if urlparse(external_url).scheme not in {'http', 'https'}:
            raise RuntimeError('다운로드 가능한 인포그래픽 경로가 없습니다.')
        response = requests.get(
            external_url,
            timeout=self.config.request_timeout,
            stream=True,
            headers={'User-Agent': f'krcglobal-kakao-relay/{self.config.worker_id}'},
        )
        response.raise_for_status()
        try:
            with destination.open('wb') as output:
                total = 0
                for chunk in response.iter_content(chunk_size=128 * 1024):
                    if not chunk:
                        continue
                    output.write(chunk)
                    total += len(chunk)
                    if total > MAX_IMAGE_BYTES:
                        raise RuntimeError('인포그래픽이 허용 크기(25MB)를 초과했습니다.')
                if total == 0:
                    raise RuntimeError('다운로드한 인포그래픽이 비어 있습니다.')
        finally:
            response.close()

    @staticmethod
    def _write_stream(source, destination: Path) -> None:
        total = 0
        with destination.open('wb') as output:
            while True:
                chunk = source.read(128 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                total += len(chunk)
                if total > MAX_IMAGE_BYTES:
                    raise RuntimeError('인포그래픽이 허용 크기(25MB)를 초과했습니다.')
        if total == 0:
            raise RuntimeError('다운로드한 인포그래픽이 비어 있습니다.')


class KmsgClient:
    def __init__(self, config: RelayConfig):
        self.config = config
        self.chat_id: str | None = None

    def _run(self, args: list[str], *, timeout: float = 60) -> subprocess.CompletedProcess:
        return subprocess.run(
            [self.config.kmsg_bin, *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    def ready(self) -> bool:
        try:
            self._run(['status'], timeout=15)
            self.chat_id = self._resolve_exact_room()
            return True
        except (subprocess.SubprocessError, RuntimeError, json.JSONDecodeError) as exc:
            LOG.warning('카카오톡 사전 점검 실패: %s', _safe_error(exc))
            return False

    def _resolve_exact_room(self) -> str:
        result = self._run(['chats', '--json', '--limit', '100'], timeout=30)
        payload = json.loads(result.stdout)
        matches = [
            chat for chat in (payload.get('chats') or [])
            if chat.get('title') == self.config.room_name
        ]
        if len(matches) != 1:
            if not matches:
                raise RuntimeError(
                    '최근 채팅 목록에서 정확한 KAKAO_ROOM_NAME을 찾지 못했습니다. '
                    '대상 방을 Mac 카카오톡에서 한 번 열어주세요.'
                )
            raise RuntimeError('같은 이름의 채팅방이 여러 개라 안전하게 선택할 수 없습니다.')
        chat_id = matches[0].get('chat_id')
        if not chat_id:
            raise RuntimeError('대상 채팅방의 chat_id를 만들지 못했습니다.')
        return str(chat_id)

    def send_image(self, image_path: Path) -> None:
        self._run([
            'send-image', self.config.room_name, str(image_path),
            '--deep-recovery', '--keep-window',
        ], timeout=90)

    def send_link(self, source_url: str) -> None:
        if not self.chat_id:
            raise RuntimeError('대상 채팅방 chat_id가 준비되지 않았습니다.')
        self._run([
            'send', self.config.room_name, source_url,
            '--deep-recovery', '--keep-window',
        ], timeout=60)

    def preview_link(self, source_url: str) -> None:
        self._run([
            'send', self.config.room_name, source_url, '--dry-run',
        ], timeout=15)


class ReceiptStore:
    def __init__(self, directory: Path):
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        try:
            self.directory.chmod(0o700)
        except OSError:
            pass

    def path_for(self, delivery_id: int) -> Path:
        return self.directory / f'{delivery_id}.json'

    def load(self, delivery_id: int) -> dict | None:
        path = self.path_for(delivery_id)
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding='utf-8'))

    def save(self, delivery_id: int, result: dict) -> None:
        path = self.path_for(delivery_id)
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
        temp.chmod(0o600)
        temp.replace(path)

    def remove(self, delivery_id: int) -> None:
        self.path_for(delivery_id).unlink(missing_ok=True)


def _safe_error(exc: BaseException) -> str:
    if isinstance(exc, subprocess.CalledProcessError):
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
    else:
        detail = str(exc).strip()
    return detail.replace('\n', ' ')[:500]


def _validate_source_url(value: str | None) -> str:
    source_url = (value or '').strip()
    parsed = urlparse(source_url)
    if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
        raise RuntimeError('공고 source_url이 올바른 http(s) URL이 아닙니다.')
    return source_url


def _validate_image(path: Path) -> None:
    head = path.read_bytes()[:16]
    valid = (
        head.startswith(b'\x89PNG\r\n\x1a\n')
        or head.startswith(b'\xff\xd8\xff')
        or head.startswith((b'GIF87a', b'GIF89a'))
        or (head.startswith(b'RIFF') and head[8:12] == b'WEBP')
    )
    if not valid:
        raise RuntimeError('다운로드 파일이 지원되는 PNG/JPEG/GIF/WebP 이미지가 아닙니다.')


def _recover_claimed(api: RelayAPI, receipts: ReceiptStore, config: RelayConfig) -> None:
    for delivery in api.list('claimed', worker_id=config.worker_id, limit=100):
        delivery_id = int(delivery['id'])
        receipt = receipts.load(delivery_id)
        if receipt and receipt.get('state') == 'sent':
            try:
                api.complete(delivery_id, receipt.get('result') or {})
                receipts.remove(delivery_id)
                LOG.info('전송 영수증 복구 완료: delivery=%s', delivery_id)
            except requests.RequestException as exc:
                LOG.warning('전송 완료 보고 재시도 실패: delivery=%s error=%s', delivery_id, _safe_error(exc))
        elif receipt and receipt.get('state') == 'attempting':
            # kmsg 호출 도중 프로세스가 종료됐다면 실제 발송 여부가 불확실하다.
            try:
                api.fail(
                    delivery_id,
                    '릴레이가 전송 시도 도중 종료되어 결과가 불확실합니다.',
                    retryable=False,
                )
                receipts.remove(delivery_id)
            except requests.RequestException as exc:
                LOG.warning('불확실 작업 실패 보고 재시도 실패: delivery=%s error=%s', delivery_id, _safe_error(exc))
        else:
            # 전송 시도 마커도 없으므로 claim 응답 유실 등 전송 전 종료로 판단한다.
            try:
                api.fail(
                    delivery_id,
                    '릴레이가 실제 전송을 시작하기 전에 종료되었습니다.',
                    retryable=True,
                )
            except requests.RequestException as exc:
                LOG.warning('미시도 작업 재큐잉 실패: delivery=%s error=%s', delivery_id, _safe_error(exc))


def _process_delivery(
    delivery: dict,
    api: RelayAPI,
    kmsg: KmsgClient,
    receipts: ReceiptStore,
) -> None:
    delivery_id = int(delivery['id'])
    claimed = api.claim(delivery_id)
    notice = claimed.get('notice') or {}
    kind = claimed.get('kind')
    attempted_send = False

    try:
        if kind == 'image':
            with tempfile.TemporaryDirectory(prefix='krc-kakao-') as temp_dir:
                image_path = Path(temp_dir) / f'notice-{notice.get("id", delivery_id)}.png'
                api.download_image(notice, image_path)
                _validate_image(image_path)
                receipts.save(delivery_id, {'state': 'attempting', 'kind': kind})
                attempted_send = True
                kmsg.send_image(image_path)
        elif kind == 'link':
            source_url = _validate_source_url(notice.get('sourceUrl'))
            receipts.save(delivery_id, {'state': 'attempting', 'kind': kind})
            attempted_send = True
            kmsg.send_link(source_url)
        else:
            raise RuntimeError(f'지원하지 않는 카카오 전송 종류: {kind}')

        result = {
            'engine': 'kmsg',
            'kind': kind,
            'sentAt': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
        }
        # 외부 전송 직후 로컬 영수증을 먼저 남겨 API 응답 유실 시 중복을 막는다.
        receipts.save(delivery_id, {'state': 'sent', 'result': result})
        try:
            api.complete(delivery_id, result)
        except requests.RequestException as exc:
            # 다음 폴링에서 로컬 영수증으로 완료 보고만 재시도한다. 재발송은 하지 않는다.
            LOG.warning(
                '전송은 성공했으나 완료 보고가 실패했습니다: delivery=%s error=%s',
                delivery_id, _safe_error(exc),
            )
            return
        receipts.remove(delivery_id)
        LOG.info('카카오톡 전송 완료: delivery=%s notice=%s kind=%s', delivery_id, notice.get('id'), kind)
    except Exception as exc:
        error = _safe_error(exc)
        LOG.error('카카오톡 전송 실패: delivery=%s kind=%s error=%s', delivery_id, kind, error)
        # kmsg 실행을 시작한 뒤의 실패는 실제 발송 여부가 불확실하므로 절대 자동 재시도하지 않는다.
        try:
            api.fail(delivery_id, error, retryable=not attempted_send)
            receipts.remove(delivery_id)
        except requests.RequestException as report_exc:
            LOG.error('실패 상태 보고도 실패했습니다: %s', _safe_error(report_exc))


def run_once(config: RelayConfig, api: RelayAPI, kmsg: KmsgClient, receipts: ReceiptStore) -> bool:
    _recover_claimed(api, receipts, config)
    pending = api.list('pending', limit=1)
    if not pending:
        return False

    delivery = pending[0]
    notice = delivery.get('notice') or {}
    if config.dry_run:
        source_url = _validate_source_url(notice.get('sourceUrl'))
        kmsg.preview_link(source_url)
        LOG.info(
            'DRY RUN: 전송 대기 작업 확인(실제 전송/claim 없음): delivery=%s notice=%s kind=%s',
            delivery.get('id'), notice.get('id'), delivery.get('kind'),
        )
        return True

    if not kmsg.ready():
        return False
    _process_delivery(delivery, api, kmsg, receipts)
    return True


def _handle_signal(_signum, _frame) -> None:
    global STOP_REQUESTED
    STOP_REQUESTED = True


def _acquire_single_instance(receipt_dir: Path):
    lock_path = receipt_dir.parent / 'relay.lock'
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open('w')
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        handle.close()
        raise RuntimeError('카카오 릴레이가 이미 실행 중입니다.') from exc
    return handle


def main() -> int:
    parser = argparse.ArgumentParser(description='KRC 발주공고 Mac 카카오톡 릴레이')
    parser.add_argument('--env-file', type=Path, help='KEY=VALUE 형식의 로컬 설정 파일')
    parser.add_argument('--once', action='store_true', help='한 번만 확인하고 종료')
    parser.add_argument('--check', action='store_true', help='카카오톡 로그인/대상 방만 확인하고 종료')
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format='%(asctime)s %(levelname)s %(message)s',
    )
    try:
        if sys.platform != 'darwin':
            raise RuntimeError('이 릴레이는 macOS에서만 실행할 수 있습니다.')
        if args.env_file:
            _load_env_file(args.env_file.expanduser().resolve())
        config = RelayConfig.from_env(once=args.once)
        receipts = ReceiptStore(config.receipt_dir)
        # 이 참조를 main 종료까지 유지해야 flock도 유지된다.
        instance_lock = _acquire_single_instance(config.receipt_dir)
        api = LocalDBRelayAPI(config) if config.local_db else RelayAPI(config)
        kmsg = KmsgClient(config)

        if args.check:
            if not kmsg.ready():
                raise RuntimeError('카카오톡 또는 대상 채팅방 사전 점검에 실패했습니다.')
            LOG.info('카카오톡 및 대상 채팅방 사전 점검 완료')
            instance_lock.close()
            return 0

        signal.signal(signal.SIGTERM, _handle_signal)
        signal.signal(signal.SIGINT, _handle_signal)
        LOG.info('카카오 릴레이 시작: worker=%s dry_run=%s', config.worker_id, config.dry_run)

        while not STOP_REQUESTED:
            try:
                processed = run_once(config, api, kmsg, receipts)
            except (requests.RequestException, RuntimeError, json.JSONDecodeError) as exc:
                processed = False
                LOG.warning('릴레이 폴링 실패: %s', _safe_error(exc))
            if config.once:
                break
            # 한 공고의 image → link를 빠르게 이어 보내고, 유휴 시에는 설정 주기로 폴링한다.
            wait_seconds = 1.0 if processed else config.poll_seconds
            end = time.monotonic() + wait_seconds
            while not STOP_REQUESTED and time.monotonic() < end:
                time.sleep(min(0.5, end - time.monotonic()))
        LOG.info('카카오 릴레이 종료')
        instance_lock.close()
        return 0
    except Exception as exc:
        LOG.error('%s', _safe_error(exc))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
