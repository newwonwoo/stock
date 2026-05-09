"""필터 ⑥ 신용·공매도. 시총 대비 공매도 잔고율 기반 (절대 거래대금 X).

기존: SHORT_TOP10 (절대 거래대금 Top10) 매칭 → 자동 차단.
문제: 시총 큰 메가캡 (삼전/현대차) 이 항상 Top10 → 우량주 무차별 차단.

수정: 공매도 잔고율 (short interest / market cap) 기준.
  < 1%   → 정상 (대부분 메가캡 여기)
  1~3%  → 보통
  3~5%  → 주의 (감점)
  ≥ 5%  → 위험 (자동 차단 → blocked)

추가 보조 지표 — 신용잔고율 (credit_ratio).
"""

from __future__ import annotations

from src.analyzers.base import GREEN, RED, YELLOW, FilterResult


def analyze(
    code: str,
    short_interest_ratio: float | None = None,
    credit_ratio: float | None = None,
    *,
    legacy_short_top10_codes: set[str] | None = None,
) -> FilterResult:
    """
    short_interest_ratio: 공매도 잔고 / 시가총액 (0.05 = 5%). 핵심 지표.
    credit_ratio: 신용잔고 / 시가총액 (0.05 = 5%). 보조.
    legacy_short_top10_codes: 호환성 — 절대 거래대금 Top10. 점수 계산엔 X,
                               메타에만 박제 (디버깅 용).
    """
    in_top10 = bool(legacy_short_top10_codes and code in legacy_short_top10_codes)

    # 1차: short_interest_ratio (공매도 잔고율) 기반
    if short_interest_ratio is not None:
        if short_interest_ratio >= 0.05:
            # 시총의 5% 이상이 공매도된 상태 — 강한 매도 압력
            return FilterResult(
                grade=RED,
                score=10,
                details={
                    "short_interest_ratio": round(short_interest_ratio, 4),
                    "auto_excluded": True,
                    "reason": "공매도 잔고율 ≥5%",
                    "credit_ratio": round(credit_ratio, 4) if credit_ratio is not None else None,
                    "in_legacy_top10": in_top10,
                },
            )
        elif short_interest_ratio >= 0.03:
            short_grade, short_score = YELLOW, 50
        elif short_interest_ratio >= 0.01:
            short_grade, short_score = YELLOW, 70
        else:
            short_grade, short_score = GREEN, 85
    else:
        # 잔고율 데이터 없으면 보수적 통과
        short_grade, short_score = GREEN, 70

    # 2차: credit_ratio (신용잔고율) 보조
    if credit_ratio is not None:
        if credit_ratio >= 0.05:
            credit_grade, credit_score = RED, 25
        elif credit_ratio >= 0.03:
            credit_grade, credit_score = YELLOW, 55
        else:
            credit_grade, credit_score = GREEN, 85
    else:
        credit_grade, credit_score = GREEN, 75

    # 두 지표 결합 — 둘 중 더 나쁜 쪽
    grade = min(short_grade, credit_grade, key=lambda g: (g == GREEN, g == YELLOW, g == RED))
    # 위 min 은 ordering 안 맞음. 명시적으로:
    if RED in (short_grade, credit_grade):
        grade = RED
    elif YELLOW in (short_grade, credit_grade):
        grade = YELLOW
    else:
        grade = GREEN

    score = min(short_score, credit_score)

    return FilterResult(
        grade=grade,
        score=score,
        details={
            "short_interest_ratio": round(short_interest_ratio, 4) if short_interest_ratio is not None else None,
            "credit_ratio": round(credit_ratio, 4) if credit_ratio is not None else None,
            "auto_excluded": False,
            "in_legacy_top10": in_top10,
        },
    )
