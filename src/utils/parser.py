"""
텔레그램 채널 메시지 파서.

3종:
  - parse_butler         : @butler_works 등 정형 브로커 요약 (정규식)
  - parse_core_analyst   : 코어 애널리스트 자유 포맷 (키워드 매칭)
  - parse_fallback       : 메타데이터만 (종목코드 추출)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# 6자리 종목코드. 뒤에 비숫자 또는 EOS.
_CODE_RE = re.compile(r"\b(\d{6})\b")
# 종목명 (한글 2~10자). 종목코드 옆에 붙는 패턴.
_NAME_RE = re.compile(r"([가-힣A-Za-z0-9]{2,15})\s*\(?(\d{6})\)?")
# 목표가 "목표가 350,000" / "TP 350,000" / "목표주가 35만원"
_TARGET_RE = re.compile(r"(?:목표\s*(?:주\s*)?가|TP|target)[\s:]*([0-9,]+)", re.IGNORECASE)
# 투자의견 (매수/매도/Hold/Buy/Sell)
_OPINION_RE = re.compile(
    r"(?P<op>매수|매도|중립|Buy|Sell|Hold|BUY|SELL|HOLD|시장수익률|outperform|underperform)",
    re.IGNORECASE,
)
# 작성자 / 애널 (간단): "작성자: 김선우" / "by 김선우"
_AUTHOR_RE = re.compile(r"(?:작성자|애널|by|analyst)[\s:]*([가-힣A-Za-z]{2,10})", re.IGNORECASE)

POSITIVE_KEYWORDS = (
    "목표가 상향", "목표주가 상향", "Top Pick", "탑픽", "최선호",
    "매수", "BUY", "강력 매수", "비중확대", "outperform",
)
NEGATIVE_KEYWORDS = (
    "목표가 하향", "목표주가 하향", "매도", "SELL",
    "비중축소", "underperform", "투자의견 하향",
)


@dataclass
class ParsedMessage:
    code: str | None = None
    name: str | None = None
    opinion: str | None = None         # 매수/매도/...
    target_price: int | None = None
    author: str | None = None
    sentiment: str = "neutral"          # positive/negative/neutral
    keywords: list[str] = field(default_factory=list)
    raw_excerpt: str = ""


def _extract_first_code(text: str) -> tuple[str | None, str | None]:
    m = _NAME_RE.search(text)
    if m:
        return m.group(2), m.group(1)
    m2 = _CODE_RE.search(text)
    return (m2.group(1), None) if m2 else (None, None)


def _parse_target(text: str) -> int | None:
    m = _TARGET_RE.search(text)
    if not m:
        return None
    raw = m.group(1).replace(",", "")
    try:
        return int(raw)
    except ValueError:
        return None


def _detect_sentiment(text: str) -> tuple[str, list[str]]:
    hits: list[str] = []
    pos = 0
    neg = 0
    for k in POSITIVE_KEYWORDS:
        if k in text:
            hits.append(k)
            pos += 1
    for k in NEGATIVE_KEYWORDS:
        if k in text:
            hits.append(k)
            neg += 1
    if pos > neg:
        return "positive", hits
    if neg > pos:
        return "negative", hits
    return "neutral", hits


def parse_butler(text: str) -> ParsedMessage:
    """정형 브로커 요약 채널. 종목코드/작성자/투자의견/목표가 추출."""
    code, name = _extract_first_code(text)
    target = _parse_target(text)
    op = (m.group("op") if (m := _OPINION_RE.search(text)) else None)
    author = (m.group(1) if (m := _AUTHOR_RE.search(text)) else None)
    sentiment, kws = _detect_sentiment(text)
    return ParsedMessage(
        code=code,
        name=name,
        opinion=op,
        target_price=target,
        author=author,
        sentiment=sentiment,
        keywords=kws,
        raw_excerpt=text[:200],
    )


def parse_core_analyst(text: str) -> ParsedMessage:
    """코어 애널 자유 포맷. 종목코드 + 키워드 매칭."""
    code, name = _extract_first_code(text)
    sentiment, kws = _detect_sentiment(text)
    target = _parse_target(text)
    return ParsedMessage(
        code=code,
        name=name,
        target_price=target,
        sentiment=sentiment,
        keywords=kws,
        raw_excerpt=text[:200],
    )


def parse_fallback(text: str) -> ParsedMessage:
    """메타데이터만. 종목코드만 잡고 끝."""
    code, name = _extract_first_code(text)
    return ParsedMessage(code=code, name=name, raw_excerpt=text[:200])


PARSERS = {
    "broker_summary": parse_butler,
    "core_analyst": parse_core_analyst,
    "fallback": parse_fallback,
}


def parse(text: str, channel_type: str) -> ParsedMessage:
    return PARSERS.get(channel_type, parse_fallback)(text)
