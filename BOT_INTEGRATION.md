# 카톡 알림 ↔ EC2 봇 상호 연계 명세서

**작성:** 2026-05-05 Cowork 세션
**대상:** EC2 봇 개발자 / 시스템 연계자
**범위:** GitHub Actions 의 카톡 자기톡 발송 흐름과 EC2 봇이 받는 데이터 사이의 schema·계약·재사용 패턴 정리.

## 1. 큰 그림 — 두 흐름이 평행

```
                  ┌─────────────────────┐
                  │  GitHub Actions     │
                  │  (server-side cron) │
                  └─────────┬───────────┘
                            │
        ┌───────────────────┴───────────────────┐
        │                                       │
        ▼ (1) SCP signed JSONs                  ▼ (2) Kakao memo/default/send
   ┌──────────┐                          ┌──────────────┐
   │ EC2 BOT  │                          │ 사용자 카톡   │
   │ /home/.. │                          │ 나와의 채팅  │
   │ /research│                          └──────────────┘
   └──────────┘
   (자체 분석 + 봇 자체 알림 가능)
```

**(1)** 은 기존부터 있던 흐름 — 손 안 댐. 4개 envelope JSON 이 봇으로 SSH push.
**(2)** 는 이번 세션에서 추가 — `scripts/kakao_send.py` 가 같은 산출물을 한국어 메시지로 만들어 사용자 카톡으로 발송.

두 흐름의 **데이터 소스가 동일**하기 때문에, 봇이 처리하는 종목과 사용자가 카톡으로 보는 종목이 일치합니다 (HMAC 서명까지 동일).

## 2. 입력 산출물 schema (봇·카톡 공용)

### 2.1 `buy_signals_{YYYY-MM-DD}.json` (envelope)
```json
{
  "signed_by": "research_v1",
  "sha256_hmac": "...",
  "data": {
    "signals": [
      {
        "code": "005930",
        "name": "삼성전자",
        "signal": "STRONG_BUY|BUY|HOLD|AVOID",
        "score": 94,
        "nine_filter": {
          "financial_trend": "GREEN", "quant_health": "YELLOW",
          "margin_diagnosis": "YELLOW", "moat": "GREEN",
          "flow": "STAR", "credit_short": "GREEN",
          "nps": "STAR", "technical": "GREEN", "report": "STAR"
        },
        "positive_signals": [
          {"type": "NPS_NEW", "score": 15},
          {"type": "STRONG_FLOW", "score": 8},
          {"type": "ANALYST_TARGET_UP", "score": 10}
        ],
        "negative_signals": [
          {"type": "SHORT_TOP10", "score": -20}
        ],
        "blocked": false,
        "block_reasons": [],
        "moving_averages": {"ma10": 62500, "ma15": 61000},
        "valid_until": "2026-05-12",
        "created_at": "2026-05-05T07:00:00+09:00"
      }
    ]
  }
}
```

**필드 정의:**

| 필드 | 의미 | 봇 사용 |
| --- | --- | --- |
| `signal` | 4단계 권고: STRONG_BUY / BUY / HOLD / AVOID | 자동매매 트리거 기준 |
| `score` | 0~100 가중평균 (9개 필터의 score × weight; report 가중 0.8, 나머지 1.0) | 종목 우선순위 정렬 |
| `nine_filter` | 9개 필터별 4단계 등급 (RED/YELLOW/GREEN/STAR). 단, 일부 출력엔 이모지 (🔴🟡🟢⭐) 로 들어올 수 있음 — 봇은 둘 다 처리 권장 | 위험 점검 |
| `positive_signals[]` | type+score (가중치). 같은 종목에 여러 개 가능 | 추가 상승 모멘텀 신호 |
| `negative_signals[]` | type+score (음수). 보유 시 주의 | 매도/회피 시그널 |
| `blocked` | true 면 즉시 매수 금지 | 자동매매 차단 조건 |
| `moving_averages.ma10/ma15` | 최근 종가 기준 이동평균. 진입 가이드 | 손절·익절 기준선 |

### 2.2 `positive_signals[].type` 종류
| type | 의미 | 점수 |
| --- | --- | --- |
| `NPS_NEW` | 국민연금 신규 편입 (이번 분기 처음 등장) | +15 |
| `NPS_ADD` | 국민연금 보유 비중 0.5%p 이상 확대 | +15 |
| `ANALYST_TARGET_UP` | 4주 내 코어 애널 리포트 STAR 등급 (목표가↑·매수의견) | +10 |
| `STRONG_FLOW` | 외인+기관 동반 매수 비율 ≥ 70% | +8 |

### 2.3 `negative_signals[].type` 종류
| type | 의미 | 점수 |
| --- | --- | --- |
| `NPS_REDUCE` | 국민연금 축소대폭/전량매도 | -10 |
| `SHORT_TOP10` | KOSPI/KOSDAQ 공매도 거래대금 Top10 | -20 (즉시 RED 등급) |

### 2.4 9 필터 한국어 매핑 (봇 자체 알림에 사용 권장)
| key | 한국어 | 분석 기준 |
| --- | --- | --- |
| `financial_trend` | 재무 추세 | 분기 매출/영익 4분기 추이 |
| `quant_health` | 정량 건전성 | DSO/OCF·영익/부채/수주잔고 |
| `margin_diagnosis` | 신용 진단 | (코드 미확인) |
| `moat` | 해자 | 5년 ROE 안정성+EPS 성장+화이트리스트 |
| `flow` | 수급 | 외인+기관 동반매수 일수 |
| `credit_short` | 신용·공매도 | 신용비율+공매도 Top10 |
| `nps` | 국민연금 | 분기 변동 (신규/확대/축소/매도) |
| `technical` | 기술적 | (코드 미확인) |
| `report` | 리포트 모멘텀 | 4주 내 코어 애널 매수의견 카운트 |

### 2.5 `weekly_picks_{date}.json` (envelope 없음, plain JSON)
```json
{
  "date": "2026-05-03",
  "entry_reference_date": "2026-05-04",
  "picks_count": 5,
  "picks": [
    {
      "code": "...", "name": "...", "signal": "STRONG_BUY",
      "score": 94, "nine_filter": {...}, "moving_averages": {...},
      "reason_short": "NPS_NEW, STRONG_FLOW · 필터 7/9 통과",
      "entry_date": "2026-05-04",
      "entry_close": 62500
    }
  ],
  "created_at": "..."
}
```

**주의:** picks 안에는 `positive_signals`/`negative_signals` 가 없습니다 (`reason_short` 로 압축). 봇이 사유 풀어 보고 싶으면 같은 날짜의 `buy_signals_*.json` 을 매칭해서 가져와야 함.

### 2.6 `backtest_{date}.json` (envelope 없음)
schema 는 `src/backtest/report.py write()` 의 출력. 핵심:
- `config`: lookback_years, universe_top_n, max_holdings, fee_bps, slippage_bps
- `metrics`: cagr_pct, sharpe, mdd_pct, alpha_vs_benchmark_pct, total_return_pct, win_rate_pct, avg_trade_pct, trade_count
- `benchmark_total_return_pct`: KOSPI 등 비교지수 5년 누적
- `trades[]`: {code, name, entry_date, exit_date, entry_price, exit_price, return_pct, days_held}
- `monthly_picks[]`: 월별 선정 종목

## 3. 카톡 발송 패턴 (봇이 같은 카톡으로 자체 알림 보낼 때 재사용)

`scripts/kakao_send.py` 의 `refresh_access_token()` + `send_to_self()` 두 함수 패턴이 가장 작은 단위입니다. EC2 봇에서 자동매매 체결·손익 등 자체 알림을 보내고 싶으면 동일 패턴 + 동일 Secrets 를 환경변수로 주입하면 됩니다.

```python
# 토큰 갱신
POST https://kauth.kakao.com/oauth/token
  Content-Type: application/x-www-form-urlencoded
  body: grant_type=refresh_token
        client_id={KAKAO_REST_API_KEY}
        client_secret={KAKAO_CLIENT_SECRET}   # 본 앱은 Client Secret ON
        refresh_token={KAKAO_REFRESH_TOKEN}
→ {"access_token": "...", "refresh_token": "...", ...}

# 자기톡 발송
POST https://kapi.kakao.com/v2/api/talk/memo/default/send
  Authorization: Bearer {access_token}
  Content-Type: application/x-www-form-urlencoded
  body: template_object={"object_type":"text",
                          "text":"{본문, 800자 이내}",
                          "link":{"web_url":"https://github.com/newwonwoo/stock/actions",
                                  "mobile_web_url":"..."},
                          "button_title":"리포트"}
→ {"result_code":0}
```

**Client Secret 주의:** 이 앱은 Client Secret 활성화 ON. 토큰 요청에 client_secret 누락 시 KOE010 오류.

**문자 한계:** template_object.text 약 800자. `kakao_send.py` 는 800자 초과 시 자동 절단.

## 4. Kakao Secrets (GitHub Repo)

repo `Settings → Secrets and variables → Actions` 에 등록됨:
- `KAKAO_REST_API_KEY` — Kakao Developers 앱의 stockresearch 키 (NOT Default Rest API Key)
- `KAKAO_REFRESH_TOKEN` — talk_message scope refresh_token (60일 수명)
- `KAKAO_CLIENT_SECRET` — Client Secret 코드 (Kakao Developers 앱 → 플랫폼 키 → 키별 페이지)

EC2 봇이 같은 카톡으로 발송하려면 위 3개를 봇 측 환경변수로도 노출 필요.

## 5. refresh_token 회전 정책

Kakao 가 refresh_token 만료 임박 (60일 수명, 1개월 이내) 시 응답에 새 refresh_token 포함. `kakao_send.py` 는 이를 감지하고 GitHub Step Summary 에 경고 출력 (앞 12자만 노출, 보안). 사용자가 GitHub Secret 을 새 값으로 교체.

EC2 봇도 동일 패턴 권장: `refresh_token` 회전 시 영구 저장소를 갱신.

## 6. 카톡 메시지 형식 (사용자가 받는 모양)

`scripts/kakao_send.py` 의 `daily_message()`/`weekly_message()`/`monthly_message()` 가 한국어 메시지 빌드. 핵심 섹션:

**daily 메시지:**
```
[원우 아빠 매크로 — YYYY-MM-DD]
🟢 외국인 순매수 + KOSPI 강보합
📊 KOSPI +0.84% / 외인 +1234억 / USDKRW 1382
🔥 핫섹터: 반도체, 2차전지

🤖 봇 시그널:
  005930 STRONG_BUY / 373220 STRONG_BUY

💡 매수 추천 사유:
1. 삼성전자 (005930) 94점
   👍 연금 신규편입(+15), 외인+기관 매수(+8), 리포트 목표가↑(+10)
2. LG에너지솔루션 (373220) 91점
   👍 연금 확대(+15)
   👎 공매도 Top10(-20)

🚫 차단:
- 가나전자 (123456): 감사의견 거절

— Claude
```

**weekly 메시지:** 종목 TOP 3, 9 필터 sparkline (`✓재무 △정량 ⭐연금 ...`), 진입가 (ma10/ma15), 4주 성과.
**monthly 메시지:** 5년 백테스트 메트릭 (CAGR/Sharpe/MDD/알파), 거래 통계 (승률/평균수익), TOP 3 수익 거래, 이번 달 추천.

봇이 자체 알림을 보낼 때 톤·길이·이모지 통일 권장 (사용자 가독성).

## 7. 봇 측 권장 구현 (선택)

체결 알림 / 손익 보고를 같은 카톡으로 받고 싶으면:

```python
# 봇 측 cron 예시
def send_trade_notification(trade):
    text = f"""[봇 체결 — {trade.timestamp:%Y-%m-%d %H:%M}]
{trade.action} {trade.name} ({trade.code})
  체결가: {trade.price:,}원
  수량: {trade.qty}주
  실현손익: {trade.pnl:+.1f}%

— Bot"""
    access = refresh_access_token(REST, RT, CS)
    send_to_self(access, text)
```

또는 봇이 별도 카톡 봇/메신저 채널을 쓰고 카톡 발송은 GitHub Actions 흐름에만 맡기는 분리 정책도 가능.

## 8. 변경 이력

- 2026-05-05 — 초기 작성 (kakao_send.py + GitHub Actions step 3개 추가). Cowork 세션 결과.
