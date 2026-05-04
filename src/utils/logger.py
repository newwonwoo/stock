"""JSON 로그 + 시크릿 마스킹 필터."""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from typing import Any

# 마스킹 대상 환경변수 이름. 값이 비어있지 않으면 로그 출력 시 *** 로 치환.
SECRET_ENV_NAMES = (
    "DART_API_KEY",
    "KIS_APP_KEY",
    "KIS_APP_SECRET",
    "KIS_ACCOUNT_NO",
    "TELEGRAM_API_ID",
    "TELEGRAM_API_HASH",
    "TELEGRAM_SESSION",
    "RESEARCH_HMAC_KEY",
    "EC2_SSH_KEY",
)

# 패턴 마스킹 (코드/메시지에 명시된 키=값 형태).
_KV_PATTERN = re.compile(
    r"(?i)(api[_-]?key|secret|token|hash|hmac|session)\s*[=:]\s*[A-Za-z0-9_\-./+=]{6,}"
)


def _collect_secret_values() -> list[str]:
    out: list[str] = []
    for name in SECRET_ENV_NAMES:
        v = os.environ.get(name, "")
        if v and len(v) >= 6:
            out.append(v)
    return out


class SecretMaskingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401
        secrets = _collect_secret_values()
        try:
            msg = record.getMessage()
        except Exception:
            return True
        for s in secrets:
            if s in msg:
                msg = msg.replace(s, "***")
        msg = _KV_PATTERN.sub(r"\1=***", msg)
        record.msg = msg
        record.args = ()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def get_logger(name: str = "stock") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(JsonFormatter())
    h.addFilter(SecretMaskingFilter())
    logger.addHandler(h)
    logger.propagate = False
    return logger
