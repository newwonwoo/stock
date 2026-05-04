"""필터 ④ 해자. 5년 ROE 안정성 + EPS 성장 + 화이트리스트."""

from __future__ import annotations

import json
import statistics
from pathlib import Path

from src import config
from src.analyzers.base import GREEN, RED, YELLOW, FilterResult

WHITELIST_FILE = config.DATA_DIR / "moat_whitelist.json"


def _load_whitelist() -> set[str]:
    if not WHITELIST_FILE.exists():
        return set()
    j = json.loads(WHITELIST_FILE.read_text(encoding="utf-8"))
    return set(j.get("codes", []))


def analyze(code: str, roe_5y: list[float], eps_5y: list[float]) -> FilterResult:
    """
    roe_5y: 최근 5년 ROE (%, 오래된 순). eps_5y: 최근 5년 EPS (오래된 순).
    """
    in_whitelist = code in _load_whitelist()

    if len(roe_5y) < 3 or len(eps_5y) < 3:
        grade = GREEN if in_whitelist else YELLOW
        return FilterResult(
            grade=grade,
            score=80 if in_whitelist else 50,
            details={"in_whitelist": in_whitelist, "reason": "insufficient_data"},
        )

    roe_avg = sum(roe_5y) / len(roe_5y)
    roe_std = statistics.pstdev(roe_5y) if len(roe_5y) > 1 else 0
    eps_growth = (eps_5y[-1] - eps_5y[0]) / abs(eps_5y[0]) if eps_5y[0] else 0

    high_roe = roe_avg >= 12
    stable_roe = roe_std <= 5
    grow_eps = eps_growth >= 0.3

    score_components = [high_roe, stable_roe, grow_eps]
    ok = sum(score_components)

    if in_whitelist:
        ok += 1

    if ok >= 4:
        grade, score = GREEN, 95
    elif ok == 3:
        grade, score = GREEN, 80
    elif ok == 2:
        grade, score = YELLOW, 60
    else:
        grade, score = RED, 30

    return FilterResult(
        grade=grade,
        score=score,
        details={
            "in_whitelist": in_whitelist,
            "roe_avg": round(roe_avg, 2),
            "roe_std": round(roe_std, 2),
            "eps_growth_5y": round(eps_growth, 2),
        },
    )
