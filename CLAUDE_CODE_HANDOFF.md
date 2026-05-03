# Claude Code 인계 명세서 — MCP 허브 개발

> 이 문서를 그대로 Claude Code에게 전달하면 처음부터 끝까지 개발 가능.
>
> **함께 전달할 파일**:
> - `MCP_HUB_DESIGN_v2.md` (설계서)
> - `PROMPTS_v1.md` (프롬프트 5개 + 슬롯 매트릭스)
> - 이 파일 (`CLAUDE_CODE_HANDOFF.md`)

---

## 0. Claude Code에게 — 시작 전 필수 행동

이 프로젝트는 조정승 님 개인용 MCP 허브 개발 작업이다. 시작 전 다음을 반드시 실행하라.

### 0-1. 사용자 정보 확인
- 환경: AWS (ap-northeast-2 Seoul 리전), 기존 EC2에 TradeBot 운영 중 (43.201.133.119)
- 워크플로우: 분석 → 설계 → 개발 → 검증 → 피드백
- 코딩 스타일: vibe coding (모바일 위주)
- 코딩 원칙: 근본 해결 우선, 코드 검증 4단계 (ast.parse → import → mock → grep)
- 매뉴얼: 항상 2버전 (유지보수용 + 사용자용)
- 세션 종료 멘트 금지: 작업 진행 중 wrap-up 표현 사용 안 함

### 0-2. 분석/설계는 이미 끝났다
이 프로젝트는 분석·설계 단계가 완료된 상태다. **너는 개발(Phase 1-4)부터 시작한다.**
설계 변경이 필요하다고 판단되면 작업 시작 전 사용자 승인 받아라. 임의로 변경 금지.

### 0-3. 코딩 원칙 (MUST)
- 근본 원인 해결 (workaround 금지, error 숨김 금지)
- 코드 작성 후 4단계 검증 자동 실행 (ast.parse → import 검증 → mock 실행 → grep)
- 함수 1개 = 책임 1개
- 주석에 평문 설명 포함 (vibe coder가 읽기 위함)

### 0-3-1. v2.1 신규 원칙 (MUST — 사용자 핵심 요구)
- **사용자가 명시하지 않은 안전장치/룰을 추가하지 않는다.** 추가하고 싶으면 먼저 물어본다.
- **확정된 결정사항(locked_decisions)을 예시·가정으로도 거론하지 않는다.**
- **모든 의사결정에 대안 ≥2개 + 트레이드오프 + 자체 기각 대안 명시.** 단 하네스/locked_decisions 위반 대안은 제시 자체 금지.
- 이 3원칙 위반은 mistakes M-SEED-021/022/023에 해당. 발견 시 즉시 record_mistake 호출.

### 0-3-2. v2.2 신규 원칙 (MUST — 실패스토리 게이트)
- **`transition_phase(new_phase='coding')` 호출 시 `run_failure_story` 자동 트리거.** 즉시 coding으로 못 감.
- 자동 트리거 후 **phase는 `pending_premortem` 상태로 보류**. 사용자 명시 결정(`apply_premortem_revision`) 받기 전엔 coding 진입 금지.
- 사용자 결정 옵션: `revise_all` / `revise_partial` / `pass` / `force_pass`(2회 한도 후만).
- 보완 루프 한도 2회. 초과 시 강제 통과 또는 보류 사용자 명시 선택.
- "실패스토리" 명령은 사용자가 명시 호출 가능 (인자 있음/없음 모두 `run_failure_story`로 라우팅).
- 이 원칙 위반은 M-SEED-024(planning-optimism), M-SEED-025(revision-skip)에 해당.

### 0-3-3. v2.3 신규 원칙 (MUST — 메타 리뷰 보완)
- **LOCKED_DECISIONS는 코드 상수가 아니라 Decisions 테이블에서 동적 로드.** 새 결정 추가는 `lock_decision` tool 호출.
- **모든 tool docstring에 한국어 트리거 문구 명시.** Claude가 자연어 명령을 정확한 tool로 라우팅.
- **revision_count는 target_phase × phase 진입시점 이후로만 카운팅.** 코딩 재진입 시 0으로 리셋되도록.
- **`force_pass` 시 자동 `record_mistake` 호출.** 보완 실패 패턴을 mistakes 테이블에 학습.
- **가정 변경(hidden_assumption) 시 Designer 다운스트림 영향 평가 필수.** UI도 가정에 의존 가능.

### 0-4. 인계 후 첫 응답 형식
시작 전 사용자에게 다음 확인 메시지를 보내라:
```
이 명세서 받았습니다. 다음을 확인하고 시작합니다:
- AWS 계정 IAM 권한: SAM deploy + DynamoDB CRUD + Bedrock InvokeModel
- 기존 EC2 영향 없음 (별도 Lambda)
- 첫 배포는 dev stage 후 prod 분리 — 진행할까요?
```

---

## 1. 프로젝트 개요

### 1-1. 한 줄 정의
Claude Code가 직접 호출해서 역할·프롬프트·핸드오프·실수기록·세션복원을 자동화하는 1인용 MCP 서버.

### 1-2. 핵심 가치
1. 매번 같은 거 설명 안 함 (역할·프롬프트 자동 매칭)
2. 새 세션 피곤함 해결 (`resume_context` 한 번 호출로 직전 상태 복원)
3. 같은 실수 반복 차단 (`query_mistakes` + 시드 20개)

### 1-3. 결정 사항 (변경 금지)
- 5개 역할 고정: Planner / Designer / Architect / Coder / Reviewer
- 16개 tool
- DynamoDB 7테이블
- Lambda + API Gateway HTTP API + Bedrock Claude 3.5 Sonnet
- API Key 인증 (단일 키)
- ap-northeast-2 (Seoul) 리전

---

## 2. 프로젝트 구조 (생성)

```
mcp-hub/
├── template.yaml              # SAM 템플릿
├── samconfig.toml             # SAM 배포 설정
├── requirements.txt
├── .gitignore
├── .env.example
├── Makefile
├── README.md                  # 사용자용 매뉴얼
├── README_DEV.md              # 유지보수용 매뉴얼
│
├── src/
│   ├── __init__.py
│   ├── handler.py             # Lambda 진입점 (Lambda Web Adapter용)
│   ├── server.py              # FastMCP 서버 정의
│   ├── config.py              # 환경변수 로드
│   │
│   ├── tools/                 # 16개 tool 구현
│   │   ├── __init__.py
│   │   ├── roles.py           # list_roles, get_role
│   │   ├── prompts.py         # get_prompt
│   │   ├── projects.py        # classify_project, approve_assignment
│   │   ├── presets.py         # list_active_presets, unlock_role
│   │   ├── phases.py          # get_current_phase, transition_phase
│   │   ├── sessions.py        # start_session, update_context, resume_context
│   │   ├── handoffs.py        # save_handoff, get_handoff
│   │   └── mistakes.py        # record_mistake, query_mistakes
│   │
│   ├── db/
│   │   ├── __init__.py
│   │   ├── client.py          # boto3 DynamoDB 클라이언트
│   │   ├── repositories/      # 테이블별 CRUD
│   │   │   ├── roles.py
│   │   │   ├── prompts.py
│   │   │   ├── projects.py
│   │   │   ├── presets.py
│   │   │   ├── sessions.py
│   │   │   ├── mistakes.py
│   │   │   └── phases.py
│   │   └── models.py          # Pydantic 모델
│   │
│   ├── llm/
│   │   ├── __init__.py
│   │   └── bedrock.py         # Bedrock Claude 호출 (classify_project 용)
│   │
│   └── lib/
│       ├── __init__.py
│       ├── auth.py            # API Key 검증
│       ├── errors.py          # 커스텀 예외
│       └── verify.py          # 코드 검증 4단계 헬퍼
│
├── seeds/
│   ├── roles.json             # 5개 역할 시드
│   ├── mistakes.json          # 20개 공통 실수 시드
│   └── prompts.json           # 5개 대표 프롬프트 시드 (PROMPTS_v1.md에서 변환)
│
├── scripts/
│   ├── seed_db.py             # 시드 데이터 입력
│   ├── verify_code.py         # 코드 검증 4단계 자동화
│   └── test_tools.py          # 16개 tool 호출 테스트
│
└── tests/
    ├── __init__.py
    ├── conftest.py
    ├── test_tools.py
    ├── test_classification.py
    └── test_lock.py           # 비활성 역할 잠금 테스트
```

---

## 3. SAM 템플릿 (`template.yaml`)

```yaml
AWSTemplateFormatVersion: '2010-09-09'
Transform: AWS::Serverless-2016-10-31

Description: Personal MCP Hub for Cho Jeongseung

Parameters:
  ApiKey:
    Type: String
    NoEcho: true
    Description: API Key for authentication
  
  Stage:
    Type: String
    Default: dev
    AllowedValues: [dev, prod]

Globals:
  Function:
    Runtime: python3.12
    Timeout: 30
    MemorySize: 512
    Environment:
      Variables:
        STAGE: !Ref Stage
        API_KEY: !Ref ApiKey
        BEDROCK_MODEL: anthropic.claude-3-5-sonnet-20241022-v2:0
        AWS_LAMBDA_EXEC_WRAPPER: /opt/bootstrap

Resources:
  # ============ Lambda Function ============
  McpHubFunction:
    Type: AWS::Serverless::Function
    Properties:
      FunctionName: !Sub mcp-hub-${Stage}
      CodeUri: src/
      Handler: run.sh
      Layers:
        - !Sub arn:aws:lambda:${AWS::Region}:753240598075:layer:LambdaAdapterLayerX86:24
      Environment:
        Variables:
          PORT: '8080'
          AWS_LAMBDA_EXEC_WRAPPER: /opt/bootstrap
          ROLES_TABLE: !Ref RolesTable
          PROMPTS_TABLE: !Ref PromptsTable
          PROJECTS_TABLE: !Ref ProjectsTable
          PRESETS_TABLE: !Ref PresetsTable
          SESSIONS_TABLE: !Ref SessionsTable
          MISTAKES_TABLE: !Ref MistakesTable
          PHASES_TABLE: !Ref PhasesTable
      Events:
        McpEndpoint:
          Type: HttpApi
          Properties:
            ApiId: !Ref McpHubApi
            Path: /{proxy+}
            Method: ANY
      Policies:
        - DynamoDBCrudPolicy:
            TableName: !Ref RolesTable
        - DynamoDBCrudPolicy:
            TableName: !Ref PromptsTable
        - DynamoDBCrudPolicy:
            TableName: !Ref ProjectsTable
        - DynamoDBCrudPolicy:
            TableName: !Ref PresetsTable
        - DynamoDBCrudPolicy:
            TableName: !Ref SessionsTable
        - DynamoDBCrudPolicy:
            TableName: !Ref MistakesTable
        - DynamoDBCrudPolicy:
            TableName: !Ref PhasesTable
        - Statement:
            - Effect: Allow
              Action: bedrock:InvokeModel
              Resource: !Sub arn:aws:bedrock:${AWS::Region}::foundation-model/*

  # ============ API Gateway HTTP API ============
  McpHubApi:
    Type: AWS::Serverless::HttpApi
    Properties:
      StageName: !Ref Stage
      CorsConfiguration:
        AllowOrigins:
          - https://claude.ai
          - https://*.anthropic.com
        AllowMethods:
          - POST
          - GET
          - OPTIONS
        AllowHeaders:
          - Content-Type
          - X-API-Key
          - Authorization

  # ============ DynamoDB Tables ============
  RolesTable:
    Type: AWS::DynamoDB::Table
    Properties:
      TableName: !Sub mcp-hub-roles-${Stage}
      BillingMode: PAY_PER_REQUEST
      AttributeDefinitions:
        - AttributeName: role_name
          AttributeType: S
      KeySchema:
        - AttributeName: role_name
          KeyType: HASH

  PromptsTable:
    Type: AWS::DynamoDB::Table
    Properties:
      TableName: !Sub mcp-hub-prompts-${Stage}
      BillingMode: PAY_PER_REQUEST
      AttributeDefinitions:
        - AttributeName: role_name
          AttributeType: S
        - AttributeName: purpose_title
          AttributeType: S
        - AttributeName: purpose
          AttributeType: S
      KeySchema:
        - AttributeName: role_name
          KeyType: HASH
        - AttributeName: purpose_title
          KeyType: RANGE
      GlobalSecondaryIndexes:
        - IndexName: purpose-index
          KeySchema:
            - AttributeName: purpose
              KeyType: HASH
          Projection:
            ProjectionType: ALL

  ProjectsTable:
    Type: AWS::DynamoDB::Table
    Properties:
      TableName: !Sub mcp-hub-projects-${Stage}
      BillingMode: PAY_PER_REQUEST
      AttributeDefinitions:
        - AttributeName: project_id
          AttributeType: S
      KeySchema:
        - AttributeName: project_id
          KeyType: HASH

  PresetsTable:
    Type: AWS::DynamoDB::Table
    Properties:
      TableName: !Sub mcp-hub-presets-${Stage}
      BillingMode: PAY_PER_REQUEST
      AttributeDefinitions:
        - AttributeName: project_id
          AttributeType: S
        - AttributeName: created_status
          AttributeType: S
      KeySchema:
        - AttributeName: project_id
          KeyType: HASH
        - AttributeName: created_status
          KeyType: RANGE

  SessionsTable:
    Type: AWS::DynamoDB::Table
    Properties:
      TableName: !Sub mcp-hub-sessions-${Stage}
      BillingMode: PAY_PER_REQUEST
      AttributeDefinitions:
        - AttributeName: session_id
          AttributeType: S
        - AttributeName: project_id
          AttributeType: S
        - AttributeName: started_at
          AttributeType: S
      KeySchema:
        - AttributeName: session_id
          KeyType: HASH
      GlobalSecondaryIndexes:
        - IndexName: project-time-index
          KeySchema:
            - AttributeName: project_id
              KeyType: HASH
            - AttributeName: started_at
              KeyType: RANGE
          Projection:
            ProjectionType: ALL

  MistakesTable:
    Type: AWS::DynamoDB::Table
    Properties:
      TableName: !Sub mcp-hub-mistakes-${Stage}
      BillingMode: PAY_PER_REQUEST
      AttributeDefinitions:
        - AttributeName: mistake_id
          AttributeType: S
        - AttributeName: role_name
          AttributeType: S
        - AttributeName: category
          AttributeType: S
      KeySchema:
        - AttributeName: mistake_id
          KeyType: HASH
      GlobalSecondaryIndexes:
        - IndexName: role-category-index
          KeySchema:
            - AttributeName: role_name
              KeyType: HASH
            - AttributeName: category
              KeyType: RANGE
          Projection:
            ProjectionType: ALL

  PhasesTable:
    Type: AWS::DynamoDB::Table
    Properties:
      TableName: !Sub mcp-hub-phases-${Stage}
      BillingMode: PAY_PER_REQUEST
      AttributeDefinitions:
        - AttributeName: project_id
          AttributeType: S
        - AttributeName: phase_name
          AttributeType: S
      KeySchema:
        - AttributeName: project_id
          KeyType: HASH
        - AttributeName: phase_name
          KeyType: RANGE

Outputs:
  ApiEndpoint:
    Description: MCP Hub API endpoint
    Value: !Sub https://${McpHubApi}.execute-api.${AWS::Region}.amazonaws.com/${Stage}/mcp
  
  McpUrl:
    Description: URL to register in claude.ai
    Value: !Sub https://${McpHubApi}.execute-api.${AWS::Region}.amazonaws.com/${Stage}/mcp
```

---

## 4. Lambda 진입점 (`src/handler.py` + `run.sh`)

### `run.sh`
```bash
#!/bin/bash
exec python -m uvicorn src.server:app --host 0.0.0.0 --port 8080
```
이 파일에 `chmod +x` 권한 부여 필요.

### `src/server.py` 구조
```python
"""
FastMCP 서버 진입점.
Lambda Web Adapter가 HTTP 요청을 이 서버로 프록시.
"""
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.server import Settings
from src.config import get_settings
from src.lib.auth import verify_api_key

# Tool 모듈 import (각 tool은 @mcp.tool() 데코레이터로 등록)
from src.tools import (
    roles,
    prompts,
    projects,
    presets,
    phases,
    sessions,
    handoffs,
    mistakes,
)

settings = get_settings()

mcp = FastMCP(
    name="mcp-hub",
    instructions="""
    개인용 역할 조율 MCP 허브.
    - 새 세션 시작 시 resume_context(project_id) 먼저 호출
    - 작업 시작 전 query_mistakes(role=...) 호출 권장
    - 비활성 역할 prompt 호출 시 unlock_role 먼저 필요
    """,
)

# 인증 미들웨어
@mcp.middleware
async def auth_middleware(request, call_next):
    if not verify_api_key(request.headers.get("x-api-key")):
        raise PermissionError("Invalid or missing API key")
    return await call_next(request)

# Streamable HTTP transport로 노출
app = mcp.streamable_http_app()
```

---

## 5. Tool 구현 패턴 (모든 tool 공통)

### 5-1. 패턴 예시: `list_roles` (가장 단순)

`src/tools/roles.py`:
```python
"""
역할 관련 tool.
"""
from typing import List
from src.server import mcp
from src.db.repositories.roles import RolesRepository
from src.db.models import Role

@mcp.tool()
def list_roles() -> List[Role]:
    """
    모든 역할(5개) 메타데이터 반환.
    
    새 프로젝트 시작 시 가장 먼저 호출하여 사용 가능한 역할을 파악.
    
    Returns:
        Role 객체 목록 (planner, designer, architect, coder, reviewer)
    """
    repo = RolesRepository()
    return repo.list_all()


@mcp.tool()
def get_role(role_name: str) -> Role:
    """
    특정 역할 상세 정보 반환.
    
    Args:
        role_name: 역할 이름 (planner, designer, architect, coder, reviewer 중 하나)
    
    Returns:
        Role 객체 (책임 범위, 서브모드, 색상 포함)
    
    Raises:
        ValueError: 존재하지 않는 역할 이름
    """
    repo = RolesRepository()
    role = repo.get(role_name)
    if not role:
        raise ValueError(f"Unknown role: {role_name}. Available: planner, designer, architect, coder, reviewer")
    return role
```

### 5-2. 핵심 tool: `classify_project` (LLM 단독 추천 — v2.1)

**v2.1 변경**: 룰 기반 결정 폐기. LLM이 한 번에 점수 + 추천 + 근거 출력.

`src/tools/projects.py`:
```python
"""
프로젝트 관련 tool.
v2.1: LLM 단독 추천. 룰 기반 _assign_roles 함수 제거.
"""
import json
import uuid
from datetime import datetime, timezone
from src.server import mcp
from src.db.repositories.projects import ProjectsRepository
from src.db.repositories.presets import PresetsRepository
from src.db.models import ClassificationDraft
from src.llm.bedrock import invoke_claude

CLASSIFICATION_PROMPT = """프로젝트 설명을 보고 다음을 한 번에 결정하라.

프로젝트 설명:
{description}

5역할 중 활성화할 역할 + 우선순위 + 근거를 출력하라.

**제약 (반드시 준수)**:
- planner와 coder는 항상 포함 (모든 프로젝트의 출발점·구현 필수)
- 활성 역할 평균 3개 권장 (Skill 과잉배정 제한)
- 4축 점수(ui_weight, system_complexity, risk_level, verify_intensity)는 0-10 정수, 참고용
- 9역할 등 폐기된 옵션 거론 금지

**자체 기각 대상** (제시 자체 금지):
- 폐기된 역할 구성 (9역할 등)
- locked_decisions 위반 추천

OUTPUT (JSON only, no markdown, no other text):
{{
  "scores": {{
    "ui_weight": 0-10,
    "system_complexity": 0-10,
    "risk_level": 0-10,
    "verify_intensity": 0-10
  }},
  "recommended_roles": [
    {{"role": "planner", "priority": 1, "reason": "구체적 이유"}},
    {{"role": "coder", "priority": 2, "reason": "..."}}
  ],
  "skipped_roles": [
    {{"role": "designer", "reason": "백엔드만이라 UI 없음"}}
  ]
}}
"""


@mcp.tool()
def classify_project(description: str) -> ClassificationDraft:
    """
    프로젝트 설명을 LLM에게 분석시켜 추천 역할 조합을 draft로 저장.
    
    v2.1: 룰 기반 결정 제거. LLM 단독 추천.
    중요: 자동 활성화 안 함. 사용자가 approve_assignment 호출해야 active.
    
    Args:
        description: 프로젝트 설명 (한국어 또는 영어)
    
    Returns:
        ClassificationDraft (점수, 추천 역할 목록, draft preset id)
    
    Side Effects:
        - projects 테이블에 새 프로젝트 생성
        - presets 테이블에 draft 상태 preset 저장
    """
    # 1. LLM 호출 (점수 + 추천 + 근거 한 번에)
    response = invoke_claude(
        prompt=CLASSIFICATION_PROMPT.format(description=description),
        max_tokens=800,
    )
    result = json.loads(response)
    
    # 2. Sanity check (출력 검증만 — 룰 결정 아님)
    result = _validate_recommendation(result)
    
    # 3. 프로젝트 생성
    project_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    
    projects_repo = ProjectsRepository()
    projects_repo.create({
        "project_id": project_id,
        "name": _extract_name(description),
        "description": description,
        "created_at": now,
        "current_phase": "planning",
    })
    
    # 4. draft preset 저장
    presets_repo = PresetsRepository()
    preset_id = presets_repo.create({
        "project_id": project_id,
        "created_status": f"{now}#draft",
        "scores": result["scores"],
        "role_assignments": result["recommended_roles"],
        "skipped_roles": result.get("skipped_roles", []),
        "status": "draft",
    })
    
    return {
        "project_id": project_id,
        "preset_id": preset_id,
        "scores": result["scores"],
        "recommended_roles": result["recommended_roles"],
        "skipped_roles": result.get("skipped_roles", []),
        "status": "draft",
        "next_action": f"approve_assignment(project_id='{project_id}') 호출하여 활성화",
    }


def _validate_recommendation(result: dict) -> dict:
    """LLM 출력 검증. 룰 결정이 아니라 형식 강제."""
    roles_in = {r["role"] for r in result.get("recommended_roles", [])}
    
    # planner, coder 필수 포함 강제
    next_priority = max((r["priority"] for r in result["recommended_roles"]), default=0) + 1
    if "planner" not in roles_in:
        result["recommended_roles"].insert(0, {
            "role": "planner",
            "priority": 1,
            "reason": "[자동 추가] 모든 프로젝트의 필수 출발점",
        })
    if "coder" not in roles_in:
        result["recommended_roles"].append({
            "role": "coder",
            "priority": next_priority,
            "reason": "[자동 추가] 코드 산출물이 있는 프로젝트의 필수 역할",
        })
    
    # 활성 역할 0개 방지
    if not result["recommended_roles"]:
        raise ValueError("LLM 추천 실패: 활성 역할 0개. 입력 description 재검토 필요.")
    
    return result


def _extract_name(description: str) -> str:
    """설명 첫 줄 또는 첫 30자를 이름으로."""
    first_line = description.split("\n")[0].strip()
    return first_line[:30] if first_line else "Untitled Project"


@mcp.tool()
def approve_assignment(project_id: str) -> dict:
    """
    draft preset을 active로 승격.
    사용자가 명시적으로 승인했을 때만 호출.
    
    Args:
        project_id: 프로젝트 ID
    
    Returns:
        활성화된 preset 정보
    """
    presets_repo = PresetsRepository()
    
    # draft preset 조회
    drafts = presets_repo.list_by_status(project_id, "draft")
    if not drafts:
        raise ValueError(f"No draft preset found for project {project_id}")
    
    latest_draft = drafts[-1]  # 최신
    
    # active로 변경
    now = datetime.now(timezone.utc).isoformat()
    activated = presets_repo.update_status(
        project_id=project_id,
        old_key=latest_draft["created_status"],
        new_status="active",
        activated_at=now,
    )
    
    return {
        "preset_id": activated["preset_id"],
        "status": "active",
        "active_roles": [r["role"] for r in activated["role_assignments"]],
        "activated_at": now,
        "next_action": "start_session(project_id, role='planner') 호출하여 첫 작업 시작",
    }
```

### 5-3. 잠금 메커니즘: `get_prompt`

`src/tools/prompts.py`:
```python
"""
프롬프트 조회 tool. 비활성 역할 잠금 메커니즘 포함.
"""
from typing import List, Optional, Union
from src.server import mcp
from src.db.repositories.prompts import PromptsRepository
from src.db.repositories.presets import PresetsRepository
from src.lib.errors import RoleNotActiveError


@mcp.tool()
def get_prompt(
    role: str,
    purpose: str,
    title: Optional[str] = None,
    project_id: Optional[str] = None,
) -> Union[dict, List[dict]]:
    """
    역할 + 목적 + (선택) 제목으로 프롬프트 조회.
    
    중요: project_id가 주어지면 해당 프로젝트에서 role이 active인지 확인.
    비활성이면 RoleNotActiveError 발생 (잠금 메커니즘).
    
    Args:
        role: 역할 (planner, designer, architect, coder, reviewer)
        purpose: 목적 (workflow, handoff, critique, troubleshoot, validate, polish)
        title: (선택) 특정 프롬프트 제목. 생략 시 해당 role+purpose 모든 프롬프트 목록 반환
        project_id: (선택) 잠금 검증용. 권장: 항상 함께 전달
    
    Returns:
        title 지정 시: 단일 Prompt 객체
        title 미지정 시: Prompt 목록
    
    Raises:
        RoleNotActiveError: project_id 주어졌는데 role이 비활성
    """
    # 1. 잠금 검증 (project_id 있을 때)
    if project_id:
        presets_repo = PresetsRepository()
        active = presets_repo.get_active(project_id)
        if active and not _is_role_active(active, role):
            raise RoleNotActiveError(
                f"역할 '{role}'은 프로젝트 {project_id}에서 비활성 상태. "
                f"unlock_role(project_id='{project_id}', role='{role}', reason='이유') 먼저 호출 필요."
            )
    
    # 2. 프롬프트 조회
    repo = PromptsRepository()
    if title:
        prompt = repo.get(role, purpose, title)
        if not prompt:
            raise ValueError(f"Prompt not found: role={role}, purpose={purpose}, title={title}")
        return prompt
    else:
        return repo.list_by_role_purpose(role, purpose)


def _is_role_active(preset: dict, role: str) -> bool:
    """preset의 role_assignments에 role이 있는지."""
    return any(r["role"] == role for r in preset.get("role_assignments", []))
```

### 5-4. 핵심 tool: `resume_context`

`src/tools/sessions.py`:
```python
"""
세션 관련 tool. resume_context가 핵심.
v2.1: locked_decisions + harness_rules 반환 추가 (결정 보존).
"""
from src.server import mcp
from src.db.repositories.projects import ProjectsRepository
from src.db.repositories.presets import PresetsRepository
from src.db.repositories.sessions import SessionsRepository
from src.db.repositories.mistakes import MistakesRepository
from src.db.repositories.phases import PhasesRepository

# v2.1: 결정 보존을 위한 정적 상수
LOCKED_DECISIONS = [
    "역할은 5개 (planner/designer/architect/coder/reviewer)",
    "9역할 구성 폐기 — 재논의 금지",
    "PostgreSQL 폐기, DynamoDB 채택",
    "EC2 + 터널 폐기, Lambda + APIGW 채택",
    "Replit 코드 폐기",
    "역할 배정은 LLM 단독 추천 (룰 기반 폐기)",
]

HARNESS_RULES = [
    "1. 의도 고정",
    "2. 역할 경계",
    "3. Skill 과잉배정 제한",
    "4. 위험 변경 제한",
    "5. 사용자 승인",
    "6. 세션 승계",
    "7. 반복 실수 기록",
    "8. 대안 N개 + 자체 기각",
]


@mcp.tool()
def resume_context(project_id: str) -> dict:
    """
    새 세션 시작 시 자동 호출. 직전 작업 상태를 한 번에 복원.
    
    v2.1: locked_decisions + harness_rules 포함. Claude는 이 두 필드를
    먼저 읽고 거론 금지 항목 인지 후 작업 시작해야 한다.
    
    Args:
        project_id: 프로젝트 ID
    
    Returns:
        직전 세션 핸드오프, 활성 preset, 현재 phase, 미해결 실수,
        locked_decisions, harness_rules, 다음 행동 제안
    """
    projects_repo = ProjectsRepository()
    presets_repo = PresetsRepository()
    sessions_repo = SessionsRepository()
    mistakes_repo = MistakesRepository()
    phases_repo = PhasesRepository()
    
    project = projects_repo.get(project_id)
    if not project:
        raise ValueError(f"Project not found: {project_id}")
    
    active_preset = presets_repo.get_active(project_id)
    last_session = sessions_repo.get_latest(project_id)
    current_phase = phases_repo.get_current(project_id)
    unresolved = mistakes_repo.list_unresolved(limit=5)
    
    suggestion = _suggest_next_action(active_preset, last_session, current_phase)
    
    return {
        "project": project,
        "active_preset": active_preset,
        "current_phase": current_phase,
        "last_session": {
            "id": last_session["session_id"] if last_session else None,
            "role": last_session["role_name"] if last_session else None,
            "handoff_note": last_session.get("handoff_note") if last_session else None,
            "context_percent": last_session.get("context_percent", 0) if last_session else 0,
            "ended_at": last_session.get("ended_at") if last_session else None,
        } if last_session else None,
        "unresolved_mistakes": unresolved,
        "locked_decisions": LOCKED_DECISIONS,    # v2.1 신규
        "harness_rules": HARNESS_RULES,          # v2.1 신규
        "suggested_next_action": suggestion,
    }


def _suggest_next_action(preset: dict, last_session: dict, phase: dict) -> str:
    """현재 상태 기반 다음 행동 제안."""
    if not preset:
        return "approve_assignment 먼저 호출하여 역할 배정 활성화"
    
    if not last_session:
        first_role = preset["role_assignments"][0]["role"]
        return f"start_session(project_id, role='{first_role}') 호출하여 첫 세션 시작"
    
    if last_session.get("handoff_note"):
        return f"직전 핸드오프 확인 후 다음 역할로 transition_phase 호출"
    
    if last_session.get("context_percent", 0) >= 80:
        return "직전 세션이 80% 초과로 종료됨. save_handoff 후 새 세션 시작"
    
    return f"{phase['phase_name']} 단계 계속 진행"
```

---

## 6. 16개 Tool 시그니처 (전체 목록)

| # | Tool | 입력 | 출력 | 잠금? |
|---|---|---|---|---|
| 1 | `list_roles` | - | List[Role] | X |
| 2 | `get_role` | role_name | Role | X |
| 3 | `get_prompt` | role, purpose, title?, project_id? | Prompt or List | ✅ |
| 4 | `query_mistakes` | role?, category?, keyword? | List[Mistake] | X |
| 5 | `get_handoff` | session_id | HandoffNote | X |
| 6 | `resume_context` | project_id | ResumeBundle | X |
| 7 | `get_current_phase` | project_id | Phase | X |
| 8 | `list_active_presets` | - | List[Preset] | X |
| 9 | `classify_project` | description | ClassificationDraft | - |
| 10 | `approve_assignment` | project_id | Preset | - |
| 11 | `transition_phase` | project_id, new_phase, reason | Phase | - |
| 12 | `unlock_role` | project_id, role, reason | Preset | - |
| 13 | `save_handoff` | from_role, to_role, summary, context?, blockers? | HandoffNote | - |
| 14 | `record_mistake` | role, category, description, root_cause?, resolution? | Mistake | - |
| 15 | `start_session` | project_id, role | Session | - |
| 16 | `update_context` | session_id, percent | Session | - |

각 tool은 docstring에 다음 명시:
- 한 줄 설명 (Claude가 언제 호출할지 판단)
- "사용자 명시 요청 시만" (쓰기 도구)
- 부작용(Side Effects)
- 예외(Raises)

---

## 7. 시드 데이터

### 7-1. roles 시드 (`seeds/roles.json`)
```json
[
  {
    "role_name": "planner",
    "display_name": "기획자",
    "description": "요구사항·분석·문서화·매뉴얼 두 버전 관리",
    "color": "#3B82F6",
    "submodes": ["requirements", "docs", "manual"],
    "default_active": true
  },
  {
    "role_name": "designer",
    "display_name": "디자이너",
    "description": "UI/UX/카피·화면 명세 형식 준수",
    "color": "#EC4899",
    "submodes": ["ui", "ux", "copy", "spec"],
    "default_active": false
  },
  {
    "role_name": "architect",
    "display_name": "아키텍트",
    "description": "시스템 구조·API·DB·왜?에 답하는 인과 구조 강제",
    "color": "#8B5CF6",
    "submodes": ["system", "api", "data", "adr"],
    "default_active": false
  },
  {
    "role_name": "coder",
    "display_name": "코더",
    "description": "구현·디버그·리팩토링·테스트작성·근본 해결 우선",
    "color": "#10B981",
    "submodes": ["implement", "debug", "refactor", "test"],
    "default_active": true
  },
  {
    "role_name": "reviewer",
    "display_name": "리뷰어",
    "description": "코드 리뷰·검증·품질확인서·보안 사전 점검",
    "color": "#F59E0B",
    "submodes": ["review", "verify", "qa-doc", "security"],
    "default_active": false
  }
]
```

### 7-2. mistakes 시드 (`seeds/mistakes.json`)
**v2.1: 23개 항목.** MCP_HUB_DESIGN_v2.1.md §6 표 그대로 변환.

```json
[
  {
    "mistake_id": "M-SEED-001",
    "role_name": "coder",
    "category": "timezone",
    "description": "KST/UTC 혼용으로 시간 계산 오류",
    "root_cause": "datetime 객체에 timezone 정보 명시 안 함",
    "resolution": "always use datetime.now(timezone.utc) or zoneinfo.ZoneInfo('Asia/Seoul') explicitly",
    "resolved_at": "2026-05-03T00:00:00Z",
    "created_at": "2026-05-03T00:00:00Z"
  },
  ... (M-SEED-002 ~ M-SEED-020: 설계서 §6 표 참조하여 동일 형식으로)
  
  {
    "mistake_id": "M-SEED-021",
    "role_name": "architect",
    "category": "over-engineering",
    "description": "사용자가 시키지 않은 안전장치를 자기 판단으로 추가",
    "root_cause": "LLM의 보수적 편향. 신뢰할 수 있는 단계(LLM 추론)에 검증 단계를 또 끼워넣음",
    "resolution": "사용자가 명시한 결정 사항만 구현. 추가 안전장치는 사용자에게 먼저 제안하고 승인받기",
    "resolved_at": "2026-05-03T00:00:00Z",
    "created_at": "2026-05-03T00:00:00Z"
  },
  {
    "mistake_id": "M-SEED-022",
    "role_name": "planner",
    "category": "decision-erosion",
    "description": "이미 확정된 결정사항을 예시·가정·우려 형태로 다시 거론해 결정을 흐림",
    "root_cause": "LLM이 '혹시 모르니' 옛 옵션을 보존하려는 편향",
    "resolution": "확정된 결정은 예시로도 쓰지 않는다. 새 대화 시작 시 resume_context로 locked_decisions 먼저 로드, 그 외 옵션은 거론 금지",
    "resolved_at": "2026-05-03T00:00:00Z",
    "created_at": "2026-05-03T00:00:00Z"
  },
  {
    "mistake_id": "M-SEED-023",
    "role_name": "architect",
    "category": "alternative-generation",
    "description": "단일 안만 제시. 대안 비교 없이 결정 강요",
    "root_cause": "LLM이 자기 추론을 정답으로 제시하는 편향",
    "resolution": "모든 의사결정 출력에 대안 ≥2개 제시 + 트레이드오프 명시. 단 확정 하네스 위반 대안은 자체 기각하고 제시 안 함",
    "resolved_at": "2026-05-03T00:00:00Z",
    "created_at": "2026-05-03T00:00:00Z"
  }
]
```

### 7-3. prompts 시드 (`seeds/prompts.json`)
PROMPTS_v1.md의 5개 프롬프트 변환.

```json
[
  {
    "role_name": "planner",
    "purpose_title": "workflow#requirements_정리",
    "purpose": "workflow",
    "title": "requirements_정리",
    "content": "[ROLE] You are a senior product planner. ...(전체 본문)",
    "lang": "ko",
    "version": "1.0",
    "exec_rules": [
      "MUST call query_mistakes FIRST",
      "MUST classify each requirement as FR or NFR",
      "MUST mark priority as Must / Should / Could",
      "MUST write DoD in measurable terms",
      "MUST NOT invent requirements",
      "MUST produce two manual versions",
      "VERIFY: every FR/NFR has unique ID"
    ],
    "created_at": "2026-05-03T00:00:00Z",
    "updated_at": "2026-05-03T00:00:00Z"
  },
  ... (총 5개)
]
```

---

## 8. 검증 절차 (개발 중·완료 시 실행)

### 8-1. 코드 검증 4단계 자동화 (`scripts/verify_code.py`)

```python
"""
코드 검증 4단계 프로토콜 자동화.
조정승 님 원칙: syntax check만으로 NameError 못 잡음 → 4단계 모두 통과해야 함.

사용법:
    python scripts/verify_code.py src/
"""
import ast
import importlib
import subprocess
import sys
from pathlib import Path


def verify_directory(target_dir: str) -> dict:
    results = {"ast_parse": [], "import": [], "mock": [], "grep": []}
    
    py_files = list(Path(target_dir).rglob("*.py"))
    
    # 1. ast.parse
    for f in py_files:
        try:
            ast.parse(f.read_text())
            results["ast_parse"].append((str(f), "PASS"))
        except SyntaxError as e:
            results["ast_parse"].append((str(f), f"FAIL: {e}"))
    
    # 2. import validation
    for f in py_files:
        module_name = str(f.relative_to(".")).replace("/", ".").replace(".py", "")
        try:
            importlib.import_module(module_name)
            results["import"].append((module_name, "PASS"))
        except Exception as e:
            results["import"].append((module_name, f"FAIL: {e}"))
    
    # 3. mock execution (각 tool 독립 호출)
    # ... (구현 시 tools/ 모듈 import 후 mock DB로 호출)
    
    # 4. grep undefined vars (pyflakes 활용)
    result = subprocess.run(
        ["pyflakes", target_dir],
        capture_output=True, text=True
    )
    if result.stdout:
        results["grep"].append(("pyflakes", f"FAIL: {result.stdout}"))
    else:
        results["grep"].append(("pyflakes", "PASS"))
    
    return results


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "src/"
    results = verify_directory(target)
    
    all_pass = True
    for stage, items in results.items():
        print(f"\n=== {stage.upper()} ===")
        for name, status in items:
            print(f"  {name}: {status}")
            if "FAIL" in status:
                all_pass = False
    
    sys.exit(0 if all_pass else 1)
```

### 8-2. Tool 호출 테스트 (`scripts/test_tools.py`)
16개 tool 모두 mock DynamoDB로 호출 후 결과 검증.

---

## 9. 배포 절차 (단계별)

### 9-1. 사전 준비
```bash
# 1. SAM CLI 설치 확인
sam --version  # >= 1.100.0

# 2. AWS CLI 설정 확인
aws sts get-caller-identity  # 본인 계정 확인

# 3. Bedrock 모델 접근 권한 활성화
# AWS Console → Bedrock → Model access → Anthropic Claude 3.5 Sonnet 활성화
# (반드시 ap-northeast-2에서 활성화)
```

### 9-2. 첫 배포
```bash
cd mcp-hub

# 1. 의존성 설치
pip install -r requirements.txt --target .build/

# 2. SAM 빌드
sam build

# 3. 배포 (대화형, 첫 배포만)
sam deploy --guided
# 다음 답변:
# - Stack name: mcp-hub-dev
# - Region: ap-northeast-2
# - ApiKey: [랜덤 64자 입력 — 별도 보관]
# - Stage: dev
# - Confirm changes: y
# - Allow SAM to create IAM roles: y
# - Save to samconfig.toml: y

# 4. URL 확인
sam list endpoints --stack-name mcp-hub-dev
# Output: https://xxx.execute-api.ap-northeast-2.amazonaws.com/dev/mcp
```

### 9-3. 시드 데이터 입력
```bash
# 환경변수 설정
export AWS_REGION=ap-northeast-2
export STAGE=dev

# 시드 스크립트 실행
python scripts/seed_db.py
```

### 9-4. 연결 테스트
```bash
# API Key로 헬스체크
curl -X POST https://xxx.execute-api.ap-northeast-2.amazonaws.com/dev/mcp \
  -H "Content-Type: application/json" \
  -H "X-API-Key: <your-api-key>" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'

# 16개 tool 목록 응답 확인
```

### 9-5. claude.ai 커넥터 등록
1. claude.ai 접속 → Settings → Connectors
2. "Add custom connector" 클릭
3. URL 입력: `https://xxx.execute-api.ap-northeast-2.amazonaws.com/dev/mcp`
4. Authentication: API Key (Header: `X-API-Key`, Value: 본인 키)
5. Save

### 9-6. 운영 모드 전환 (검증 후)
```bash
sam deploy --parameter-overrides Stage=prod
# prod URL 별도 발급. dev는 테스트용으로 유지.
```

---

## 10. Phase별 작업 체크리스트

### Phase 1: 인프라 + 코어 (3일)
- [ ] 프로젝트 디렉토리 생성
- [ ] requirements.txt + .gitignore + Makefile
- [ ] template.yaml (위 SAM 템플릿)
- [ ] src/server.py (FastMCP 진입점)
- [ ] src/config.py (환경변수)
- [ ] src/lib/auth.py (API Key 검증)
- [ ] src/lib/errors.py (RoleNotActiveError 등)
- [ ] src/db/client.py (boto3 wrapper)
- [ ] src/db/models.py (Pydantic 모델 7개)
- [ ] seeds/roles.json (5개)
- [ ] seeds/mistakes.json (20개)
- [ ] seeds/prompts.json (5개)
- [ ] scripts/seed_db.py
- [ ] **검증**: ast.parse + import 모두 통과

### Phase 2: Tool 구현 (4일)
- [ ] src/db/repositories/ 7개 파일 (Roles, Prompts, Projects, Presets, Sessions, Mistakes, Phases)
- [ ] src/llm/bedrock.py (invoke_claude 함수)
- [ ] src/tools/roles.py (list_roles, get_role)
- [ ] src/tools/prompts.py (get_prompt + 잠금 메커니즘)
- [ ] src/tools/projects.py (classify_project, approve_assignment)
- [ ] src/tools/presets.py (list_active_presets, unlock_role)
- [ ] src/tools/phases.py (get_current_phase, transition_phase)
- [ ] src/tools/sessions.py (start_session, update_context, resume_context)
- [ ] src/tools/handoffs.py (save_handoff, get_handoff)
- [ ] src/tools/mistakes.py (record_mistake, query_mistakes)
- [ ] **검증**: scripts/verify_code.py 4단계 모두 PASS
- [ ] **검증**: scripts/test_tools.py 16개 모두 PASS

### Phase 3: 배포 (1일)
- [ ] sam build 성공
- [ ] sam deploy --guided 첫 배포
- [ ] DynamoDB 7테이블 생성 확인
- [ ] API Gateway URL 확보
- [ ] 시드 데이터 입력 (seed_db.py)
- [ ] curl 테스트 — tools/list로 16개 응답 확인
- [ ] claude.ai 커넥터 등록
- [ ] 실제 호출 테스트 (list_roles → 5개 응답)

### Phase 4: 검증 + 문서 (1일)
- [ ] 16개 tool 각각 실제 호출 + 응답 검증
- [ ] 비활성 역할 잠금 동작 확인 (RoleNotActiveError)
- [ ] classify_project 4축 점수 합리성 확인
- [ ] resume_context 시나리오 테스트
- [ ] 품질확인서 작성 (이 문서 기준)
- [ ] README.md (사용자 매뉴얼 — 어떻게 호출하는지)
- [ ] README_DEV.md (유지보수 매뉴얼 — 배포·롤백·디버깅)

---

## 11. 품질확인서 템플릿 (Phase 4 완료 시 작성)

```markdown
# MCP 허브 v1.0 품질확인서

## 기본 정보
- 산출물: 개인용 역할 조율 MCP 허브
- 검증일: YYYY-MM-DD
- 검증자: Claude Code
- 검증 범위: 코드 + 인프라 + 통합

## 검증 결과
| 카테고리 | 항목 | 결과 | 증거 |
|---|---|---|---|
| 기능 | 16개 tool 모두 동작 | ✅ | test_tools.py PASS |
| 기능 | classify_project 4축 합리성 | ✅ | 샘플 5건 검증 |
| 기능 | 비활성 역할 잠금 | ✅ | unit test PASS |
| 기능 | resume_context 복원 | ✅ | 시나리오 테스트 PASS |
| 코드 | ast.parse | ✅ | 모든 .py 파일 |
| 코드 | import 검증 | ✅ | 순환참조 없음 |
| 코드 | mock 실행 | ✅ | DynamoDB local mock |
| 코드 | undefined var grep | ✅ | pyflakes clean |
| 보안 | API Key 인증 | ✅ | 무인증 호출 차단 확인 |
| 보안 | IAM 최소 권한 | ✅ | 7테이블만 CRUD |
| 운영 | sam deploy | ✅ | dev stage 배포 성공 |
| 운영 | claude.ai 연결 | ✅ | 16개 tool 인식 |
| 운영 | DynamoDB 무료티어 | ✅ | 사용량 0% |
| 문서 | 매뉴얼 두 버전 | ✅ | README + README_DEV |

## 최종 판정
- 적합 / 조건부 적합 / 부적합 (택 1)
- 조건 (조건부 적합 시): ...

## 후속 조치
- 즉시 수정: [...]
- 다음 사이클: 사용자 직접 프롬프트 입력
- 참고: 14개 핵심 프롬프트 추가 작성 권장
```

---

## 12. 시작하기 (Claude Code 실행 명령)

다음 메시지를 사용자가 Claude Code에 붙여넣으면 작업 시작:

```
첨부 3개 파일 받았습니다:
- MCP_HUB_DESIGN_v2.3.md (설계서)
- PROMPTS_v1.3.md (프롬프트 8개 + 공통 규칙)
- CLAUDE_CODE_HANDOFF.md (이 명세서)

CLAUDE_CODE_HANDOFF.md §0 (Claude Code에게) 부분 먼저 읽고 시작 확인 메시지부터 보내주세요.
- §0-3-1 v2.1 원칙 3개 (anti-overeng / decision-preservation / alternatives)
- §0-3-2 v2.2 원칙 (실패스토리 게이트)
- §0-3-3 v2.3 원칙 (Decisions 동적 / 한국어 트리거 / phase별 카운트 / force_pass 학습 / Designer 영향)
모두 준수.

v2.3 핵심: 20개 tool, 9개 DynamoDB 테이블, 코딩 진입 시 실패스토리 게이트, lock_decision으로 결정 동적 관리.
Phase 1부터 순차 진행. 각 Phase 끝에 코드 검증 4단계 + 결과 보고.
```

---

*이 명세서로 처음부터 끝까지 자체 완결. 추가 질문 발생 시 사용자에게 물어보고 진행.*

---

## 부록 A: v2 → v2.1 변경 요약 (Claude Code용)

| 변경 | 영향 파일 |
|---|---|
| `_assign_roles` 함수 삭제 | `src/tools/projects.py` |
| `classify_project`가 LLM에게 점수+추천 한 번에 요청 | `src/tools/projects.py` |
| `_validate_recommendation` 함수 추가 (출력 형식 검증만) | `src/tools/projects.py` |
| `resume_context`에 `LOCKED_DECISIONS`, `HARNESS_RULES` 상수 + 반환 | `src/tools/sessions.py` |
| mistakes 시드 20 → 23 (M-SEED-021/022/023 추가) | `seeds/mistakes.json` |
| 모든 프롬프트 EXECUTION RULES에 공통 3원칙 추가 | `seeds/prompts.json` |
| 의사결정형 프롬프트 OUTPUT FORMAT에 "대안 비교" 섹션 추가 | `seeds/prompts.json` |

## 부록 B: v2.1 → v2.2 변경 요약 (실패스토리 / Pre-mortem 통합)

| 변경 | 영향 파일 | 비고 |
|---|---|---|
| Tool 16 → 19개 | `src/tools/premortem.py` (신규) | run_failure_story / apply_premortem_revision / get_premortem_history |
| Reviewer 서브모드 5번째 추가 | `seeds/roles.json` | premortem |
| `transition_phase` 동작 변경 | `src/tools/phases.py` | new_phase='coding' 시 자동으로 run_failure_story 호출 |
| Phase 상태 5 → 7개 | `src/db/repositories/phases.py` | pending_premortem, under_revision 추가 |
| DynamoDB 테이블 7 → 8개 | `template.yaml`, `src/db/repositories/failure_stories.py` (신규) | FailureStoriesTable 추가 |
| mistakes 시드 23 → 25 | `seeds/mistakes.json` | M-SEED-024/025 추가 |
| 신규 프롬프트 3개 | `seeds/prompts.json` | reviewer.premortem / architect.실패보완 / planner.실패보완 |
| 명령어 "실패스토리" 라우팅 | `src/server.py` 또는 진입점 | 인자 있음/없음 모두 run_failure_story로 |
| LOCKED_DECISIONS 1개 추가 | `src/tools/sessions.py` | "코딩 단계 진입 전 실패스토리 자동 트리거 — 사용자 승인 후 진행" |

## 부록 C: v2.2 → v2.3 변경 요약 (메타 리뷰 보완)

| 변경 | 영향 파일 | 비고 |
|---|---|---|
| LOCKED_DECISIONS 코드 → DB | `src/tools/sessions.py`, `src/db/repositories/decisions.py` (신규) | B1 — DynamoDB Decisions 테이블 동적 로드 |
| 신규 tool: `lock_decision` | `src/tools/decisions.py` (신규) | 사용자가 채팅 한 줄로 결정 추가 |
| Tool 19 → 20개 | `src/server.py` | lock_decision 등록 |
| DynamoDB 테이블 8 → 9개 | `template.yaml` | DecisionsTable 추가 |
| Decisions 시드 7개 | `seeds/decisions.json` (신규) | 기존 LOCKED_DECISIONS를 source="system_seed"로 시드 |
| `force_pass` 시 자동 record_mistake | `src/tools/premortem.py` | B2 — 보완 실패 학습 |
| `revision_count` phase별 카운팅 | `src/tools/premortem.py`, `src/db/repositories/phases.py` | S2 — phase 진입시점 이후만 |
| 모든 tool docstring 한국어 트리거 | 모든 `src/tools/*.py` | S1 — 자연어 매칭 정확도 |
| Planner.실패스토리_가정변경 Designer 명시 | `seeds/prompts.json` | S3 — UI 영향 누락 방지 |

### v2.3 신규 코드 스켈레톤

`src/tools/decisions.py`:
```python
"""
결정사항 동적 관리. v2.3 신규.
"""
import uuid
from datetime import datetime, timezone
from src.server import mcp
from src.db.repositories.decisions import DecisionsRepository


@mcp.tool()
def lock_decision(text: str, project_id: str = None, scope: str = "global") -> dict:
    """
    확정된 결정사항을 동적으로 추가. 코드 재배포 없이 채팅으로 결정 잠금.
    
    Trigger phrases (한국어): "결정 잠가줘", "이거 락 걸어", "결정사항 추가", "lock 해줘"
    Trigger phrases (English): "lock decision", "save decision"
    
    Args:
        text: 결정 내용 (예: "프롬프트는 한국어 우선")
        project_id: 특정 프로젝트 한정 (None이면 전역)
        scope: "global" (모든 프로젝트) | "project" (해당 project_id만)
    
    Returns:
        Decision 객체. 다음 resume_context 호출 시 자동 반영됨.
    
    Raises:
        ValueError: scope=project인데 project_id 없음
    """
    if scope == "project" and not project_id:
        raise ValueError("scope='project'면 project_id 필수")
    
    repo = DecisionsRepository()
    decision_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    
    decision = {
        "decision_id": decision_id,
        "text": text,
        "scope": scope,
        "project_id": project_id if scope == "project" else None,
        "active": True,
        "created_at": now,
        "revoked_at": None,
        "source": "user_lock",
    }
    repo.create(decision)
    
    return decision
```

`src/db/repositories/decisions.py`:
```python
"""Decisions 테이블 CRUD."""
import boto3
from boto3.dynamodb.conditions import Attr, Key

class DecisionsRepository:
    def __init__(self):
        self.table = boto3.resource("dynamodb").Table("mcp-hub-decisions-dev")
    
    def create(self, decision: dict):
        self.table.put_item(Item=decision)
    
    def list_active_for_project(self, project_id: str) -> list:
        """전역 + 해당 프로젝트의 active 결정 모두 반환.
        
        scope-active-index GSI 사용.
        """
        # 전역 결정
        global_resp = self.table.query(
            IndexName="scope-active-index",
            KeyConditionExpression=Key("scope").eq("global") & Key("active").eq(True),
        )
        # 프로젝트별 결정
        project_resp = self.table.query(
            IndexName="scope-active-index",
            KeyConditionExpression=Key("scope").eq("project") & Key("active").eq(True),
            FilterExpression=Attr("project_id").eq(project_id),
        )
        
        all_decisions = global_resp.get("Items", []) + project_resp.get("Items", [])
        # created_at 순 정렬
        return sorted(all_decisions, key=lambda d: d["created_at"])
    
    def revoke(self, decision_id: str):
        """결정 무효화. 삭제하지 않고 active=false."""
        now = datetime.now(timezone.utc).isoformat()
        self.table.update_item(
            Key={"decision_id": decision_id},
            UpdateExpression="SET active = :a, revoked_at = :r",
            ExpressionAttributeValues={":a": False, ":r": now},
        )
```

### resume_context 변경 (v2.3)

```python
# Before (v2.2): 코드 상수
LOCKED_DECISIONS = ["역할은 5개 ...", ...]

# After (v2.3): DB에서 동적 로드
@mcp.tool()
def resume_context(project_id: str) -> dict:
    """..."""
    decisions_repo = DecisionsRepository()
    locked_decisions = [d["text"] for d in decisions_repo.list_active_for_project(project_id)]
    
    return {
        ...
        "locked_decisions": locked_decisions,  # 동적
        "harness_rules": HARNESS_RULES,        # 8개 고정 (코드 상수 유지)
        ...
    }
```

### apply_premortem_revision 변경 (v2.3 — B2)

```python
@mcp.tool()
def apply_premortem_revision(project_id, story_id, mode, target_items=None):
    """..."""
    if mode == "force_pass":
        # B2: 자동 record_mistake
        from src.tools.mistakes import record_mistake
        story = stories_repo.get(project_id, story_id)
        record_mistake(
            role="reviewer",
            category="premortem-loop-failure",
            description=f"실패스토리 2회 보완 후에도 통과 못 함. project={project_id}, story={story_id}",
            root_cause=f"revised_plan과 사용자 결정의 차이: revised={story['revised_plan'][:200]}",
            resolution=None,  # 회고 시 추가
        )
    
    # ... 기존 로직
```

### Decisions 시드 (v2.3)

`seeds/decisions.json`:
```json
[
  {"decision_id": "D-SEED-001", "text": "역할은 5개 (planner/designer/architect/coder/reviewer)", "scope": "global", "active": true, "source": "system_seed"},
  {"decision_id": "D-SEED-002", "text": "9역할 구성 폐기 — 재논의 금지", "scope": "global", "active": true, "source": "system_seed"},
  {"decision_id": "D-SEED-003", "text": "PostgreSQL 폐기, DynamoDB 채택", "scope": "global", "active": true, "source": "system_seed"},
  {"decision_id": "D-SEED-004", "text": "EC2 + 터널 폐기, Lambda + APIGW 채택", "scope": "global", "active": true, "source": "system_seed"},
  {"decision_id": "D-SEED-005", "text": "Replit 코드 폐기", "scope": "global", "active": true, "source": "system_seed"},
  {"decision_id": "D-SEED-006", "text": "역할 배정은 LLM 단독 추천 (룰 기반 폐기)", "scope": "global", "active": true, "source": "system_seed"},
  {"decision_id": "D-SEED-007", "text": "코딩 단계 진입 전 실패스토리 자동 트리거 — 사용자 승인 후 진행", "scope": "global", "active": true, "source": "system_seed"}
]
```

### SAM 템플릿 추가 (v2.3)

```yaml
DecisionsTable:
  Type: AWS::DynamoDB::Table
  Properties:
    TableName: !Sub mcp-hub-decisions-${Stage}
    BillingMode: PAY_PER_REQUEST
    AttributeDefinitions:
      - AttributeName: decision_id
        AttributeType: S
      - AttributeName: scope
        AttributeType: S
      - AttributeName: active
        AttributeType: S  # Bool은 GSI 키로 못 써서 "true"/"false" 문자열로 저장
    KeySchema:
      - AttributeName: decision_id
        KeyType: HASH
    GlobalSecondaryIndexes:
      - IndexName: scope-active-index
        KeySchema:
          - AttributeName: scope
            KeyType: HASH
          - AttributeName: active
            KeyType: RANGE
        Projection:
          ProjectionType: ALL
```

McpHubFunction 정책에 추가:
```yaml
- DynamoDBCrudPolicy:
    TableName: !Ref DecisionsTable
```

환경변수에 추가:
```yaml
DECISIONS_TABLE: !Ref DecisionsTable
```

### v2.2 신규 tool 코드 스켈레톤

`src/tools/premortem.py`:
```python
"""
실패스토리 (Pre-mortem) 관련 tool.
v2.2: LLM 긍정 환각 중화. 코딩 진입 게이트.
"""
import json
import uuid
from datetime import datetime, timezone
from src.server import mcp
from src.db.repositories.failure_stories import FailureStoriesRepository
from src.db.repositories.phases import PhasesRepository
from src.db.repositories.sessions import SessionsRepository
from src.llm.bedrock import invoke_claude

PREMORTEM_PROMPT = """6개월 후 미래로 이동했다고 가정하라.
다음 계획이 어떻게 실패했는지 기정사실로 보고하라.

검토 대상:
{plan_text}

대상 phase: {target_phase}
revision_count: {revision_count}

OUTPUT (JSON only):
{{
  "stories": ["구체적 실패 서사 1", "...2", "...3"],
  "warnings": ["관찰 가능한 신호 1", "...2"],
  "assumption": "단 하나의 핵심 숨은 가정",
  "revised_plan": "실패 모드 반영한 재작성 계획"
}}

규칙:
- 모든 서술 과거형 ("~했다")
- 가능성 표현 금지 ("might", "could")
- 3개 실패 서사는 서로 달라야 함
- assumption은 정확히 1개
"""


@mcp.tool()
def run_failure_story(
    project_id: str,
    plan_text: str = None,
    target_phase: str = "coding",
) -> dict:
    """
    실패스토리(Pre-mortem) 실행.
    
    호출 경로:
    1. transition_phase('coding')에서 자동 트리거 (plan_text=None → 직전 산출물 자동)
    2. 사용자 명시 호출 ("실패스토리" 명령) — plan_text 있거나 없거나
    """
    sessions_repo = SessionsRepository()
    stories_repo = FailureStoriesRepository()
    
    if not plan_text:
        last_session = sessions_repo.get_latest(project_id)
        plan_text = last_session.get("handoff_note") if last_session else ""
        if not plan_text:
            raise ValueError("검토 대상이 없음. plan_text 명시 또는 직전 세션 핸드오프 필요")
    
    history = stories_repo.list_by_project(project_id)
    revision_count = len(history)
    
    response = invoke_claude(
        prompt=PREMORTEM_PROMPT.format(
            plan_text=plan_text,
            target_phase=target_phase,
            revision_count=revision_count,
        ),
        max_tokens=2000,
    )
    result = json.loads(response)
    
    story_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    stories_repo.create({
        "project_id": project_id,
        "created_at": now,
        "story_id": story_id,
        "target_phase": target_phase,
        "source_artifact": plan_text[:200],
        "stories": result["stories"],
        "warnings": result["warnings"],
        "assumption": result["assumption"],
        "revised_plan": result["revised_plan"],
        "revision_count": revision_count,
        "status": "pending",
    })
    
    return {
        "story_id": story_id,
        "stories": result["stories"],
        "warnings": result["warnings"],
        "assumption": result["assumption"],
        "revised_plan": result["revised_plan"],
        "revision_count": revision_count,
        "status": "pending",
        "next_action": "사용자 검토 후 apply_premortem_revision 호출 (mode: revise_all/revise_partial/pass)",
    }


@mcp.tool()
def apply_premortem_revision(
    project_id: str,
    story_id: str,
    mode: str,
    target_items: list = None,
) -> dict:
    """
    실패스토리 보완 결정 적용.
    mode: revise_all / revise_partial / pass / force_pass
    """
    stories_repo = FailureStoriesRepository()
    phases_repo = PhasesRepository()
    
    story = stories_repo.get(project_id, story_id)
    if not story:
        raise ValueError(f"Story not found: {story_id}")
    
    if mode in ("pass", "force_pass"):
        new_status = "passed" if mode == "pass" else "forced"
        stories_repo.update_status(project_id, story_id, new_status, mode)
        phases_repo.transition(project_id, "coding", reason=f"premortem {mode}")
        return {
            "story_id": story_id,
            "mode_applied": mode,
            "phase_status": "coding",
            "next_action": "Coder 작업 시작",
        }
    
    if mode == "revise_all":
        target_role = "architect"
    elif mode == "revise_partial":
        target_role = "planner" if "assumption" in (target_items or []) else "architect"
    else:
        raise ValueError(f"Unknown mode: {mode}")
    
    revision_count = story["revision_count"] + 1
    remaining = max(0, 2 - revision_count)
    
    stories_repo.update_status(project_id, story_id, "revised", mode, target_items)
    phases_repo.transition(project_id, "under_revision", reason=f"premortem revision #{revision_count}")
    
    return {
        "story_id": story_id,
        "mode_applied": mode,
        "target_items": target_items or ["all"],
        "handoff_target": target_role,
        "revision_count": revision_count,
        "remaining_attempts": remaining,
        "next_action": f"{target_role}가 보완 완료 후 run_failure_story 재실행. 한도 잔여 {remaining}회",
        "phase_status": "under_revision",
    }


@mcp.tool()
def get_premortem_history(project_id: str) -> list:
    """프로젝트의 실패스토리 보완 이력 조회."""
    stories_repo = FailureStoriesRepository()
    return stories_repo.list_by_project(project_id)
```

### transition_phase 동작 변경 (v2.2)

```python
@mcp.tool()
def transition_phase(project_id: str, new_phase: str, reason: str) -> dict:
    """
    단계 전환. v2.2: new_phase='coding'인 경우 자동으로 실패스토리 트리거.
    """
    from src.tools.premortem import run_failure_story
    
    if new_phase == "coding":
        story_report = run_failure_story(project_id=project_id, target_phase="coding")
        phases_repo.transition(project_id, "pending_premortem", reason=f"auto-triggered: {reason}")
        return {
            "phase": "pending_premortem",
            "premortem_report": story_report,
            "next_action": "사용자 검토 후 apply_premortem_revision 호출",
            "user_prompt": "실패스토리 검토 완료. 보완하시겠어요? (전체 보완 / 부분 보완 / 통과)",
        }
    
    phases_repo.transition(project_id, new_phase, reason)
    return {"phase": new_phase, "reason": reason}
```

### LOCKED_DECISIONS 갱신 (v2.2)

```python
LOCKED_DECISIONS = [
    "역할은 5개 (planner/designer/architect/coder/reviewer)",
    "9역할 구성 폐기 — 재논의 금지",
    "PostgreSQL 폐기, DynamoDB 채택",
    "EC2 + 터널 폐기, Lambda + APIGW 채택",
    "Replit 코드 폐기",
    "역할 배정은 LLM 단독 추천 (룰 기반 폐기)",
    "코딩 단계 진입 전 실패스토리 자동 트리거 — 사용자 승인 후 진행 (v2.2)",
]
```
