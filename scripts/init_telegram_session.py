"""
텔레그램 Session 문자열 1회 발급 스크립트.

본인 PC 에서 1회 실행:
  - TELEGRAM_API_ID / TELEGRAM_API_HASH 환경변수로 설정
  - 휴대폰 번호 입력 → 텔레그램으로 온 인증코드 입력
  - 출력된 StringSession 을 GitHub Secrets 에 TELEGRAM_SESSION 으로 등록
"""

from __future__ import annotations

import os
import sys


def main() -> int:
    api_id = os.environ.get("TELEGRAM_API_ID", "")
    api_hash = os.environ.get("TELEGRAM_API_HASH", "")
    if not api_id or not api_hash:
        print("ERROR: TELEGRAM_API_ID / TELEGRAM_API_HASH 환경변수 필요")
        return 1

    from telethon.sessions import StringSession
    from telethon.sync import TelegramClient

    with TelegramClient(StringSession(), int(api_id), api_hash) as client:
        client.start()
        s = client.session.save()
        print("=" * 60)
        print("아래 문자열을 GitHub Secrets 의 TELEGRAM_SESSION 에 등록:")
        print("=" * 60)
        print(s)
        print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
