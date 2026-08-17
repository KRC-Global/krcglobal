import os
import sys
import tempfile
import unittest
from pathlib import Path


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
    _validate_image,
    _validate_source_url,
)


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
        link = KakaoDelivery.query.filter_by(notice_id=notice.id, kind='link').one()
        self.assertEqual(link.status, 'pending')

        # 완료 재보고는 idempotent하며 링크 작업도 하나만 유지한다.
        response = self.client.post(
            f'/api/notices/kakao-deliveries/{image.id}/complete',
            headers=self.headers,
            json={'result': {'engine': 'kmsg'}},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            KakaoDelivery.query.filter_by(notice_id=notice.id, kind='link').count(),
            1,
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


if __name__ == '__main__':
    unittest.main()
