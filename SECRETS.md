# 환경변수 (Secrets) 발급 가이드

> 사용자(조정승)가 직접 발급. Claude Code는 코드에서 `os.environ`으로 읽기만 함.
> 모든 키는 GitHub repo의 Secrets에 등록 (절대 코드에 ❌).

---

## 등록 위치

GitHub repo `wonwoo-research` → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

---

## 1. DART API 키

**용도**: 금융감독원 전자공시시스템 (재무·공시) 호출

**발급 방법**:
1. https://opendart.fss.or.kr 접속
2. 회원가입 (개인)
3. 인증키 신청 → 사용용도 "투자 분석"
4. 즉시 발급 (40자 영숫자)

**한도**: 일 10,000건 (충분)

**Secret 이름**: `DART_API_KEY`

---

## 2. 텔레그램 API ID + Hash

**용도**: 텔레그램 채널 메시지 자동 수신

**발급 방법**:
1. https://my.telegram.org 접속
2. 본인 텔레그램 계정 휴대폰 번호로 로그인
3. 인증코드 입력 (텔레그램으로 옴)
4. **API development tools** 클릭
5. App 정보 입력:
   - App title: `wonwoo-research`
   - Short name: `wonwoo_research`
   - Platform: `Other`
   - Description: `Personal stock research automation`
6. 생성 → **api_id** (숫자)와 **api_hash** (32자 영숫자) 받음

**Secret 이름**:
- `TELEGRAM_API_ID`
- `TELEGRAM_API_HASH`

⚠️ **이 키는 본인 외 절대 공유 ❌**. 텔레그램 계정 전체 접근 권한.

---

## 3. 텔레그램 Session 문자열

**용도**: 매번 인증코드 받지 않고 자동 로그인

**발급 방법** (1회):

Phase 3의 `scripts/init_telegram_session.py` 실행 (Claude Code가 작성).

```bash
# 본인 PC에서 1회 실행
python scripts/init_telegram_session.py
# → 휴대폰 번호 입력
# → 텔레그램으로 온 인증코드 입력
# → Session 문자열 출력 (긴 base64)
# → GitHub Secrets에 등록
```

**Secret 이름**: `TELEGRAM_SESSION`

⚠️ 이 문자열로 본인 텔레그램에 로그인 가능. **절대 공유 ❌**.

---

## 4. KIS API (한국투자증권)

**용도**: 주가·체결·외인기관 수급

**기존 자산**: TradeBot v5.1에서 사용 중. 같은 키 재활용 가능.

**Secret 이름**:
- `KIS_APP_KEY`
- `KIS_APP_SECRET`
- `KIS_ACCOUNT_NO` (계좌번호, 시세 조회만 하면 옵션)

**주의**: TradeBot과 동시 호출 시 분당 제한 충돌 가능. 호출 시간대 분리 (TradeBot은 09:00~15:30, 본 시스템은 그 외 시간).

---

## 5. Firebase Service Account

**용도**: Firestore (데이터 저장소) 접근

**옵션 A: FocusKit 프로젝트 재활용**
- 기존 Firestore 인스턴스 사용
- 새 컬렉션만 추가 (`reports/`, `financials/` 등)

**옵션 B: 신규 프로젝트**
1. https://console.firebase.google.com 접속
2. **프로젝트 추가** → 이름: `wonwoo-research`
3. **Firestore Database** → 데이터베이스 만들기 → 프로덕션 모드 → asia-northeast3 (서울)
4. **프로젝트 설정** → **서비스 계정** → **새 비공개 키 생성** → JSON 다운로드

**JSON → base64 변환**:
```bash
# Mac/Linux
base64 -i firebase-sa.json | tr -d '\n' > sa.b64

# Windows PowerShell
[Convert]::ToBase64String([IO.File]::ReadAllBytes("firebase-sa.json")) > sa.b64
```

**Secret 이름**: `FIREBASE_SA_BASE64`

---

## 6. PlayMCP 카카오톡 연동

**용도**: 카톡 "나와의 채팅방"으로 산출물 발송

**연결 방법**:
1. https://playmcp.kakao.com 접속
2. 카카오 계정 로그인
3. **도구함**에서 "카카오톡 - 나와의 채팅방 MCP" 추가
4. **Claude.ai 연결**:
   - Claude.ai → Settings → Connectors → Custom Connector
   - PlayMCP 도구함 URL 등록 (PlayMCP에서 발급)
5. Claude.ai 루틴에서 도구 호출 가능

⚠️ 이 단계는 **Claude.ai 루틴이 호출**하는 것. GitHub Actions와 무관.
GitHub Secrets에 등록할 필요 ❌.

---

## 7. KRX 데이터 (선택)

**용도**: 신용잔고·공매도

**기본**: `pykrx` 라이브러리 사용 (별도 키 ❌)

**대안**: 공식 API (https://data.krx.co.kr) — 회원가입 후 발급. `pykrx` 막힐 때만.

**Secret 이름** (사용 시): `KRX_API_KEY`

---

## 📋 최종 등록 체크리스트

GitHub Secrets에 다음 등록 후 Phase 1 시작:

- [ ] `DART_API_KEY`
- [ ] `TELEGRAM_API_ID`
- [ ] `TELEGRAM_API_HASH`
- [ ] `TELEGRAM_SESSION` (Phase 3에서 발급. 일단 나머지부터)
- [ ] `KIS_APP_KEY`
- [ ] `KIS_APP_SECRET`
- [ ] `FIREBASE_SA_BASE64`

PlayMCP 카카오톡은 GitHub Secret 등록 ❌. Claude.ai에서만 연결.

---

## 🛡️ 보안 원칙

- **로그에 키 출력 ❌**: `logger.py`에 마스킹 필터 필수
- **에러 메시지에 키 노출 ❌**
- **`.env` 파일 만들 시 `.gitignore`에 반드시 포함**
- **Secret 노출 의심 시 즉시 재발급**:
  - DART: 인증키 관리에서 재발급
  - 텔레그램 API: my.telegram.org에서 폐기 후 재발급
  - KIS: 토큰 폐기 후 재발급
  - Firebase: SA 키 삭제 후 새로 생성

---

## 💡 GitHub Secrets 등록 팁

- 변수명은 **대문자 + 언더스코어**
- 값 앞뒤 공백 ❌
- Multi-line 값 (Firebase JSON 등)은 base64 인코딩 권장
- 등록 후 수정 ❌, 삭제 후 재등록만 가능
