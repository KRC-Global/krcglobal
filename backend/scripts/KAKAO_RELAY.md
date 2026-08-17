# 발주공고 Mac 카카오톡 릴레이

신규 발주공고의 인포그래픽 작업이 완료되면 항상 켜진 Mac의 카카오톡에서
지정한 1:1 친구방으로 아래 순서대로 전송합니다.

1. 공고 인포그래픽 이미지
2. `BidNotice.source_url` 원문 출처 링크

이미지와 링크는 별도 큐로 처리하므로 링크만 실패해도 이미지가 중복
전송되지 않습니다. 외부 전송 직후 로컬 영수증을 먼저 기록해 서버 응답이
유실된 경우에도 같은 항목을 다시 보내지 않습니다.

## 1. 서버 설정

서버를 다시 배포합니다. 카카오 큐는 기본 활성화되며, 일시 중지할 때만
배포 환경변수에 `KAKAO_RELAY_ENABLED=false`를 지정합니다.

```text
WORKER_SECRET=<충분히 긴 임의 문자열>
```

## 2. Mac 준비

```bash
brew install channprj/tap/kmsg
kmsg status
```

카카오톡에 로그인하고, 시스템 설정 → 개인정보 보호 및 보안 → 손쉬운 사용에서
`kmsg` 실행을 허용합니다. 대상 친구방을 한 번 열어 최근 채팅 목록에 보이게
합니다. 릴레이는 정확히 일치하는 방이 하나일 때만 전송합니다.

## 3. 로컬 설정 및 dry run

```bash
cp backend/kakao-relay.env.example backend/kakao-relay.env
chmod 600 backend/kakao-relay.env
python3 backend/scripts/kakao_relay.py \
  --env-file backend/kakao-relay.env --check

python3 backend/scripts/kakao_relay.py \
  --env-file backend/kakao-relay.env --once
```

`KAKAO_RELAY_DRY_RUN=true`에서는 실제 전송 및 서버 작업 claim을 하지 않습니다.
점검이 끝나면 `KAKAO_RELAY_DRY_RUN=false`로 바꿉니다.

## 4. 재부팅 후 자동 실행

```bash
python3 backend/scripts/install_kakao_relay_launch_agent.py \
  --env-file backend/kakao-relay.env
```

로그는 `~/Library/Logs/krcglobal-kakao-relay.log`에 기록됩니다.

```bash
tail -f ~/Library/Logs/krcglobal-kakao-relay.log
launchctl print gui/$(id -u)/com.krcglobal.kakao-relay
```

## 안전 동작

- `KAKAO_ROOM_NAME`과 정확히 일치하는 방이 하나가 아니면 전송하지 않습니다.
- 이미지 전송을 시도한 뒤 결과가 불확실하면 자동 재시도하지 않습니다.
- 이미지 성공 후에만 원문 출처 링크 작업이 생성됩니다.
- `WORKER_SECRET`은 명령행 인자로 노출하지 않고 HTTP 헤더로만 사용합니다.
