#!/usr/bin/env python3
"""
Kakao "나에게 보내기" sender — newwonwoo/stock 리서치 봇용.

사용:
    python scripts/kakao_send.py {daily|weekly|monthly}

GitHub Actions 의 마지막 step 에서 호출. out/ 의 JSON 산출물을 한국어
메시지로 만들어 Kakao memo/default/send API 로 발송. PC 무관.

필수 env (= GitHub Secrets):
    KAKAO_REST_API_KEY    — Kakao Developers 앱 REST API 키
    KAKAO_REFRESH_TOKEN   — talk_message scope refresh_token
    KAKAO_CLIENT_SECRET   — Client Secret 활성 ON 시 필수
    RESEARCH_HMAC_KEY     — envelope HMAC 검증

선택 env:
    OUT_DIR    — 산출물 디렉터리 (기본 ./out)
    DRY_RUN=1  — 실제 발송 안 하고 메시지 미리보기만
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

KST = timezone(timedelta(hours=9))
OUT_DIR = Path(os.environ.get("OUT_DIR", "out"))


# ---------------------------- 공용 유틸 ----------------------------

def kst_today() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d")


def kst_yyyymm() -> str:
    return datetime.now(KST).strftime("%Y-%m")


def latest(pattern: str) -> Path | None:
    candidates = sorted(OUT_DIR.glob(pattern))
    return candidates[-1] if candidates else None


def fmt_signed(n: float, places: int = 2) -> str:
    sign = "+" if n >= 0 else ""
    return f"{sign}{n:.{places}f}"


def load_envelope(path: Path | None):
    """envelope JSON 이면 HMAC 검증 후 data 반환. plain JSON 이면 그대로."""
    if path is None or not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"[ERR] {path.name} JSON parse fail: {e}", file=sys.stderr)
        return None
    if not isinstance(raw, dict) or "data" not in raw:
        return raw
    data = raw["data"]
    sig = raw.get("sha256_hmac", "") or ""
    key = os.environ.get("RESEARCH_HMAC_KEY", "") or ""
    if sig and key:
        canonical = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        expected = hmac.new(key.encode("utf-8"), canonical, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, sig):
            print(f"[WARN] HMAC mismatch on {path.name}", file=sys.stderr)
            if isinstance(data, dict):
                data = dict(data)
                data["__hmac_invalid"] = True
    elif sig and not key:
        print(f"[WARN] RESEARCH_HMAC_KEY 없음 — {path.name} HMAC 검증 스킵", file=sys.stderr)
    return data


# ---------------------------- 라벨 매핑 ----------------------------

OVERALL_EMOJI = {
    "BULL": "🟢", "GOOD": "🟢", "GREEN": "🟢",
    "NEUTRAL": "🟡", "MIXED": "🟡", "YELLOW": "🟡",
    "BEAR": "🔴", "BAD": "🔴", "RED": "🔴",
    "PANIC": "🚨", "CRASH": "🚨", "ALERT": "🚨",
}

# 9 필터 한국어 라벨 (src/analyzers/buy_signal_generator.py NINE_FILTER_KEYS 순서)
# ① 재무 추세 (financial_trend)
# ② 정량 건전성 (quant_health)
# ③ 신용 진단 (margin_diagnosis)
# ④ 해자 (moat_score)
# ⑤ 수급 (flow_analysis)
# ⑥ 신용·공매도 (credit_short)
# ⑦ 국민연금 (nps_tracker)
# ⑧ 기술적 (technical)
# ⑨ 리포트 모멘텀 (report_momentum)
FILTER_LABELS = {
    "financial_trend": "재무",
    "quant_health": "정량",
    "margin_diagnosis": "진단",
    "moat": "해자",
    "flow": "수급",
    "credit_short": "공매도",
    "nps": "연금",
    "technical": "기술",
    "report": "리포트",
}
NINE_FILTER_ORDER = (
    "financial_trend", "quant_health", "margin_diagnosis",
    "moat", "flow", "credit_short", "nps",
    "technical", "report",
)
# nine_filter dict 값이 영문 grade ("GREEN") 이거나 이모지 ("🟢") 둘 다 들어올 수 있음
GRADE_ICON = {
    "STAR": "⭐", "GREEN": "✓", "YELLOW": "△", "RED": "✗",
    "⭐": "⭐", "🟢": "✓", "🟡": "△", "🔴": "✗",
}

# positive_signals[].type 한국어 (buy_signal_generator._collect_positive)
POSITIVE_LABELS = {
    "NPS_NEW": "연금 신규편입",
    "NPS_ADD": "연금 확대",
    "ANALYST_TARGET_UP": "리포트 목표가↑",
    "STRONG_FLOW": "외인+기관 매수",
    "PULLBACK_AT_MA250_SUPPORT": "1년선 위 조정 후 지지",
}
NEGATIVE_LABELS = {
    "NPS_REDUCE": "연금 축소/매도",
    "SHORT_TOP10": "공매도 Top10",
}


def emoji_for(overall) -> str:
    if not overall:
        return "🟡"
    s = str(overall).strip()
    if s and ord(s[0]) > 127:
        return s[:1]
    return OVERALL_EMOJI.get(s.upper(), "🟡")


def filter_sparkline(nine) -> str:
    """nine_filter dict({key:grade}) → '✓재무 △정량 ⭐연금 ...' 한 줄."""
    if not nine or not isinstance(nine, dict):
        return ""
    parts = []
    for k in NINE_FILTER_ORDER:
        v = nine.get(k)
        if v is None:
            continue
        key = str(v).upper() if isinstance(v, str) and v.isascii() else str(v)
        icon = GRADE_ICON.get(key, "·")
        parts.append(f"{icon}{FILTER_LABELS.get(k, k)}")
    return " ".join(parts)


def positives_summary(pos, neg, max_items: int = 3):
    """positive/negative_signals 배열 → 한국어 라벨 + 점수 리스트."""
    pos_lines = []
    for p in (pos or [])[:max_items]:
        if not isinstance(p, dict):
            continue
        t = p.get("type", "")
        s = p.get("score", 0)
        label = POSITIVE_LABELS.get(t, t)
        try:
            sign = "+" if s >= 0 else ""
            pos_lines.append(f"{label}({sign}{int(s)})")
        except (TypeError, ValueError):
            pos_lines.append(label)
    neg_lines = []
    for n in (neg or [])[:max_items]:
        if not isinstance(n, dict):
            continue
        t = n.get("type", "")
        s = n.get("score", 0)
        label = NEGATIVE_LABELS.get(t, t)
        try:
            neg_lines.append(f"{label}({int(s)})")
        except (TypeError, ValueError):
            neg_lines.append(label)
    return pos_lines, neg_lines


def reason_short_humanize(reason_short: str) -> str:
    """weekly_picks._summarize_reason 의 'NPS_NEW, STRONG_FLOW · 필터 7/9 통과' →
    '연금 신규편입, 외인+기관 매수 · 필터 7/9 통과' 로 한국어화."""
    if not reason_short:
        return ""
    out = reason_short
    for k, v in POSITIVE_LABELS.items():
        out = out.replace(k, v)
    for k, v in NEGATIVE_LABELS.items():
        out = out.replace(k, v)
    return out


# ---------------------------- 메시지 빌더 ----------------------------

def daily_message() -> str:
    today = kst_today()
    macro = load_envelope(latest("macro_status_*.json"))
    hot = load_envelope(latest("hot_sectors_*.json"))
    buys = load_envelope(latest("buy_signals_*.json"))
    blacklist = load_envelope(OUT_DIR / "blacklist_active.json")

    # market_as_of 가 envelope 에 박혀 있으면 헤더에 보조 표시 (휴장일 직전 영업일 기준)
    market_as_of = None
    for env in (macro, hot, buys):
        if env and isinstance(env, dict) and env.get("market_as_of"):
            market_as_of = env["market_as_of"]
            break
    if market_as_of and market_as_of != today:
        lines = [f"[원우 아빠 매크로 — {today} (기준 {market_as_of})]"]
    else:
        lines = [f"[원우 아빠 매크로 — {today}]"]

    if macro:
        emoji = emoji_for(macro.get("overall"))
        summary = macro.get("summary") or macro.get("comment") or macro.get("headline") or "시장 점검"
        lines.append(f"{emoji} {summary}")
        ind = macro.get("indicators") or {}
        parts = []
        try:
            if ind.get("kospi_change") is not None:
                parts.append(f"KOSPI {fmt_signed(float(ind['kospi_change']))}%")
            # 원 단위 → 억 단위 변환 (1e8 으로 나눔)
            fn = ind.get("foreign_kospi_net")
            if fn is not None:
                parts.append(f"외인 {fmt_signed(float(fn) / 1e8, 0)}억")
            inst = ind.get("institution_kospi_net")
            if inst is not None:
                parts.append(f"기관 {fmt_signed(float(inst) / 1e8, 0)}억")
            if ind.get("usd_krw") is not None:
                parts.append(f"USDKRW {int(float(ind['usd_krw']))}")
        except (TypeError, ValueError):
            pass
        if parts:
            lines.append("📊 " + " / ".join(parts))
        # 시장 거래대금 (조 단위)
        tv = ind.get("total_kospi_value")
        if tv:
            try:
                tv_jo = float(tv) / 1e12
                if tv_jo >= 0.1:
                    lines.append(f"💰 KOSPI 거래대금: {tv_jo:.1f}조원")
            except (TypeError, ValueError):
                pass
        if macro.get("__hmac_invalid"):
            lines.append("⚠️ HMAC 검증 실패")
    else:
        lines.append("🟡 매크로 데이터 없음")

    if hot:
        h = [s.get("name") or s.get("sector") for s in (hot.get("hot_sectors") or [])]
        h = [x for x in h if x][:2]
        if h:
            lines.append("🔥 핫섹터: " + ", ".join(h))

    # 봇 시그널 (자동매매 트리거용 압축 라인) — STRONG_BUY/BUY 코드만 한 줄
    if buys:
        signals = buys.get("signals") or []
        bot_sigs = [s for s in signals if s.get("signal") in ("STRONG_BUY", "BUY") and not s.get("blocked")]
        if bot_sigs:
            lines.append("")
            lines.append("🤖 봇 시그널:")
            line_parts = []
            for s in bot_sigs[:5]:
                line_parts.append(f"{s.get('code','')} {s.get('signal','')}")
            lines.append("  " + " / ".join(line_parts))

    lines.append("")
    lines.append("💡 매수 추천 사유:")
    if buys:
        signals = buys.get("signals") or []
        strong = [s for s in signals if s.get("signal") == "STRONG_BUY" and not s.get("blocked")]
        if not strong:
            lines.append("STRONG_BUY 없음 (관망)")
        else:
            for i, s in enumerate(strong[:2], 1):
                name = s.get("name", "")
                code = s.get("code", "")
                score = s.get("score", "?")
                lines.append(f"{i}. {name} ({code}) {score}점")
                pos, neg = positives_summary(s.get("positive_signals"), s.get("negative_signals"))
                if pos:
                    lines.append("   👍 " + ", ".join(pos))
                if neg:
                    lines.append("   👎 " + ", ".join(neg))
    else:
        lines.append("데이터 없음")

    # 텔레그램 근거 링크 — STRONG_BUY 종목 중 source_url 박힌 positive_signal 모음
    # buy_signal_generator._collect_positive 가 ANALYST_TARGET_UP 에 source_url 채움.
    links = []
    if buys:
        for s in (buys.get("signals") or []):
            if s.get("signal") == "STRONG_BUY" and not s.get("blocked"):
                for p in (s.get("positive_signals") or []):
                    if isinstance(p, dict) and p.get("source_url"):
                        links.append((s.get("code", ""), p.get("source_url")))
                        break  # 종목당 한 개만
    if links:
        lines.append("")
        lines.append("🔍 리포트 근거:")
        for code, url in links[:3]:
            lines.append(f"- {code} → {url}")

    if blacklist:
        items = blacklist.get("blacklist") or []
        if items:
            lines.append("")
            lines.append("🚫 차단:")
            for b in items[:2]:
                reasons = b.get("block_reasons") or [{}]
                first = reasons[0]
                desc = first.get("description") if isinstance(first, dict) else str(first)
                lines.append(f"- {b.get('name','')} ({b.get('code','')}): {desc or '?'}")

    lines.append("")
    lines.append("— Claude")
    return "\n".join(lines)


def weekly_message() -> str:
    """weekly_picks_*.json 은 envelope 없는 plain JSON.
    schema (scripts/weekly_picks.py main()): {date, picks_count, picks:[
        {code, name, signal, score, nine_filter, moving_averages,
         reason_short, entry_date, entry_close}
    ]}
    positive_signals/negative_signals 는 picks 에 들어가지 않음 (reason_short 로 압축됨).
    """
    today = kst_today()
    picks_data = load_envelope(latest("weekly_picks_*.json"))
    perf = load_envelope(latest("weekly_performance_*.json"))
    hot = load_envelope(latest("hot_sectors_*.json"))

    market_as_of = None
    for env in (picks_data, hot):
        if env and isinstance(env, dict) and env.get("market_as_of"):
            market_as_of = env["market_as_of"]
            break
    if market_as_of and market_as_of != today:
        lines = [f"[원우 아빠 주간 추천 — {today} (기준 {market_as_of})]"]
    else:
        lines = [f"[원우 아빠 주간 추천 — {today}]"]

    items = []
    if picks_data:
        items = picks_data.get("picks") or picks_data.get("signals") or picks_data.get("recommendations") or []

    if not items:
        lines.append("")
        lines.append("(이번 주 추천 데이터 없음)")
    else:
        n_show = min(3, len(items))
        lines.append("")
        lines.append(f"이번 주 TOP {n_show}")
        for i, p in enumerate(items[:n_show], 1):
            name = p.get("name", "")
            code = p.get("code", "")
            score = p.get("score", "?")
            ma = p.get("moving_averages") or {}
            ma10 = ma.get("ma10") or p.get("ma10")
            ma15 = ma.get("ma15") or p.get("ma15")

            lines.append("")
            lines.append(f"{i}. {name} ({code}) {score}점")

            spark = filter_sparkline(p.get("nine_filter"))
            if spark:
                lines.append(f"   {spark}")

            # weekly 는 reason_short (압축 한국어 + type 코드 혼합) 사용 → type 코드 풀어서 노출
            rs = reason_short_humanize(p.get("reason_short", ""))
            if rs:
                lines.append(f"   👍 {rs}")
            else:
                pos, neg = positives_summary(p.get("positive_signals"), p.get("negative_signals"))
                if pos:
                    lines.append("   👍 " + ", ".join(pos))
                if neg:
                    lines.append("   👎 " + ", ".join(neg))

            try:
                if ma10 and ma15:
                    lines.append(f"   진입: ma10 {int(float(ma10)):,} / ma15 {int(float(ma15)):,}")
            except (TypeError, ValueError):
                pass

        # 텔레그램 근거 링크 — TOP 3 picks 대상. picks 항목에 positive_signals 가 박혀
        # 있으면 source_url 추출, 없고 source_url 직접 박혀 있으면 그것 사용.
        wlinks = []
        for p in items[:3]:
            if not isinstance(p, dict):
                continue
            url = ""
            for ps in (p.get("positive_signals") or []):
                if isinstance(ps, dict) and ps.get("source_url"):
                    url = ps["source_url"]
                    break
            if not url and p.get("source_url"):
                url = p["source_url"]
            if url:
                wlinks.append((p.get("code", ""), url))
        if wlinks:
            lines.append("")
            lines.append("🔍 리포트 근거:")
            for code, url in wlinks[:3]:
                lines.append(f"- {code} → {url}")

    if perf:
        avg = perf.get("avg_return_pct") or perf.get("avg_return")
        winrate = perf.get("win_rate_pct") or perf.get("win_rate")
        n = perf.get("count") or perf.get("n")
        try:
            if avg is not None:
                lines.append("")
                lines.append(f"4주 성과: 평균 {fmt_signed(float(avg))}% / 승률 {int(float(winrate or 0))}% (n={n if n is not None else '?'})")
        except (TypeError, ValueError):
            pass

    if hot:
        h = [s.get("name") or s.get("sector") for s in (hot.get("hot_sectors") or [])]
        h = [x for x in h if x][:2]
        if h:
            lines.append("")
            lines.append("🔥 핫섹터: " + ", ".join(h))

    lines.append("")
    lines.append("— Claude")
    return "\n".join(lines)


def monthly_message() -> str:
    """src/backtest/report.py write() schema:
    {config:{end_date, lookback_years, initial_cash, universe_top_n, max_holdings, ...},
     metrics:{cagr_pct, sharpe, mdd_pct, alpha_vs_benchmark_pct, total_return_pct,
              win_rate_pct, avg_trade_pct, trade_count},
     benchmark_total_return_pct, trades:[{code,name,return_pct,...}], equity_curve, monthly_picks}
    """
    bt = load_envelope(latest("backtest_*.json"))
    yyyymm = kst_yyyymm()

    lines = [f"[원우 아빠 월간 백테스트 — {yyyymm}]"]

    if not bt:
        lines.append("")
        lines.append("(백테스트 데이터 없음)")
        run_id = os.environ.get("GITHUB_RUN_ID", "?")
        lines.append(f"리포트: artifact backtest-{run_id}")
        lines.append("")
        lines.append("— Claude")
        return "\n".join(lines)

    cfg = bt.get("config") or {}
    m = bt.get("metrics") or {}
    bench_ret = bt.get("benchmark_total_return_pct")

    header_parts = []
    if cfg.get("lookback_years") is not None:
        header_parts.append(f"{cfg['lookback_years']}년")
    if cfg.get("universe_top_n") is not None:
        header_parts.append(f"Top{cfg['universe_top_n']}")
    if cfg.get("max_holdings") is not None:
        header_parts.append(f"보유{cfg['max_holdings']}")
    if header_parts:
        lines.append("")
        lines.append("config: " + " / ".join(header_parts))

    def push_metric(label, key, fmt="{:.1f}", suffix="%"):
        v = m.get(key)
        if v is None:
            return
        try:
            lines.append(f"  {label}: {fmt.format(float(v))}{suffix}")
        except (TypeError, ValueError):
            pass

    lines.append("")
    lines.append("📊 5년 성과")
    push_metric("총수익(누적)", "total_return_pct", "{:+.1f}")
    push_metric("CAGR(연복리)", "cagr_pct", "{:+.1f}")
    # Sharpe: 위험대비 수익. 1↑ 양호, 2↑ 우수
    v = m.get("sharpe")
    if v is not None:
        try:
            lines.append(f"  Sharpe(위험대비): {float(v):.2f}  (1↑ 양호)")
        except (TypeError, ValueError):
            pass
    # MDD: 최대 낙폭. 절댓값 클수록 손실 위험 큼
    v = m.get("mdd_pct")
    if v is not None:
        try:
            lines.append(f"  MDD(최대낙폭): {float(v):+.1f}%  (절댓값↑ 위험↑)")
        except (TypeError, ValueError):
            pass

    alpha = m.get("alpha_vs_benchmark_pct")
    if alpha is not None:
        try:
            lines.append(f"  알파(KOSPI 대비): {fmt_signed(float(alpha), 1)}%pt")
        except (TypeError, ValueError):
            pass
    if bench_ret is not None:
        try:
            lines.append(f"  벤치마크(KOSPI 5년 단순보유): {fmt_signed(float(bench_ret), 1)}%")
        except (TypeError, ValueError):
            pass

    win = m.get("win_rate_pct")
    avg_trade = m.get("avg_trade_pct")
    n_trade = m.get("trade_count")
    if any(v is not None for v in (win, avg_trade, n_trade)):
        lines.append("")
        lines.append("📈 거래")
        if win is not None:
            try:
                lines.append(f"  승률: {float(win):.0f}% (n={n_trade if n_trade is not None else '?'})")
            except (TypeError, ValueError):
                pass
        if avg_trade is not None:
            try:
                lines.append(f"  평균수익: {fmt_signed(float(avg_trade))}%")
            except (TypeError, ValueError):
                pass

    trades = bt.get("trades") or []
    if trades:
        try:
            top = sorted(
                [t for t in trades if isinstance(t.get("return_pct"), (int, float))],
                key=lambda t: t["return_pct"],
                reverse=True,
            )[:3]
            if top:
                lines.append("")
                lines.append("🏆 TOP 3 수익")
                for t in top:
                    code = t.get("code", "")
                    name = t.get("name", "")
                    ret = t["return_pct"]
                    lines.append(f"  + {code} {name} {fmt_signed(float(ret))}%")
        except (TypeError, ValueError, KeyError):
            pass

    mp = bt.get("monthly_picks") or []
    if mp:
        last = mp[-1]
        ps = last.get("picks") or []
        if ps:
            names = []
            for x in ps[:5]:
                if isinstance(x, dict):
                    names.append(f"{x.get('code','')} {x.get('name','')}".strip())
                else:
                    names.append(str(x))
            if names:
                lines.append("")
                lines.append("🎯 이번 달 추천")
                lines.append("  " + " / ".join(names[:5]))

    run_id = os.environ.get("GITHUB_RUN_ID", "?")
    lines.append("")
    lines.append(f"전체 리포트: artifact backtest-{run_id}")
    lines.append("")
    lines.append("— Claude")
    return "\n".join(lines)


# ---------------------------- Kakao API ----------------------------

KAUTH = "https://kauth.kakao.com"
KAPI = "https://kapi.kakao.com"


def refresh_access_token(rest_api_key: str, refresh_token: str, client_secret: str = "") -> dict:
    payload = {
        "grant_type": "refresh_token",
        "client_id": rest_api_key,
        "refresh_token": refresh_token,
    }
    if client_secret:
        payload["client_secret"] = client_secret
    body = urllib.parse.urlencode(payload).encode("utf-8")
    req = Request(
        f"{KAUTH}/oauth/token",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def send_to_self(access_token: str, text: str) -> dict:
    safe_text = text if len(text) <= 800 else text[:797] + "..."
    template = {
        "object_type": "text",
        "text": safe_text,
        "link": {
            "web_url": "https://github.com/newwonwoo/stock/actions",
            "mobile_web_url": "https://github.com/newwonwoo/stock/actions",
        },
        "button_title": "리포트",
    }
    body = urllib.parse.urlencode({"template_object": json.dumps(template, ensure_ascii=False)}).encode("utf-8")
    req = Request(
        f"{KAPI}/v2/api/talk/memo/default/send",
        data=body,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    with urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ---------------------------- main ----------------------------

def test_message() -> str:
    """E2E 발송 테스트용. 데이터 fetch 없이 하드코딩 메시지."""
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
    return (
        f"[원우 아빠 시스템 테스트 — {now}]\n"
        "🛠️ 카카오 발송 파이프라인 작동 확인.\n"
        "이 메시지가 도착하면:\n"
        "  - GitHub Actions 워크플로우 OK\n"
        "  - KAKAO_REST_API_KEY / REFRESH_TOKEN OK\n"
        "  - talk_message API OK\n"
        "데이터 수집 (DART/KRX) 은 별도 검증.\n"
        "\n— Claude (research test)"
    )


BUILDERS = {
    "daily": daily_message,
    "weekly": weekly_message,
    "monthly": monthly_message,
    "test": test_message,
}


def write_step_summary(text: str) -> None:
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary:
        return
    try:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(text)
    except OSError:
        pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=list(BUILDERS.keys()))
    args = ap.parse_args()

    text = BUILDERS[args.kind]()

    print("---- message preview ----")
    print(text)
    print("---- end preview ----")
    write_step_summary(f"### Kakao msg preview ({args.kind})\n\n```\n{text}\n```\n")

    if os.environ.get("DRY_RUN") == "1":
        print("DRY_RUN=1 -> skip send")
        return 0

    rest = os.environ.get("KAKAO_REST_API_KEY")
    rt = os.environ.get("KAKAO_REFRESH_TOKEN")
    cs = os.environ.get("KAKAO_CLIENT_SECRET", "")
    if not rest or not rt:
        print("[ERR] KAKAO_REST_API_KEY / KAKAO_REFRESH_TOKEN missing", file=sys.stderr)
        return 2

    try:
        tok = refresh_access_token(rest, rt, cs)
    except (HTTPError, URLError) as e:
        body = e.read().decode("utf-8", "ignore") if isinstance(e, HTTPError) else str(e)
        print(f"[ERR] token refresh fail: {body}", file=sys.stderr)
        write_step_summary(f"### Kakao token refresh fail\n```\n{body}\n```\n")
        return 3

    access = tok.get("access_token")
    new_rt = tok.get("refresh_token")
    if not access:
        print(f"[ERR] no access_token: {tok}", file=sys.stderr)
        return 4

    try:
        result = send_to_self(access, text)
    except (HTTPError, URLError) as e:
        body = e.read().decode("utf-8", "ignore") if isinstance(e, HTTPError) else str(e)
        print(f"[ERR] memo/default/send fail: {body}", file=sys.stderr)
        write_step_summary(f"### Kakao send fail\n```\n{body}\n```\n")
        return 5

    print(f"[OK] send: {result}")

    if new_rt and new_rt != rt:
        warn = (
            "## Kakao refresh_token rotated\n\n"
            "New refresh_token returned. Update GitHub Secret KAKAO_REFRESH_TOKEN.\n\n"
            f"first 12: {new_rt[:12]}...  len: {len(new_rt)}\n"
        )
        print(warn, file=sys.stderr)
        write_step_summary(warn)

    return 0


if __name__ == "__main__":
    sys.exit(main())
