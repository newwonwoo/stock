"""
DART (전자공시) API 수집기.

엔드포인트:
  - corpCode.xml          : 종목코드 ↔ DART 고유번호(corp_code) 매핑 (zip)
  - list.json             : 일별 공시 목록
  - fnlttSinglAcntAll.json: 정기보고서 단일회사 전체 재무
  - majorstock.json       : 5%↑ 대량보유 변동 (NPS 추적)
  - elestock.json         : 임원·주요주주 변동

호출 한도: 일 10,000건 (DART_DAILY_LIMIT). call counter 로 추적.
"""

from __future__ import annotations

import io
import time
import zipfile
from dataclasses import dataclass
from typing import Any
from xml.etree import ElementTree as ET

import requests

from src import config
from src.utils.logger import get_logger

log = get_logger("dart")

_TIMEOUT = 30
_RETRIES = 3
_RETRY_BACKOFF = (1.0, 2.0, 4.0)


@dataclass
class CorpCode:
    corp_code: str   # 8자리
    corp_name: str
    stock_code: str  # 6자리, 비상장은 ""


class DartCallLimit(RuntimeError):
    pass


class DartApiError(RuntimeError):
    pass


class DartFetcher:
    def __init__(self, api_key: str | None = None, daily_limit: int = config.DART_DAILY_LIMIT) -> None:
        self.api_key = api_key or config.DART_API_KEY
        if not self.api_key:
            raise RuntimeError("DART_API_KEY 미설정")
        self.daily_limit = daily_limit
        self._calls = 0
        self._session = requests.Session()

    @property
    def call_count(self) -> int:
        return self._calls

    def _check_limit(self) -> None:
        if self._calls >= self.daily_limit:
            raise DartCallLimit(f"DART daily call limit reached: {self._calls}")

    def _get(self, path: str, params: dict[str, Any] | None = None, *, raw: bool = False) -> Any:
        self._check_limit()
        url = f"{config.DART_BASE_URL}/{path}"
        merged = {"crtfc_key": self.api_key, **(params or {})}
        last_err: Exception | None = None
        for attempt in range(_RETRIES):
            try:
                self._calls += 1
                r = self._session.get(url, params=merged, timeout=_TIMEOUT)
                r.raise_for_status()
                if raw:
                    return r.content
                payload = r.json()
                # DART 의 status: "000" = 정상, "013" = 조회결과 없음 (정상 취급).
                status = payload.get("status")
                if status not in ("000", "013"):
                    raise DartApiError(f"{path}: status={status} message={payload.get('message')}")
                return payload
            except (requests.RequestException, ValueError) as e:
                last_err = e
                if attempt < _RETRIES - 1:
                    time.sleep(_RETRY_BACKOFF[attempt])
                    continue
                raise DartApiError(f"{path}: {e}") from e
        raise DartApiError(f"{path}: unreachable (last={last_err})")

    # ----- 공개 메서드 -----

    def fetch_corp_codes(self) -> list[CorpCode]:
        """월 1회 호출. 전체 기업 corp_code 매핑 zip → list[CorpCode]."""
        zbytes = self._get("corpCode.xml", raw=True)
        with zipfile.ZipFile(io.BytesIO(zbytes)) as zf:
            with zf.open("CORPCODE.xml") as f:
                tree = ET.parse(f)
        out: list[CorpCode] = []
        for el in tree.getroot().findall("list"):
            stock = (el.findtext("stock_code") or "").strip()
            out.append(
                CorpCode(
                    corp_code=(el.findtext("corp_code") or "").strip(),
                    corp_name=(el.findtext("corp_name") or "").strip(),
                    stock_code=stock,
                )
            )
        log.info(f"corp_codes fetched: total={len(out)} listed={sum(1 for c in out if c.stock_code)}")
        return out

    def fetch_quarterly_financials(
        self,
        corp_code: str,
        bsns_year: str,
        reprt_code: str = "11013",
        fs_div: str = "CFS",
    ) -> list[dict[str, Any]]:
        """
        정기보고서 단일회사 전체 재무.

        reprt_code: 11013=1Q, 11012=반기, 11014=3Q, 11011=사업보고서.
        fs_div: CFS=연결, OFS=별도. 연결 우선, 없으면 별도 fallback.
        """
        params = {
            "corp_code": corp_code,
            "bsns_year": bsns_year,
            "reprt_code": reprt_code,
            "fs_div": fs_div,
        }
        payload = self._get("fnlttSinglAcntAll.json", params)
        items = payload.get("list", []) or []
        if not items and fs_div == "CFS":
            # 연결 없으면 별도로 재시도
            log.info(f"financials CFS empty, fallback OFS: corp={corp_code} year={bsns_year}")
            params["fs_div"] = "OFS"
            payload = self._get("fnlttSinglAcntAll.json", params)
            items = payload.get("list", []) or []
        return items

    def fetch_daily_disclosures(
        self,
        bgn_de: str,
        end_de: str | None = None,
        *,
        page_count: int = 100,
    ) -> list[dict[str, Any]]:
        """일별 공시 목록 (전체 시장). YYYYMMDD."""
        end = end_de or bgn_de
        out: list[dict[str, Any]] = []
        page = 1
        while True:
            self._check_limit()
            payload = self._get(
                "list.json",
                {
                    "bgn_de": bgn_de,
                    "end_de": end,
                    "page_no": str(page),
                    "page_count": str(page_count),
                },
            )
            items = payload.get("list", []) or []
            out.extend(items)
            total_page = int(payload.get("total_page", 1) or 1)
            if page >= total_page or not items:
                break
            page += 1
        log.info(f"disclosures: {bgn_de}~{end} count={len(out)}")
        return out

    def fetch_major_stock_changes(
        self,
        corp_code: str,
    ) -> list[dict[str, Any]]:
        """5%↑ 대량보유 변동 보고. NPS 추적용."""
        payload = self._get("majorstock.json", {"corp_code": corp_code})
        return payload.get("list", []) or []

    def fetch_executive_changes(
        self,
        corp_code: str,
    ) -> list[dict[str, Any]]:
        """임원·주요주주 소유주식 변동."""
        payload = self._get("elestock.json", {"corp_code": corp_code})
        return payload.get("list", []) or []
