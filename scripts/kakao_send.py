#!/usr/bin/env python3
"""
Kakao "나에게 보내기" sender — newwonwoo/stock 리서치 봇용.

사용:
    python scripts/kakao_send.py {daily|weekly|monthly}

GitHub Actions 워크플로우의 마지막 step에서 호출되어
out/ 의 JSON 산출물을 prompts/*.md spec대로 한국어 메시지로 만들고,
Kakao memo/default/send API ("나와의 채팅") 로 발송한다.

PC on/off 무관 — 발송이 GitHub Actions 러너에서 일어나기 때문.

필수 env (= GitHub Secrets):
    KAKAO_REST_API_KEY    — Kakao Developers 앱의 REST API 키 (=client_id)
    KAKAO_REFRESH_TOKEN   — talk_message scope로 발급된 refresh_token
    KAKAO_CLIENT_SECRET   — 앱 Client Secret 활성 ON 시 필수 (없으면 빈 값)
    RESEARCH_HMAC_KEY     — envelope HMAC 검증 키 (있으면 검증, 없으면 경고만)

선택 env:
    OUT_DIR               — 산출물 디렉터리 (기본 ./out)
    DRY_RUN=1             — 실제 발송 안 하고 메시지만 출력
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


def load_envelope(path: Path | None) -> dict | None:
    """JSON envelope 로드 + HMAC 검증. data 부분만 반환.

    envelope 가 아닌 plain JSON 이면 그대로 반환.
    envelope 인데 RESEARCH_HMAC_KEY 가 없으면 검증 스킵 + 경고 로그.
    """
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
        canonical = json.dumps(
            data, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        expected = hmac.new(key.encode("utf-8"), canonical, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, sig):
            print(
                f"[WARN] HMAC mismatch on {path.name} — 메시지 발송은 진행하되 본문에 표식 추가",
                file=sys.stderr,
            )
            data = dict(data) if isinstance(data, dict) else {"_raw": data}
            if isinstance(data, dict):
                data["__hmac_invalid"] = True
    elif sig and not key:
        print(
            f"[WARN] RESEARCH_HMAC_KEY 없음 — {path.name} HMAC 검증 스킵",
            file=sys.stderr,
        )

    return data


# ---------------------------- 메시지 빌더 ----------------------------

OVERALL_EMOJI = {
    "BULL": "🟢", "GOOD": "🟢", "GREEN": "🟢",
    "NEUTRAL": "🟡", "MIXED": "🟡", "YELLOW": "🟡",
    "BEAR": "🔴", "BAD": "🔴", "RED": "🔴",
    "PANIC": "🚨", "CRASH": "🚨", "ALERT": "🚨",
}


def emoji_for(overall) -> str:
    if not overall:
        return "🟡"
    s = str(overall).strip()
    if s and ord(s[0]) > 127:
        return s[:2] if len(s) > 1 and ord(s[1]) > 127 else s[:1]
    return OVERALL_EMOJI.get(s.upper(), "🟡")


def daily_message() -> str:
    today = kst_today()
    macro = load_envelope(latest("macro_status_*.json"))
    hot = load_envelope(latest("hot_sectors_*.json"))
    buys = load_envelope(latest("buy_signals_*.json"))
    blacklist = load_envelope(OUT_DIR / "blacklist_active.json")

    lines = [f"[원우 아빠 매크로 — {today}]"]

    if macro:
        emoji = emoji_for(macro.get("overall"))
        summary = (
            macro.get("summary")
            or macro.get("comment")
            or macro.get("headline")
            or "시장 점검"
        )
        lines.append(f"{emoji} {summary}")
        ind = macro.get("indicators") or {}
        parts = []
        kospi = ind.get("kospi_change")
        foreign = ind.get("foreign_kospi_net")
        usdkrw = ind.get("usd_krw")
        try:
            if kospi is not None:
                parts.append(f"KOSPI {fmt_signed(float(kospi))}%")
            if foreign is not None:
                parts.append(f"외인 {fmt_signed(float(foreign), 0)}억")
            if usdkrw is not None:
                parts.append(f"USDKRW {int(float(usdkrw))}")
        except (TypeError, ValueError):
            pass
        if parts:
            lines.append("📊 " + " / ".join(parts))
        if macro.get("__hmac_invalid"):
            lines.append("⚠️ HMAC 검증 실패 — 데이터 신뢰성 주의")
    else:
        lines.append("🟡 매크로 데이터 없음")

    if hot:
        h = [s.get("name") or s.get("sector") for s in (hot.get("hot_sectors") or [])]
        c = [s.get("name") or s.get("sector") for s in (hot.get("cold_sectors") or [])]
        h = [x for x in h if x][:2]
        c = [x for x in c if x][:1]
        if h:
            lines.append("🔥 핫섹터: " + ", ".join(h))
        if c:
            lines.append("❄️ 콜드: " + ", ".join(c))

    lines.append("")
    lines.append("매수 신호:")
    if buys:
        signals = buys.get("signals") or []
        strong = [s for s in signals if s.get("signal") == "STRONG_BUY" and not s.get("blocked")]
        if strong:
            for s in strong[:3]:
                code = s.get("code", "")
                name = s.get("name", "")
                score = s.get("score", "?")
                nf = s.get("nine_filter", "?")
                lines.append(f"- {name} ({code}) 점수 {score} / 필터 {nf}/9")
        else:
            lines.append("없음 (관망)")
    else:
        lines.append("없음 (관망)")

    if blacklist:
        items = blacklist.get("blacklist") or []
        if items:
            lines.append("")
            lines.append("차단:")
            for b in items[:2]:
                reasons = b.get("block_reasons") or ["?"]
                lines.append(f"- {b.get('name','')} ({b.get('code','')}) — {reasons[0]}")

    lines.append("")
    lines.append("— Claude")
    return "\n".join(lines)


def weekly_message() -> str:
    today = kst_today()
    picks = load_envelope(latest("weekly_picks_*.json"))
    perf = load_envelope(latest("weekly_performance_*.json"))
    hot = load_envelope(latest("hot_sectors_*.json"))

    lines = [f"[원우 아빠 주간 추천 — {today}]", "", "이번 주 5종목"]

    items = []
    if picks:
        items = picks.get("picks") or picks.get("signals") or picks.get("recommendations") or []

    if not items:
        lines.append("(데이터 없음)")
    else:
        for i, p in enumerate(items[:5], 1):
            name = p.get("name", "")
            code = p.get("code", "")
            score = p.get("score", "?")
            nf = p.get("nine_filter", "?")
            reason = p.get("reason") or ", ".join(p.get("positive_signals") or []) or "-"
            ma = p.get("moving_averages") or {}
            ma10 = ma.get("ma10") or p.get("ma10") or 0
            ma15 = ma.get("ma15") or p.get("ma15") or 0
            lines.append("")
            lines.append(f"{i}. {name} ({code})  점수 {score}  필터 {nf}/9")
            lines.append(f"   사유: {reason}")
            try:
                lines.append(
                    f"   진입 가이드: 1차 시초가 / 2차 ma10 {int(float(ma10)):,} / 3차 ma15 {int(float(ma15)):,}"
                )
            except (TypeError, ValueError):
                lines.append("   진입 가이드: 1차 시초가 / 2차 ma10 / 3차 ma15")

    if perf:
        avg = perf.get("avg_return_pct") or perf.get("avg_return")
        winrate = perf.get("win_rate_pct") or perf.get("win_rate")
        n = perf.get("count") or perf.get("n")
        try:
            if avg is not None:
                lines.append("")
                lines.append("지난 4주 추천 성과:")
                lines.append(
                    f"  평균 수익률 {fmt_signed(float(avg))}% / 승률 {int(float(winrate or 0))}% (n={n if n is not None else '?'})"
                )
        except (TypeError, ValueError):
            pass

    if hot:
        h = [s.get("name") or s.get("sector") for s in (hot.get("hot_sectors") or [])]
        h = [x for x in h if x][:2]
        if h:
            lines.append("")
            lines.append("🔥 이번 주 핫섹터: " + ", ".join(h))

    lines.append("")
    lines.append("— Claude")
    return "\n".join(lines)


def monthly_message() -> str:
    bt = load_envelope(latest("backtest_*.json"))
    yyyymm = kst_yyyymm()

    lines = [f"[원우 아빠 월간 백테스트 — {yyyymm}]", "", "지난 5년 성과 (KRX 모멘텀 3필터 MVP)"]
    if bt:
        cagr = bt.get("cagr") or bt.get("CAGR")
        sharpe = bt.get("sharpe") or bt.get("Sharpe")
        mdd = bt.get("mdd") or bt.get("MDD")
        alpha = bt.get("alpha_pp") or bt.get("alpha")
        try:
            if cagr is not None:
                lines.append(f"  CAGR  : {float(cagr):.1f}%")
            if sharpe is not None:
                lines.append(f"  Sharpe: {float(sharpe):.2f}")
            if mdd is not None:
                lines.append(f"  MDD   : {float(mdd):.1f}%")
            if alpha is not None:
                lines.append(f"  알파  : KOSPI 대비 {fmt_signed(float(alpha), 1)}%pt")
        except (TypeError, ValueError):
            pass

        wl = bt.get("whitelist") or {}
        n_wl = wl.get("count")
        cands_in = wl.get("add_candidates") or []
        cands_out = wl.get("remove_candidates") or []
        if n_wl is not None:
            lines.append("")
            lines.append(f"화이트리스트: 현재 {n_wl}종목")
        if cands_in or cands_out:
            lines.append("  변경 검토 후보 (백테스트 상위·하위):")
            for c in cands_in[:2]:
                contrib = c.get("contrib_pp")
                try:
                    contrib_s = fmt_signed(float(contrib or 0), 0)
                except (TypeError, ValueError):
                    contrib_s = "?"
                lines.append(f"    - {c.get('code','')} {c.get('name','')}  (CAGR 기여 {contrib_s}%pt)")
            for c in cands_out[:2]:
                contrib = c.get("contrib_pp")
                try:
                    contrib_s = fmt_signed(float(contrib or 0), 0)
                except (TypeError, ValueError):
                    contrib_s = "?"
                lines.append(
                    f"    - {c.get('code','')} {c.get('name','')}  (CAGR 기여 {contrib_s}%pt) → 제외 검토"
                )
    else:
        lines.append("  데이터 없음 (백테스트 실패 추정)")

    run_id = os.environ.get("GITHUB_RUN_ID", "?")
    lines.append("")
    lines.append(f"전체 리포트: GitHub Actions artifact `backtest-{run_id}`")
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
    # Client Secret 활성화된 앱은 반드시 함께 보내야 KOE010 회피
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
    body = urllib.parse.urlencode(
        {"template_object": json.dumps(template, ensure_ascii=False)}
    ).encode("utf-8")
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

BUILDERS = {
    "daily": daily_message,
    "weekly": weekly_message,
    "monthly": monthly_message,
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
    write_step_summary(f"### Kakao 메시지 미리보기 ({args.kind})\n\n```\n{text}\n```\n")

    if os.environ.get("DRY_RUN") == "1":
        print("DRY_RUN=1 → 발송 생략")
        return 0

    rest = os.environ.get("KAKAO_REST_API_KEY")
    rt = os.environ.get("KAKAO_REFRESH_TOKEN")
    cs = os.environ.get("KAKAO_CLIENT_SECRET", "")
    if not rest or not rt:
        print(
            "[ERR] KAKAO_REST_API_KEY / KAKAO_REFRESH_TOKEN 누락 — Secrets 설정 필요",
            file=sys.stderr,
        )
        return 2

    try:
        tok = refresh_access_token(rest, rt, cs)
    except (HTTPError, URLError) as e:
        body = e.read().decode("utf-8", "ignore") if isinstance(e, HTTPError) else str(e)
        print(f"[ERR] token refresh 실패: {body}", file=sys.stderr)
        write_step_summary(f"### Kakao token refresh 실패\n```\n{body}\n```\n")
        return 3

    access = tok.get("access_token")
    new_rt = tok.get("refresh_token")
    if not access:
        print(f"[ERR] access_token 없음: {tok}", file=sys.stderr)
        return 4

    try:
        result = send_to_self(access, text)
    except (HTTPError, URLError) as e:
        body = e.read().decode("utf-8", "ignore") if isinstance(e, HTTPError) else str(e)
        print(f"[ERR] memo/default/send 실패: {body}", file=sys.stderr)
        write_step_summary(f"### Kakao 발송 실패\n```\n{body}\n```\n")
        return 5

    print(f"[OK] send: {result}")

    if new_rt and new_rt != rt:
        warn = (
            "## ⚠️ Kakao refresh_token 이 갱신되었습니다\n\n"
            "이번 실행에서 Kakao 가 새로운 `refresh_token` 을 반환했습니다. "
            "**GitHub Secret `KAKAO_REFRESH_TOKEN` 을 즉시 새 값으로 교체**해 주세요.\n\n"
            f"new_refresh_token 앞 12자: `{new_rt[:12]}...`\n"
            f"new_refresh_token 길이: {len(new_rt)}\n"
        )
        print(warn, file=sys.stderr)
        write_step_summary(warn)

    return 0


if __name__ == "__main__":
    sys.exit(main())
