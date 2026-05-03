# SWING_RESEARCH_DATA_REQUIREMENTS — 리서치 → 봇 데이터 요구사항

> 본 문서는 **리서치 시스템 (`wonwoo-research`)** 이 봇에 보내야 할 데이터의
> 분석용 sub-field 요구사항.
> 인터페이스 schema 자체는 `docs/INTEGRATION.md` 의 spec 그대로.
> 본 doc 은 **분석 박제 (paper_trades_swing.csv) 에 필요한 sub-field**를 명세.
>
> 리서치 측이 이 필드를 빠뜨리면 봇이 받아서 박제할 수 없고 분석 가치 ↓.
>
> 작성: 2026-05-03 (브랜치 claude/new-shared-harness-BLB3f).

---

## 1. 왜 이 필드가 필요한가

봇은 받은 시그널로 paper 진입 → 청산까지 모든 step 의 **메타 데이터를
paper_trades_swing.csv 에 박제**. 이 csv 가 1개월 후 분석 시 다음 질문에 답:

- 어떤 nine_filter 조합이 승률 높은가?
- positive_signals 의 type (NPS_NEW / ANALYST_TARGET_UP 등) 별 효과?
- block_reasons 의 type 별 손익 분포?
- macro 환경 (overall / 외인 순매수) 별 진입 효과?
- sell_signal trigger type (DISCLOSURE/CB/EARNING/ANALYST) 별 매도 결과?

→ **데이터 없으면 분석 0**. 리서치 측이 이 필드를 spec 그대로 채워야 함.

---

## 2. buy_signals/{date}/{code}.json — 필수 sub-field

INTEGRATION.md §3.1 spec 그대로. 다음 필드는 **분석용 의무**:

```json
{
  "code": "000660",
  "name": "SK하이닉스",
  "signal": "STRONG_BUY",          // STRONG_BUY/BUY/HOLD/AVOID
  "score": 92,                       // 0~100

  "nine_filter": {                   // ★ 9 sub-field 모두 의무
    "financial_trend":    "🟢",      // 🟢/🟡/🔴
    "quant_health":       "🟢",
    "margin_diagnosis":   "🟢",
    "moat":               "🟢",
    "flow":               "🟢",
    "credit_short":       "🟢",
    "nps":                "🟢",
    "technical":          "🟢",
    "report":             "⭐"        // 🟢/🟡/🔴/⭐ (코어 애널 매수)
  },

  "positive_signals": [              // ★ list — 가산점 source 분석
    {"type": "NPS_NEW", "score": 15},
    {"type": "ANALYST_TARGET_UP", "score": 10}
  ],

  "negative_signals": [              // ★ list — 감점 source
    {"type": "INSIDER_SELL_SMALL", "score": -5}
  ],

  "blocked": false,                  // bool
  "block_reasons": [                 // ★ blocked=true 시 list (paper 도 진입)
    {
      "type": "EARNING_NEAR",        // 16개 type (INTEGRATION.md §3.3)
      "detected_at": "2026-05-04",
      "expires_at": "2026-05-10",
      "severity": "URGENT"
    }
  ],

  "moving_averages": {               // ★ 분할 진입 ma10/ma15
    "ma10": 215000,
    "ma15": 208000
  },

  "valid_until": "2026-05-09",       // ISO date — 만료 시 자체 룰만
  "created_at": "2026-05-04T07:45:00+09:00"
}
```

### 분석에 사용되는 sub-field 박제 (봇 측)

| 박제 컬럼 | source | 분석 가치 |
|---|---|---|
| `nine_filter_financial_trend` ~ `nine_filter_report` (9 컬럼) | nine_filter.* | 필터 조합 별 승률 |
| `positive_signals_count` | positive_signals.length | 가산 source 수 |
| `positive_signals_total_score` | sum(positive_signals[].score) | 가산 총점 |
| `positive_signals_types` | comma-join (type) | type 별 효과 |
| `negative_signals_count` | negative_signals.length | 감점 source 수 |
| `block_reasons_count` | block_reasons.length | 차단 사유 수 |
| `block_reasons_first_type` | block_reasons[0].type | blocked=true 시 첫 type 분포 |

---

## 3. sell_signals/{signal_id}.json — 필수 sub-field

INTEGRATION.md §3.2 그대로. 분석 박제용 의무 필드:

```json
{
  "signal_id": "20260504_035720_001",
  "code": "035720",
  "severity": "URGENT",              // ★ URGENT/REVIEW/MONITOR

  "trigger": {                       // ★ 매도 trigger 분류
    "type": "DISCLOSURE",            // DISCLOSURE/CB_EXERCISE/EARNING/NEWS/ANALYST
    "subtype": "전환사채권발행결정",   // 세부 분류 (옵션)
    "details": "300억, 행사 2026-08-01부터"
  },

  "action_recommendation": "전량 시초가 매도",
  "reason_short": "CB 발행",
  "expires_at": "2026-05-05T15:30:00+09:00",
  "created_at": "...",
  "consumed": false
}
```

### 박제 컬럼

| 컬럼 | source |
|---|---|
| `exit_signal_severity` | severity |
| `exit_signal_trigger_type` | trigger.type |
| `exit_signal_subtype` | trigger.subtype |
| `exit_signal_reason` | reason_short |

---

## 4. blacklist_active.json — 필수 sub-field

INTEGRATION.md §3.3 그대로. 분석 박제 (paper 진입 시 blacklist 매칭 분석):

```json
{
  "blacklist": [
    {
      "code": "047810",
      "name": "한국항공우주",
      "blocked_until": "2026-07-14",
      "block_reasons": [               // ★ list
        {
          "type": "MAJOR_SHAREHOLDER_SELL",
          "detected_at": "2026-04-15",
          "severity": "URGENT",
          "description": "최대주주 5.2% 매도"
        }
      ]
    }
  ]
}
```

### 박제 (paper 진입 종목이 blacklist 와 매칭됐을 때)
| 컬럼 | source |
|---|---|
| `entry_blacklist_tagged` | bool — paper 시점 blacklist 매칭 |
| `entry_blacklist_first_type` | block_reasons[0].type |

---

## 5. macro_status/{date}.json — 필수 sub-field

INTEGRATION.md §3.4 그대로:

```json
{
  "date": "2026-05-04",
  "overall": "🟡",                   // ★ 🟢/🟡/🔴/🚨

  "indicators": {                    // ★ 분석 박제용
    "kospi_change":      -0.42,
    "kosdaq_change":     -0.81,
    "sp500_change":       0.31,
    "usd_krw":          1394,
    "us_10y_yield":       4.51,
    "foreign_kospi_net": -284000000000   // ★ 외인 순매수 (원)
  },

  "events_today": [                  // 옵션
    {"time": "14:00", "type": "BOK_RATE", "expected": "동결"}
  ],

  "claude_opinion_short": "환율 1400 임박 + 외인 매도 지속",
  "created_at": "..."
}
```

### 박제
| 컬럼 | source |
|---|---|
| `entry_macro_overall` | overall |
| `entry_macro_kospi_change` | indicators.kospi_change |
| `entry_macro_foreign_net` | indicators.foreign_kospi_net |

청산 시점 (exit) 도 같은 필드 박제 — entry vs exit 비교 분석.

---

## 6. 빠뜨리면 안 되는 이유 (정량)

| 빠뜨린 필드 | 분석 손실 |
|---|---|
| `nine_filter` 9 sub-field | "어떤 필터 조합이 승률 ↑" 분석 불가 → 룰 개선 근거 0 |
| `positive_signals[].type` | 가산 source 별 ROI 분석 불가 → 시그널 정밀화 0 |
| `block_reasons[].type` | blocked=true 종목의 차단 사유 별 손익 분포 불가 → 차단 정책 검증 0 |
| `trigger.type` (sell_signal) | URGENT 매도의 trigger 별 분포 (CB vs EARNING vs ANALYST) 분석 불가 |
| `indicators.foreign_kospi_net` | 외인 매수/매도 환경 별 진입 승률 분석 불가 |
| `moving_averages.ma10/ma15` | 분할 진입 트리거 자체 작동 X (필수) |

---

## 7. 리서치 측 → 봇 데이터 검증 (자동)

봇 측 `swing/research_reader._validate_*` 가 schema validate:
- buy_signal: `code/name/signal/score/valid_until` 필수
- sell_signal: `signal_id/code/severity/trigger/expires_at` 필수
- blacklist: `code/blocked_until` 필수
- macro: `date/overall` 필수

위 nine_filter / positive_signals / block_reasons / indicators sub-field 는
**현재 검증 안 함 (옵션)** — 리서치가 보내면 박제, 안 보내면 빈 값. 다만
분석 가치 ↓.

→ **리서치 측은 INTEGRATION.md spec 의 모든 sub-field 채워야 함**.

---

## 8. 운영 절차

1. 리서치 GitHub Actions `daily.yml` 매일 07:45:
   - DART/KIS/KRX/텔레그램 데이터 수집
   - 9중 필터 분석
   - **buy_signals/{date}/{code}.json 작성 — 본 doc 의 모든 sub-field 채움**
   - blacklist_active.json / macro_status/{date}.json 갱신
   - HMAC sig 동봉 (RESEARCH_HMAC_KEY)
   - SSH push to bot EC2 `data/research/`

2. 봇 측 매일 08:50:
   - swing_dry_run → research_reader read → paper_executor 진입
   - 모든 sub-field 박제 → paper_trades_swing.csv

3. 1주~ 후 `tools/swing_simulator.py --mode offline` 분석:
   - nine_filter 조합 별 승률
   - sell_signal trigger 별 결과
   - macro 환경 별 진입 효과
   - 모든 셀 분석

---

## 9. 사용자 → 리서치 repo 측에 공유

본 doc 을 리서치 repo (`wonwoo-research`) 의 `docs/BOT_DATA_SPEC.md` 같은
파일로 옮겨서 Claude Code 가 spec 따라 buy_signals 작성하게 함.

또는 본 doc 그대로 link 만 공유 — INTEGRATION.md spec 이미 충실하므로 본 doc
은 "어떤 sub-field 가 분석에 필수인지" 강조하는 보조 문서.

---

**문서 끝.**
