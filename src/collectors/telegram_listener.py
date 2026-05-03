"""
텔레그램 listener (Telethon, 비대화식).

Session 문자열 인증. 채널별 last_processed_id 이후 메시지만 fetch.
파서 호출 후 결과를 dict 리스트로 반환 (저장은 호출자 책임).

채널 목록: data/telegram_channels.json
  {"channels": [{"username": "butler_works", "type": "broker_summary"}, ...]}

last_processed_id 박제: .cache/telegram_state.json
  {"butler_works": 12345, ...}
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from src import config
from src.utils.logger import get_logger
from src.utils.parser import parse as parse_msg

log = get_logger("telegram")

CHANNELS_FILE = config.DATA_DIR / "telegram_channels.json"
STATE_FILE = config.CACHE_DIR / "telegram_state.json"


@dataclass
class CollectedMessage:
    channel: str
    channel_type: str
    message_id: int
    message_uid: str
    text: str
    parsed: dict[str, Any]
    date_iso: str


def _load_channels() -> list[dict[str, str]]:
    if not CHANNELS_FILE.exists():
        log.info(f"channels file 없음 ({CHANNELS_FILE}), 빈 리스트 반환")
        return []
    j = json.loads(CHANNELS_FILE.read_text(encoding="utf-8"))
    return list(j.get("channels", []))


def _load_state() -> dict[str, int]:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


def _save_state(state: dict[str, int]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2))


async def _fetch_channel(client: Any, ch: dict[str, str], min_id: int, limit: int) -> list[CollectedMessage]:
    out: list[CollectedMessage] = []
    username = ch["username"]
    ch_type = ch.get("type", "fallback")
    max_id = min_id
    async for msg in client.iter_messages(username, limit=limit, min_id=min_id):
        text = msg.message or ""
        if not text:
            continue
        parsed = parse_msg(text, ch_type)
        out.append(
            CollectedMessage(
                channel=username,
                channel_type=ch_type,
                message_id=msg.id,
                message_uid=f"{username}_{msg.id}",
                text=text,
                parsed=asdict(parsed),
                date_iso=msg.date.isoformat() if msg.date else "",
            )
        )
        if msg.id > max_id:
            max_id = msg.id
    return out


async def collect_async(limit_per_channel: int = 200) -> list[CollectedMessage]:
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    api_id = config.TELEGRAM_API_ID
    api_hash = config.TELEGRAM_API_HASH
    session_str = config.TELEGRAM_SESSION
    if not (api_id and api_hash and session_str):
        raise RuntimeError("TELEGRAM_API_ID / API_HASH / SESSION 미설정")

    channels = _load_channels()
    if not channels:
        log.info("등록된 채널 없음")
        return []

    state = _load_state()
    all_msgs: list[CollectedMessage] = []
    async with TelegramClient(StringSession(session_str), int(api_id), api_hash) as client:
        for ch in channels:
            username = ch["username"]
            min_id = int(state.get(username, 0))
            try:
                msgs = await _fetch_channel(client, ch, min_id, limit_per_channel)
            except Exception as e:
                log.info(f"channel {username} fetch 실패: {e}")
                continue
            all_msgs.extend(msgs)
            if msgs:
                state[username] = max(m.message_id for m in msgs)
            log.info(f"channel {username}: +{len(msgs)} (cursor → {state.get(username)})")

    _save_state(state)
    return all_msgs


def collect(limit_per_channel: int = 200) -> list[CollectedMessage]:
    return asyncio.run(collect_async(limit_per_channel))
