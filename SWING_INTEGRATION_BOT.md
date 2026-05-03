# SWING_INTEGRATION_BOT — TradeBot 측 스윙/리서치 연동 spec

> 본 문서는 **TradeBot v5.x 측** spec.
> 리서치 측 spec = `docs/INTEGRATION.md` (일반 인터페이스 명세) + `docs/{README,TASKS,DESIGN}.md` (리서치 시스템).
> 본 doc 은 봇 측 구현 결정 + 통신 방식 + 5건 사용자 결정 + Phase 진행 게이트.

작성: 2026-05-03 (브랜치 `claude/new-shared-harness-BLB3f`).
관련 plan: `/root/.claude/plans/tender-sprouting-moler.md` (세션 내 plan file).

---

## 1. 통신 방식 결정 (Firestore deprecate)

INTEGRATION.md 가 default 로 Firestore 추천했으나 봇은 단일 EC2 24/7 운영 + 추가 비용 0원 의지 → **Firestore 사용 X**. 봇 기존 인프라 활용:

| 방향 | 통신 | 인증 | 지연 |
|---|---|---|---|
| **리서치 → 봇** | GitHub Actions SSH file push (atomic mv) | `secrets.EC2_SSH_KEY` (deploy 인프라 재활용) | 즉시 (push 끝나면) |
| **봇 → 리서치** | dashboard `/api/swing/*` GET endpoint | bearer token (`SWING_API_TOKEN`, 64-char) | 즉시 |

INTEGRATION.md 의 데이터 schema (buy_signals / sell_signals / blacklist / macro_status / held_stocks / buy_history / sell_history) 는 그대로 유지. 통신 수단만 변경.

### 1.1 리서치 → 봇 (SSH push)

리서치 GitHub Actions (`daily.yml`) 마지막 step:
```bash
scp -r out/*.json $EC2_HOST:/home/user/tradingbot/data/research/incoming/
ssh $EC2_HOST "mv /home/user/tradingbot/data/research/incoming/*.json \
                  /home/user/tradingbot/data/research/"
```

원자성: incoming → final dir mv 는 same-FS rename = atomic. 봇 polling 이 partial JSON 못 읽음.

봇 file path:
- `data/research/buy_signals_{YYYY-MM-DD}.json`
- `data/research/sell_signals_{signal_id}.json` (실시간 추가)
- `data/research/blacklist_active.json`
- `data/research/macro_status_{YYYY-MM-DD}.json`

처리 후:
- sell_signals consumed → `data/research/processed/sell_signals_{id}.json` mv
- `data/research/processed_signal_ids.json` set 박제 (중복 push 가드)

### 1.2 봇 → 리서치 (dashboard GET)

봇 dashboard `dashboard_server.py` 신규 6 endpoint (bearer token 의무):

| endpoint | 응답 | 호출자 |
|---|---|---|
| `GET /api/swing/held_stocks` | 현재 보유 (status / tranches / avg_price / days_held) | 리서치 GitHub Actions 16:30 + 일요일 21:00 |
| `GET /api/swing/buy_history?date=D` | 그날 매수 이력 | 리서치 일일 보고 |
| `GET /api/swing/sell_history?date=D` | 그날 매도 이력 | 리서치 일일 보고 |
| `GET /api/swing/kpi` | 누적 승률 / 평균 익절·손절 / 평균 보유일 | 주간 리포트 |
| `GET /api/swing/research_status` | research file mtime / staleness / processed 카운트 | 리서치 self-check |
| `GET /api/swing/pending_signals` | 오늘 후보 N개 (1차 진입 전) | 리서치 검증 |

인증: HTTP header `Authorization: Bearer <SWING_API_TOKEN>`. token 미일치 시 403. `_check_auth` 신규 분기.

### 1.3 INTEGRATION.md 와 차이 요약

| 항목 | INTEGRATION.md | 본 봇 결정 |
|---|---|---|
| 통신 | Firestore `shared/` 컬렉션 | SSH file push + dashboard GET |
| 의존 | `google-cloud-firestore` + Firebase 프로젝트 + 2 SA | 0 (기존 SSH/Flask 재활용) |
| 인증 | Service Account JSON ×2 | SSH key + bearer token |
| 지연 | 5분 폴링 | 즉시 |
| 비용 | Firebase 무료 tier | 0 |

---

## 2. 사용자 결정 5건 (채택됨)

### 2.1 TRANCHE_RATIO = (0.15, 0.15, 0.70)

```python
# config 또는 _DEFAULTS 에 노출
TRANCHE_RATIO = (0.15, 0.15, 0.70)  # 1차 시초가 / 2차 ma10 / 3차 ma15
```
1차 = 시초가 진입 15% / 2차 = ma10 도달 15% / 3차 = ma15 도달 70%. 큰 비중을 ma15 로 보낸 건 "충분히 빠진 후 큰 비중" 룰.

### 2.2 ma10/ma15 = freeze (Plan A)

1차 진입 시점의 ma10/ma15 를 position 에 박제. 다음날 ma 변동되어도 미실행 tranche 의 target_price 는 변경 X.

```json
{
  "tranches": {
    "second": {"target_price": 215000, "ma_ref": "ma10", "ma_ref_frozen": true},
    "third":  {"target_price": 208000, "ma_ref": "ma15", "ma_ref_frozen": true}
  }
}
```

이유: 변동성 있는 시기 ma10 이 5% 떨어져 2차 트리거가 갑자기 사라지면 분할 진입 의도 무력. freeze 가 보수적 안전.

다음날 같은 종목 STRONG_BUY 또 도착해도 미실행 tranche target 갱신 X (단 valid_until 만 갱신).

### 2.3 valid_until 만료 시

- 보유 유지 (이미 진입한 1차/2차 tranche 는 그대로)
- 미실행 tranche → cancel (`tranches.second.cancelled_at` 박제, filled=false 유지)
- 자체 매도 룰만 적용 (시그널 expire = 리서치 더 이상 권장 X → 외부 sell_signal 도 대상 X)
- valid_until 갱신은 다음 시그널 도착 시만

### 2.4 시초가 진입 = 지정가 IOC

1차 진입:
- 가격 = `prev_close × 1.01` (전일 종가 +1%)
- 주문 type = IOC 지정가 (즉시 체결 or cancel)
- 미체결 시 → skip (시장가 fallback X)

이유: 갭 +5% 위 진입 차단. STRONG_BUY 신호가 갭 큰 종목에 자주 발생 → 시장가 진입 시 평균 진입가 +5~10% 위. 보수적으로 +1% 안 체결되면 다음 기회 (2차 ma10) 까지 대기.

2차/3차 진입:
- 가격 = ma 도달 시 시장가 (보수성 작아도 OK — 이미 충분히 빠진 시점)

### 2.5 HMAC 시그 키 = SSH 키와 분리

- research repo GitHub Secrets: `RESEARCH_HMAC_KEY` (별도)
- 봇 EC2 환경변수: `RESEARCH_HMAC_KEY` (별도, SSH 키와 무관)
- research file 머리에 `signed_by` / `sha256_hmac` 동봉:
  ```json
  {
    "signed_by": "research_v1",
    "sha256_hmac": "abc123...",
    "data": { ... 실제 시그널 ... }
  }
  ```
- 봇이 read 시 HMAC 검증 → 위반 시 reject + `RESEARCH_HMAC_FAIL` emit + 텔레그램 alert

이유: SSH 키 leak 시에도 HMAC 키 모르면 시그널 위조 불가. 이중 방어.

---

## 3. Phase 진행 (단계적 도입)

```
Phase 0 → INTEGRATION 갱신 + 본 문서 작성 (현재)
  └─ Phase 1 → research_reader read-only, 1주 dry-run
       └─ Phase 2 → dashboard endpoint 가짜 데이터 GET 검증
            └─ Phase 3 → swing_simulator §29 게이트 → paper 2주
                 └─ Phase 4 → 모의투자 canary 1종목 1주
                      └─ Phase 5 → 모의투자 전체 활성화 1개월
                           └─ Phase 6 → KIS_MOCK=False 별도 트리거
```

각 phase 게이트는 plan file `/root/.claude/plans/tender-sprouting-moler.md` §3 참조. 회귀 시 직전 phase 로 즉시 rollback (`swing_real_enabled=False` 토글 1줄).

---

## 4. 파일 구조 (구현 대상)

### 신규
```
swing/
  __init__.py
  research_reader.py     # file polling + mtime/HMAC + schema validate
  buy_strategy.py        # 분할 진입 룰 (1차 IOC / 2차 ma10 / 3차 ma15)
  sell_strategy.py       # 자체 룰 + RESEARCH_SIGNAL 응답
  position_reporter.py   # data/swing/positions.json + history JSON write
  swing_runner.py        # 메인 루프 (main.py dispatcher 통합)
tools/
  swing_simulator.py     # §29 게이트
tests/
  test_swing_*.py        # M30~M38 mutation
data/
  research/              # SSH push 도착지
  research/processed/    # consumed sell_signals 보관
  swing/                 # positions.json / sell_history_*.json
```

### 수정
- `main.py` — dispatcher swing tick / `_on_realtime_execution` swing 분기 / `MAX_POSITIONS_SWING` capital 분리
- `strategy.py` — `_force_liquidate_position` swing skip / `_buy_prefilter_rejected` pool 분기 / `swing_positions` 컨테이너
- `state_manager.py` — `load_swing_positions` / `save_swing_positions` / `_validate_loaded` schema 갱신
- `dashboard_server.py` — `/api/swing/*` 6 endpoint + bearer token (`_check_auth` 신규 분기)
- `CLAUDE.md` — §2 신규 9 행 (자금 분리 / EOD skip / state schema / 인증 등)

---

## 5. 안전장치 (§2 신규 9 행)

plan file `/root/.claude/plans/tender-sprouting-moler.md` §4 참조.

1. swing_positions 분리 (∩ day positions = ∅)
2. `_force_liquidate_position` swing skip
3. MAX_POSITIONS_DAY/SWING 분리 enforce
4. swing capital floor (`≤ total_balance × 0.30`)
5. research file freshness (mtime ≤24h + HMAC)
6. sell_signal idempotency (set + processed/ mv)
7. swing tranche 단조 (first→second→third, true→false 후진 X)
8. swing positions schema (state_manager 검증)
9. dashboard swing endpoint bearer token 의무

각 행 mutation M30~M38 으로 보호.

---

## 6. 검증

각 phase 종료 시:

1. `python3 -m pytest tests/test_swing_*.py -v` — M30~M38 통과
2. `python3 pre_deploy_check.py` — 13단계 통과
3. `python3 -m mypy swing/ tools/swing_simulator.py` — R7 fail 0
4. `python3 -m pytest tests/` — 921+ tests pass (회귀 0)
5. safety-auditor agent 점검 (METHODOLOGY §31)
6. `tools/swing_simulator.py` — Net ≥80% / 이유 불명 = 0
7. paper 운영 시 INV-10 trip 0 / RequestGate fail_cache 증가율 < 5%
8. dashboard `/api/swing/*` bearer token 인증 + 응답 schema 일치

---

## 7. 의도적 미해결 (다음 세션)

- KIS_MOCK=False 전환 (CLAUDE.md §10.5 BUG-04 fail-closed 트리거)
- WS Stage 1/2 revert (사용자 보류 중)
- 텔레그램 `/sector` wiring (PLAN.md §3-1)

---

## 8. 리서치 측 데이터 요구사항

봇 측 paper_trades_swing.csv 박제 (~80 컬럼, 데이트 매매 동일급) 가 작동하려면
리서치 측이 buy_signals.json 등에 모든 sub-field 를 채워야 함.

상세 spec: **`docs/SWING_RESEARCH_DATA_REQUIREMENTS.md`** — 사용자가 리서치
repo (`wonwoo-research`) 측에 공유.

핵심 의무:
- buy_signals: `nine_filter` 9 sub-field + `positive_signals[].type` +
  `negative_signals[].type` + `block_reasons[].type` + `moving_averages`
- sell_signals: `severity` + `trigger.type` + `trigger.subtype`
- blacklist: `block_reasons[].type` (paper 진입 시 매칭 분석)
- macro_status: `indicators.foreign_kospi_net` 외인 순매수

빠뜨리면 분석 가치 ↓ (개별 ROI / 승률 분포 분석 불가).
