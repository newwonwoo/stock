"""
필터 ③ 마진 진단. 영업이익률 변화의 원인을 5가지로 분류.

DESIGN.md 6.3 단순화 버전:
  - 정상     : OPM 안정 또는 상승
  - CAPEX형  : OPM 하락 + CAPEX 급증 (감가상각 일시 압박)
  - R&D형    : OPM 하락 + R&D 급증
  - 신사업형 : OPM 하락 + 매출 급증 (신규 라인 적자)
  - 원가/경쟁: OPM 하락 + 위 셋 모두 X (위험 신호)
"""

from __future__ import annotations

from src.analyzers.base import GREEN, RED, YELLOW, FilterResult


def analyze(
    opm_prev: float,
    opm_curr: float,
    capex_yoy: float = 0.0,
    rnd_yoy: float = 0.0,
    revenue_yoy: float = 0.0,
) -> FilterResult:
    """
    opm_*: 영업이익률 (%, 0~100). capex_yoy/rnd_yoy/revenue_yoy: YoY 증가율 (1.0 = 100%).
    """
    delta = opm_curr - opm_prev

    if delta >= -0.5:  # 0.5%p 이내는 안정으로 본다
        return FilterResult(
            grade=GREEN,
            score=80,
            details={"category": "정상", "opm_delta_pp": round(delta, 2)},
        )

    if capex_yoy >= 0.5:
        category, grade, score = "CAPEX형", YELLOW, 60
    elif rnd_yoy >= 0.5:
        category, grade, score = "R&D형", YELLOW, 60
    elif revenue_yoy >= 0.5:
        category, grade, score = "신사업형", YELLOW, 55
    else:
        category, grade, score = "원가/경쟁", RED, 25

    return FilterResult(
        grade=grade,
        score=score,
        details={
            "category": category,
            "opm_delta_pp": round(delta, 2),
            "capex_yoy": capex_yoy,
            "rnd_yoy": rnd_yoy,
            "revenue_yoy": revenue_yoy,
        },
    )
