import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ['FLASK_ENV'] = 'testing'
os.environ['WORKER_SECRET'] = 'test-worker-secret'
os.environ['KAKAO_RELAY_ENABLED'] = 'true'

import app as app_module  # noqa: E402
from models import BidNotice, KakaoDelivery, NoticeTask, db  # noqa: E402
from scripts.kakao_relay import (  # noqa: E402
    ReceiptStore,
    _compact_source_url,
    _format_link_message,
    _validate_image,
    _validate_source_url,
)
from services.notice_pipeline import enqueue_default_tasks  # noqa: E402


class KakaoDeliveryFlowTest(unittest.TestCase):
    def setUp(self):
        self.app = app_module.app
        self.app.config.update(TESTING=True, KAKAO_RELAY_ENABLED=True)
        app_module._tables_created = True
        self.context = self.app.app_context()
        self.context.push()
        db.drop_all()
        db.create_all()
        self.client = self.app.test_client()
        self.headers = {'Authorization': 'Bearer test-worker-secret'}

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def _create_infographic_task(self):
        notice = BidNotice(
            source='test',
            title='Test procurement notice',
            source_url='https://source.example/notices/123',
            summary_ko='① 테스트 공고 개요입니다.\n② 요약을 확인합니다.',
        )
        db.session.add(notice)
        db.session.flush()
        task = NoticeTask(
            notice_id=notice.id,
            task_type='infographic',
            status='claimed',
            attempts=1,
        )
        db.session.add(task)
        db.session.commit()
        return notice, task

    def _create_translate_task(self):
        notice = BidNotice(
            source='worldbank',
            title='Irrigation support [Request for Expression of Interest]',
            country='Kenya',
            client='Water Authority',
            sector='irrigation',
            deadline='2026-09-30',
            source_url='https://source.example/notices/translate',
        )
        db.session.add(notice)
        db.session.flush()
        task = NoticeTask(
            notice_id=notice.id,
            task_type='translate',
            status='claimed',
            attempts=1,
        )
        db.session.add(task)
        db.session.commit()
        return notice, task

    def test_default_pipeline_only_enqueues_translation(self):
        notice = BidNotice(
            source='test',
            title='Queue test',
            source_url='https://source.example/notices/queue',
        )
        db.session.add(notice)
        db.session.commit()

        self.assertEqual(enqueue_default_tasks([notice.id]), 1)
        tasks = NoticeTask.query.filter_by(notice_id=notice.id).all()
        self.assertEqual([(row.task_type, row.priority) for row in tasks], [('translate', 0)])

    def test_pending_poll_recovers_stale_claim(self):
        notice, task = self._create_translate_task()
        task.claimed_at = datetime.utcnow() - timedelta(minutes=31)
        db.session.commit()

        response = self.client.get(
            '/api/notices/tasks?status=pending',
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()['recovered'], 1)
        self.assertEqual(response.get_json()['data'][0]['id'], task.id)
        db.session.refresh(task)
        self.assertEqual(task.status, 'pending')
        self.assertIsNone(task.claimed_at)
        self.assertIn('자동 회수', task.error)

    def test_translation_completion_renders_uploads_and_queues_image(self):
        notice, task = self._create_translate_task()
        uploaded = {}

        def fake_generate(payload, output, *, style):
            self.assertEqual(payload['titleKo'], '케냐 관개 지원 관심표명요청')
            self.assertEqual(style, 'slide')
            Path(output).write_bytes(b'\x89PNG\r\n\x1a\n' + b'x' * 4096)
            return {
                'path': str(output), 'width': 1920, 'height': 1080,
                'style': style, 'kind': 'eoi',
            }

        def fake_upload(file_obj, key, content_type=None):
            uploaded['key'] = key
            uploaded['content_type'] = content_type
            uploaded['head'] = file_obj.read(8)
            return key

        with (
            patch('services.notice_infographic.generate_notice_infographic', fake_generate),
            patch('utils.r2_storage.upload_file', fake_upload),
        ):
            response = self.client.post(
                f'/api/notices/tasks/{task.id}/complete',
                headers=self.headers,
                json={
                    'fields_to_update': {
                        'titleKo': '케냐 관개 지원 관심표명요청',
                        'summaryKo': '① 사업 개요입니다.\n② 관개 개선 사업입니다.\n'
                                     '③ 마감을 확인합니다.\n④ 규모를 확인합니다.\n'
                                     '⑤ KRC 참여를 검토합니다.',
                    },
                    'result': {'engine': 'translator'},
                },
            )

        self.assertEqual(response.status_code, 200, response.get_json())
        db.session.refresh(notice)
        db.session.refresh(task)
        self.assertEqual(task.status, 'done')
        self.assertEqual(notice.title_ko, '케냐 관개 지원 관심표명요청')
        self.assertEqual(notice.infographic_path, f'infographics/notice_{notice.id}.png')
        self.assertEqual(notice.infographic_url, f'/api/notices/{notice.id}/infographic')
        self.assertEqual(uploaded['key'], notice.infographic_path)
        self.assertEqual(uploaded['content_type'], 'image/png')
        self.assertEqual(uploaded['head'], b'\x89PNG\r\n\x1a\n')
        self.assertEqual(task.result['infographic']['style'], 'slide')
        self.assertTrue(task.result['infographic']['kakao_queued'])
        self.assertEqual(
            KakaoDelivery.query.filter_by(notice_id=notice.id, kind='image').count(),
            1,
        )
        self.assertEqual(
            NoticeTask.query.filter_by(notice_id=notice.id, task_type='infographic').count(),
            0,
        )

    def test_translation_without_summary_does_not_queue_kakao(self):
        notice, task = self._create_translate_task()
        response = self.client.post(
            f'/api/notices/tasks/{task.id}/complete',
            headers=self.headers,
            json={'fields_to_update': {'titleKo': '요약 없는 번역만'}},
        )
        self.assertEqual(response.status_code, 503, response.get_json())
        self.assertTrue(response.get_json()['retryable'])
        self.assertIn('요약', response.get_json()['message'])
        db.session.expire_all()
        stored = db.session.get(BidNotice, notice.id)
        self.assertIsNone(stored.title_ko)
        self.assertIsNone(stored.infographic_path)
        self.assertEqual(
            KakaoDelivery.query.filter_by(notice_id=notice.id, kind='image').count(),
            0,
        )

    def test_translation_completion_rolls_back_when_rendering_fails(self):
        notice, task = self._create_translate_task()
        with patch(
            'services.notice_infographic.generate_notice_infographic',
            side_effect=RuntimeError('renderer unavailable'),
        ):
            response = self.client.post(
                f'/api/notices/tasks/{task.id}/complete',
                headers=self.headers,
                json={'fields_to_update': {'titleKo': '저장되면 안 되는 번역'}},
            )

        self.assertEqual(response.status_code, 503, response.get_json())
        self.assertTrue(response.get_json()['retryable'])
        db.session.expire_all()
        stored_notice = db.session.get(BidNotice, notice.id)
        stored_task = db.session.get(NoticeTask, task.id)
        self.assertIsNone(stored_notice.title_ko)
        self.assertIsNone(stored_notice.infographic_path)
        self.assertEqual(stored_task.status, 'claimed')
        self.assertEqual(
            KakaoDelivery.query.filter_by(notice_id=notice.id, kind='image').count(),
            0,
        )

    def test_translation_completion_closes_preexisting_infographic_task(self):
        notice, translate_task = self._create_translate_task()
        legacy_task = NoticeTask(
            notice_id=notice.id,
            task_type='infographic',
            status='pending',
            priority=5,
        )
        db.session.add(legacy_task)
        db.session.commit()

        def fake_generate(_payload, output, *, style):
            Path(output).write_bytes(b'\x89PNG\r\n\x1a\n' + b'x' * 4096)
            return {
                'path': str(output), 'width': 1920, 'height': 1080,
                'style': style, 'kind': 'eoi',
            }

        with (
            patch('services.notice_infographic.generate_notice_infographic', fake_generate),
            patch('utils.r2_storage.upload_file', return_value='ok'),
        ):
            response = self.client.post(
                f'/api/notices/tasks/{translate_task.id}/complete',
                headers=self.headers,
                json={'fields_to_update': {'titleKo': '서버 렌더 전환 공고'}},
            )

        self.assertEqual(response.status_code, 200, response.get_json())
        db.session.refresh(legacy_task)
        self.assertEqual(legacy_task.status, 'done')
        self.assertEqual(legacy_task.worker_id, 'server-renderer')
        self.assertTrue(legacy_task.result['superseded_external_task'])

    def test_infographic_completion_creates_image_then_link_delivery(self):
        notice, task = self._create_infographic_task()

        response = self.client.post(
            f'/api/notices/tasks/{task.id}/complete',
            headers=self.headers,
            json={
                'result': {
                    'r2_key': f'notices/{notice.id}/infographic.png',
                    'infographic_url': f'/api/notices/{notice.id}/infographic',
                }
            },
        )
        self.assertEqual(response.status_code, 200, response.get_json())

        image = KakaoDelivery.query.filter_by(notice_id=notice.id, kind='image').one()
        self.assertEqual(image.status, 'pending')

        response = self.client.get(
            '/api/notices/kakao-deliveries?status=pending',
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200)
        queued = response.get_json()['data'][0]
        self.assertEqual(queued['notice']['sourceUrl'], notice.source_url)
        self.assertEqual(queued['kind'], 'image')

        response = self.client.post(
            f'/api/notices/kakao-deliveries/{image.id}/claim',
            headers=self.headers,
            json={'worker_id': 'test-mac'},
        )
        self.assertEqual(response.status_code, 200)

        response = self.client.post(
            f'/api/notices/kakao-deliveries/{image.id}/complete',
            headers=self.headers,
            json={'result': {'engine': 'kmsg'}},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            KakaoDelivery.query.filter_by(notice_id=notice.id, kind='link').count(),
            0,
        )

        # 완료 재보고는 idempotent하며 링크 작업은 만들지 않는다.
        response = self.client.post(
            f'/api/notices/kakao-deliveries/{image.id}/complete',
            headers=self.headers,
            json={'result': {'engine': 'kmsg'}},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            KakaoDelivery.query.filter_by(notice_id=notice.id, kind='link').count(),
            0,
        )

    def test_uncertain_send_can_be_marked_failed_without_retry(self):
        notice, _task = self._create_infographic_task()
        delivery = KakaoDelivery(
            notice_id=notice.id,
            kind='image',
            status='claimed',
            attempts=1,
            worker_id='test-mac',
        )
        db.session.add(delivery)
        db.session.commit()

        response = self.client.post(
            f'/api/notices/kakao-deliveries/{delivery.id}/fail',
            headers=self.headers,
            json={'error': 'uncertain result', 'retryable': False},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json()['requeued'])
        db.session.refresh(delivery)
        self.assertEqual(delivery.status, 'failed')

    def test_delivery_api_requires_worker_auth(self):
        response = self.client.get('/api/notices/kakao-deliveries?status=pending')
        self.assertEqual(response.status_code, 401)

    def test_worker_can_download_local_infographic(self):
        notice = BidNotice(
            source='test',
            title='Download test',
            source_url='https://source.example/notices/download',
        )
        db.session.add(notice)
        db.session.flush()

        infographic_dir = Path(self.app.config['UPLOAD_FOLDER']) / 'infographics'
        infographic_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            dir=infographic_dir,
            suffix='.png',
            delete=False,
        ) as image:
            image.write(b'\x89PNG\r\n\x1a\n' + b'test-image')
            image_path = Path(image.name).resolve()
        notice.infographic_path = str(image_path)
        notice.infographic_url = f'/api/notices/{notice.id}/infographic'
        db.session.commit()

        try:
            response = self.client.get(
                f'/api/notices/{notice.id}/infographic',
                headers=self.headers,
            )
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.data.startswith(b'\x89PNG'))
            response.close()
        finally:
            image_path.unlink(missing_ok=True)

    def test_relay_receipt_and_payload_validation(self):
        self.assertEqual(
            _validate_source_url('https://source.example/notices/ok'),
            'https://source.example/notices/ok',
        )
        with self.assertRaises(RuntimeError):
            _validate_source_url('file:///tmp/not-allowed')

        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            image_path = directory / 'notice.png'
            image_path.write_bytes(b'\x89PNG\r\n\x1a\n' + b'test-image')
            _validate_image(image_path)

            receipts = ReceiptStore(directory / 'receipts')
            receipts.save(42, {'state': 'sent', 'result': {'kind': 'image'}})
            self.assertEqual(receipts.load(42)['state'], 'sent')
            receipts.remove(42)
            self.assertIsNone(receipts.load(42))

    def test_link_message_is_summary_plus_schemeless_url(self):
        self.assertEqual(
            _compact_source_url(
                'https://projects.worldbank.org/en/projects-operations/procurement-detail/OP00462061'
            ),
            'projects.worldbank.org/en/projects-operations/procurement-detail/OP00462061',
        )
        message = _format_link_message({
            'source': 'worldbank',
            'titleKo': 'RESILAND CA+ 프로그램: 타지키스탄 회복력 있는 경관 복원 프로젝트 [입찰 초청]',
            'deadline': '2026-09-11',
            'sourceUrl': 'https://projects.worldbank.org/en/projects-operations/procurement-detail/OP00462061',
        })
        summary, url = message.split('\n')
        self.assertTrue(summary.startswith('World Bank · '))
        self.assertIn('마감 9/11', summary)
        self.assertNotIn('https://', message)
        self.assertEqual(
            url,
            'projects.worldbank.org/en/projects-operations/procurement-detail/OP00462061',
        )


if __name__ == '__main__':
    unittest.main()
