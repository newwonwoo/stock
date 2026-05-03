"""
DART 공시 보고서명(report_nm) 22개 타입 분류.

INTEGRATION.md §3.3 + DESIGN.md 17.4·17.6 매트릭스 기반 매핑.

severity 3등급:
  - URGENT  : 즉시 매도 권장 (객관적 사실)
  - REVIEW  : 매도 검토
  - MONITOR : 관찰만

trigger.type 5종 (매도 시그널 분류용):
  DISCLOSURE / CB_EXERCISE / EARNING / NEWS / ANALYST
(현재는 DISCLOSURE 만 사용. 나머지는 다른 트리거 소스에서 채움.)

방향 (effect):
  - BLOCK_BUY    : 매수 차단 (block_reasons 에 등록)
  - SELL_TRIGGER : 보유 시 매도 시그널 발생
  - POSITIVE     : 가산 신호 (매수 추가 점수)
  - NEUTRAL      : 추적만
"""

from __future__ import annotations

import re
from dataclasses import dataclass

URGENT = "URGENT"
REVIEW = "REVIEW"
MONITOR = "MONITOR"

EFFECT_BLOCK = "BLOCK_BUY"
EFFECT_SELL = "SELL_TRIGGER"
EFFECT_POSITIVE = "POSITIVE"
EFFECT_NEUTRAL = "NEUTRAL"


@dataclass
class DisclosureRule:
    type_code: str           # INTEGRATION.md block type 또는 신규 type
    pattern: re.Pattern[str]
    severity: str
    effect: str
    block_days: int | None = None  # BLOCK_BUY 시 차단 일수
    description: str = ""


# 우선순위 순서로 매칭. 먼저 매칭되는 규칙 채택.
RULES: list[DisclosureRule] = [
    # === URGENT 매도 트리거 ===
    DisclosureRule(
        "TRADING_HALT",
        re.compile(r"매매거래정지|상장폐지|관리종목"),
        URGENT, EFFECT_SELL,
        description="매매정지/상장폐지/관리종목",
    ),
    DisclosureRule(
        "FRAUD_DETECTED",
        re.compile(r"분식회계|회계처리위반|감사인.*의견거절"),
        URGENT, EFFECT_SELL,
        description="회계 부정/감사 의견거절",
    ),
    DisclosureRule(
        "CAPITAL_REDUCTION",
        re.compile(r"감자|자본금감소"),
        URGENT, EFFECT_SELL, block_days=999,
        description="자본 감소 결정",
    ),
    DisclosureRule(
        "MAJOR_SHAREHOLDER_SELL",
        re.compile(r"최대주주.*변경|최대주주.*매각|대주주.*매도"),
        URGENT, EFFECT_SELL, block_days=90,
        description="최대주주 변경/매도",
    ),
    DisclosureRule(
        "BLOCK_DEAL_MAJOR",
        re.compile(r"블록딜|시간외대량매매|대량매매"),
        URGENT, EFFECT_BLOCK, block_days=90,
        description="블록딜 (대주주)",
    ),

    # === REVIEW (CB/BW/유증/잠정실적) ===
    DisclosureRule(
        "CB_BW_ISSUE",
        re.compile(r"전환사채권발행결정|신주인수권부사채권발행결정|CB.*발행|BW.*발행"),
        REVIEW, EFFECT_SELL, block_days=60,
        description="CB/BW 발행 결정 (행사기간 추적 필요)",
    ),
    DisclosureRule(
        "RIGHTS_OFFERING_3RD",
        re.compile(r"제3자배정"),
        MONITOR, EFFECT_POSITIVE,
        description="제3자배정 유증 (전략적 투자자 유치)",
    ),
    DisclosureRule(
        "RIGHTS_OFFERING",
        re.compile(r"유상증자결정|주주배정.*증자|일반공모.*증자"),
        REVIEW, EFFECT_BLOCK, block_days=30,
        description="유상증자 결정",
    ),
    DisclosureRule(
        "EARNING_SHOCK",
        re.compile(r"잠정.*영업.*적자전환|잠정.*영업.*손실확대|영업.*적자.*확대"),
        URGENT, EFFECT_SELL, block_days=60,
        description="잠정실적 어닝쇼크",
    ),
    DisclosureRule(
        "EARNING_DISCLOSURE",
        re.compile(r"잠정실적|영업\(잠정\)실적|매출액.*손익.*잠정"),
        URGENT, EFFECT_SELL,
        description="잠정실적 발표 — 매도 트리거",
    ),
    DisclosureRule(
        "BLOCK_DEAL_INSTITUTION",
        re.compile(r"기관.*대량매매|투자기관.*매도"),
        REVIEW, EFFECT_BLOCK, block_days=30,
        description="기관 블록딜",
    ),

    # === POSITIVE (가산 신호) ===
    DisclosureRule(
        "TREASURY_BUY",
        re.compile(r"자기주식취득결정|자기주식.*매입"),
        MONITOR, EFFECT_POSITIVE,
        description="자사주 매입 결정",
    ),
    DisclosureRule(
        "TREASURY_CANCEL",
        re.compile(r"자기주식소각결정|자사주.*소각"),
        MONITOR, EFFECT_POSITIVE,
        description="자사주 소각 결정",
    ),
    DisclosureRule(
        "DIVIDEND_INCREASE",
        re.compile(r"배당.*결정|중간배당|배당금"),
        MONITOR, EFFECT_POSITIVE,
        description="배당 결정/증가",
    ),

    # === MONITOR (추적) ===
    DisclosureRule(
        "MERGER_ACQUISITION",
        re.compile(r"합병결정|영업양도|영업양수|회사합병"),
        REVIEW, EFFECT_NEUTRAL,
        description="합병/영업양수도",
    ),
    DisclosureRule(
        "SPINOFF",
        re.compile(r"분할결정|회사분할"),
        REVIEW, EFFECT_NEUTRAL,
        description="분할 결정",
    ),
    DisclosureRule(
        "MAJOR_HOLDER_CHANGE",
        re.compile(r"주식.*대량보유.*보고|5%.*보고"),
        MONITOR, EFFECT_NEUTRAL,
        description="5%↑ 보유 변동 보고",
    ),
    DisclosureRule(
        "EXEC_STOCK_CHANGE",
        re.compile(r"임원.*주요주주.*소유주식"),
        MONITOR, EFFECT_NEUTRAL,
        description="임원·주요주주 소유주식 변동",
    ),
    DisclosureRule(
        "CONTRACT_LARGE",
        re.compile(r"단일판매.*공급계약|대규모.*공급계약"),
        MONITOR, EFFECT_POSITIVE,
        description="대규모 공급계약 체결",
    ),
    DisclosureRule(
        "INVESTMENT_DECISION",
        re.compile(r"투자판단.*관련.*주요경영사항|신규시설투자"),
        MONITOR, EFFECT_NEUTRAL,
        description="신규 투자/시설 투자 결정",
    ),
    DisclosureRule(
        "LITIGATION",
        re.compile(r"소송.*제기|소송.*판결"),
        REVIEW, EFFECT_NEUTRAL,
        description="소송 관련 공시",
    ),
    DisclosureRule(
        "OTHER_MATERIAL",
        re.compile(r"기타.*경영사항|기타.*주요사항"),
        MONITOR, EFFECT_NEUTRAL,
        description="기타 주요 경영사항",
    ),
]


@dataclass
class ClassifiedDisclosure:
    type_code: str
    severity: str
    effect: str
    description: str
    block_days: int | None
    matched_pattern: str
    raw_report_nm: str


def classify(report_nm: str) -> ClassifiedDisclosure | None:
    """report_nm → 22 타입 중 첫 매칭. 미매칭이면 None."""
    if not report_nm:
        return None
    for rule in RULES:
        if rule.pattern.search(report_nm):
            return ClassifiedDisclosure(
                type_code=rule.type_code,
                severity=rule.severity,
                effect=rule.effect,
                description=rule.description,
                block_days=rule.block_days,
                matched_pattern=rule.pattern.pattern,
                raw_report_nm=report_nm,
            )
    return None
