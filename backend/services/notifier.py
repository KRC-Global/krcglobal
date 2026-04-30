"""
알림 어댑터 — 1차는 Discord webhook, 추후 Slack/Telegram 추가 시 같은 인터페이스를 따른다.

`get_notifier()` 가 환경변수에 따라 적절한 구현을 돌려준다. 환경변수 미설정이면
NullNotifier 가 반환되어 알림 호출은 no-op (수집/큐잉 흐름은 영향 없음).

발송 실패는 절대 raise 하지 않는다 — 호출자(post_collect_hook 등) 가 알림 실패로
수집 트랜잭션을 깨뜨리지 않게 하기 위함. 실패는 stderr 출력 + False 반환.
"""
from __future__ import annotations

import os
from typing import Protocol


class Notifier(Protocol):
    def send(self, *, title: str, body: str, url: str | None = None,
             fields: dict | None = None) -> bool:
        ...


class NullNotifier:
    """환경변수 미설정/테스트용 — 모든 호출을 즉시 성공 처리."""

    def send(self, **_kwargs) -> bool:
        return True


class DiscordWebhookNotifier:
    """Discord Incoming Webhook 1개로 embed 메시지를 발송."""

    # Discord embed 1개 본문 한도 4096, description 한도 등 고려해 안전하게 자른다.
    MAX_TITLE = 240
    MAX_DESC = 3800
    TIMEOUT_SEC = 5.0

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def send(self, *, title: str, body: str, url: str | None = None,
             fields: dict | None = None) -> bool:
        try:
            import requests as _req
        except Exception as e:
            print(f'[notifier] requests 미설치: {e}')
            return False

        embed = {
            'title': (title or '')[: self.MAX_TITLE],
            'description': (body or '')[: self.MAX_DESC],
        }
        if url:
            embed['url'] = url
        if fields:
            embed['fields'] = [
                {'name': str(k)[:256], 'value': str(v)[:1024], 'inline': True}
                for k, v in fields.items() if v not in (None, '')
            ][:25]  # Discord embed 필드 한도

        try:
            resp = _req.post(
                self.webhook_url,
                json={'embeds': [embed]},
                timeout=self.TIMEOUT_SEC,
            )
            if resp.status_code >= 400:
                print(f'[notifier] Discord HTTP {resp.status_code}: {resp.text[:200]}')
                return False
            return True
        except Exception as e:
            print(f'[notifier] Discord 발송 예외: {e}')
            return False


def get_notifier() -> Notifier:
    """환경변수 기반 팩토리. URL 미설정 시 NullNotifier."""
    url = os.environ.get('DISCORD_NOTICE_WEBHOOK_URL', '').strip()
    if not url:
        return NullNotifier()
    return DiscordWebhookNotifier(url)
