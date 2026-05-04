# 봇 측 패치 완료 보고 — swing endpoint Basic Auth 우회

> 대상: wonwoo-research 측 (BOT_FIX_REQUEST_swing_auth.md 발신자)
> 패치: 봇 측 commit `f7d6954` (branch `claude/new-shared-harness-BLB3f`)
> 일시: 2026-05-05 KST

## 요약

리서치 측 발견 + 요청 — 패치 적용 완료.

`dashboard_server.do_GET` 진입부에 `/api/swing/*` 분기 추가. Basic Auth 우회 + bearer 전용. 다른 path 는 기존 Basic Auth 그대로.

## 변경 (10줄)

```python
def do_GET(self):
    parsed = urllib.parse.urlparse(self.path)
    is_swing = parsed.path.startswith("/api/swing/")
    if not is_swing and not self._require_auth():
        return
    # ... 기존 라우팅 (그대로)
```

각 swing endpoint 6개의 자체 `_require_swing_auth()` (bearer + 403 fail-closed) 가 그대로 작동.

## 검증 (deploy 후)

| 케이스 | 기대 | 비고 |
|---|---|---|
| `/api/swing/*` + bearer 정상 | 200 + JSON | ✅ |
| `/api/swing/*` + bearer 미전송 | 403 | spec 일치 (401 X) |
| 비-swing path | 401 (Basic Auth) | 기존 그대로 |
| do_POST | 변경 X | swing path 없음 |

## 영향

- 리서치 측 `bot_dashboard.fetch_held_stocks()` 정상 응답 → held_stocks 필터 작동
- `generate_sell_signals.py` 가 보유 종목만 대상으로 sell_signals 발행
- DASHBOARD_PASSWORD 그대로 보존 (다른 화면 무영향)

## 별건 (참고)

`vts_access_token` 미발급 이슈 (fix request §7) 는 봇 시작 시 1분당 1회 KIS 제한 — 1분 후 자동 재시도 정상 (`✅ 모의투자 토큰 발급 완료`). 일과성. 별도 작업 X.

## 영구 박제

- 봇 측 `CLAUDE.md §2` 신규 invariant 행 추가 (회귀 방지)
- `BOT_FIX_REQUEST_swing_auth.md` 헤더에 `✅ PATCHED` 표시
