"""분석기 공통 타입."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

GREEN = "🟢"
YELLOW = "🟡"
RED = "🔴"
STAR = "⭐"


@dataclass
class FilterResult:
    grade: str  # "🟢" | "🟡" | "🔴" | "⭐"
    score: int  # 0~100, 종합 점수에 가중 평균
    details: dict[str, Any] = field(default_factory=dict)
