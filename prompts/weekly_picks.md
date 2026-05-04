# Weekly Picks — Claude.ai 루틴 프롬프트

> 매주 일요일 21:00 KST. weekly.yml run 직후. 카톡 발송.

## 입력

repo `newwonwoo/stock` 최신 `out/` artifact (또는 `data/recommendations/{YYYY-MM-DD}.json`):
- `weekly_picks_{YYYY-MM-DD}.json` — top 5 picks
- `weekly_performance_{YYYY-MM-DD}.json` — 4주 전 추천 실측 (있으면)
- `hot_sectors_{YYYY-MM-DD}.json`

## 작성 지침

- 5종목 모두 노출. 종목명 + 점수 + 사유 1줄.
- 나인 필터 9개 중 🟢/⭐ 카운트만 표시 (예: "필터 7/9").
- ma10/ma15 가 있으면 진입 가격 가이드로 1줄 (예: "1차 시초가, 2차 ma10 215,000").
- 4주 전 추천이 있으면 평균 수익률·승률 짧게 (1줄).
- 종목별 한 줄 사유는 positive_signals 의 type 을 자연어로 풀어서
  ("국민연금 신규 매수 + 애널 목표가 상향").
- 핵심: **매도 권유 X**, **수량 추천 X**. 정보 제공.

## 출력 포맷

```
[원우 아빠 주간 추천 — YYYY-MM-DD]

이번 주 5종목

1. {종목명} ({code})  점수 {nn}  필터 {n}/9
   사유: {reason}
   진입 가이드: 1차 시초가 / 2차 ma10 {price:,} / 3차 ma15 {price:,}

(2~5 동일 포맷)

지난 4주 추천 성과:
  평균 수익률 {±xx}% / 승률 {nn}% (n={count})

🔥 이번 주 핫섹터: {sector1}, {sector2}

— Claude
```
