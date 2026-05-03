# INTEGRATION — wonwoo-research ↔ TradeBot v5.x

> **이 문서는 인터페이스 명세서입니다.**
> 매수/매도 전략·위험방지 로직은 TradeBot 측에서 결정.
> 본 문서는 **데이터 인터페이스만** 정의.
>
> **봇 측 결정 (2026-05-03)**: Firestore 사용 X. 통신 = SSH file push (리서치→봇) + dashboard GET (봇→리서치).
> 데이터 schema 는 본 문서 그대로. 통신 수단만 다름. 상세 = `docs/SWING_INTEGRATION_BOT.md`.

---

## 1. 두 시스템의 책임 분리

```
┌──────────────────────────┐         ┌──────────────────────────┐
│   wonwoo-research        │         │   TradeBot v5.x          │
│   (분석·신호 생산)       │         │   (실행·전략 운용)       │
├──────────────────────────┤         ├──────────────────────────┤
│ - 9중 필터 분석          │         │ - 매수 실행 전략         │
│ - 매수 시그널 생성       │  ──→   │ - 분할 진입 (1.5/1.5/7)  │
│ - 매도 시그널 생성       │  ──→   │ - 손절·익절·트레일링     │
│ - 매크로 상태 산출       │  ──→   │ - 위험 인지 (초방어)     │
│ - 워치/화이트리스트      │         │ - 자금 운용 (30%)        │
│                           │         │                           │
│                           │  ←──   │ - 보유 종목 정보         │
│                           │  ←──   │ - 매수가·매수일·수량     │
└──────────────────────────┘         └──────────────────────────┘
              │                                    │
              └─────────────┬──────────────────────┘
                            ↓
                    [Firestore: shared/]
```

**원칙:**
- 리서치는 **신호만 생산**. 실행 ❌. 전략 결정 ❌.
- 봇은 **신호 소비 + 실행 + 자체 전략**.
- 통신은 **Firestore `shared/` 컬렉션 단방향 쓰기/읽기**.
- 직접 함수 호출 ❌, REST API ❌.

---

## 2. Firestore 공유 스키마

### 2.1 컬렉션 구조

```
shared/
  ├─ to_bot/                     [리서치 → 봇]
  │   ├─ buy_signals/{date}      매수 시그널 (매일 갱신)
  │   ├─ sell_signals/{id}       매도 시그널 (실시간 추가)
  │   ├─ blacklist/active        매수 차단 종목 (실시간)
  │   └─ macro_status/{date}     매크로 상태 (매일)
  │
  └─ from_bot/                   [봇 → 리서치]
      ├─ held_stocks/{code}      현재 보유 종목 (실시간)
      ├─ buy_history/{date}      매수 이력 (참조용)
      └─ sell_history/{date}     매도 이력 (참조용)
```

### 2.2 권한 매트릭스

| 컬렉션 | 리서치 | 봇 |
|---|---|---|
| `to_bot/*` | Read/Write | Read only |
| `from_bot/*` | Read only | Read/Write |

**Firestore 보안 룰:**
```javascript
match /shared/to_bot/{document=**} {
  allow read: if request.auth.uid in ["research_sa", "bot_sa"];
  allow write: if request.auth.uid == "research_sa";
}
match /shared/from_bot/{document=**} {
  allow read: if request.auth.uid in ["research_sa", "bot_sa"];
  allow write: if request.auth.uid == "bot_sa";
}
```

각 시스템은 **별도 Service Account** 사용.

---

## 3. 리서치 → 봇 인터페이스

### 3.1 buy_signals (매수 시그널)

**경로**: `shared/to_bot/buy_signals/{YYYY-MM-DD}/{stock_code}`

**갱신 주기**: 매일 07:45 KST (GitHub Actions)

**스키마**:
```json
{
  "code": "000660",
  "name": "SK하이닉스",
  
  "signal": "STRONG_BUY",
  "score": 92,
  
  "nine_filter": {
    "financial_trend": "🟢",
    "quant_health": "🟢",
    "margin_diagnosis": "🟢",
    "moat": "🟢",
    "flow": "🟢",
    "credit_short": "🟢",
    "nps": "🟢",
    "technical": "🟢",
    "report": "⭐"
  },
  
  "positive_signals": [
    {"type": "NPS_NEW", "score": 15},
    {"type": "ANALYST_TARGET_UP", "score": 10}
  ],
  
  "negative_signals": [],
  
  "blocked": false,
  "block_reasons": [],
  
  "moving_averages": {
    "ma10": 215000,
    "ma15": 208000
  },
  
  "valid_until": "2026-05-09",
  "created_at": "2026-05-04T07:45:00+09:00"
}
```

**Signal 값 정의**:
| signal | 의미 | 점수 범위 |
|---|---|---|
| `STRONG_BUY` | 즉시 진입 권장 | 90+ |
| `BUY` | 분할 진입 가능 | 70~89 |
| `HOLD` | 더 기다림 | 50~69 |
| `AVOID` | 진입 보류 | <50 |

**봇이 사용하는 필드**:
- `signal == "STRONG_BUY"` → 1차 시초가 진입 트리거
- `moving_averages.ma10` → 2차 진입 트리거 가격
- `moving_averages.ma15` → 3차 진입 트리거 가격
- `valid_until` → 유효기간 만료 시 신호 폐기

**유의:**
- `blocked: true`면 절대 매수 ❌
- 이동평균선 값은 **매일 갱신** (다음날 재진입 시점 계산용)

---

### 3.2 sell_signals (매도 시그널)

**경로**: `shared/to_bot/sell_signals/{signal_id}`

**갱신 주기**: 실시간 (공시 발생 즉시)

**스키마**:
```json
{
  "signal_id": "20260504_035720_001",
  "code": "035720",
  "name": "카카오",
  
  "severity": "URGENT",
  
  "trigger": {
    "type": "DISCLOSURE",
    "subtype": "전환사채권발행결정",
    "details": "300억, 전환가 ₩42,000, 행사 2026-08-01부터"
  },
  
  "action_recommendation": "전량 시초가 매도",
  "reason_short": "CB 발행 (행사기간 D-89)",
  
  "created_at": "2026-05-04T15:42:11+09:00",
  "expires_at": "2026-05-05T15:30:00+09:00",
  "consumed": false
}
```

**Severity 값 정의**:
| severity | 의미 | 봇 행동 (권장) |
|---|---|---|
| `URGENT` | 즉시 매도 (객관적 사실) | 자체 룰에 따라 즉시 매도 |
| `REVIEW` | 매도 검토 필요 | 자체 룰로 판단 |
| `MONITOR` | 모니터링 강화 | 매도 ❌, 관찰만 |

**Trigger Type 정의**:
- `DISCLOSURE` — DART 공시 기반
- `CB_EXERCISE` — CB 행사기간 도달
- `EARNING` — 잠정실적 발표
- `NEWS` — 펀더 훼손 뉴스 (v1.5+)
- `ANALYST` — 코어 애널 매도 의견

**봇이 사용하는 필드**:
- `code` — 보유 중인 종목과 매칭 (보유 ❌면 무시)
- `severity` — 매도 강도 결정
- `action_recommendation` — 참고용 (봇이 자체 판단)
- `consumed` — 봇이 처리한 후 `true`로 갱신

**유의:**
- 봇은 처리 후 `consumed: true`로 표시 (재처리 방지)
- `expires_at` 지나면 리서치가 자동 정리

---

### 3.3 blacklist (매수 차단)

**경로**: `shared/to_bot/blacklist/active/{stock_code}`

**갱신 주기**: 부정 시그널 발생 즉시

**스키마**:
```json
{
  "code": "047810",
  "name": "한국항공우주",
  
  "block_reasons": [
    {
      "type": "MAJOR_SHAREHOLDER_SELL",
      "detected_at": "2026-04-15",
      "expires_at": "2026-07-14",
      "description": "최대주주 5.2% 매도",
      "severity": "URGENT"
    }
  ],
  
  "blocked_until": "2026-07-14",
  "can_resume_at": "2026-07-15"
}
```

**Block Type 정의**:
| Type | 차단 기간 |
|---|---|
| `TRADING_HALT` | 영구 |
| `FRAUD_DETECTED` | 영구 |
| `CAPITAL_REDUCTION` | 영구 |
| `MAJOR_SHAREHOLDER_SELL` | 90일 |
| `BLOCK_DEAL_MAJOR` | 90일 |
| `BLOCK_DEAL_INSTITUTION` | 30일 |
| `RIGHTS_OFFERING` | 30일 |
| `EARNING_SHOCK` | 60일 |
| `EARNING_NEAR` | D-3 ~ D+3 |
| `ANALYST_SELL` | 60일 |
| `SHORT_TOP10` | 이탈 시까지 |
| `DSO_DETERIORATION` | 정상화 시까지 |
| `NPS_FULL_EXIT` | 90일 |
| `CB_BW_EXERCISE_PERIOD` | 종료 시까지 |
| `CB_BW_NEAR_EXERCISE` | D+0 후 60일 |
| `CB_BW_EXERCISED` | 60일 |

**봇이 사용하는 필드**:
- 매수 진입 직전 `blacklist/active/{code}` 존재 여부 확인
- 존재하면 매수 절대 ❌
- 만료된 차단은 리서치가 자동 삭제 (cleanup_expired)

---

### 3.4 macro_status (매크로 상태)

**경로**: `shared/to_bot/macro_status/{YYYY-MM-DD}`

**갱신 주기**: 매일 07:45 KST

**스키마**:
```json
{
  "date": "2026-05-04",
  
  "overall": "🟡",
  
  "indicators": {
    "kospi_change": -0.42,
    "kosdaq_change": -0.81,
    "sp500_change": 0.31,
    "usd_krw": 1394,
    "us_10y_yield": 4.51,
    "foreign_kospi_net": -284000000000
  },
  
  "events_today": [
    {"time": "14:00", "type": "BOK_RATE", "expected": "동결"},
    {"time": "21:30", "type": "US_ISM_PMI"}
  ],
  
  "claude_opinion_short": "환율 1400 임박 + 외인 매도 지속. 금통위까지 신규 진입 보류 권고",
  
  "created_at": "2026-05-04T07:45:00+09:00"
}
```

**Overall 값 정의**:
| overall | 의미 | 봇 권장 행동 (참고용) |
|---|---|---|
| `🟢` | 정상 시장 | 정상 매수 |
| `🟡` | 관망 | 봇 자체 판단 |
| `🔴` | 위험회피 강화 | 신규 매수 정지 권고 |
| `🚨` | 비상 | 모든 진입 정지 권고 |

**봇이 사용하는 필드**:
- `overall` — 매수 시점 결정에 참고
- 단, **최종 결정은 봇 자체 룰** (위험 인지 로직 활용)

---

## 4. 봇 → 리서치 인터페이스

### 4.1 held_stocks (현재 보유 종목)

**경로**: `shared/from_bot/held_stocks/{stock_code}`

**갱신 주기**: 매수/매도 체결 시 실시간

**스키마**:
```json
{
  "code": "000660",
  "name": "SK하이닉스",
  
  "positions": {
    "first": {
      "filled": true,
      "price": 220500,
      "quantity": 50,
      "filled_at": "2026-05-04T09:00:32+09:00"
    },
    "second": {
      "filled": false,
      "target_price": 215000
    },
    "third": {
      "filled": false,
      "target_price": 208000
    }
  },
  
  "total_invested": 11025000,
  "total_quantity": 50,
  "avg_price": 220500,
  
  "first_bought_at": "2026-05-04T09:00:32+09:00",
  "days_held": 3,
  "status": "partial"
}
```

**Status 값 정의**:
| status | 의미 |
|---|---|
| `partial` | 분할 진입 진행 중 |
| `full` | 1·2·3차 모두 진입 |
| `closed` | 매도 완료 (이 경우 컬렉션에서 삭제) |

**리서치가 사용하는 필드**:
- 매도 시그널 발생 시 보유 여부 매칭
- 보유 종목의 CB·BW 행사기간 추적
- 보유 종목 잠정실적 D-day 모니터링
- 일요일 주간 리포트에 보유 종목 성과 포함

**유의:**
- 봇이 매도 완료 시 이 컬렉션에서 종목 **삭제**
- 그 전에 `from_bot/sell_history/`에 이력 저장

---

### 4.2 buy_history (매수 이력, 참조용)

**경로**: `shared/from_bot/buy_history/{YYYY-MM-DD}/{tx_id}`

**스키마**:
```json
{
  "tx_id": "buy_20260504_000660_1",
  "code": "000660",
  "tranche": "first",
  "price": 220500,
  "quantity": 50,
  "amount": 11025000,
  "filled_at": "2026-05-04T09:00:32+09:00",
  "research_signal_id": "20260504_000660"
}
```

**용도**: 리서치가 포워드 테스팅 시 실제 진입 시점/가격 활용.

---

### 4.3 sell_history (매도 이력, 참조용)

**경로**: `shared/from_bot/sell_history/{YYYY-MM-DD}/{tx_id}`

**스키마**:
```json
{
  "tx_id": "sell_20260615_000660",
  "code": "000660",
  "price": 253500,
  "quantity": 50,
  "amount": 12675000,
  "sold_at": "2026-06-15T14:23:11+09:00",
  
  "trigger": "TARGET_HIT",
  "buy_avg_price": 220500,
  "pnl": 1650000,
  "pnl_pct": 14.97,
  "days_held": 42,
  
  "research_signal_id": null
}
```

**Trigger 값 정의**:
| trigger | 의미 |
|---|---|
| `TARGET_HIT` | 목표가 도달 (봇 자체 룰) |
| `STOP_LOSS` | 손절선 도달 (봇 자체 룰) |
| `TRAILING_STOP` | 트레일링 스톱 (봇 자체 룰) |
| `RESEARCH_SIGNAL` | 리서치 sell_signal 응답 |
| `TIME_EXPIRED` | 보유 기간 만료 (봇 자체 룰) |
| `MANUAL` | 본인 수동 매도 |

**용도**: 리서치 시스템 검증·통계.

---

## 5. 시간축 — 누가 언제 무엇을

```
[매일 KST]

07:00  GitHub Actions: 데이터 수집 (텔레그램·DART·KIS·KRX)
07:30  Claude.ai 루틴: 매크로 브리핑 카톡
07:45  GitHub Actions: 시그널 갱신
       → shared/to_bot/buy_signals/{today} 저장
       → shared/to_bot/blacklist/active 갱신
       → shared/to_bot/macro_status/{today} 저장

08:50  봇: 매수 대상 결정 (자체 룰)
       - shared/to_bot/buy_signals 읽기
       - shared/to_bot/macro_status 참조
       - shared/to_bot/blacklist 검증

09:00  봇: 1차 시초가 진입 (자체 분할 룰)
       - 체결 시 shared/from_bot/held_stocks 갱신
       - shared/from_bot/buy_history 추가

장중   봇: 자체 모니터링
       - 10일선·15일선 도달 시 2·3차 진입
       - 손절·익절·트레일링 (자체 룰)
       - 위험 인지 (초방어전략)
       - shared/to_bot/sell_signals 새로 추가됐는지 폴링

15:30  장 마감

16:00  Claude.ai 루틴: 일일 보고 카톡 (보유 종목 + 매매 이력)

[일요일]
21:00  Claude.ai 루틴: 주간 종목 리포트 카톡
22:00  Claude.ai 루틴: 주간 성과 카톡

[월 1일]
09:00  Claude.ai 루틴: 월간 화이트리스트 + 백테스트
```

---

## 6. 폴링 vs 이벤트

본 인터페이스는 **폴링 기반**입니다. 봇이 정해진 시점에 Firestore를 읽음.

**왜 폴링인가**:
- Firestore Listener 사용 시 24/7 연결 필요 → EC2 부담
- 매수/매도 결정은 분 단위 정밀도면 충분 (스윙 매매)

**봇 폴링 주기 권장**:
- `buy_signals`: 09:00 1회 + 13:00 1회 (이평선 변화 반영)
- `sell_signals`: 5분 간격 (장중)
- `blacklist`: 09:00, 13:00, 15:00
- `macro_status`: 09:00 1회

**예외 — 실시간 푸시가 필요할 때**:
- 매도 시그널 URGENT급은 Firestore Cloud Function으로 봇에 텔레그램 알림 전송 (옵션)

---

## 7. 봇 측 구현 가이드 (참조)

> 이 섹션은 TradeBot 측 수정 시 참고용. 본 repo와 무관.

### 7.1 신규 모듈 (TradeBot에 추가)

```
tradebot/
  └─ swing/                          # 신규 폴더
      ├─ __init__.py
      ├─ research_reader.py          # shared/to_bot/* 읽기
      ├─ buy_strategy.py             # 분할 진입 룰
      ├─ sell_strategy.py            # 매도 룰 (자체 + 시그널)
      ├─ position_reporter.py        # shared/from_bot/* 쓰기
      └─ swing_runner.py             # 메인 루프
```

### 7.2 기존 모듈 활용

- KIS API 토큰 → 기존 재활용
- 위험 인지 → 기존 초방어전략 재활용
- Firestore 클라이언트 → 신규 추가 (TradeBot이 Firebase 사용 ❌이면)

### 7.3 충돌 방지

- 데이트레이딩 종목 풀 vs 스윙 종목 풀 **완전 분리**
- 자금 분리: 데이트레이딩 70%, 스윙 30%
- 동시 호출 방지: 시간대 분리
  - 데이트레이딩: 09:00~15:30
  - 스윙: 09:00 시초가 매수만 + 장중 모니터링은 가벼움

---

## 8. 보안

- **Firestore Service Account 분리**:
  - `research_sa` (research repo의 GitHub Actions에서 사용)
  - `bot_sa` (TradeBot EC2에서 사용)
- 각 SA는 자신이 쓸 컬렉션에만 권한
- 두 시스템 모두 SA 키를 암호화된 환경변수에 저장

---

## 9. 버저닝

- 이 인터페이스 변경 시 **하위호환** 필수
- Breaking change는 신규 컬렉션(`shared/to_bot_v2/`)으로 분리 후 점진 마이그레이션
- 변경 시 본 문서 + DESIGN.md 17장 동시 갱신

---

**문서 끝.** 봇 측 수정은 본인이 별도 진행. 본 문서를 봇 측 작업 시 참고.
