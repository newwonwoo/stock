# 봇 측 fix 요청 — swing endpoint Basic Auth 우회

> ✅ **PATCHED** (2026-05-05) — 봇 측 commit `f7d6954`. 검증: `PATCH_REPORT_swing_auth_B65.md` 참조.
>
> 작성: 2026-05-05 (리서치 측 첫 push 검증 중 발견).
> 대상 repo: TradeBot (EC2 `/home/ec2-user/trading-bot/`).
> 우선순위: **차단 (blocking)** — 본 fix 없으면 리서치 측 `bot_dashboard.py`
> (held_stocks fetch) 무력화. 모든 sell_signals 가 보유 종목 필터 없이
> 전종목 대상으로 발행됨 (작동은 함, spec 위반).

---

## 1. 증상

리서치 측 `src/integrations/bot_dashboard.py` 가 봇 dashboard `/api/swing/*`
호출 시 항상 401 응답 + body `"인증이 필요합니다"`.

검증 환경: EC2 SSH 직접 호출 (localhost:8080). 토큰 일치 확인됨.

```
$ curl -s -H "Authorization: Bearer $SWING_API_TOKEN" \
       http://localhost:8080/api/swing/research_status
인증이 필요합니다

$ curl -s -o /dev/null -w "%{http_code}\n" \
       http://localhost:8080/api/swing/research_status
401   ← spec 상 403 이어야 함 (fail-closed)
```

dashboard 환경변수 검증:
```
proc 길이=65, MATCH ✅   (override.conf 와 process env 일치)
```

→ 토큰은 맞게 주입됐는데 401 발사.

---

## 2. 원인

`dashboard_server.py` line 240~245 기준, 모든 endpoint 가 진입 시
**Basic Auth 게이트** 를 먼저 거침:

```python
# 비밀번호 설정돼 있으면 항상 검사
if self._password_set():
    if self._check_auth():     # Basic Auth (DASHBOARD_PASSWORD)
        return True
    self._send_401()           # ← /api/swing/* 도 여기서 차단됨
    return
```

`_check_swing_auth` (bearer 검사, line 200~219) 는 그 **다음** 라우팅 단계
에서 호출되도록 설계되어 있어, `/api/swing/*` path 로 들어와도 Basic Auth
게이트에서 401 으로 막혀 bearer 검사 자체에 도달하지 못함.

`DASHBOARD_PASSWORD` 가 환경변수에 없어도 `config.py` 또는 다른 경로에서
읽혀서 `_password_set()` 이 True 평가되는 것으로 추정됨.

---

## 3. 요청 fix

`dashboard_server.py` 의 `do_GET` (필요 시 `do_POST`) 진입부에서
`/api/swing/*` path 는 **Basic Auth 우회 + bearer 전용 분기** 추가.

### 패치 (제안)

```python
SWING_PATH_PREFIX = "/api/swing/"

def do_GET(self):
    # 1) /api/swing/* 는 bearer 전용 (Basic Auth 우회)
    if self.path.startswith(SWING_PATH_PREFIX):
        if not self._require_swing_auth():
            return  # 403 already sent inside _require_swing_auth
        return self._handle_swing_get(self.path)

    # 2) 그 외는 기존 Basic Auth 흐름 그대로
    if self._password_set():
        if not self._check_auth():
            self._send_401()
            return
    # ... 기존 라우팅 ...
```

`do_POST` 도 같은 분기 적용 (현재 swing 측에 POST 가 있으면).

### 보안 spec 유지

- swing endpoint = **bearer token 전용** (64자 `SWING_API_TOKEN`)
- 다른 dashboard 화면 = **Basic Auth (DASHBOARD_PASSWORD)** 그대로
- 두 인증 분리 → 토큰 leak 시 비번 무관, 비번 leak 시 swing 무관 (이중 방어)

### fail-closed status code

- bearer 미전송 / 불일치 시 → **403** (현 spec)
- 401 은 "Basic Auth 필요" 의미 → swing endpoint 에는 부적절

---

## 4. 검증 (봇 측 패치 후)

```bash
# 1. dashboard 재시작
sudo systemctl daemon-reload
sudo systemctl restart dashboard
sleep 3

# 2. bearer 정상 → 200 + JSON
TOKEN=$(sudo grep -oP 'SWING_API_TOKEN="?\K[^"]+' \
        /etc/systemd/system/dashboard.service.d/override.conf)
curl -s -H "Authorization: Bearer $TOKEN" \
     http://localhost:8080/api/swing/research_status
# → JSON 응답 (research file mtime / staleness 등)

curl -s -H "Authorization: Bearer $TOKEN" \
     http://localhost:8080/api/swing/held_stocks
# → JSON 응답 (held positions list, 보유 0이면 빈 배열)

# 3. bearer 미전송 → 403
curl -s -o /dev/null -w "%{http_code}\n" \
     http://localhost:8080/api/swing/research_status
# → 403

# 4. dashboard 화면 (비-swing) → 여전히 Basic Auth 요구
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8080/
# → 401
```

위 4개 모두 기대값 일치하면 패치 완료.

---

## 5. 수정 영향 범위

- **봇 측**: `dashboard_server.py` 라우팅 분기 1곳 추가 (~10줄)
- **리서치 측**: 변경 없음 (`src/integrations/bot_dashboard.py` 가 이미
  Bearer 보내고 있고 401/403 둘 다 graceful fallback 처리)
- **사용자**: 변경 없음 (DASHBOARD_PASSWORD 그대로 유지)

---

## 6. 패치 미적용 시 임시 운영

리서치 측 `bot_dashboard.fetch_held_stocks()` 가 None 반환 →
`generate_sell_signals.py` 가 **전종목 대상으로 sell_signals 발행** (작동은
함, spec 위반 + 봇 측 노이즈 ↑).

봇 측에서 받은 sell_signal 의 code 가 보유 종목과 매칭 안 되면 무시하면
됨 (이미 봇 측 spec). 다만 처리 비용 / 로그 노이즈 증가.

→ **빠른 패치 권장** (~10줄 + 테스트).

---

## 7. 관련 이슈 (별건, 참고)

봇 로그에서 함께 관찰됨 (본 fix 와 무관):

```
❌ 잔고 조회 실패: KIS_MOCK=True + vts_access_token 없음
  — 실전 토큰 fallback 차단 (실계좌 주문 방지, §2 token-scope)
⚠️ Bootstrap: 잔고 조회 실패 — 포지션 복구 생략
```

봇 측 KIS 모의투자 토큰 (`vts_access_token`) 미발급 또는 만료. 본 fix
범위 밖. 봇 측에서 별도 처리 필요.

---

**문서 끝.** 패치 적용 후 본 파일 삭제 또는 archive.
