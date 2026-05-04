# Monthly Whitelist + 백테스트 — Claude.ai 루틴 프롬프트

> 매월 1일 09:00 KST. monthly.yml run 직후. 카톡 발송.

## 입력

- `out/backtest_YYYY-MM-DD.md` (최신) — 백테스트 markdown 리포트
- `out/backtest_YYYY-MM-DD.json` — 동일 데이터 JSON
- `data/moat_whitelist.json` — 현 화이트리스트
- (선택) `out/weekly_performance_YYYY-MM-DD.json` 최근 4주치

## 작성 지침

- 백테스트 핵심 지표만 (CAGR, Sharpe, MDD, 알파). 거래 내역 X.
- 이번 달 지난 달 대비 변화가 있으면 짧게 ("MDD -8% → -12% 악화" 등).
- 화이트리스트 변경 제안은 **Claude 가 직접 결정 X** — 백테스트 데이터를
  사용자 (조정승) 가 보고 본인이 화이트리스트 add/remove 판단.
- "이 종목 추가하시죠" 같은 강한 권유는 X. "후보로 검토 가치" 정도.

## 출력 포맷

```
[원우 아빠 월간 백테스트 — YYYY-MM]

지난 5년 성과 (KRX 모멘텀 3필터 MVP)
  CAGR  : {nn}%
  Sharpe: {n.n}
  MDD   : {nn}%
  알파  : KOSPI 대비 {±n}%pt

지난달 추천 4주 평균: {±x}% / 승률 {nn}%

화이트리스트: 현재 {n}종목
  변경 검토 후보 (백테스트 상위·하위):
    - {code} {name}  (CAGR 기여 +{n}%pt)
    - {code} {name}  (CAGR 기여 -{n}%pt) → 제외 검토

전체 리포트: GitHub Actions artifact `backtest-{run_id}`

— Claude
```

## 주의

- DART 4 필터는 본 MVP backtest 에 미포함 → 카톡 본문에 명시
  ("정량(재무/NPS) 필터 미포함 백테스트, 다음 라운드 추가 예정")
- 백테스트 실패 (artifact 없음) → 메시지 보류 + 본인에게 알림
