#!/usr/bin/env python3
"""발주공고 인포그래픽 생성 CLI.

예:
  python generate_notice_infographic.py --notice-json notice.json --out /tmp/card.png
  python generate_notice_infographic.py --notice-id 383 --out /tmp/card.png --upload
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _load_notice_from_db(notice_id: int) -> dict:
    from app import app
    from models import BidNotice

    with app.app_context():
        notice = BidNotice.query.get(notice_id)
        if not notice:
            raise SystemExit(f'공고 #{notice_id} 를 찾을 수 없습니다.')
        return notice.to_dict()


def _upload_and_record(notice: dict, image_path: Path) -> str:
    from app import app
    from models import BidNotice, db
    from services.notice_pipeline import enqueue_kakao_image_delivery
    from utils.r2_storage import upload_file

    notice_id = int(notice['id'])
    object_key = f'infographics/notice_{notice_id}.png'
    with app.app_context():
        with image_path.open('rb') as fh:
            upload_file(fh, object_key, content_type='image/png')
        row = BidNotice.query.get(notice_id)
        if not row:
            raise SystemExit(f'공고 #{notice_id} 를 찾을 수 없습니다.')
        row.infographic_path = object_key
        row.infographic_url = f'/api/notices/{notice_id}/infographic'
        enqueue_kakao_image_delivery(notice_id)
        db.session.commit()
    return object_key


def main() -> int:
    parser = argparse.ArgumentParser(description='발주공고 인포그래픽 생성')
    parser.add_argument('--notice-json', type=Path)
    parser.add_argument('--notice-id', type=int)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument(
        '--style',
        choices=('slide', 'imagegen'),
        default='slide',
        help='slide=HTML+Chrome 결정론적 렌더(기본), imagegen=Codex $imagegen',
    )
    parser.add_argument(
        '--skip-imagegen',
        action='store_true',
        help='(구 옵션) --style slide 와 동일',
    )
    parser.add_argument('--upload', action='store_true', help='R2 업로드 + kakao_deliveries 등록')
    args = parser.parse_args()

    if args.notice_json:
        notice = json.loads(args.notice_json.read_text(encoding='utf-8'))
    elif args.notice_id:
        notice = _load_notice_from_db(args.notice_id)
    else:
        parser.error('--notice-json 또는 --notice-id 가 필요합니다.')

    from services.notice_infographic import generate_notice_infographic

    style = 'slide' if args.skip_imagegen else args.style
    result = generate_notice_infographic(notice, args.out, style=style)
    print(json.dumps(result, ensure_ascii=False))

    if args.upload:
        if not notice.get('id'):
            raise SystemExit('--upload 는 notice id 가 필요합니다.')
        key = _upload_and_record(notice, Path(result['path']))
        print(json.dumps({'uploaded': key}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
