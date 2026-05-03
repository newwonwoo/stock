# 개인용 역할 조율 MCP 허브 — 설계서 v2.3

> 버전: 2.3 | 작성일: 2026-05-03 | 대상: 조정승(개인 전용) | 단계: 설계 확정

---

## 변경 이력

### v1 → v2
| 항목 | v1 | v2 | 이유 |
|---|---|---|---|
| 배포 | EC2 + Cloudflare Tunnel | **Lambda + API Gateway + DynamoDB** | 도메인 X, 터널 학습 부담 회피, AWS 네이티브 |
| DB | SQLite | **DynamoDB** | Lambda stateless 호환 |
| Tool 개수 | 11개 | **16개** | 자동 스킬 배정 + 세션 복원 추가 |
| 새 세션 복원 | 수동 | **resume_context() 1회 호출** | "새 세션 피곤함" 해결 |
| 공통 실수 시드 | 미정 | **20개 사전 입력** | "전부 다 실수함" 대응 |

### v2 → v2.1 (사용자 피드백 반영)
| 항목 | v2 | v2.1 | 이유 |
|---|---|---|---|
| 자동 스킬 배정 | LLM 점수 + 룰 기반 결정 | **LLM 단독 추천** | 이중 추론 제거. LLM 신뢰. 룰은 사용자 비요구 |
| 공통 실수 시드 | 20개 | **23개** | LLM 자기 편향 3종 추가 |
| 안전 하네스 | 7개 | **8개** | 대안 N개 제시 + 자체 기각 추가 |
| `resume_context` 필드 | 기본 | **+locked_decisions, +harness_rules** | 결정 보존, 거론 금지 항목 명시 |
| 프롬프트 EXECUTION RULES | 기본 | **+anti-overeng, +decision-preservation, +alternatives** | LLM 보수적 편향 차단 |
| 출력 형식 | 기본 | **+대안 비교, +자체 기각된 대안 섹션** | 의사결정 투명성 |

### v2.1 → v2.2 (Pre-mortem / 실패스토리 통합)
| 항목 | v2.1 | v2.2 | 이유 |
|---|---|---|---|
| Tool 개수 | 16개 | **19개** | run_failure_story + apply_premortem_revision + get_premortem_history 추가 |
| Reviewer 서브모드 | 4개 | **5개** | premortem 추가 |
| 코딩 단계 진입 | 즉시 가능 | **실패스토리 자동 트리거 → 사용자 승인 필수** | LLM 긍정 환각 중화 |
| 명령어 | - | **"실패스토리" 고정** | 인자 있으면 명시 검토, 없으면 직전 산출물 |
| 보완 루프 | - | **선택적 보완 + 기본값 전체 채택, 2회 한도** | 항목별 정밀 보완 + 모바일 단순 사용 |
| Phase 상태 | 5개 | **+pending_premortem, +under_revision** | 실패스토리 게이트 추적 |
| 공통 실수 시드 | 23개 | **25개** | planning-optimism + revision-skip 추가 |
| DynamoDB 테이블 | 7개 | **8개** | failure_stories 테이블 추가 |
| 프롬프트 | 5개 | **+3개 신규** | reviewer.premortem / architect.실패보완 / planner.실패보완 |

### v2.2 → v2.3 (메타 리뷰 보완)
| 항목 | v2.2 | v2.3 | 이유 |
|---|---|---|---|
| LOCKED_DECISIONS | 코드 하드코딩 | **DynamoDB Decisions 테이블 동적 관리** | B1 — 새 결정마다 재배포 비현실적 |
| Tool 개수 | 19개 | **20개** | lock_decision tool 추가 |
| DynamoDB 테이블 | 8개 | **9개** | Decisions 테이블 추가 |
| 보완 한도 도달 시 | 강제 통과만 | **자동 record_mistake 호출** | B2 — 학습 강제 |
| revision_count 카운팅 | 프로젝트 전체 누적 | **target_phase × phase 진입시점 이후만** | S2 — 코딩 재진입 시 카운트 누적 방지 |
| 자연어 명령 매핑 | 보장 X | **모든 tool docstring에 한국어 트리거 명시** | S1 — Claude의 매칭 정확도↑ |
| 가정 변경 다운스트림 | Architect/Coder만 | **Designer 추가** | S3 — UI도 가정에 의존 가능 |

---

## 1. 프로젝트 정의 (재확인)

**한 줄**: Claude Code가 직접 호출해서 역할·프롬프트·핸드오프·실수기록·세션복원을 자동화하는 1인용 MCP 서버.

**핵심 가치 3개**:
1. 매번 같은 거 설명 안 함 (역할·프롬프트 자동 매칭)
2. 새 세션 피곤함 해결 (`resume_context` 한 번이면 복원)
3. 같은 실수 반복 차단 (`query_mistakes` 자동 참조)

---

## 2. 5개 역할 (확정)

| # | 역할 | 책임 | 서브모드 | 색상 |
|---|---|---|---|---|
| 1 | **Planner** | 요구사항·분석·문서화·매뉴얼 두 버전 관리 | requirements / docs / manual | `#3B82F6` |
| 2 | **Designer** | UI/UX/카피·화면 명세 형식 준수 | ui / ux / copy / spec | `#EC4899` |
| 3 | **Architect** | 시스템 구조·API·DB·"왜?" 인과 구조 강제 | system / api / data / adr | `#8B5CF6` |
| 4 | **Coder** | 구현·디버그·리팩토링·테스트작성·근본 해결 우선 | implement / debug / refactor / test | `#10B981` |
| 5 | **Reviewer** | 코드 리뷰·검증·품질확인서·보안 사전 점검·실패스토리 | review / verify / qa-doc / security / **premortem** | `#F59E0B` |

### 화면 명세 형식 강제 (Designer)

조정승 님 메모리 기반 규칙:
- 색상은 Claude 재량
- 화면 코드(CM####) 불필요
- 연결은 화살표만 (→ navigate, ← inflow)
- 팝업은 (팝) 표기
- 탭은 (화면명-탭명) 표기
- [화면구조] 섹션 최상단

이 규칙을 Designer 프롬프트에 영어 실행 규칙으로 박아둠.

---

## 3. 자동 스킬 배정 로직 (v2.1 — LLM 단독)

### 3-1. LLM 단독 추천 (`classify_project`)

**v2.1 핵심 변경**: 이중 추론(LLM 점수 → 룰 결정) 제거. LLM이 한 번에 추천 + 근거 출력.

LLM 호출은 **AWS Bedrock Claude**(`anthropic.claude-3-5-sonnet`) 사용.
이유: Lambda에서 가장 가까운 LLM, IAM으로 인증 가능, 외부 API 키 관리 불필요.

LLM 입력 프롬프트 구조:

```python
LLM_PROMPT = """프로젝트 설명을 보고 다음을 한 번에 결정하라.

프로젝트 설명:
{description}

5역할 중 활성화할 역할 + 우선순위 + 근거 + 비활성 역할 + 비활성 사유를 출력.

**제약**:
- planner와 coder는 반드시 포함 (모든 프로젝트의 필수 출발점)
- 활성 역할 평균 3개 권장 (과잉배정 제한)
- 4축 점수(ui_weight, system_complexity, risk_level, verify_intensity)는 참고용으로 함께 출력

**자체 기각 룰**:
- 9역할 같은 폐기된 옵션 거론 금지
- locked_decisions 위반 추천 금지

OUTPUT (JSON only):
{{
  "scores": {{"ui_weight": 0-10, "system_complexity": 0-10, "risk_level": 0-10, "verify_intensity": 0-10}},
  "recommended_roles": [
    {{"role": "planner", "priority": 1, "reason": "구체적 이유"}},
    ...
  ],
  "skipped_roles": [
    {{"role": "designer", "reason": "백엔드만이라 UI 없음"}}
  ]
}}
"""
```

### 3-2. Sanity Check (룰 아님 — 출력 검증)

LLM 응답 받은 후 코드는 **검증만** 수행:
- planner, coder 누락 시 자동 추가 (강제 포함 룰 위반 시)
- 활성 역할 0개 시 에러
- 그 외 LLM 판단 그대로 신뢰

이건 룰 기반 결정이 아니라 **출력 형식 검증**. 의사결정은 LLM이 단독.

### 3-3. 비활성 역할 잠금

`get_prompt(role, purpose, title)` 호출 시:
- 활성 preset에 해당 role 있음 → 정상 반환
- 없음 → `RoleNotActiveError` 반환 + 안내:
  ```
  "designer 역할은 현재 프로젝트에서 비활성. 
   필요하면 unlock_role(project_id='xxx', role='designer', reason='이유') 먼저 호출"
  ```

이게 **Skill 과잉배정 제한**의 실제 구현.

### 3-4. 실패스토리 자동 트리거 (v2.2 → v2.3 강화)

**목적**: LLM 긍정 환각 중화. 코딩 시작 전 6개월 후 실패 시나리오 강제 검토.

#### 트리거 조건
`transition_phase(new_phase='coding')` 호출 시 자동 실행. 다른 phase 전환에는 트리거 없음.

#### 실행 흐름
```
사용자: "코딩 단계로 가자" 또는 transition_phase("coding") 호출
      ↓
[자동] run_failure_story(직전 산출물, project_id) 실행
      ↓
4개 보고서 출력:
  - failure_stories: 구체적 실패 서사 (3개)
  - early_warning_signs: 실제 깨지기 전 관찰 가능한 신호
  - hidden_assumption: 계획이 의존하는 단 하나의 핵심 가정
  - revised_plan: 실패 모드 반영해 다시 쓴 계획
      ↓
phase 상태: pending_premortem (코딩 단계 진입 보류)
      ↓
[명시 질문] "실패스토리 검토 완료. 보완하시겠어요?"
  - "보완해줘" / "전체 보완" → revised_plan 전체 채택 (기본값)
  - "1번 보완해줘" / "가정 보완" → 항목별 부분 보완
  - "통과" / "그대로 진행" → 원본 유지, 코딩 진행
      ↓
[보완 선택 시] phase 상태: under_revision
  → 해당 역할(architect/planner)에게 자동 핸드오프
  → 보완 산출물 받으면 재실행 (최대 2회)
      ↓
[승인 또는 통과] phase 상태: coding 전환
```

#### 명령어 "실패스토리"
사용자가 `transition_phase` 없이도 명시 호출 가능:
- `"실패스토리"` (인자 없음) → 직전 산출물 자동 사용
- `"실패스토리 [계획 텍스트]"` → 명시 입력 검토
- 두 형식 모두 `run_failure_story` tool로 라우팅

#### 보완 루프 (선택적 + 기본값 전체 채택)
| 사용자 입력 | 동작 | 핸드오프 대상 |
|---|---|---|
| "보완해줘" / "전체 보완" | revised_plan 전체 채택 | 직전 phase 역할 |
| "1번 보완" / "스토리1 보완" | failure_stories[0] 관련만 수정 | 직전 phase 역할 |
| "가정 보완" | hidden_assumption 변경, 영향 평가 | planner |
| "경고신호 보완" | early_warning_signs 반영해 수정 | architect |
| "통과" / "그대로" | 원본 유지 | 없음 (coding 진입) |

#### 재검토 한도: 2회 (S2 — phase별 분리 카운팅)
**v2.3 변경**: `revision_count`를 프로젝트 전체가 아닌 **target_phase × phase 진입시점 이후**로만 카운팅.

```python
# v2.2 (잘못된 누적)
revision_count = len(history)

# v2.3 (phase별 + 진입시점 이후)
last_phase_entry = phases_repo.get_entry_time(project_id, target_phase)
revision_count = len([
    s for s in history 
    if s.target_phase == target_phase 
    and s.created_at > last_phase_entry
])
```

**왜**: 코딩 → 리뷰 → 코딩 재진입 시나리오에서 카운트가 0으로 리셋돼야 정상.

#### 한도 도달 시 자동 학습 (B2 — v2.3 신규)
2회 후에도 통과 못 하면:
- "보완 한도 도달. 강제 통과 / 프로젝트 보류 중 선택" 명시 질문
- **사용자가 `force_pass` 선택 시 자동으로 `record_mistake` 호출**:
  ```python
  record_mistake(
    role="reviewer",
    category="premortem-loop-failure",
    description=f"실패스토리 2회 보완 후에도 통과 못 함. project={project_id}",
    root_cause=f"revised_plan과 사용자 결정의 차이: {분석 텍스트}",
    resolution=None  # 미해결 상태로 시작 — 회고 시 추가
  )
  ```
- 다음 프로젝트에서 같은 패턴 발생 시 `query_mistakes(category='premortem-loop-failure')`로 검색됨

**왜**: 강제 통과만 하고 학습 안 하면 같은 패턴 반복. M-SEED-025(revision-skip)의 진화형 막기.

#### 하네스 5(사용자 승인)와의 정합성
- 자동 트리거되는 것: **실패스토리 보고서 출력만**
- 사용자 명시 승인 필요: **phase 전환, 보완 채택, 강제 통과**
- 따라서 하네스 위반 아님. "검토는 자동, 결정은 수동" 패턴.

### 3-5. 단계(Phase) 추적 (v2.2 — 상태 2개 추가)

5단계 + 권장 활성 역할:

| Phase | 권장 역할 | 진입 조건 |
|---|---|---|
| `planning` | Planner | 프로젝트 시작 시 자동 |
| `designing` | Designer (UI 있을 때) | Planner 결과물 승인 후 |
| `architecting` | Architect (복잡할 때) | 설계 결과 승인 후 |
| `pending_premortem` ⭐ | Reviewer (premortem) | coding 진입 시도 시 자동 트리거 |
| `under_revision` ⭐ | architect 또는 planner | 보완 선택 시 |
| `coding` | Coder | pending_premortem 통과 또는 보완 완료 후 |
| `reviewing` | Reviewer (위험/검증 있을 때) | 코딩 완료 후 |

`transition_phase`로 전환 시:
- 이전 phase의 미완료 핸드오프 경고
- 새 phase의 권장 역할 자동 활성화 (이미 활성이면 무시)
- **`new_phase='coding'`인 경우 자동으로 `pending_premortem` 거침**

### 3-6. 워크플로우 (v2.2 — premortem 게이트 포함)

```
[프로젝트 입력]
    ↓
classify_project(설명)
    ↓
LLM 추천 (점수 + 역할 + 근거)
    ↓
draft preset 저장  ← 자동 적용 안 함
    ↓
사용자: "승인해줘"
    ↓
approve_assignment(project_id)
    ↓
active preset 전환
    ↓
phase: planning 시작
    ↓
[Planner 작업 → 핸드오프]
    ↓
transition_phase("designing")
    ↓
[Designer 작업 → 핸드오프] (UI 있을 때)
    ↓
transition_phase("architecting")
    ↓
[Architect 작업 → 핸드오프] (복잡할 때)
    ↓
transition_phase("coding")  ⚠️ 트리거 발생
    ↓
[자동] run_failure_story 실행
    ↓
phase: pending_premortem
    ↓
4개 보고서 출력 + "보완하시겠어요?" 명시 질문
    ↓
사용자 선택:
  ├─ "통과" → phase: coding 전환
  └─ "보완" → phase: under_revision
                ↓
              해당 역할 자동 핸드오프
                ↓
              보완 산출물 → 재실행 (최대 2회)
                ↓
              사용자 승인 → phase: coding 전환
    ↓
[Coder 작업 → 핸드오프]
    ↓
transition_phase("reviewing")
    ↓
[Reviewer 검증 → 품질확인서]
    ↓
프로젝트 완료
```

---

## 4. Tool 명세 (20개 — v2.3)

### 4-0. 한국어 트리거 명시 (v2.3 신규 — S1)

**모든 tool의 docstring에 한국어 트리거 문구를 명시한다.** Claude가 자연어 명령(예: "실패스토리")을 들었을 때 정확한 tool로 라우팅하도록.

형식:
```python
@mcp.tool()
def run_failure_story(...):
    """
    실패스토리(Pre-mortem) 실행. 6개월 후 미래에서 실패 보고.
    
    Trigger phrases (한국어): "실패스토리", "프리모템", "실패 보고서", "위험 분석"
    Trigger phrases (English): "premortem", "failure story", "pre-mortem"
    
    ... (기존 docstring 내용)
    """
```

이 규칙은 20개 tool 모두에 적용. seed/prompts.json 같은 시드 데이터에도 반영.

### 4-1. 읽기 도구 (9개) — Claude 자유 호출

#### `list_roles() -> list[Role]`
모든 역할 메타데이터 (5개 고정).

#### `get_role(role_name: str) -> Role`
특정 역할 상세 + 서브모드 + 색상.

#### `get_prompt(role: str, purpose: str, title: str = None) -> Prompt | list[Prompt]`
프롬프트 반환. **활성 역할만 가능** (잠금 메커니즘).
- title 생략 시 해당 role+purpose의 모든 프롬프트 목록 반환

#### `query_mistakes(role: str = None, category: str = None, keyword: str = None) -> list[Mistake]`
과거 실수 검색. 새 작업 전 자동 호출 권장.

#### `get_handoff(session_id: str) -> HandoffNote`
세션의 직전 핸드오프 메모.

#### `resume_context(project_id: str) -> ResumeBundle` ⭐ NEW (v2.3 갱신)
**새 세션 시 자동 호출.** 반환:
```python
{
  "project": {...},
  "active_preset": {...},
  "current_phase": "coding",
  "last_session": {
    "id": "...",
    "role": "coder",
    "handoff_note": "...",
    "context_percent": 95
  },
  "unresolved_mistakes": [...],
  "locked_decisions": [
    # v2.3: Decisions 테이블에서 동적 로드 (전역 + 프로젝트별 필터)
    # 시드된 7개 + lock_decision으로 추가된 모든 결정
    "역할은 5개 (planner/designer/architect/coder/reviewer)",
    "9역할 구성 폐기 — 재논의 금지",
    "PostgreSQL 폐기, DynamoDB 채택",
    "EC2 + 터널 폐기, Lambda + APIGW 채택",
    "Replit 코드 폐기",
    "역할 배정은 LLM 단독 추천 (룰 기반 폐기)",
    "코딩 단계 진입 전 실패스토리 자동 트리거 — 사용자 승인 후 진행",
    # 사용자가 추가한 결정들...
  ],
  "harness_rules": [
    "1. 의도 고정",
    "2. 역할 경계",
    "3. Skill 과잉배정 제한",
    "4. 위험 변경 제한",
    "5. 사용자 승인",
    "6. 세션 승계",
    "7. 반복 실수 기록",
    "8. 대안 N개 + 자체 기각"
  ],
  "suggested_next_action": "직전 세션 핸드오프 확인 후 reviewer 단계 진입"
}
```

**v2.3 변경**: `locked_decisions`는 Decisions 테이블에서 동적 로드.
- 전역(scope=global) + 해당 project_id(scope=project, active=true) 결정 모두 포함
- `lock_decision` tool로 새 결정 추가 시 즉시 반영 (재배포 0번)
- `harness_rules`는 8개 고정 (코드 상수 유지)

#### `get_current_phase(project_id: str) -> Phase`
현재 단계 + 활성 역할 + 권장 다음 행동.

#### `list_active_presets() -> list[Preset]`
현재 active 상태인 프리셋 전체 목록.

#### `get_premortem_history(project_id: str) -> list[FailureStory]` ⭐ NEW (v2.2)
프로젝트의 실패스토리 보완 이력 조회.
- 각 회차의 4개 보고서, 사용자 선택, 보완 결과, 통과/보류 여부
- 디버깅·회고용

### 4-2. 쓰기 도구 (10개) — 사용자 명시 요청 시만 (단 run_failure_story는 transition_phase 자동 트리거)

#### `classify_project(description: str) -> ClassificationDraft`
LLM 단독 추천 + draft 저장. 자동 활성화 안 됨.

#### `approve_assignment(project_id: str) -> Preset`
draft → active 승격.

#### `transition_phase(project_id: str, new_phase: str, reason: str) -> Phase` ⭐ CHANGED (v2.2)
단계 전환. 권장 역할 자동 활성화.
**v2.2 변경**: `new_phase='coding'`인 경우 자동으로 `run_failure_story` 호출 → `pending_premortem` 상태로 전환. 사용자 승인 후에야 실제 coding으로 진입.

#### `unlock_role(project_id: str, role: str, reason: str) -> Preset`
비활성 역할 임시 활성화.

#### `save_handoff(from_role: str, to_role: str, summary: str, context: dict = None, blockers: list = None) -> HandoffNote`
핸드오프 저장.

#### `record_mistake(role: str, category: str, description: str, root_cause: str = None, resolution: str = None) -> Mistake`
실수 기록. root_cause 필수.

#### `start_session(project_id: str, role: str) -> Session`
새 세션 시작.

#### `update_context(session_id: str, percent: int) -> Session`
컨텍스트 사용률 갱신.

#### `run_failure_story(project_id: str, plan_text: str = None, target_phase: str = "coding") -> FailureStoryReport` ⭐ NEW (v2.2)
실패스토리(Pre-mortem) 실행. LLM에게 6개월 후 미래에서 실패 보고하게 함.

**호출 경로**:
1. `transition_phase('coding')` 자동 트리거 (plan_text 비움 → 직전 산출물 자동 사용)
2. 사용자 명시 호출 ("실패스토리" 명령) — plan_text 있으면 그대로 사용, 없으면 직전 산출물

반환:
```python
{
  "story_id": "uuid",
  "project_id": "...",
  "target_phase": "coding",
  "stories": [
    "구체적 실패 서사 1 (한 단락)",
    "구체적 실패 서사 2",
    "구체적 실패 서사 3"
  ],
  "warnings": [
    "관찰 가능한 신호 1",
    "관찰 가능한 신호 2"
  ],
  "assumption": "계획이 의존하는 단 하나의 핵심 가정",
  "revised_plan": "실패 모드 반영한 재작성 계획",
  "revision_count": 0,
  "status": "pending"  # pending | revised | passed | forced
}
```

#### `apply_premortem_revision(project_id: str, story_id: str, mode: str, target_items: list = None) -> dict` ⭐ NEW (v2.2)
실패스토리 보완 결정 적용.

**mode 값**:
- `"revise_all"` — revised_plan 전체 채택. 직전 phase 역할에 핸드오프 (기본값)
- `"revise_partial"` — target_items 지정 항목만 보완. 항목별로 적절한 역할에 핸드오프
- `"pass"` — 원본 유지. 코딩 진행
- `"force_pass"` — 보완 한도 도달 후 강제 통과 (2회 후만 사용)

**target_items 예시** (mode=revise_partial 시):
- `["story_1"]` — 첫 번째 실패스토리만
- `["assumption"]` — hidden_assumption만 (planner로)
- `["warning_2", "story_3"]` — 복수 항목

반환:
```python
{
  "story_id": "...",
  "mode_applied": "revise_partial",
  "handoff_target": "architect",  # 또는 planner / null
  "revision_count": 1,
  "remaining_attempts": 1,  # 2회 한도 - 사용 회수
  "next_action": "architect가 보완 완료 후 run_failure_story 재실행 권장",
  "phase_status": "under_revision"
}
```

---

## 4-3. Tool 시그니처 요약 (20개 — v2.3)

| # | Tool | 입력 | 출력 | 잠금? | v2.2/v2.3 |
|---|---|---|---|---|---|
| 1 | `list_roles` | - | List[Role] | X | |
| 2 | `get_role` | role_name | Role | X | |
| 3 | `get_prompt` | role, purpose, title?, project_id? | Prompt or List | ✅ | |
| 4 | `query_mistakes` | role?, category?, keyword? | List[Mistake] | X | |
| 5 | `get_handoff` | session_id | HandoffNote | X | |
| 6 | `resume_context` | project_id | ResumeBundle | X | 🔄 v2.3 |
| 7 | `get_current_phase` | project_id | Phase | X | |
| 8 | `list_active_presets` | - | List[Preset] | X | |
| 9 | `get_premortem_history` | project_id | List[FailureStory] | X | ⭐ v2.2 |
| 10 | `classify_project` | description | ClassificationDraft | - | |
| 11 | `approve_assignment` | project_id | Preset | - | |
| 12 | `transition_phase` | project_id, new_phase, reason | Phase | - | 🔄 v2.2 |
| 13 | `unlock_role` | project_id, role, reason | Preset | - | |
| 14 | `save_handoff` | from_role, to_role, summary, context?, blockers? | HandoffNote | - | |
| 15 | `record_mistake` | role, category, description, root_cause?, resolution? | Mistake | - | |
| 16 | `start_session` | project_id, role | Session | - | |
| 17 | `update_context` | session_id, percent | Session | - | |
| 18 | `run_failure_story` | project_id, plan_text?, target_phase? | FailureStoryReport | - | ⭐ v2.2 |
| 19 | `apply_premortem_revision` | project_id, story_id, mode, target_items? | dict | - | ⭐ v2.2 |
| 20 | `lock_decision` | text, project_id?, scope? | Decision | - | ⭐ v2.3 |

⭐ = 신규 / 🔄 = 동작 변경

---

## 4-4. v2.3 신규 tool 명세

#### `lock_decision(text: str, project_id: str = None, scope: str = "global") -> Decision` ⭐ NEW (v2.3)

확정된 결정사항을 동적으로 추가/관리. 코드 재배포 없이 채팅으로 결정 잠금.

**한국어 트리거**: "결정 잠가줘", "이거 락 걸어", "lock decision", "결정사항 추가"

**Args**:
- `text`: 결정 내용 (예: "프롬프트는 한국어 우선")
- `project_id`: 특정 프로젝트 한정 (None이면 전역)
- `scope`: "global" (모든 프로젝트) | "project" (해당 project_id만)

**Returns**:
```python
{
  "decision_id": "uuid",
  "text": "프롬프트는 한국어 우선",
  "project_id": null,
  "scope": "global",
  "created_at": "2026-05-03T...",
  "active": true
}
```

**Side Effects**:
- Decisions 테이블에 행 추가
- 다음 `resume_context` 호출 시 `locked_decisions` 배열에 자동 포함

**Use cases**:
- 사용자: "이 결정 잠가줘: API 응답은 200ms 이내" → tool 호출
- 사용자: "프로젝트 X에서만: 모바일 우선 반응형" → scope="project", project_id=X

---

## 5. 데이터 모델 (DynamoDB, 9개 테이블 — v2.3)

### 5-1. Roles
```
PK: role_name (planner, designer, architect, coder, reviewer)
Attributes: display_name, description, color, submodes (list), default_active (bool)
```

5개 행 시드.

### 5-2. Prompts
```
PK: role_name
SK: purpose#title          (예: "workflow#requirements_정리")
Attributes: content, lang, version, created_at, updated_at, exec_rules (list)
```

GSI: `purpose-index` (purpose별 조회).

### 5-3. Projects
```
PK: project_id (uuid)
Attributes: name, description, created_at, current_phase, owner
```

### 5-4. Presets
```
PK: project_id
SK: created_at#status      (예: "2026-05-03T10:00:00#draft")
Attributes: scores, role_assignments (list), status, approved_at, activated_at
```

### 5-5. Sessions
```
PK: session_id (uuid)
Attributes: project_id, role_name, started_at, ended_at, context_percent, handoff_note
```

GSI: `project-time-index` (project_id, started_at) — 최근 세션 조회.

### 5-6. Mistakes
```
PK: mistake_id (uuid)
Attributes: role_name, category, description, root_cause, resolution, resolved_at, created_at
```

GSI: `role-category-index` (role_name, category) — 카테고리별 검색.

### 5-7. Phases
```
PK: project_id
SK: phase_name (planning|designing|architecting|pending_premortem|under_revision|coding|reviewing)
Attributes: started_at, ended_at, status (active|completed|skipped), reason_skipped
```

### 5-8. FailureStories
```
PK: project_id
SK: created_at  (ISO 8601 timestamp)
Attributes:
  - story_id (uuid)
  - target_phase (예: "coding")
  - source_artifact (어떤 산출물 검토했는지)
  - stories (list of strings, 3개 권장)
  - warnings (list of strings)
  - assumption (string, 핵심 가정 1개)
  - revised_plan (string)
  - revision_count (int, 0~2)
  - status (pending | revised | passed | forced)
  - user_decision (revise_all | revise_partial | pass | force_pass | null)
  - target_items (list, partial 시 사용)
  - applied_at (timestamp)
```

GSI: `project-status-index` (project_id, status) — 보류 중 보고서 조회.

### 5-9. Decisions ⭐ NEW (v2.3)
```
PK: decision_id (uuid)
Attributes:
  - text (string, 결정 내용)
  - scope (global | project)
  - project_id (string, scope=project일 때만)
  - active (bool, 기본 true)
  - created_at (timestamp)
  - revoked_at (timestamp, 무효화 시)
  - source (system_seed | user_lock)  # 시드 7개는 system_seed
```

GSI: `scope-active-index` (scope, active) — `resume_context`가 빠르게 active 결정만 조회.

**시드 7개**: 기존 LOCKED_DECISIONS 7개를 source="system_seed"로 시드. 사용자가 `lock_decision` 호출하면 source="user_lock"으로 추가.

**무효화**: 결정 폐기 시 `revoked_at` 기록 + `active=false`. 삭제하지 않음 (감사 로그).

---

## 6. 공통 실수 시드 25개 (사전 입력 — v2.2)

조정승 님 메모리 + 본 프로젝트 진행 중 발견된 LLM 편향. mistakes 테이블에 시드.

| # | 카테고리 | description | root_cause |
|---|---|---|---|
| 1 | timezone | KST/UTC 혼용으로 시간 계산 오류 | datetime 객체에 timezone 정보 명시 안 함 |
| 2 | encoding | JSON 템플릿에 한국어 주석 → 파싱 실패 | JSON 표준은 주석 미지원 |
| 3 | verification | syntax check만으로 NameError 못 잡음 | ast.parse는 정의되지 않은 변수 사용 못 잡음 |
| 4 | environment | mock vs real API 도메인/URL 차이 | 환경 분기 로직 누락 |
| 5 | dependency | 라이브러리 버전별 메서드 누락 (예: THREE r142 미만 CapsuleGeometry) | requirements.txt 버전 미고정 |
| 6 | async | race condition 미점검 | 동시 요청 가능성 무시 |
| 7 | env_var | 빈 환경변수 체크 누락 | os.environ.get(default=None) 그대로 사용 |
| 8 | refactor | 리팩토링 후 구 import 잔존 | grep으로 사용처 전체 검색 안 함 |
| 9 | data | UTC vs KST 타임스탬프 → 캔들 데이터 부족 | 데이터 소스의 시간대 미확인 |
| 10 | api | KIS API mock/real 도메인 mismatch | 환경별 base_url 분리 안 함 |
| 11 | error_handling | 예외 swallowing (try/except: pass) | 디버깅 곤란 |
| 12 | naming | 클래스/함수 이름 비일관 | 명명 규칙 합의 없음 |
| 13 | scope | 함수 내부 변수가 외부에서 사용 | 스코프 미파악 |
| 14 | concurrency | 파일 동시 접근 락 누락 | 단일 사용자 가정 |
| 15 | logging | 민감정보 로그 출력 | 로그 마스킹 미구현 |
| 16 | input_validation | 사용자 입력 검증 없이 DB 쿼리 | SQL injection 가능성 |
| 17 | performance | N+1 쿼리 패턴 | ORM 동작 이해 부족 |
| 18 | docs | 매뉴얼 두 버전(유지보수/사용자) 동시 갱신 누락 | 문서화 워크플로우 부재 |
| 19 | testing | 정상 케이스만 테스트, 엣지 누락 | 테스트 케이스 설계 미흡 |
| 20 | deployment | 환경변수 누락 상태로 배포 | 프리플라이트 체크 없음 |
| 21 | over-engineering | 사용자가 시키지 않은 안전장치를 자기 판단으로 추가 | LLM의 보수적 편향. 신뢰할 단계에 검증을 또 끼워넣음 |
| 22 | decision-erosion | 이미 확정된 결정사항을 예시·가정·우려 형태로 다시 거론해 결정을 흐림 | LLM이 '혹시 모르니' 옛 옵션을 보존하려는 편향 |
| 23 | alternative-generation | 단일 안만 제시. 대안 비교 없이 결정 강요 | LLM이 자기 추론을 정답으로 제시하는 편향 |
| **24** | **planning-optimism** | **계획 검토 시 낙관 편향. 실패 모드를 추상적으로만 언급** | **LLM이 자기 산출물을 옹호하려는 경향. "잘 될 것" 가정 강함** |
| **25** | **revision-skip** | **실패스토리만 받고 보완 없이 코딩 시작** | **보고서를 의식만 하고 행동 변경 안 함. 보완 루프 강제 필요** |

### v2.2 신규 시드 24-25 상세

**M-SEED-024 (planning-optimism)**
- 예시: 계획 리뷰 시 "이런 위험 있을 수 있음" 추상적 언급만, 6개월 후 구체적 실패 서사 없음
- 회피: 코딩 진입 전 `run_failure_story` 자동 트리거. 4개 보고서 강제 출력

**M-SEED-025 (revision-skip)**
- 예시: 실패스토리 보고서 받고 "오 좋네" 한 후 그대로 코딩 시작. revised_plan 무시
- 회피: `apply_premortem_revision` 호출 강제. mode=pass도 명시 결정이어야 함

---

## 7. 기술 스택

| 영역 | 선택 | 근거 |
|---|---|---|
| 언어 | Python 3.12 | TradeBot 동일 |
| MCP SDK | FastMCP (`mcp[cli]>=1.2.0`) | 공식 SDK |
| Lambda Runtime | Python 3.12 | AWS 기본 지원 |
| Web Adapter | AWS Lambda Web Adapter | FastMCP HTTP 서버를 Lambda에서 그대로 실행 |
| DB | DynamoDB (boto3) | Lambda 호환, 무료티어 |
| LLM | AWS Bedrock Claude 3.5 Sonnet | Lambda 동일 리전, IAM 인증 |
| API Gateway | HTTP API (REST 아님) | 비용 1/3, MCP 충분 |
| Auth | API Key (헤더) | 1인용 |
| 배포 도구 | AWS SAM (Serverless Application Model) | YAML로 인프라 + Lambda 함께 정의 |

### `requirements.txt`
```
mcp[cli]>=1.2.0
boto3>=1.35.0
python-dotenv>=1.0.0
```

---

## 8. 배포 구조 (Lambda + API Gateway + DynamoDB)

```
[Claude Code 웹 / 모바일 앱]
    ↓ HTTPS POST
[API Gateway HTTP API]
    ↓
[Lambda Function: mcp-hub]
    ↓ boto3
    ├── [DynamoDB] (7 tables)
    └── [Bedrock] (Claude 3.5 Sonnet, classify_project 시)
```

### URL 형식 (도메인 불필요)

```
https://abc123xyz.execute-api.ap-northeast-2.amazonaws.com/prod/mcp
```

이 URL을 `claude.ai/customize/connectors`에 등록 → 자동 연동.

### SAM 템플릿 (`template.yaml` 핵심)

```yaml
AWSTemplateFormatVersion: '2010-09-09'
Transform: AWS::Serverless-2016-10-31

Resources:
  McpHubFunction:
    Type: AWS::Serverless::Function
    Properties:
      Runtime: python3.12
      MemorySize: 512
      Timeout: 30
      Environment:
        Variables:
          API_KEY: !Ref McpApiKey
          BEDROCK_MODEL: anthropic.claude-3-5-sonnet-20241022-v2:0
      Layers:
        - arn:aws:lambda:ap-northeast-2:753240598075:layer:LambdaAdapterLayerX86:24
      Events:
        McpEndpoint:
          Type: HttpApi
          Properties:
            Path: /mcp
            Method: ANY
      Policies:
        - DynamoDBCrudPolicy:
            TableName: !Ref RolesTable
        # ... (각 테이블별 권한)
        - Statement:
            - Effect: Allow
              Action: bedrock:InvokeModel
              Resource: arn:aws:bedrock:ap-northeast-2::foundation-model/*
  
  RolesTable:
    Type: AWS::Serverless::SimpleTable
    Properties:
      PrimaryKey:
        Name: role_name
        Type: String
  
  # ... (Prompts, Projects, Presets, Sessions, Mistakes, Phases)
```

전체 SAM 템플릿은 인계 명세서에 포함.

### 배포 명령

```bash
# 1회만
pip install aws-sam-cli

# 매 배포
sam build
sam deploy --guided  # 첫 배포만
sam deploy           # 이후
```

배포 시간: 약 3-5분.

---

## 9. 비용 추정 (월간)

| 항목 | 무료티어 | 예상 사용 | 초과 비용 |
|---|---|---|---|
| Lambda 호출 | 100만 호출 | 1만 호출/월 | $0 |
| Lambda 실행시간 | 40만 GB-초 | 5만 GB-초 | $0 |
| API Gateway | 100만 호출 | 1만 호출 | $0 |
| DynamoDB 쓰기 | 25 WCU | 평균 1 WCU | $0 |
| DynamoDB 읽기 | 25 RCU | 평균 2 RCU | $0 |
| DynamoDB 저장 | 25GB | <100MB | $0 |
| Bedrock Claude 3.5 | 무료티어 없음 | classify 호출 100회/월, 평균 1500토큰 | ~$0.5 |

**총 예상**: 월 $0.5 ~ $1. 거의 무료.

---

## 10. 8가지 안전 하네스 (v2.1 — 1개 추가)

| # | 하네스 | v2.1 구현 |
|---|---|---|
| 1 | **의도 고정** | classify_project → draft 저장. activate 별도 |
| 2 | **역할 경계** | 5역할 고정 + 비활성 잠금 |
| 3 | **Skill 과잉배정 제한** | LLM 추천 + 활성 평균 3개 가이드 |
| 4 | **위험 변경 제한** | 쓰기 도구 모두 사용자 명시 요청 |
| 5 | **사용자 승인** | approve_assignment 명시 호출 |
| 6 | **세션 승계** | resume_context 1회 호출 + auto checkpoint |
| 7 | **반복 실수 기록** | mistakes 23개 시드 + root_cause 필수 |
| **8** | **대안 N개 + 자체 기각** | **모든 의사결정에 대안 ≥2개. 하네스 위반 대안은 자체 기각하고 제시 안 함** |

### 하네스 8 상세

**규칙**:
- 모든 의사결정형 출력은 **대안 ≥2개** 제시 + 각 트레이드오프 명시
- 단, **확정된 하네스/locked_decisions를 위반하는 대안은 자체 기각** (제시 자체 안 함)
- 자체 기각된 대안은 "다른 대안은 하네스 위반으로 자체 기각됨" 한 줄로만 명시

**적용 대상 tool**:
- classify_project (역할 추천 시)
- 모든 프롬프트 출력 (Architect, Reviewer, Planner)

**예시**:
```
## 대안 비교
### 대안 A: Lambda + DynamoDB
- 트레이드오프: 콜드스타트 2-3초 / 무료티어 충분 / SAM 학습 필요

### 대안 B: ECS Fargate
- 트레이드오프: 콜드스타트 없음 / 월 $15 / 컨테이너 빌드 워크플로우 추가

## 자체 기각된 대안
- EC2 + 터널: locked_decisions 위반 (v2에서 폐기)
- PostgreSQL: locked_decisions 위반 (v2에서 폐기)

## 추천: A
근거: 1인용·저빈도 호출이라 콜드스타트 허용 가능. 비용 0.
```

---

## 11. MVP 개발 단계 (Phase 1-4)

### Phase 1: 인프라 + 코어 (3일)
- [ ] SAM 프로젝트 초기화
- [ ] DynamoDB 7테이블 정의
- [ ] Lambda 함수 골격 + Web Adapter 연동
- [ ] FastMCP 서버 골격
- [ ] roles 시드 (5개)
- [ ] mistakes 시드 (20개)

### Phase 2: Tool 구현 (4일)
- [ ] 읽기 도구 8개
- [ ] 쓰기 도구 8개
- [ ] Bedrock 연동 (classify_project)
- [ ] 비활성 역할 잠금 로직
- [ ] phase 자동 전환 로직

### Phase 3: 배포 + 연결 (1일)
- [ ] SAM deploy
- [ ] API Key 발급
- [ ] claude.ai 커넥터 등록
- [ ] 연결 테스트 (16개 tool 모두)

### Phase 4: 검증 + 시드 (1일)
- [ ] 코드 검증 프로토콜 적용 (ast.parse → import → mock → grep)
- [ ] 품질확인서 자동 생성
- [ ] 사용자 프롬프트 입력 (조정승 님이 직접)

**총 9일** (저녁 작업 기준).

---

## 12. 검증 기준 (품질확인서 항목)

### 기능 적합성
- [ ] 16개 tool 전부 정상 동작
- [ ] classify_project 4축 점수 합리적
- [ ] 비활성 역할 잠금 동작
- [ ] phase 전환 자동 활성화 동작
- [ ] resume_context 1회 호출로 직전 상태 복원
- [ ] mistakes 시드 20개 query_mistakes에서 검색됨

### 코드 품질
- [ ] ast.parse 통과
- [ ] import 검증 통과 (모든 모듈 로드)
- [ ] grep으로 정의되지 않은 변수 없음 확인
- [ ] mock 실행 — 각 tool 독립 호출 통과
- [ ] root_cause 필드 누락 시 record_mistake 거부 (강제 검증)

### 운영
- [ ] sam deploy 성공
- [ ] API Gateway HTTPS 응답 정상
- [ ] DynamoDB 무료티어 안 초과 확인
- [ ] Bedrock 호출 성공 (classify_project)
- [ ] claude.ai 커넥터 16개 tool 모두 인식

### 보안
- [ ] API Key 인증 동작
- [ ] DynamoDB IAM 정책 최소 권한
- [ ] 환경변수 SAM 파라미터로만 주입
- [ ] CloudTrail 로깅 활성화

---

## 13. 리스크 + 완화

| 리스크 | 완화 |
|---|---|
| Lambda 콜드스타트 (첫 호출 2-3초) | Lambda Provisioned Concurrency 1개 (월 $5 추가). MVP는 미사용 |
| Bedrock 응답 느림 (classify_project) | 30초 타임아웃 설정. 실패 시 사용자가 수동 입력 |
| DynamoDB 무료티어 초과 | CloudWatch 알람 (RCU/WCU 80% 시 경고) |
| API Key 유출 | SAM 파라미터로만 관리. git 커밋 절대 금지. 분기별 회전 |
| Claude가 쓰기 도구 마음대로 호출 | tool description에 "사용자 명시 요청 시만" 명기 |
| classify_project LLM 잘못 추천 | draft 게이트가 안전망. 사용자가 reject 가능 |
| MCP 스펙 변경 | FastMCP 버전 고정. 분기별 업데이트 검토 |

---

## 14. 다음 단계

이 v2 설계서 + 대표 프롬프트 5개 + Claude Code 인계 명세서 = 한 세트.
검토 후 Claude Code에게 그대로 전달하면 즉시 개발 진입 가능.

---

*문서 버전 v2.0. 변경 시 v2.1로 증가.*
