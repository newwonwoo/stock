# 시스템 상세 설계서

> 이 문서 한 장만 보고 Claude Code가 구현 가능하도록 작성됨.
> 어려운 용어는 처음 등장할 때 풀어서 적음.

---

## 0. 용어 풀이

| 용어 | 풀이 |
|---|---|
| **GitHub Actions** | GitHub가 무료 제공하는 자동 실행 도구. 정해진 시간에 코드를 자동으로 돌려줌 |
| **Cron** | "매일 7시" 같은 시간 예약 표현 |
| **Workflow** | GitHub Actions의 자동 작업 한 묶음 (yml 파일) |
| **Secrets** | GitHub repo에 안전하게 비밀번호를 저장하는 기능 |
| **Firestore** | 구글이 제공하는 무료 클라우드 DB. JSON 형태로 저장 |
| **Telethon** | 텔레그램 메시지를 자동으로 가져오는 파이썬 라이브러리 |
| **Session 문자열** | 텔레그램에 한 번 로그인한 인증 정보를 문자열로 저장한 것. Secrets에 보관 |
| **PlayMCP** | 카카오가 만든 AI 도구 플랫폼 |
| **MCP** | AI(Claude)가 외부 서비스와 연결되는 표준 통로 |
| **DART** | 금융감독원 전자공시시스템. 재무제표·공시 정보 |
| **KIS API** | 한국투자증권 Open API. 주가·체결·수급 |
| **KRX** | 한국거래소. 시장 통계·신용잔고·공매도 |
| **NPS** | 국민연금공단 |
| **Moat** | 경제적 해자. 회사의 지속 가능한 경쟁 우위 |
| **DSO** | 매출 회수기간. 장사한 돈이 실제 들어오는 데 걸리는 평균 일수 |
| **CAPEX** | 자본적 지출. 공장·설비 같은 큰 투자 |
| **OCF** | 영업현금흐름. 본업으로 실제 손에 쥔 현금 |
| **FCF** | 잉여현금흐름. OCF에서 CAPEX 뺀 진짜 자유 현금 |
| **EBITDA** | 이자·세금·감가상각 빼기 전 영업이익. 현금 창출력 보는 지표 |
| **워치리스트** | 본인이 관심 있게 보는 종목 명단 |
| **화이트리스트** | Moat 통과한 매수 후보군 |
| **포워드 테스팅** | 추천 종목의 미래 주가를 추적해 시스템 성과를 검증 |
| **백테스팅** | 과거 데이터로 시스템을 가상 시뮬레이션 |

---

## 1. 프로젝트 개요

### 1.1 목적
조정승의 6주 이상 보유 스윙 매매를 위한 종목 리서치 자동화.

### 1.2 핵심 가치
- **데이터 기반**: 9중 정량+정성 필터로 객관 선별
- **자동화**: 본인 손길 = 카톡 메시지 보기만
- **누적 자산**: 데이터가 쌓일수록 시스템 검증 가능
- **비용 0원**: Claude Max + 무료 API + GitHub Actions 무료 한도

### 1.3 비기능 요구사항
| 항목 | 기준 |
|---|---|
| 운영 비용 | 월 0원 |
| 사용자 인터페이스 | 카카오톡 단일 |
| 데이터 보존 | 영구 (Firestore + 월 1회 JSON 백업) |
| 장애 복구 | 다음 실행에 자동 복구 |
| 확장성 | 환경변수로 조정 가능 |

---

## 2. 시스템 아키텍처

```
┌────────────────────────────────────────────────────────┐
│                  데이터 원천                            │
├────────────────────────────────────────────────────────┤
│ 텔레그램 9채널 │ DART │ KIS API │ KRX │ web_search    │
└────────┬───────────────────────────────────────────────┘
         │
         ↓ (매일 07:00 KST)
┌────────────────────────────────────────────────────────┐
│       GitHub Actions: collector workflow               │
│   - telegram_listener.py (Telethon)                    │
│   - dart_fetcher.py                                    │
│   - kis_fetcher.py                                     │
│   - krx_fetcher.py                                     │
│   - web_news.py (보조)                                 │
└────────┬───────────────────────────────────────────────┘
         │
         ↓
┌────────────────────────────────────────────────────────┐
│                 Firestore                              │
│  reports/ financials/ market/ watchlist/               │
│  whitelist/ recommendations/ performance/ news/        │
└────────┬───────────────────────────────────────────────┘
         │
         ↓ (매일 07:30 KST)
┌────────────────────────────────────────────────────────┐
│       Claude.ai 자동 루틴 (Max 플랜)                   │
│   1. Firestore 읽기                                    │
│   2. 9중 필터·분석                                     │
│   3. Claude 의견 생성                                  │
│   4. PlayMCP 카톡 MCP로 발송                           │
└────────┬───────────────────────────────────────────────┘
         │
         ↓
[ 카톡 나와의 채팅방 ] ← 본인이 보는 유일한 곳
```

---

## 3. 디렉토리 구조

```
wonwoo-research/
├── README.md
├── DESIGN.md
├── TASKS.md
├── SECRETS.md
├── requirements.txt
├── .gitignore
│
├── .github/
│   └── workflows/
│       ├── daily.yml          # 매일 07:00 KST 데이터 수집
│       ├── weekly.yml         # 일요일 20:30 KST 종목 후보 사전계산
│       └── monthly.yml        # 매월 1일 08:30 KST 화이트리스트 갱신
│
├── src/
│   ├── __init__.py
│   ├── config.py              # 환경변수 로딩, 상수
│   │
│   ├── collectors/            # 데이터 수집
│   │   ├── __init__.py
│   │   ├── telegram_listener.py
│   │   ├── dart_fetcher.py
│   │   ├── kis_fetcher.py
│   │   ├── krx_fetcher.py
│   │   └── web_news.py
│   │
│   ├── analyzers/             # 분석 모듈 (정량 계산만, LLM ❌)
│   │   ├── __init__.py
│   │   ├── financial_trend.py     # 필터 ① 재무 추세
│   │   ├── quant_health.py        # 필터 ② 계량 건전성
│   │   ├── margin_diagnosis.py    # 필터 ③ 마진 진단
│   │   ├── moat_score.py          # 필터 ④ Moat 점수 (월 1회)
│   │   ├── flow_analysis.py       # 필터 ⑤ 외인/기관 수급
│   │   ├── credit_short.py        # 필터 ⑥ 신용/대차
│   │   ├── nps_tracker.py         # 필터 ⑦ NPS 보유 변동
│   │   ├── technical.py           # 필터 ⑧ 주봉 기술
│   │   └── report_momentum.py     # 필터 ⑨ 리포트 모멘텀
│   │
│   ├── storage/
│   │   ├── __init__.py
│   │   └── firestore_client.py
│   │
│   ├── backtest/
│   │   ├── __init__.py
│   │   ├── forward_tracker.py     # 매주 자동 성과 추적
│   │   └── historical_runner.py   # 5년 백테스팅 (1회 실시)
│   │
│   └── utils/
│       ├── __init__.py
│       ├── kst_time.py            # KST 시간 처리
│       ├── parser.py              # 텔레그램 메시지 파싱
│       └── logger.py
│
├── prompts/                   # Claude.ai 루틴용 프롬프트 (사람이 읽음)
│   ├── daily_macro.md
│   ├── weekly_picks.md
│   └── monthly_whitelist.md
│
├── data/                      # 정적 데이터
│   ├── core_analysts.json     # 코어 애널리스트 명단 (수정 가능)
│   ├── telegram_channels.json # 추적 채널 명단
│   └── sector_keywords.json   # 섹터 분류 키워드
│
└── tests/
    ├── __init__.py
    ├── test_telegram_listener.py
    ├── test_dart_fetcher.py
    ├── test_filters.py
    └── test_integration.py
```

---

## 4. Firestore 스키마

### 4.1 컬렉션 구조

```
reports/                    # 텔레그램 채널에서 수집한 리포트
  {YYYY-MM-DD}/
    {message_uid}:
      channel: "butler_works"
      received_at: timestamp
      stock_code: "000660"
      stock_name: "SK하이닉스"
      analyst: "김선우"
      brokerage: "메리츠증권"
      opinion: "BUY"
      target_price: 260000
      target_change: "UP"        # UP/MAINTAIN/DOWN/NEW
      summary: "HBM4 진입 본격화..."
      original_link: "https://..."

financials/                 # DART에서 가져온 재무 데이터
  {stock_code}/
    quarterly:
      {YYYY-Qn}:
        revenue: 100000000
        operating_profit: ...
        net_profit: ...
        ocf: ...
        capex: ...
        accounts_receivable: ...
        # ... 모든 필드는 4.2 참조

market/                     # 시장 일별 데이터
  {YYYY-MM-DD}:
    indices:
      kospi: {close, change_pct, ...}
      kosdaq: {...}
      sp500: {...}
    fx:
      usd_krw: 1394
    rates:
      kr_10y: 3.52
      us_10y: 4.51
    foreign_flow:
      kospi_net: -284000000000
      ...
    sector_flow:
      buy_top3: ["금융", "화학", "보험"]
      sell_top3: ["반도체", "IT부품"]
    short_top10:
      kospi: [...]
      kosdaq: [...]

watchlist/                  # 워치리스트 (사용자 관리 + 자동 추가)
  {stock_code}:
    added_at: timestamp
    source: "manual" | "weekly_filter"
    status: "active" | "paused"
    note: ""

whitelist/                  # Moat 화이트리스트 (월 1회 갱신)
  {YYYY-MM}/
    stocks:
      - stock_code, stock_name, moat_score, sector

recommendations/            # 주간 추천 5종목
  {YYYY-MM-DD}/             # 추천일 (일요일)
    {stock_code}:
      stock_code, stock_name
      grade: "STAR3" | "STAR2" | "MONITOR"
      filters_passed: [1,2,3,4,5,6,7,8,9]
      entry_price, stop_loss, target_price
      reasoning: ""
      next_earning_date

performance/                # 추천 성과 추적
  {stock_code}_{recommended_date}:
    recommended_at, entry_price
    +1w, +4w, +6w, +8w, +12w: {price, return_pct}
    max_price, min_price, mdd_pct
    status: "active" | "stopped" | "target_hit"

news/                       # 주요 뉴스·공시
  {YYYY-MM-DD}/
    {news_id}:
      type: "disclosure" | "news"
      stock_code, title, summary, sentiment

system_logs/                # 시스템 운영 로그
  {YYYY-MM-DD}/
    collector_run, analyzer_run, sender_run: {status, duration}
```

### 4.2 financials/ 상세 필드

```python
# DART에서 추출하는 분기 재무 항목 (전체 리스트)
QUARTERLY_FIELDS = [
    # 손익계산서
    "revenue",                      # 매출액
    "cost_of_sales",                # 매출원가
    "gross_profit",                 # 매출총이익
    "sga",                          # 판관비
    "operating_profit",             # 영업이익
    "rnd_expense",                  # 연구개발비
    "depreciation",                 # 감가상각비
    "ebitda",                       # = 영익 + 감가상각
    "net_profit",                   # 당기순이익
    
    # 재무상태표
    "total_assets",                 # 자산총계
    "current_assets",               # 유동자산
    "accounts_receivable",          # 매출채권
    "inventory",                    # 재고자산
    "cash_and_equivalents",         # 현금및현금성자산
    "tangible_assets",              # 유형자산
    "construction_in_progress",     # 건설중인자산
    "total_liabilities",            # 부채총계
    "interest_bearing_debt",        # 차입금
    "total_equity",                 # 자본총계
    
    # 현금흐름표
    "ocf",                          # 영업활동현금흐름
    "icf",                          # 투자활동현금흐름
    "fcf",                          # 잉여현금흐름 = ocf - capex
    "capex",                        # 자본적지출
    
    # 사업보고서 추출 (있을 때만)
    "order_backlog",                # 수주잔고
    "guidance_revenue",             # 가이던스 매출
    "guidance_op_profit",           # 가이던스 영익
    "segment_revenue",              # 사업부문별 매출 dict
    "segment_op_profit",            # 사업부문별 영익 dict
]
```

### 4.3 인덱스

다음 쿼리에 인덱스 필요:
- `reports/{date}` 전체 + `stock_code` 필터
- `financials/{code}/quarterly` 최근 4분기
- `recommendations/{date}` 전체
- `performance/` `recommended_at` 4주 전·6주 전

---

## 5. 모듈별 상세 설계

### 5.1 telegram_listener.py

**목적**: 9개 텔레그램 채널의 새 메시지 수집 후 Firestore에 저장.

**입력**: `data/telegram_channels.json` (채널 username 목록)

**출력**: `reports/{date}/{message_uid}` 도큐먼트

**핵심 동작**:
```
1. Telethon으로 본인 계정 로그인 (Session 문자열 사용, 비대화식)
2. 각 채널의 last_processed_message_id 이후 새 메시지 fetch
3. 채널별 파서로 구조화 (parser.py 참조)
4. Firestore에 저장
5. last_processed_message_id 업데이트
```

**채널별 파싱 규칙** (`utils/parser.py`):
- **`@butler_works`**: 정형 포맷 → 정규식 추출 (종목코드/작성자/투자의견/목표가/요약)
- **베스트 애널 개인 채널**: 자유 포맷 → 종목 코드(\d{6}) + 키워드 매칭으로 의견 추정
- **`@searfin` 등 보조**: 메타데이터만 추출 (제목+링크)

**파싱 실패 처리**: 원문은 통째 저장 + `parse_status: "failed"` 플래그. 운영 후 패턴 보강.

**중복 방지**: `message_uid = {channel}_{message_id}` 유니크.

---

### 5.2 dart_fetcher.py

**목적**: DART에서 재무·공시 데이터 수집.

**입력**: 시총 5,000억 이상 종목 코드 리스트 (KRX에서 매일 갱신)

**출력**: `financials/{code}/quarterly/{YYYY-Qn}`, `news/{date}/{news_id}` (공시)

**필수 호출 API**:
```
1. corpCode.xml — 종목코드↔DART고유번호 매핑 (월 1회)
2. fnlttSinglAcntAll — 분기 재무제표 (분기 갱신 시)
3. list — 일별 공시 목록 (매일)
4. majorstock — 5%↑ 보유 변동 (NPS 추적용)
```

**호출 정책**:
- 일일 한도 10,000건. 월 평균 사용량 약 1,700건 (한도의 17%)
- 분기 재무는 신규 공시 감지 시에만 갱신 (전체 재호출 ❌)
- 매일 공시 목록은 1회 호출

**에러 처리**:
- `status != '000'` 시 재시도 3회
- 3회 실패 시 system_logs에 기록, 다음 날 재시도
- API 한도 초과 시 즉시 중단 (다음날까지 대기)

**파싱 깊이**:
- 재무제표 XBRL: 5.2 QUARTERLY_FIELDS 모두 추출
- 사업보고서 텍스트: 수주잔고·가이던스·사업부문 추출 시도. 실패해도 OK (Claude.ai 루틴이 보강)

---

### 5.3 kis_fetcher.py

**목적**: KIS API로 주가·수급 데이터 수집.

**입력**: 워치리스트 + 화이트리스트 종목 코드

**출력**: `market/{date}` 일부 필드 + `financials/{code}/daily/{date}`

**핵심 호출**:
```
1. inquire-daily-itemchartprice — 일봉 (주봉 계산용 누적)
2. inquire-investor — 외인/기관/개인 일별 순매수
3. inquire-foreign — 외인 보유율
4. 시장 지수 — KOSPI, KOSDAQ, KOSPI200
```

**호출 정책**:
- TradeBot에서 사용 중인 토큰 재활용 가능. 다만 동시 호출 시 제한 주의
- 워치리스트(50~80) + 화이트리스트(50~80) = 일 평균 200~400 호출
- 토큰 24시간 만료. 자동 재발급 로직 포함

**주의**:
- 모의투자 vs 실투자 도메인 다름. **실투자 도메인 사용 권장** (조회만 하면 무료)
- API 응답 한도 (분당 20건). 적절한 sleep 필요

---

### 5.4 krx_fetcher.py

**목적**: KRX 정보데이터시스템에서 시장 통계 수집.

**출력 필드**:
- 일별 신용거래잔고 (종목별)
- 일별 대차잔고
- 공매도 거래대금 Top 10 (KOSPI/KOSDAQ 별)
- 외국인 보유 통계

**접근 방법**:
- **공식 OpenAPI**: data.krx.co.kr (CSV 다운로드 형태). 회원가입 + API 키 발급
- **대안**: `pykrx` 파이썬 라이브러리 (KRX 사이트 조회 자동화. 비공식이지만 안정적)

**권장**: `pykrx` 우선 시도 → 막히면 공식 API로 전환.

---

### 5.5 nps_tracker.py

**목적**: 국민연금 5%↑ 보유 종목 분기 변동 추적.

**데이터 소스**: DART majorstock API (대량보유 상황보고)

**처리**:
```
1. 국민연금공단 = 보고자 "국민연금공단"으로 필터
2. 신규 등장 / 비중 확대 / 비중 축소 / 전량 매도 분류
3. news/{date}/nps_quarterly 에 저장
```

**호출 빈도**: 분기 1회 (3월·6월·9월·12월 말 다음 영업일).

---

### 5.6 firestore_client.py

**목적**: Firestore 접근 통합 wrapper.

**제공 메소드**:
```python
class FirestoreClient:
    def save_report(self, date, message_uid, data): ...
    def get_reports_by_date(self, date): ...
    def get_reports_by_stock(self, stock_code, days=7): ...
    
    def save_financial(self, stock_code, period, data): ...
    def get_recent_quarters(self, stock_code, n=4): ...
    
    def save_market(self, date, data): ...
    def get_market(self, date): ...
    
    def save_recommendation(self, date, stock_code, data): ...
    def get_performance(self, stock_code, recommended_date): ...
    def update_performance(self, stock_code, recommended_date, week_offset, price): ...
    
    def get_watchlist(self): ...
    def get_whitelist(self, year_month=None): ...
    
    def log_run(self, run_type, status, duration_ms): ...
```

**인증**: Firebase Service Account JSON. GitHub Secrets에 base64 인코딩 저장.

**무료 티어 한도**:
- 일 50,000 reads / 20,000 writes / 1GB
- 본인 사용량 추정: reads 5,000/day, writes 2,000/day → 한도의 10%

---

### 5.7 Claude.ai 루틴 프롬프트 (3종)

루틴은 Claude.ai의 자동 작업 기능. 각 프롬프트는 `prompts/` 폴더의 md 파일.

#### 5.7.1 prompts/daily_macro.md

**핵심 동작**:
1. PlayMCP의 Firestore MCP(또는 Google Drive 동기화 파일)에서 어제~오늘 데이터 읽기
2. 9개 섹션으로 매크로 브리핑 생성 (포맷 → 10장 산출물 샘플)
3. Claude 의견 섹션 생성 (시장 톤·핵심 변수 2개·오늘 주의)
4. PlayMCP 카톡 MCP로 본인 "나와의 채팅방" 발송

**프롬프트 구조** (TASKS.md에서 구체화):
```
[역할 설정]
당신은 조정승의 6주 스윙 매매 리서치 어시스턴트입니다...

[입력 데이터 위치]
- Firestore market/{오늘 날짜}
- Firestore reports/{오늘 날짜} 어제 16:00~오늘 07:00
- Firestore news/{오늘 날짜} 어제 16:00~오늘 07:00
- Firestore watchlist/ 활성 종목 전체

[출력 포맷]
... (10장 샘플 그대로)

[Claude 의견 작성 규칙]
- 시장 톤 1줄
- 핵심 변수 2개 (각 2~3문장)
- 오늘 주의 1~2개
- 6주 스윙 관점에서의 함의
- 데이터 나열 ❌, 해석 ⭐
```

#### 5.7.2 prompts/weekly_picks.md

**핵심 동작**:
1. GitHub Actions에서 사전 계산된 "이번주 후보군"(weekly.yml의 산출물) 읽기
2. 9중 필터 적용
3. 5종목 선정 (★ 등급 자동 판정)
4. 각 종목별 진입가/손절/목표가 계산
5. 4주 전 추천의 현재 성과 추적 섹션 생성
6. 카톡 발송 + 구글 드라이브 PDF 저장

#### 5.7.3 prompts/monthly_whitelist.md

**핵심 동작**:
1. KRX 시총 5천억↑ 종목 전수 (collector가 사전 정리)
2. 워런 버핏 + 피셔 정량 점수 계산
3. 사업보고서 정성 평가 (DART 텍스트 기반)
4. 50~80개 화이트리스트 확정
5. 신규 진입 / 제외 종목 표시
6. 카톡 + 구글 드라이브 PDF

---

### 5.8 PlayMCP 카톡 발송

**현재 가용 MCP**:
- `kakao-talk-mcp` (PlayMCP 등록): "나와의 채팅방"으로 메시지 전송
- 길이 제한: 1,000자/메시지 (확실치 않음 — 검증 필요)

**길이 초과 시**: 분할 발송 (섹션 단위로 자르기). 첫 메시지에 "[1/3]" 표시.

**전송 실패 시**: GitHub Actions 로그 + 다음 시도. 3회 실패 시 텔레그램 본인 계정 DM으로 fallback.

---

## 6. 9중 필터 알고리즘

### 6.1 필터 통과 기준 매트릭스

| 필터 | 판정 기준 | 통과 조건 |
|---|---|---|
| ① 재무 추세 | 4분기 매출/영익 추세 | 매출 우상향 또는 ±5% 유지 + 영익 우상향 또는 마진 진단 🟢 |
| ② 계량 건전성 | OCF/영익, DSO, 부채 | OCF/영익 ≥ 0.8 + DSO 30일 이상 악화 ❌ + 부채비율 ≤ 200% |
| ③ 마진 진단 | 마진 하락의 질 | 🟢 (CAPEX/R&D형) 또는 정상 마진 |
| ④ Moat | 화이트리스트 포함 | 월간 화이트리스트 포함 |
| ⑤ 수급 | 외인+기관 | 외인 1M +0.5%p↑ 또는 외인+기관 5일 동반 매수 |
| ⑥ 신용/대차 | 신용비율, 대차증가 | 신용 5% 미만 + 대차잔고 1주 +50% ❌ |
| ⑦ NPS | 분기 변동 | NPS 신규/확대 = 가산점, 축소 = 감점 |
| ⑧ 기술 (주봉) | 60주선·RSI·반등 | 주봉 60주선 위 + RSI 40~55 + 반등 거래량 |
| ⑨ 리포트 | 코어 애널리스트 | 4주 내 매수 의견 또는 목표가 상향 |

### 6.2 등급 판정

```python
def grade(filters_passed: list[bool]) -> str:
    green_count = sum(filters_passed)
    
    # 즉시 제외 조건 (어떤 등급도 받지 않음)
    if any_critical_red:  # 공매도 Top 10 진입 / 코어 매도 의견 / DSO 30일↑ 악화
        return "EXCLUDED"
    
    if green_count >= 7:  return "STAR3"   # ★★★
    if green_count >= 5:  return "STAR2"   # ★★
    if green_count >= 3:  return "MONITOR" # ★
    return "EXCLUDED"
```

### 6.3 마진 진단 알고리즘 (③)

```python
def diagnose_margin(financials):
    """
    영업이익률 하락 원인을 5가지로 분류해 판정
    """
    op_margin_now = ...
    op_margin_prev_4q = ...
    
    # 정상 (마진 유지/상승)
    if op_margin_now >= op_margin_prev_4q - 0.005:
        return "🟢 정상"
    
    # EBITDA 마진 vs 영익 마진 비교
    ebitda_margin_change = ...
    op_margin_change = ...
    
    if ebitda_margin_change >= 0 and op_margin_change < 0:
        # 감가상각 증가형
        if capex_ratio_increase > 0.30:
            if construction_in_progress_increase > 0:
                if debt_ratio < 2.0 and revenue_growth > 0:
                    return "🟢 증설형"
        return "🟡 일시 D&A 증가"
    
    rnd_ratio_change = ...
    if rnd_ratio_change > 0.02 and revenue_growth > 0:
        return "🟢 R&D 강화형"
    
    # 사업부문별 분리
    main_margin, new_margin = split_segments(financials)
    if main_margin_stable and new_margin < 0:
        return "🟡 신사업 투자형"
    
    # 매출원가율 변화
    cogs_ratio_change = ...
    if cogs_ratio_change > 0.02:
        # 원재료 가격 매칭 (외부 데이터)
        if material_price_peaked:
            return "🟡 일시 원가 압박"
        return "🔴 구조적 원가 악화"
    
    # 경쟁사 비교 (동종 업종 평균)
    if peer_margin_stable and own_margin_down:
        return "🔴 경쟁 악화"
    
    if peer_margin_also_down:
        return "🟡 산업 사이클"
    
    return "🔴 원인 불명"
```

자세한 데이터 소스·임계값은 `analyzers/margin_diagnosis.py` 주석에 명시.

---

## 7. GitHub Actions Workflows

### 7.1 daily.yml

```yaml
name: Daily Data Collection
on:
  schedule:
    - cron: '0 22 * * *'    # UTC 22:00 = KST 07:00
  workflow_dispatch:         # 수동 실행 가능

jobs:
  collect:
    runs-on: ubuntu-latest
    timeout-minutes: 30
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install -r requirements.txt
      - run: python -m src.collectors.telegram_listener
        env:
          TELEGRAM_API_ID: ${{ secrets.TELEGRAM_API_ID }}
          TELEGRAM_API_HASH: ${{ secrets.TELEGRAM_API_HASH }}
          TELEGRAM_SESSION: ${{ secrets.TELEGRAM_SESSION }}
          FIREBASE_SA_BASE64: ${{ secrets.FIREBASE_SA_BASE64 }}
      - run: python -m src.collectors.dart_fetcher
        env:
          DART_API_KEY: ${{ secrets.DART_API_KEY }}
          FIREBASE_SA_BASE64: ${{ secrets.FIREBASE_SA_BASE64 }}
      - run: python -m src.collectors.kis_fetcher
        env:
          KIS_APP_KEY: ${{ secrets.KIS_APP_KEY }}
          KIS_APP_SECRET: ${{ secrets.KIS_APP_SECRET }}
          FIREBASE_SA_BASE64: ${{ secrets.FIREBASE_SA_BASE64 }}
      - run: python -m src.collectors.krx_fetcher
      - run: python -m src.backtest.forward_tracker  # 보유 종목 가격 업데이트
      - if: failure()
        run: echo "::warning::Daily collection failed at ${{ github.run_id }}"
```

### 7.2 weekly.yml

일요일 20:30 KST. 다음 날(월) 카톡 발송 전 후보군 사전 계산.

```yaml
on:
  schedule:
    - cron: '30 11 * * 0'    # UTC 일요일 11:30 = KST 일요일 20:30
```

작업: 화이트리스트 + 워치리스트 전수 9중 필터 통과 점수 계산 → Firestore `weekly_candidates/{date}`에 저장.

### 7.3 monthly.yml

매월 1일 23:30 KST 전월 마지막 영업일 데이터 기준.

```yaml
on:
  schedule:
    - cron: '30 14 1 * *'    # 매월 1일 UTC 14:30 = KST 23:30
```

작업: KRX 시총 5천억↑ 전수 → 정량 스크리닝 → 화이트리스트 후보 추출 → Firestore `whitelist_candidates/{YYYY-MM}` 저장.

---

## 8. 환경변수 (Secrets)

`SECRETS.md` 참조. 발급은 사용자가 직접. Claude Code는 `os.environ`으로 읽기만.

| 키 | 발급처 | 용도 |
|---|---|---|
| `TELEGRAM_API_ID` | my.telegram.org | 텔레그램 인증 |
| `TELEGRAM_API_HASH` | my.telegram.org | 텔레그램 인증 |
| `TELEGRAM_SESSION` | 첫 실행 시 생성 | 세션 문자열 (재인증 방지) |
| `DART_API_KEY` | opendart.fss.or.kr | DART 호출 |
| `KIS_APP_KEY` | TradeBot 재활용 | 한국투자증권 |
| `KIS_APP_SECRET` | TradeBot 재활용 | 한국투자증권 |
| `KRX_API_KEY` | data.krx.co.kr (옵션) | KRX (pykrx 사용 시 불필요) |
| `FIREBASE_SA_BASE64` | console.firebase.google.com | Firestore 인증 (base64) |
| `KAKAO_ACCESS_TOKEN` | PlayMCP 연동으로 자동 | 카톡 발송 (Claude.ai 루틴이 사용) |

---

## 9. 산출물 포맷 (샘플)

### 9.1 매일 매크로 브리핑

```
━━━━━━━━━━━━━━━━━━━━━━
🌅 [원우 아빠 매크로]
2026-05-04 (월) 07:30
━━━━━━━━━━━━━━━━━━━━━━

📊 시장 신호등: 🟡 관망

━━━━━━━━━━━━━━━━━━━━━━
① 시장 동향
━━━━━━━━━━━━━━━━━━━━━━
코스피     2,742  -0.42%  🟡
코스닥       872  -0.81%  🔴
S&P 500   5,318  +0.31%  🟢
USD/KRW   1,394          🔴 1400 임박
미10년    4.51%           🔴 ↑

━━━━━━━━━━━━━━━━━━━━━━
② 외인/기관 수급
━━━━━━━━━━━━━━━━━━━━━━
외인 코스피 -2,840억      🔴
기관 코스피 +1,520억      🟡

📈 매수 섹터: 금융 🟢 / 화학 🟢
📉 매도 섹터: 반도체 🔴 / IT부품 🔴

⭐ 워치리스트 동반매수
   - 종목A: 외인+기관 5일 中 4일

━━━━━━━━━━━━━━━━━━━━━━
③ 신용/대차 (워치리스트)
━━━━━━━━━━━━━━━━━━━━━━
🔴 종목D: 신용비율 6.2% (1주 +38%)
🟡 대차잔고 급증: 종목F (1주 +52%)

━━━━━━━━━━━━━━━━━━━━━━
④ 주요 공시
━━━━━━━━━━━━━━━━━━━━━━
🟢 자사주 매입: LS ELECTRIC 200억
🟢 잠정실적: 현대모비스 1Q 컨센 상회
🔴 유증 결의: 에코프로 (희석 9.5%)
⭐ 수주: 한화에어로 K2 18조

━━━━━━━━━━━━━━━━━━━━━━
⑤ 베스트 애널 + 버틀러
━━━━━━━━━━━━━━━━━━━━━━
⭐ 김선우 (메리츠/반도체)
   [SK하이닉스] 목표 ₩240k → ₩260k 상향
   "HBM4 진입 본격화"

📊 섹터 신호: 반도체 5건 일제 긍정 🟢

━━━━━━━━━━━━━━━━━━━━━━
⑥ NPS (분기 공시 D-3)
━━━━━━━━━━━━━━━━━━━━━━
⭐ 신규 5%↑: HD현대중공업

━━━━━━━━━━━━━━━━━━━━━━
⑦ 공매도 Top 10
━━━━━━━━━━━━━━━━━━━━━━
🚨 종목H 진입 → 워치리스트 자동 제외

━━━━━━━━━━━━━━━━━━━━━━
⑧ 오늘 일정
━━━━━━━━━━━━━━━━━━━━━━
⚠️ 14:00  한은 금통위 (동결 컨센 95%)

━━━━━━━━━━━━━━━━━━━━━━
💬 Claude 의견
━━━━━━━━━━━━━━━━━━━━━━
오늘 톤: 🟡 위험회피, 단 섹터 차별화

핵심 변수 2개:
1) 환율 1400 임박 → 외인 매도 지속.
   다만 펀더 무관 매크로 → 6주 관점에선
   매집 구간일 수 있음.
   
2) 베스트 애널 반도체 5건 일제 긍정 +
   NPS 신규 진입 → 펀더와 수급 동시 신호.
   SK하이닉스 6주 누적 매집 후보.

오늘 주의:
- 14:00 금통위 결과까지 신규 진입 보류
- 매파 발언 시 환율 1400 돌파 → 추가 하방

━━━━━━━━━━━━━━━━━━━━━━
⚠️ 정보 제공 목적, 투자 권유 아님
━━━━━━━━━━━━━━━━━━━━━━
```

### 9.2 주간 종목 리포트 + 9.3 월간 화이트리스트

지면상 생략. 세부는 `prompts/weekly_picks.md`, `prompts/monthly_whitelist.md` 작성 시 첨부.

---

## 10. 백테스팅

### 10.1 포워드 테스팅 (자동 영구 운영)

`src/backtest/forward_tracker.py`:
- 매일 daily.yml에서 자동 실행
- `recommendations/`에 등록된 종목들의 +1w/+4w/+6w/+8w/+12w 가격 자동 갱신
- KIS API에서 종가 가져옴
- `performance/{stock}_{date}` 갱신

### 10.2 과거 백테스팅 (1회 실시)

`src/backtest/historical_runner.py`:
- 5년치(2021-01 ~ 2026-05) 시뮬레이션
- 매주 9중 필터(④⑨ 제외, 정량만) 적용 → 가상 5종목 추천 → 6주 보유 가정 → -8% 손절 또는 +15% 익절
- 결과: 누적 수익률, 샤프 비율, MDD, 월별 수익률
- KOSPI/KOSDAQ 벤치마크 대비 알파
- PDF 리포트 생성

**한계 명시**: ④ Moat·⑨ 리포트는 과거 시점 데이터 재현 불가 → 정량만으로. 결과는 방향 확인용.

---

## 11. 보안

- **모든 API 키는 GitHub Secrets**. 코드/repo에 절대 ❌
- **`.gitignore`**: `*.session`, `*.json` (인증 파일), `__pycache__/`, `.env`
- **로그에 키 출력 ❌**: `logger.py`에 마스킹 필터
- **Firestore 룰**: 인증된 서비스 계정만 접근. 공개 ❌

---

## 12. 검증 단계 + 품질확인서

### 12.1 단위 테스트 (필수)

`tests/`에 모든 파서·필터 테스트:
- `test_telegram_listener.py`: 버틀러 메시지 샘플 5개 → 정확 파싱
- `test_dart_fetcher.py`: 삼성전자(005930) 1Q 재무 정확성
- `test_filters.py`: 9개 필터 각각 mock 데이터로 통과/탈락 검증
- `test_integration.py`: 전체 파이프라인 dry-run

### 12.2 자체 검증 프로토콜

각 모듈 구현 직후 5단계 검증:
```
1. python -c "import ast; ast.parse(open('파일.py').read())"
2. python -c "from src.모듈 import *"
3. mock 데이터로 핵심 함수 실행
4. grep -E "[a-z_]+\s*=\s*[a-z_]+\(" 미정의 변수 체크
5. 함수 내 사용 변수가 def 안에 있는지 확인
```

### 12.3 품질확인서 양식

모든 모듈 구현 후 `QUALITY_REPORT.md` 작성:

```markdown
# 품질확인서 — 2026-MM-DD

## 1. 요구사항 충족 여부
- [ ] 9중 필터 모두 구현
- [ ] 매일/주간/월간 산출물 포맷 일치
- [ ] 비용 0원 운영 가능
- [ ] 카톡 발송 정상

## 2. 단위 테스트
- [ ] tests/ 전체 pass
- [ ] 커버리지 ___%

## 3. 통합 테스트
- [ ] daily.yml dry-run 성공
- [ ] weekly.yml dry-run 성공
- [ ] monthly.yml dry-run 성공

## 4. 제약 조건 검증
- [ ] DART API 일일 호출 < 1,500
- [ ] KIS API 분당 < 20
- [ ] Firestore reads < 5,000/day
- [ ] 모든 Secrets 외부 노출 ❌

## 5. 알려진 한계
- (예: 미국주식 외인 보유율 데이터 없음 → 한국 한정)
- (예: 사업보고서 정성 파싱은 80% 신뢰도)

## 6. 다음 개선 후보
- ...
```

---

## 13. 운영 시나리오

### 13.1 정상 운영
- 매일 07:00 collector 자동 실행 → Firestore 갱신
- 매일 07:30 사용자가 Claude.ai 루틴 트리거 (또는 자동 스케줄)
- 카톡 도착 → 사용자 확인

### 13.2 장애 시
- collector 실패 → 다음날 자동 복구. 누락 데이터는 수동 백필 가능
- API 한도 초과 → 24시간 대기 후 재개
- 카톡 발송 실패 → 텔레그램 본인 DM으로 fallback

### 13.3 사용자 액션
- **워치리스트 추가**: Firestore 직접 또는 별도 Telegram 봇 명령 (옵션)
- **종목 제외**: `watchlist/{code}.status = "paused"`
- **시스템 일시 중단**: GitHub Actions의 workflow 비활성화

---

## 14. 트러블슈팅

| 증상 | 원인 추정 | 조치 |
|---|---|---|
| 텔레그램 메시지 안 옴 | Session 만료 | TELEGRAM_SESSION 재발급 |
| DART 401 에러 | API 키 오기재 | Secrets 확인 |
| KIS 토큰 에러 | 24h 만료 미처리 | refresh 로직 점검 |
| Firestore 권한 | SA 키 잘못 | base64 다시 인코딩 |
| 카톡 미수신 | PlayMCP 인증 만료 | Claude.ai에서 재연결 |
| 파싱 실패 多 | 채널 포맷 변경 | 새 샘플로 정규식 보강 |

---

## 15. 향후 확장 (현 단계 ❌, 6개월 후 검토)

- 펀더멘털 훼손 뉴스 자동 감지 (정확도 검증 후)
- 본인 매매 일지 통합 (시스템 vs 본인 결정 비교)
- 미국주식 깊이 강화 (SEC EDGAR + 옵션 데이터)
- 데이트레이딩 풀 vs 스윙 풀 자동 분리

---

## 17. TradeBot 연계 시스템

> **상세 인터페이스 명세는 별도 문서 `INTEGRATION.md` 참조.**
> 본 장은 리서치 시스템이 생산해야 하는 시그널의 **분석 논리**만 정의.

### 17.1 두 시스템의 책임

```
[wonwoo-research]              [TradeBot v5.x]
분석·신호 생산 전담            매수/매도 실행·전략 운용
                ──── shared/ 컬렉션 통신 ────
```

리서치는 **신호만 생산**, 매수/매도 실행 ❌.
봇은 **신호 소비 + 자체 전략**, 분석 ❌.

### 17.2 매수 시그널 산출 — 4단계 판정

`src/analyzers/buy_signal_generator.py`:

```python
def generate_buy_signal(stock):
    # 1. 매수 차단 검증
    if buy_blocker.is_blocked(stock.code):
        return {"signal": "AVOID", "blocked": True, "reasons": [...]}
    
    # 2. 9중 필터 점수
    base_score = nine_filter.calculate(stock)
    
    # 3. 가산점·감점
    positive = sum_positive_signals(stock)
    negative = sum_negative_signals(stock)
    
    score = base_score + positive - negative
    
    # 4. 4단계 판정
    if score >= 90 and stock.grade == "★★★":
        signal = "STRONG_BUY"
    elif score >= 70:
        signal = "BUY"
    elif score >= 50:
        signal = "HOLD"
    else:
        signal = "AVOID"
    
    # 5. 이동평균선 (분할 진입 트리거 가격)
    ma10 = calculate_ma(stock.code, 10)
    ma15 = calculate_ma(stock.code, 15)
    
    return {
        "signal": signal,
        "score": score,
        "moving_averages": {"ma10": ma10, "ma15": ma15},
        "valid_until": today + 10_business_days
    }
```

### 17.3 매수 가산/감점 매트릭스

**가산 시그널** (긍정):

| 시그널 | 점수 |
|---|---|
| 9중 필터 ★★★ | +50 |
| 9중 필터 ★★ | +30 |
| 외인 보유율 1M +1%p↑ | +10 |
| 외인+기관 동반 매수 5일 中 4일+ | +15 |
| NPS 신규 5%↑ 진입 | +15 |
| NPS 비중 확대 | +10 |
| 코어 애널 목표가 상향 (4주 內 2건+) | +10 |
| 자사주 매입 결의 | +10 |
| 자사주 소각 결의 | +20 |
| **제3자 유증 (모든 케이스)** | +15 |
| 무상증자 결의 | +5 |
| 잠정실적 서프라이즈 (+20%↑) | +20 |
| 대규모 신규 수주 (수주잔고 +20%↑) | +15 |
| 주봉 60주선 반등 + 양봉 | +10 |
| RSI 40~50 + 거래량 ↑ | +10 |

**감점 시그널** (부정, 차단은 아님):

| 시그널 | 점수 |
|---|---|
| 블록딜 (기관·외인) | -15 |
| 유상증자 (주주배정/공모) | -20 |
| 외인 1M -2%p 이상 매도 | -15 |
| 신용비율 5%↑ + 1주 +30%↑ 급증 | -20 |
| 대차잔고 1주 +50%↑ 급증 | -10 |
| 자사주 매각 결의 | -5 |
| 외인 5일 연속 순매도 | -10 |

### 17.4 매수 차단 (즉시 AVOID)

`src/analyzers/buy_blocker.py`:

| 차단 사유 | 차단 기간 |
|---|---|
| 거래정지·분식·횡령 | 영구 |
| 무상감자 | 영구 |
| **CB·BW 행사기간 진행 중** | 종료 시까지 |
| **CB·BW 행사기간 D-60 이내** | D+0 후 60일 |
| **CB·BW 전환 신청 직후** | 60일 |
| **대주주 매도 (1%↑)** | 90일 |
| **블록딜 (대주주·주요주주)** | 90일 |
| 공매도 Top 10 진입 | 이탈 시까지 |
| **잠정실적 D-3 ~ D+3** | D+3까지 |
| 어닝 쇼크 (-20%↓) | 60일 |
| 매도 의견 (코어 애널) | 60일 |
| DSO 30일↑ 악화 | 정상화 시까지 |
| NPS 전량 매도 | 90일 |

만료 시 자동 해제 (`cleanup_expired` 매일 실행).

### 17.5 매도 시그널 산출

`src/analyzers/sell_signal_generator.py`:

**3등급 매도 시그널**:

| Severity | 트리거 | 봇 권장 행동 |
|---|---|---|
| `URGENT` | 거래정지·분식·횡령·무상감자·대주주 매도·블록딜·CB 전환신청·CB 행사기간 D-7 | 즉시 매도 |
| `REVIEW` | 어닝 쇼크·코어 매도 의견·CB 행사기간 D-30·신용 급증 | 봇 자체 판단 |
| `MONITOR` | 외인 매도·NPS 축소·섹터 자금 유출 | 관찰만 |

### 17.6 공시 분류 매트릭스 (요약)

`src/analyzers/disclosure_classifier.py`:

22개 공시 유형을 분류. 핵심 룰:

- **CB·BW 발행 자체 = 무신호** (시간축 추적만 등록)
- **CB·BW 행사기간 진입이 진짜 시그널**
- **제3자 유증 = 무조건 긍정**
- **대주주 매도·블록딜 = 즉시 매도**
- **자사주 매입/소각 = 긍정**

전체 매트릭스는 `disclosure_classifier.py` 주석 참조.

### 17.7 CB·BW 시간축 추적

`src/analyzers/cb_bw_tracker.py`:

매일 daily.yml에서 호출. 보유 종목 + 화이트리스트의 모든 미상환 CB·BW를 시간축으로 추적.

```python
def track_lifecycle(stock_code):
    cbs = dart.get_unredeemed_cbs(stock_code)
    
    for cb in cbs:
        d_minus = (cb.exercise_start - today).days
        
        # 매수 차단 등록
        if 0 <= d_minus <= 60:
            buy_blocker.register(stock_code, "CB_BW_NEAR_EXERCISE")
        
        # 매도 시그널 발행 (보유 시)
        if stock_code in held_stocks:
            if d_minus == 30:
                emit_sell_signal(stock_code, "MONITOR", "CB 행사 D-30")
            elif d_minus == 7:
                emit_sell_signal(stock_code, "REVIEW", "CB 행사 D-7")
            elif d_minus <= 0 and today <= cb.exercise_end:
                # 행사기간 중 전환가 프리미엄 체크
                premium = (current_price / cb.conversion_price - 1) * 100
                if premium > 10:
                    emit_sell_signal(stock_code, "REVIEW", f"전환 압력 (+{premium}%)")
        
        # 실제 전환 신청 감지
        recent_exercises = dart.get_recent_cb_exercises(stock_code, days=3)
        for ex in recent_exercises:
            emit_sell_signal(stock_code, "URGENT", "CB 전환 신청")
            buy_blocker.register(stock_code, "CB_BW_EXERCISED")
```

### 17.8 봇 → 리서치 데이터 활용

봇이 `shared/from_bot/held_stocks/`에 보유 정보 갱신 시:

리서치는 다음 분석에 활용:
- 보유 종목 한정 잠정실적 D-day 모니터링
- 보유 종목 한정 CB·BW 행사기간 추적
- 일요일 주간 리포트의 "보유 종목 성과" 섹션
- 포워드 테스팅 (실제 진입가 기준)

### 17.9 매도 전략·위험 관리는 봇 측 책임

다음은 **본 시스템의 책임이 아님**. TradeBot 측에서 결정:

- 손절선 (예: -8%)
- 익절선 (예: +15%)
- 트레일링 스톱
- 분할 진입 (1.5/1.5/7 비율, 10·15일선 트리거)
- 위험 인지 (초방어전략)
- 매크로 🔴 시 행동
- 매수 후 보유 기간 만료 처리
- 손절·익절 후 자금 재배치

리서치는 신호만 보냄. 실행과 운용 룰은 봇이 자체 판단.

---

## 16. 라이선스 / 사용 제한

- 이 시스템은 **개인 사용 전용**
- 외부 공개·재배포 ❌
- 텔레그램 채널 데이터는 **본인 계정으로 본인이 받은 메시지** (Telethon User Client API). 합법
- 모든 산출물 끝에 "정보 제공 목적, 투자 권유 아님" 고지 필수

---

**문서 끝.** Claude Code는 `TASKS.md`로 이동.
