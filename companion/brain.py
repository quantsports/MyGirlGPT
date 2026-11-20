"""The companion: builds each request from persona + memory + recent messages,
and folds old messages into long-term memory notes.

Request layout is append-only between folds (stable system prompt, timestamps
rendered from stored values), so prompt caching can reuse the prefix.
"""

import asyncio
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import anthropic

from store import Store

log = logging.getLogger("brain")

HERE = Path(__file__).parent
MODEL = os.getenv("MODEL", "claude-opus-5-5")
TZ = ZoneInfo(os.getenv("TZ_NAME", "Africa/Johannesburg"))
FOLD_AT = int(os.getenv("FOLD_AT", "40"))        # fold once this many messages are unfolded
FOLD_BATCH = int(os.getenv("FOLD_BATCH", "20"))  # how many of the oldest to fold each time

MEMORY_SYSTEM = """You maintain the long-term memory of a character in an ongoing private chat with her boyfriend. You are given her current memory notes and a stretch of older conversation that is about to drop out of view. Rewrite the notes so they include what matters from that stretch.

Write in the first person, as her, in plain prose under these headings: "About him", "About us", "What I've told him about my life", "Open threads". Keep specifics that will matter later: names, dates, plans, preferences, things he was worried or excited about, running jokes, promises either of you made, and every concrete fact she has stated about her own life so she stays consistent. Drop small talk. When new information contradicts an old note, keep the new version. Stay under 500 words. Output only the notes."""


class Refused(Exception):
    """The model declined to answer this turn."""


class Brain:
    def __init__(self, store: Store, client: anthropic.AsyncAnthropic | None = None):
        self.store = store
        self.client = client or anthropic.AsyncAnthropic()
        self.persona = (HERE / "persona.md").read_text(encoding="utf-8").strip()
        self.lock = asyncio.Lock()  # one turn at a time, so replies and nudges never interleave

    # -- public -------------------------------------------------------------

    async def reply(self, chat_id: int, text: str) -> str:
        """He sent a message. Returns her reply; stores both only on success."""
        return await self._turn(chat_id, text, kind="msg")

    async def nudge(self, chat_id: int, note: str) -> str:
        """The app prompts her to speak first (silence, first open)."""
        return await self._turn(chat_id, f"[app note: {note}]", kind="nudge")

    # -- internals ----------------------------------------------------------

    async def _turn(self, chat_id: int, content: str, kind: str) -> str:
        async with self.lock:
            now = int(time.time())
            messages = self._render(self.store.window(chat_id))
            messages.append({"role": "user", "content": self._stamp(content, now)})
            text = await self._complete(self._system(chat_id), messages)
            self.store.add(chat_id, "user", content, kind=kind, ts=now)
            self.store.add(chat_id, "assistant", text)
            await self._maybe_fold(chat_id)
            return text

    def _system(self, chat_id: int) -> str:
        notes = self.store.notes(chat_id)
        if not notes:
            return self.persona
        return f"{self.persona}\n\n## Memory notes\n\n{notes}"

    def _stamp(self, content: str, ts: int) -> str:
        return f"[{datetime.fromtimestamp(ts, TZ):%a %d %b %Y, %H:%M}] {content}"

    def _render(self, rows) -> list[dict]:
        return [
            {
                "role": r["role"],
                "content": self._stamp(r["content"], r["ts"]) if r["role"] == "user" else r["content"],
            }
            for r in rows
        ]

    async def _complete(self, system: str, messages: list[dict]) -> str:
        params = dict(
            model=MODEL,
            max_tokens=16000,
            system=system,
            messages=messages,
            output_config={"effort": "low"},      # chat turns; depth is not the point
            cache_control={"type": "ephemeral"},  # reuse the unchanged prefix between turns
        )
        if "haiku" not in MODEL:
            # If a safety classifier declines, retry on Anthropic's recommended fallback model.
            params.update(betas=["server-side-fallback-2026-07-01"], fallbacks="default")
        response = await self.client.beta.messages.create(**params)
        if response.stop_reason == "refusal":
            raise Refused(getattr(response.stop_details, "category", None))
        text = "".join(b.text for b in response.content if b.type == "text").strip()
        if not text:
            raise Refused("empty reply")
        u = response.usage
        log.info("tokens in=%s cached=%s out=%s", u.input_tokens, u.cache_read_input_tokens, u.output_tokens)
        return text

    async def _maybe_fold(self, chat_id: int) -> None:
        rows = self.store.window(chat_id)
        if len(rows) < FOLD_AT:
            return
        # Cut where the remaining window starts with one of his messages.
        cut = next((i for i in range(FOLD_BATCH, len(rows)) if rows[i]["role"] == "user"), None)
        if cut is None:
            return
        old = rows[:cut]
        transcript = "\n".join(
            f"{'Him' if r['role'] == 'user' else 'Me'} ({datetime.fromtimestamp(r['ts'], TZ):%d %b %H:%M}): {r['content']}"
            for r in old
        )
        prompt = (
            f"Current memory notes:\n\n{self.store.notes(chat_id) or '(none yet)'}\n\n"
            f"Older conversation to fold in:\n\n{transcript}"
        )
        try:
            notes = await self._complete(MEMORY_SYSTEM, [{"role": "user", "content": prompt}])
        except (Refused, anthropic.APIError) as e:
            log.warning("memory fold skipped, will retry next turn: %s", e)
            return
        self.store.set_notes(chat_id, notes)
        self.store.mark_folded(chat_id, old[-1]["id"])
        log.info("folded %d messages into memory", len(old))
