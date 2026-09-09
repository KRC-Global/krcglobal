# 발주공고 Mac 카카오톡 릴레이

신규 발주공고의 번역이 완료되면 서버가 16:9 보고 슬라이드를 직접 생성해 R2에
저장하고 이미지 전송 큐를 만듭니다. 항상 켜진 Mac의 카카오톡에서는
지정한 1:1 친구방으로 아래 순서대로 전송합니다.

1. 공고 인포그래픽 이미지 (우측 하단 QR = 원문 공고)

```text
수집 → 번역·요약 완료(summary_ko) → 서버 슬라이드 렌더 → R2 저장 → 이미지 큐
     → Mac 릴레이 이미지 전송
요약이 비어 있으면 인포그래픽도, 카톡 전송도 하지 않습니다.
```

서버는 Chrome이 있으면 HTML 캡처를 사용하고, Vercel처럼 Chrome이 없는 환경은
Pillow 렌더러로 자동 전환합니다. 두 방식 모두 실제 Pretendard 폰트를 사용하며
AI 이미지 생성에 의존하지 않습니다. 렌더 또는 R2 업로드가 실패하면 번역 완료도
확정하지 않아 워커가 전체 단계를 안전하게 재시도할 수 있습니다.
완료/실패 보고 전에 워커가 종료되어도 30분 지난 claim은 다음 pending 폴링에서
자동 회수됩니다(`NOTICE_TASK_CLAIM_TIMEOUT_MINUTES`로 조정 가능).

외부 전송 직후 로컬 영수증을 먼저 기록해 서버 응답이 유실된 경우에도
같은 항목을 다시 보내지 않습니다.

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

운영 서버 배포 권한이 없는 Mac에서는 공용 Supabase/R2를 직접 감시할 수 있습니다.
이때 설치 시점의 마지막 공고 ID를 기준선으로 고정하면 과거 공고가 재전송되지
않습니다.

```text
KAKAO_RELAY_USE_LOCAL_DB=true
KAKAO_RELAY_MIN_NOTICE_ID=<설치 시점의 마지막 공고 ID>
```

현재 Mac 릴레이 기준선은 공고 `#413`이다. 이 ID 이하(오늘 테스트방에 넣은 KOICA 발주계획 포함)는
다시 보내지 않고, 그 다음부터 새로 쌓인 공고만 전송한다.

나라장터 KOICA 발주계획은 `KOICA_PLAN_MIN_POSTED=2026-09-10` 이후 공개분만 수집한다.

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

- 번역 완료 전에는 인포그래픽을 만들지 않아 영문/미완성 카드 전송을 막습니다.
- R2 키는 `infographics/notice_<ID>.png`로 고정되어 재시도해도 파일이 늘어나지 않습니다.
- 공고별 이미지 큐는 하나만 만들어져 완료 요청 재시도에도 중복 전송되지 않습니다.
- `KAKAO_ROOM_NAME`과 정확히 일치하는 방이 하나가 아니면 전송하지 않습니다.
- 이미지 전송을 시도한 뒤 결과가 불확실하면 자동 재시도하지 않습니다.
- 원문 링크는 카톡으로 보내지 않고 인포그래픽 우측 하단 QR로만 엽니다.
- `WORKER_SECRET`은 명령행 인자로 노출하지 않고 HTTP 헤더로만 사용합니다.
