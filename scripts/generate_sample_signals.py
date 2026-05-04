"""
HMAC-SHA256 서명된 샘플 시그널 JSON 4종 생성.

생성 파일 (out/ 디렉토리):
  - buy_signals_{YYYY-MM-DD}.json
  - macro_status_{YYYY-MM-DD}.json
  - blacklist_active.json
  - sell_signals_test.json

각 파일은 다음 envelope 로 감싼다:
  {
    "signed_by": "research_v1",
    "sha256_hmac": "<hex>",
    "data": { ... }
  }

HMAC 키: 환경변수 RESEARCH_HMAC_KEY.
HMAC 대상: data 부분의 canonical JSON (sort_keys=True, separators=(",", ":")).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))
SIGNED_BY = "research_v1"
OUT_DIR = Path(__file__).resolve().parent.parent / "out"


def _canonical(data: dict) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _hmac_hex(data: dict, key: str) -> str:
    return hmac.new(key.encode("utf-8"), _canonical(data), hashlib.sha256).hexdigest()


def _wrap(data: dict, key: str) -> dict:
    return {
        "signed_by": SIGNED_BY,
        "sha256_hmac": _hmac_hex(data, key),
        "data": data,
    }


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"[write] {path}")


def build_buy_signals(today: str, now_iso: str) -> dict:
    valid_until = (datetime.strptime(today, "%Y-%m-%d") + timedelta(days=5)).strftime("%Y-%m-%d")
    return {
        "date": today,
        "signals": [
            {
                "code": "000660",
                "name": "SK하이닉스",
                "signal": "STRONG_BUY",
                "score": 92,
                "nine_filter": {
                    "financial_trend": "🟢",
                    "quant_health": "🟢",
                    "margin_diagnosis": "🟢",
                    "moat": "🟢",
                    "flow": "🟢",
                    "credit_short": "🟢",
                    "nps": "🟢",
                    "technical": "🟢",
                    "report": "⭐",
                },
                "positive_signals": [
                    {"type": "NPS_NEW", "score": 15},
                    {"type": "ANALYST_TARGET_UP", "score": 10},
                ],
                "negative_signals": [],
                "blocked": False,
                "block_reasons": [],
                "moving_averages": {
                    "ma10": 215000,
                    "ma15": 208000,
                },
                "valid_until": valid_until,
                "created_at": now_iso,
            },
            {
                "code": "005930",
                "name": "삼성전자",
                "signal": "BUY",
                "score": 78,
                "nine_filter": {
                    "financial_trend": "🟢",
                    "quant_health": "🟢",
                    "margin_diagnosis": "🟡",
                    "moat": "🟢",
                    "flow": "🟡",
                    "credit_short": "🟢",
                    "nps": "🟡",
                    "technical": "🟢",
                    "report": "🟢",
                },
                "positive_signals": [
                    {"type": "ANALYST_TARGET_UP", "score": 8},
                ],
                "negative_signals": [
                    {"type": "INSIDER_SELL_SMALL", "score": -5},
                ],
                "blocked": False,
                "block_reasons": [],
                "moving_averages": {
                    "ma10": 71500,
                    "ma15": 70200,
                },
                "valid_until": valid_until,
                "created_at": now_iso,
            },
        ],
    }


def build_macro_status(today: str, now_iso: str) -> dict:
    return {
        "date": today,
        "overall": "🟡",
        "indicators": {
            "kospi_change": -0.42,
            "kosdaq_change": -0.81,
            "sp500_change": 0.31,
            "usd_krw": 1394,
            "us_10y_yield": 4.51,
            "foreign_kospi_net": -284000000000,
        },
        "events_today": [
            {"time": "14:00", "type": "BOK_RATE", "expected": "동결"},
        ],
        "claude_opinion_short": "환율 1400 임박 + 외인 매도 지속. 신규 진입 보수적 권고.",
        "created_at": now_iso,
    }


def build_blacklist(today: str) -> dict:
    blocked_until = (datetime.strptime(today, "%Y-%m-%d") + timedelta(days=90)).strftime("%Y-%m-%d")
    return {
        "updated_at_date": today,
        "blacklist": [
            {
                "code": "047810",
                "name": "한국항공우주",
                "blocked_until": blocked_until,
                "block_reasons": [
                    {
                        "type": "MAJOR_SHAREHOLDER_SELL",
                        "detected_at": today,
                        "severity": "URGENT",
                        "description": "최대주주 5.2% 매도",
                    }
                ],
            }
        ],
    }


def build_sell_signal_test(now_iso: str, today: str) -> dict:
    expires_at = (datetime.now(KST) + timedelta(days=1)).replace(microsecond=0).isoformat()
    return {
        "signal_id": f"{today.replace('-', '')}_035720_TEST",
        "code": "035720",
        "name": "카카오",
        "severity": "URGENT",
        "trigger": {
            "type": "DISCLOSURE",
            "subtype": "전환사채권발행결정",
            "details": "300억, 행사 2026-08-01부터 (샘플)",
        },
        "action_recommendation": "전량 시초가 매도",
        "reason_short": "CB 발행 (테스트 시그널)",
        "created_at": now_iso,
        "expires_at": expires_at,
        "consumed": False,
    }


def main() -> None:
    key = os.environ.get("RESEARCH_HMAC_KEY")
    if not key:
        raise SystemExit("RESEARCH_HMAC_KEY 환경변수가 비어있다.")

    now = datetime.now(KST).replace(microsecond=0)
    today = now.strftime("%Y-%m-%d")
    now_iso = now.isoformat()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    files = [
        (OUT_DIR / f"buy_signals_{today}.json", build_buy_signals(today, now_iso)),
        (OUT_DIR / f"macro_status_{today}.json", build_macro_status(today, now_iso)),
        (OUT_DIR / "blacklist_active.json", build_blacklist(today)),
        (OUT_DIR / "sell_signals_test.json", build_sell_signal_test(now_iso, today)),
    ]

    for path, data in files:
        _write(path, _wrap(data, key))

    print(f"[done] {len(files)} files in {OUT_DIR}")


if __name__ == "__main__":
    main()
