"""Terminal chat with the same brain and database, for testing without Telegram.

Run: python cli.py      Commands: /memory  /forget  /quit
"""

import asyncio
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

import anthropic  # noqa: E402

from brain import Brain, Refused  # noqa: E402
from store import Store  # noqa: E402

CHAT_ID = 0


async def main():
    brain = Brain(Store(Path(__file__).parent / "companion.db"))
    while True:
        try:
            text = (await asyncio.to_thread(input, "you> ")).strip()
        except (EOFError, KeyboardInterrupt):
            return
        if not text:
            continue
        if text == "/quit":
            return
        if text == "/memory":
            print(brain.store.notes(CHAT_ID) or "(no memory notes yet)")
            continue
        if text == "/forget":
            brain.store.forget(CHAT_ID)
            print("(wiped)")
            continue
        try:
            print(f"\n{await brain.reply(CHAT_ID, text)}\n")
        except Refused as e:
            print(f"(model declined: {e})")
        except anthropic.APIError as e:
            print(f"(API error: {e})")


if __name__ == "__main__":
    asyncio.run(main())
