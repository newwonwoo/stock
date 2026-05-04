"""
KIS API (한국투자증권) 수집기.

토큰 24h 만료 → 캐시 파일에 만료시각 박제 후 자동 재발급.
TradeBot 과 키 공유. 분당 호출 한도 충돌 방지를 위해 호출 사이 sleep.

KIS 분당 한도가 빠듯하므로 본 fetcher 는 **KRX 로 못 뽑는 데이터만**:
  - 외인 보유율 정밀 (장중 갱신, KRX 는 D+1)
  - 시장 지수 KOSPI/KOSDAQ/KOSPI200
  - (선택) 일봉 보강

대부분 시세성 데이터는 KRX (pykrx) 가 우선.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import requests

from src import config
from src.utils.kst_time import KST
from src.utils.logger import get_logger

log = get_logger("kis")

KIS_BASE_URL_REAL = "https://openapi.koreainvestment.com:9443"
KIS_BASE_URL_MOCK = "https://openapivts.koreainvestment.com:29443"

_TOKEN_CACHE = config.CACHE_DIR / "kis_token.json"
_CALL_INTERVAL_SEC = 0.2   # 분당 호출 한도 보수적 분산
_TIMEOUT = 15


@dataclass
class KisToken:
    access_token: str
    expires_at: datetime  # KST


class KisError(RuntimeError):
    pass


class KisFetcher:
    def __init__(
        self,
        app_key: str | None = None,
        app_secret: str | None = None,
        *,
        use_mock: bool = False,
    ) -> None:
        self.app_key = app_key or config.KIS_APP_KEY
        self.app_secret = app_secret or config.KIS_APP_SECRET
        if not self.app_key or not self.app_secret:
            raise RuntimeError("KIS_APP_KEY / KIS_APP_SECRET 미설정")
        self.base_url = KIS_BASE_URL_MOCK if use_mock else KIS_BASE_URL_REAL
        self._session = requests.Session()
        self._last_call_ts: float = 0.0
        self._token: KisToken | None = None

    # ----- token -----

    def _load_cached_token(self) -> KisToken | None:
        if not _TOKEN_CACHE.exists():
            return None
        try:
            j = json.loads(_TOKEN_CACHE.read_text())
            exp = datetime.fromisoformat(j["expires_at"])
            if exp - datetime.now(KST) < timedelta(minutes=5):
                return None
            return KisToken(access_token=j["access_token"], expires_at=exp)
        except Exception:
            return None

    def _save_token(self, tok: KisToken) -> None:
        _TOKEN_CACHE.parent.mkdir(parents=True, exist_ok=True)
        _TOKEN_CACHE.write_text(
            json.dumps(
                {"access_token": tok.access_token, "expires_at": tok.expires_at.isoformat()}
            )
        )

    def _issue_token(self) -> KisToken:
        url = f"{self.base_url}/oauth2/tokenP"
        body = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
        }
        r = self._session.post(url, json=body, timeout=_TIMEOUT)
        r.raise_for_status()
        d = r.json()
        # KIS 토큰 만료: 24h. 응답 expires_in (초) 있으면 사용, 없으면 23.5h 보수적.
        exp_sec = int(d.get("expires_in", 23 * 3600 + 30 * 60))
        exp = datetime.now(KST) + timedelta(seconds=exp_sec)
        tok = KisToken(access_token=d["access_token"], expires_at=exp)
        self._save_token(tok)
        log.info(f"KIS token issued, expires_at={exp.isoformat()}")
        return tok

    def _ensure_token(self) -> str:
        if self._token is None:
            self._token = self._load_cached_token() or self._issue_token()
        elif self._token.expires_at - datetime.now(KST) < timedelta(minutes=5):
            self._token = self._issue_token()
        return self._token.access_token

    # ----- request helper -----

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_call_ts
        if elapsed < _CALL_INTERVAL_SEC:
            time.sleep(_CALL_INTERVAL_SEC - elapsed)
        self._last_call_ts = time.monotonic()

    def _get(self, path: str, tr_id: str, params: dict[str, Any]) -> dict[str, Any]:
        self._throttle()
        token = self._ensure_token()
        url = f"{self.base_url}{path}"
        headers = {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {token}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": tr_id,
            "custtype": "P",
        }
        r = self._session.get(url, headers=headers, params=params, timeout=_TIMEOUT)
        if r.status_code != 200:
            raise KisError(f"{path} HTTP {r.status_code}: {r.text[:200]}")
        d = r.json()
        if d.get("rt_cd") not in (None, "0"):
            raise KisError(f"{path}: rt_cd={d.get('rt_cd')} msg={d.get('msg1')}")
        return d

    # ----- 공개 메서드 -----

    def fetch_daily_ohlcv(self, code: str, period: str = "D", count: int = 100) -> list[dict[str, Any]]:
        """일/주/월봉. period: D/W/M."""
        end = datetime.now(KST).strftime("%Y%m%d")
        start = (datetime.now(KST) - timedelta(days=count * 2 + 10)).strftime("%Y%m%d")
        d = self._get(
            "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice",
            tr_id="FHKST03010100",
            params={
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": code,
                "FID_INPUT_DATE_1": start,
                "FID_INPUT_DATE_2": end,
                "FID_PERIOD_DIV_CODE": period,
                "FID_ORG_ADJ_PRC": "0",
            },
        )
        return d.get("output2", []) or []

    def fetch_market_indices(self) -> dict[str, dict[str, Any]]:
        """KOSPI(0001) / KOSDAQ(1001) / KOSPI200(2001) 현재가."""
        out: dict[str, dict[str, Any]] = {}
        idx_map = {"KOSPI": "0001", "KOSDAQ": "1001", "KOSPI200": "2001"}
        for name, code in idx_map.items():
            d = self._get(
                "/uapi/domestic-stock/v1/quotations/inquire-index-price",
                tr_id="FHPUP02100000",
                params={"FID_COND_MRKT_DIV_CODE": "U", "FID_INPUT_ISCD": code},
            )
            out[name] = d.get("output", {}) or {}
        return out

    def fetch_investor_flow(self, code: str) -> dict[str, Any]:
        """외인/기관/개인 일별 순매수 (당일 누적)."""
        d = self._get(
            "/uapi/domestic-stock/v1/quotations/inquire-investor",
            tr_id="FHKST01010900",
            params={"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code},
        )
        return {"output": d.get("output", []) or []}

    def fetch_foreign_ownership(self, code: str) -> dict[str, Any]:
        """외인 보유율 (현재). 정밀 모니터링용."""
        d = self._get(
            "/uapi/domestic-stock/v1/quotations/inquire-foreign-institution-total",
            tr_id="FHKST01010900",
            params={"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code},
        )
        return d
