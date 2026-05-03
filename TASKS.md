# 구현 작업 체크리스트

> 의존성 순서로 정렬됨. 위에서부터 순서대로 진행.
> 각 작업 완료 시 `[ ]` → `[x]` 갱신 + 자체 검증 5단계 수행.
> 검증 실패 시 다음 작업으로 넘어가지 말 것.

---

## Phase 0: 사용자 사전 작업 (Claude Code가 시작 전 확인)

> Claude Code는 이 단계가 완료되었는지 사용자에게 확인 후 시작.

- [ ] 0-1. **DART API 키 발급** — opendart.fss.or.kr (5분)
- [ ] 0-2. **텔레그램 API ID/Hash 발급** — my.telegram.org (5분)
- [ ] 0-3. **KIS API 키 확인** — TradeBot에서 재활용 (이미 있음)
- [ ] 0-4. **Firebase 프로젝트 준비** — FocusKit 재활용 또는 신규
- [ ] 0-5. **Firebase Service Account JSON 다운로드** — base64로 인코딩
- [ ] 0-6. **GitHub repo 생성** — 이름: `wonwoo-research` (private 권장)
- [ ] 0-7. **GitHub Secrets에 8개 키 등록** — `SECRETS.md` 참조

**확인 방법**: 사용자에게 "Phase 0 완료됐나요?"라고 물어보고 진행.

---

## Phase 1: 프로젝트 초기 셋업 (난이도: 쉬움)

- [ ] 1-1. `requirements.txt` 작성
  - 의존성: telethon, google-cloud-firestore, requests, pandas, pykrx, pydantic, python-dotenv, openpyxl, reportlab
  - 검증: `pip install -r requirements.txt` 로컬 테스트

- [ ] 1-2. `.gitignore` 작성
  - 제외: `*.session`, `*.json` (인증 파일), `__pycache__/`, `.env`, `*.log`, `.venv/`

- [ ] 1-3. 디렉토리 구조 생성 (DESIGN.md 3장 그대로)
  - `src/`, `src/collectors/`, `src/analyzers/`, `src/storage/`, `src/backtest/`, `src/utils/`
  - `prompts/`, `data/`, `tests/`, `.github/workflows/`

- [ ] 1-4. `src/config.py` 작성
  - 환경변수 로딩
  - 상수 (시총 하한 5천억, 코어 채널 목록 경로 등)
  - 검증: `python -c "from src.config import *; print(MARKET_CAP_MIN)"`

- [ ] 1-5. `src/utils/logger.py` 작성
  - JSON 로그 포맷 + 키 마스킹 필터
  - 검증: 의도적으로 로그에 "DART_API_KEY=abc123" 출력 → 마스킹 확인

- [ ] 1-6. `src/utils/kst_time.py` 작성
  - UTC ↔ KST 변환 헬퍼
  - 영업일 계산 (휴장일 제외)
  - 검증: 2026-05-04 공휴일 확인 함수 호출

- [ ] 1-7. `data/telegram_channels.json` 작성
  ```json
  {
    "channels": [
      {"username": "butler_works", "type": "broker_summary"},
      {"username": "...", "type": "core_analyst", "name": "김선우(메리츠)"}
    ]
  }
  ```
  실제 채널 목록은 사용자와 확인 필요.

- [ ] 1-8. `data/core_analysts.json` 작성
  - 매경/한경/FnGuide 베스트 애널리스트 명단
  - 텔레그램 채널 운영자만 필터링

---

## Phase 2: 데이터 저장 계층 (난이도: 보통)

- [ ] 2-1. `src/storage/firestore_client.py` 작성
  - DESIGN.md 5.6절 메소드 모두 구현
  - 인증: base64 → JSON 디코딩 후 임시 파일 생성
  - 검증: `save_market` 후 `get_market` → 동일 데이터 확인

- [ ] 2-2. `tests/test_firestore_client.py`
  - mock Firestore 사용 (firebase-admin emulator 또는 unittest.mock)
  - 모든 메소드 단위 테스트
  - 검증: `pytest tests/test_firestore_client.py` 전체 pass

---

## Phase 3: 데이터 수집기 (난이도: 보통~어려움)

### 3A. 텔레그램 listener

- [ ] 3-1. `src/utils/parser.py` — 채널별 파서
  - `parse_butler(text)`: 정규식으로 종목코드/작성자/투자의견/목표가 추출
  - `parse_core_analyst(text)`: 자유 포맷에서 종목 코드 + 키워드 매칭
  - `parse_fallback(text)`: 메타데이터만 추출
  - 검증: tests/에 실제 메시지 샘플 5개 → 정확성 95%↑

- [ ] 3-2. `src/collectors/telegram_listener.py`
  - Telethon 비대화식 모드 (Session 문자열 사용)
  - 각 채널의 last_processed_id 이후 메시지만 fetch
  - 파서 호출 → Firestore 저장
  - 중복 방지: message_uid = f"{channel}_{message_id}"
  - 검증: 단일 채널(@butler_works) 24시간 분량 fetch → Firestore 확인

- [ ] 3-3. **Session 문자열 최초 발급 스크립트** — `scripts/init_telegram_session.py`
  - 1회만 사용. 사용자가 PC에서 실행.
  - 폰으로 인증 코드 받아 입력
  - StringSession 출력 → 사용자가 GitHub Secrets에 등록

### 3B. DART fetcher

- [ ] 3-4. `src/collectors/dart_fetcher.py`
  - `fetch_corp_codes()`: 월 1회. 종목코드↔DART고유번호 매핑
  - `fetch_quarterly_financials(stock_code)`: 분기 재무 (5.2 모든 필드)
  - `fetch_daily_disclosures(date)`: 일별 공시 목록
  - `fetch_major_stock_changes()`: 5%↑ 보유 변동 (NPS 추적)
  - 호출 한도 모니터링 (일 10,000건)
  - 검증: 삼성전자(005930) 1Q 재무 → 공시 자료와 대조

- [ ] 3-5. `tests/test_dart_fetcher.py`
  - 실제 API 호출 (운영 키 사용)
  - 검증: 삼성전자 매출, SK하이닉스 OCF 정확성

### 3C. KIS fetcher

- [ ] 3-6. `src/collectors/kis_fetcher.py`
  - 토큰 발급/갱신 자동화 (24h 만료)
  - `fetch_daily_ohlcv(stock_code)`: 일봉
  - `fetch_investor_flow(stock_code)`: 외인/기관/개인 일별 순매수
  - `fetch_foreign_ownership(stock_code)`: 외인 보유율
  - `fetch_market_indices()`: KOSPI/KOSDAQ/KOSPI200
  - 분당 호출 제한 (sleep 적용)
  - 검증: TradeBot에서 사용 중인 토큰과 충돌 없는지 확인

### 3D. KRX fetcher

- [ ] 3-7. `src/collectors/krx_fetcher.py`
  - 우선 `pykrx` 라이브러리 사용
  - `fetch_credit_balance(date)`: 종목별 신용잔고
  - `fetch_short_top10(date)`: 공매도 거래대금 Top 10 (KOSPI/KOSDAQ)
  - `fetch_market_cap_filter(min_cap)`: 시총 5천억↑ 종목 리스트
  - 검증: 2026-05-01 데이터 vs 한국거래소 사이트 직접 비교

### 3E. 웹 뉴스 (보조)

- [ ] 3-8. `src/collectors/web_news.py`
  - web_search로 코어 애널리스트 이름 + 종목 검색 (보조)
  - 매일 5~10건 정도 수집
  - 텔레그램 listener의 보강용
  - 검증: 뉴스 인덱싱 후 코어 애널리스트 매칭 정확도

---

## Phase 4: 분석 모듈 (정량 계산만, LLM ❌)

> 이 모듈들은 입력 데이터 → 정량 점수 출력. Claude.ai 루틴이 점수를 받아 의사결정.

- [ ] 4-1. `src/analyzers/financial_trend.py` (필터 ①)
  - 입력: 4분기 재무 데이터
  - 출력: 매출 추세 (🟢🟡🔴), 영익 추세
  - 검증: 삼성전자 4Q 데이터 → 정상 분류

- [ ] 4-2. `src/analyzers/quant_health.py` (필터 ②)
  - DSO 계산, OCF/영익 비율, 부채비율, 수주잔고/매출
  - 출력: 각 항목 (🟢🟡🔴) + 종합
  - 검증: HD현대중공업(수주잔고 多) → 🟢

- [ ] 4-3. `src/analyzers/margin_diagnosis.py` (필터 ③)
  - DESIGN.md 6.3 알고리즘 그대로 구현
  - 5가지 분류 (정상/CAPEX형/R&D형/신사업/원가/경쟁)
  - 검증: 케이스별 mock 데이터 5개 → 정확 분류

- [ ] 4-4. `src/analyzers/moat_score.py` (필터 ④)
  - 워런 버핏 스타일 정량 점수 (ROE 5년 안정성 + EPS 성장)
  - 화이트리스트 멤버십 확인
  - 검증: 화이트리스트 in/out 정확성

- [ ] 4-5. `src/analyzers/flow_analysis.py` (필터 ⑤)
  - 외인+기관 동반 매수 일수
  - 외인 보유율 1M 변화
  - 섹터 자금 흐름
  - 검증: KIS 데이터 7일치 → 동반 매수 정확 카운트

- [ ] 4-6. `src/analyzers/credit_short.py` (필터 ⑥)
  - 신용비율, 대차잔고 변화
  - 공매도 Top 10 매칭 (자동 제외)
  - 검증: 공매도 Top 종목 강제 제외 확인

- [ ] 4-7. `src/analyzers/nps_tracker.py` (필터 ⑦)
  - 분기 변동: 신규/확대/축소/매도 분류
  - 검증: NPS 분기 공시 데이터로 검증

- [ ] 4-8. `src/analyzers/technical.py` (필터 ⑧)
  - 일봉 → 주봉 변환
  - 60주선, 주봉 RSI, 반등 거래량
  - 양봉 반전 패턴 감지
  - 검증: SK하이닉스 주봉 차트 → 시각 확인 (matplotlib 출력)

- [ ] 4-9. `src/analyzers/report_momentum.py` (필터 ⑨)
  - 4주 내 코어 애널 매수 의견 카운트
  - 목표가 상향/하향 추적
  - 매도 의견 = 자동 제외
  - 검증: 텔레그램 1주일 데이터 → 종목별 모멘텀 점수

- [ ] 4-10. `tests/test_filters.py` 통합
  - 9개 필터 각각 mock 데이터 5개씩
  - `pytest tests/test_filters.py` 전체 pass

---

## Phase 5: 백테스팅 모듈

- [ ] 5-1. `src/backtest/forward_tracker.py`
  - 매일 daily.yml에서 자동 실행
  - `recommendations/` 활성 종목들의 +1w/+4w/+6w/+8w/+12w 가격 갱신
  - KIS API에서 종가 fetch → `performance/` 갱신
  - 검증: 가상 추천 → 7일 후 +1w 자동 채워지는지 확인

- [ ] 5-2. `src/backtest/historical_runner.py` (1회 실시)
  - 5년 데이터 시뮬레이션
  - 정량 필터(④⑨ 제외)만 적용
  - 가상 매수/매도 → 누적 수익률, 샤프, MDD
  - PDF 리포트 생성 (reportlab)
  - 검증: 샘플 1년 → 결과 sanity check (KOSPI 대비 알파)

---

## Phase 6: GitHub Actions Workflow

- [ ] 6-1. `.github/workflows/daily.yml`
  - DESIGN.md 7.1 그대로
  - 모든 Secrets 참조
  - 검증: workflow_dispatch로 수동 실행 → 30분 내 정상 종료

- [ ] 6-2. `.github/workflows/weekly.yml`
  - 일요일 20:30 KST. 후보군 사전 계산
  - 검증: 수동 실행

- [ ] 6-3. `.github/workflows/monthly.yml`
  - 매월 1일. 화이트리스트 갱신 후보
  - 검증: 수동 실행

---

## Phase 7: Claude.ai 루틴용 프롬프트 작성

> 코드 ❌. 사용자가 Claude.ai 루틴에 등록할 마크다운 파일.

- [ ] 7-1. `prompts/daily_macro.md` 작성
  - 역할 설정 + 입력 위치 + 출력 포맷 + Claude 의견 작성 규칙
  - 9.1 산출물 샘플과 일치
  - 검증: 사용자가 Claude.ai에 붙여넣어 1회 테스트 → 카톡 도착 확인

- [ ] 7-2. `prompts/weekly_picks.md` 작성

- [ ] 7-3. `prompts/monthly_whitelist.md` 작성

---

## Phase 8: 통합 테스트 + 실 운영 시작

- [ ] 8-1. `tests/test_integration.py`
  - 전체 파이프라인 dry-run
  - GitHub Actions 환경 시뮬레이션
  - 검증: collector → Firestore → 분석기 → 출력 일관성

- [ ] 8-2. **시범 운영 1주일**
  - daily.yml 실 가동
  - 매일 카톡 수신 확인
  - 데이터 정확성 검증
  - 발견된 이슈 → TASKS.md에 추가

- [ ] 8-3. **시범 운영 2주차** — 주간 종목 리포트 첫 발송
  - 일요일 21:00 카톡 수신
  - 5종목 선정 결과 검증

- [ ] 8-4. **시범 운영 4주차** — 월간 화이트리스트 첫 발송 + 4주 전 추천 성과 첫 추적

---

## Phase 9: 자체 검증 + 품질확인서

- [ ] 9-1. `QUALITY_REPORT.md` 작성 — DESIGN.md 12.3 양식
- [ ] 9-2. 사용자(조정승) 최종 승인

---

## Phase 10: TradeBot 연계 (v1.0) — Phase 8 이후 진행

> 본 시스템이 안정 가동된 후(Phase 8 시범 운영 완료) 진행.
> TradeBot 측 수정은 사용자가 별도로 진행. 본 Phase는 **리서치 측 시그널 생산**만.

- [ ] 10-1. `shared/` Firestore 스키마 셋업
  - 컬렉션 생성: `to_bot/buy_signals`, `to_bot/sell_signals`, `to_bot/blacklist/active`, `to_bot/macro_status`
  - Firestore 보안 룰: `research_sa`만 쓰기, `bot_sa`는 읽기만
  - 검증: 보안 룰 시뮬레이터로 권한 매트릭스 검증

- [ ] 10-2. `src/analyzers/disclosure_classifier.py` — 22개 공시 분류
  - DESIGN.md 17.4·17.6 참조
  - 핵심 룰:
    - 제3자 유증 = 무조건 POSITIVE
    - CB·BW 발행 자체 = NEUTRAL (행사기간 추적만)
    - 대주주 매도·블록딜 = URGENT
    - 자사주 매입/소각 = POSITIVE
  - 검증: 22개 케이스 단위 테스트

- [ ] 10-3. `src/analyzers/cb_bw_tracker.py` — CB·BW 시간축 추적
  - DESIGN.md 17.7 참조
  - 매일 daily.yml에서 호출
  - D-30/D-7/D-0/전환신청 4단계 신호
  - 행사기간 중 전환가 프리미엄 체크
  - 검증: 가상 CB 데이터로 4단계 시그널 생성 확인

- [ ] 10-4. `src/analyzers/buy_blocker.py` — 매수 차단 검증
  - DESIGN.md 17.4 매트릭스 그대로 구현
  - `register_block()`, `is_blocked()`, `cleanup_expired()` 메소드
  - 검증: 시간 mock으로 만료 자동 해제 확인

- [ ] 10-5. `src/analyzers/buy_signal_generator.py` — 매수 시그널 생산
  - DESIGN.md 17.2·17.3 참조
  - 4단계 판정 (STRONG_BUY/BUY/HOLD/AVOID)
  - 가산점·감점 매트릭스 적용
  - 이동평균선 (10일·15일) 계산 포함
  - 검증: 가상 종목 5개 × 5케이스 = 25개 시나리오

- [ ] 10-6. `src/analyzers/sell_signal_generator.py` — 매도 시그널 생산
  - DESIGN.md 17.5 참조
  - 3등급 (URGENT/REVIEW/MONITOR)
  - 트리거 타입 5종 (DISCLOSURE/CB_EXERCISE/EARNING/NEWS/ANALYST)
  - 검증: 보유 종목 mock + 공시 발생 시뮬레이션

- [ ] 10-7. GitHub Actions daily.yml에 통합
  - 07:45 시그널 생성 단계 추가
  - shared/to_bot/* 갱신
  - 검증: workflow_dispatch로 수동 실행 → Firestore 확인

- [ ] 10-8. `src/storage/shared_writer.py` — 시그널 쓰기 wrapper
  - 봇이 읽기 편한 포맷으로 저장
  - INTEGRATION.md 스키마 그대로
  - 검증: 스키마 일치성 테스트

- [ ] 10-9. 봇 → 리서치 데이터 활용 통합
  - `shared/from_bot/held_stocks` 읽기
  - 보유 종목 한정 CB·BW 추적
  - 보유 종목 한정 잠정실적 D-day 차단
  - 일요일 주간 리포트에 보유 종목 성과 섹션 추가
  - 검증: 가상 보유 데이터로 통합 흐름 확인

- [ ] 10-10. 통합 테스트 시나리오
  - 시나리오 1: 매수 시그널 → 봇 매수 → 보유 등록 → 정상 흐름
  - 시나리오 2: CB 행사기간 D-30 → 매도 시그널 → 봇 매도
  - 시나리오 3: 대주주 매도 공시 → 즉시 매도 시그널 + 매수 차단
  - 시나리오 4: 잠정실적 D-3 → 매수 차단 등록
  - 시나리오 5: 매크로 🔴 → macro_status 업데이트

- [ ] 10-11. 운영 시작 전 사용자 확인
  - TradeBot 측 수정 완료 여부
  - shared/ 컬렉션 양쪽 정상 접근 확인
  - 시범 운영 1주일 (실제 매매 없이 시그널만 검증)

---

### 작업 단위
- 한 작업 = 한 PR 또는 한 커밋
- 커밋 메시지: `[Phase 3-2] telegram_listener 구현`

### 검증 5단계 (수정 후 매번)
```bash
# 1. 문법 체크
python -c "import ast; ast.parse(open('src/모듈.py').read())"

# 2. import 체크
python -c "from src.모듈 import *"

# 3. 핵심 함수 mock 실행
python -m src.모듈 --dry-run

# 4. 미정의 변수 grep
grep -E "[a-zA-Z_]+\s*=\s*[a-zA-Z_]+\(" src/모듈.py

# 5. 변수 정의 확인 (육안)
```

### 컨텍스트 관리
- 5개 작업 완료마다 `progress.md` 갱신
- Claude Code 세션 종료 전 다음 작업 위치 기록

### 막혔을 때
- DESIGN.md 재확인 후 그래도 막히면 사용자에게 질문
- "근본 해결 우선": 우회 ❌, 원인 제거

### 사용자에게 질문할 때
- 한국어, 직설적·간결
- 옵션 A/B/C 제시
- 기술 용어는 풀어서

---

## 🎯 1주차 목표 (현실적 마일스톤)

```
Day 1: Phase 0 (사용자) + Phase 1 (셋업)
Day 2-3: Phase 2 + Phase 3A (Firestore + 텔레그램)
Day 4: Phase 3B + 3C (DART + KIS)
Day 5: Phase 3D + 3E (KRX + 뉴스)
Day 6: Phase 4 (분석 모듈) — 시간이 가장 많이 걸림
Day 7: Phase 6 (Workflow) + Phase 7 (프롬프트) + 시범 가동 시작
```

Phase 4·5·8·9는 이후 2~4주에 걸쳐 진행.

---

**문서 끝.** 첫 작업 시작 시 사용자에게 "Phase 0 완료됐나요?" 확인부터.
