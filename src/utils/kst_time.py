"""KST 시간 헬퍼. UTC↔KST 변환 + 영업일 판단."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))

# 한국 증시 휴장일 (정규장). 매년 갱신 필요.
HOLIDAYS_2026 = frozenset(
    {
        "2026-01-01",
        "2026-02-16", "2026-02-17", "2026-02-18",
        "2026-03-02",
        "2026-05-01",
        "2026-05-05",
        "2026-05-25",
        "2026-06-03",
        "2026-06-06",
        "2026-08-17",
        "2026-09-24", "2026-09-25",
        "2026-10-05", "2026-10-09",
        "2026-12-25",
        "2026-12-31",
    }
)


def now_kst() -> datetime:
    return datetime.now(KST)


def today_kst() -> date:
    return now_kst().date()


def to_kst(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=KST)
    return dt.astimezone(KST)


def fmt_date(d: date) -> str:
    return d.strftime("%Y-%m-%d")


def fmt_compact(d: date) -> str:
    return d.strftime("%Y%m%d")


def is_holiday(d: date) -> bool:
    return fmt_date(d) in HOLIDAYS_2026


def is_business_day(d: date) -> bool:
    if d.weekday() >= 5:  # 5=Sat, 6=Sun
        return False
    return not is_holiday(d)


def prev_business_day(d: date) -> date:
    cur = d - timedelta(days=1)
    while not is_business_day(cur):
        cur -= timedelta(days=1)
    return cur


def next_business_day(d: date) -> date:
    cur = d + timedelta(days=1)
    while not is_business_day(cur):
        cur += timedelta(days=1)
    return cur
