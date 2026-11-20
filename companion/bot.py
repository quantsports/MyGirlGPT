"""Discord front end: she lives in your direct messages. Run: python bot.py"""

import asyncio
import logging
import os
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

import anthropic  # noqa: E402
import discord  # noqa: E402
from discord.ext import tasks  # noqa: E402

from brain import TZ, Brain, Refused  # noqa: E402
from store import Store  # noqa: E402

log = logging.getLogger("bot")

OWNER_ID = int(os.getenv("OWNER_ID") or 0)
SILENCE_HOURS = float(os.getenv("SILENCE_HOURS") or 20)  # she messages first after this long; 0 disables
AWAKE = (8, 21)  # local hours in which she may message first
MAX_LEN = 2000   # Discord's per-message limit

brain = Brain(Store(Path(__file__).parent / "companion.db"))


async def send(channel, text: str) -> None:
    """Blank lines become separate messages, like someone sending a few in a row."""
    bubbles = [b.strip() for b in text.split("\n\n") if b.strip()]
    for i, bubble in enumerate(bubbles):
        if i:
            async with channel.typing():
                await asyncio.sleep(min(2.5, 0.4 + len(bubble) / 60))
        for start in range(0, len(bubble), MAX_LEN):
            await channel.send(bubble[start:start + MAX_LEN])


async def run_turn(channel, turn) -> None:
    """Await one brain turn while showing 'typing', then send the result or a plain error."""
    try:
        async with channel.typing():
            text = await turn
    except Refused as e:
        log.warning("model declined: %s", e)
        await channel.send("(The model declined to answer that one. Nothing was saved.)")
    except anthropic.RateLimitError:
        await channel.send("(Rate limited. Try again in a minute.)")
    except anthropic.APIStatusError as e:
        log.error("API error %s: %s", e.status_code, e.message)
        await channel.send(f"(API error {e.status_code}. Check the log.)")
    except anthropic.APIConnectionError:
        await channel.send("(Could not reach the API. Try again.)")
    else:
        await send(channel, text)


async def on_dm(author_id: int, channel, text: str) -> None:
    """Handle one direct message. Only the owner may talk to her."""
    if not OWNER_ID:
        await channel.send(f"Set OWNER_ID={author_id} in .env and restart.")
        return
    if author_id != OWNER_ID or not text:
        return
    chat_id = OWNER_ID
    if text == "!memory":
        notes = brain.store.notes(chat_id) or "No memory notes yet. They are written once the chat gets long enough."
        for start in range(0, len(notes), MAX_LEN):
            await channel.send(notes[start:start + MAX_LEN])
    elif text == "!forget":
        brain.store.forget(chat_id)
        await channel.send("Wiped: all messages and memory notes.")
    elif text == "!start":
        first = brain.store.last(chat_id) is None
        note = (
            "this is the first message in this chat; you two already know each other, so just say hi the way you would"
            if first else "he has just reopened the chat"
        )
        await run_turn(channel, brain.nudge(chat_id, note))
    else:
        await run_turn(channel, brain.reply(chat_id, text))


def silence_note() -> str | None:
    """The app note for a long silence, or None if she should stay quiet."""
    if not OWNER_ID or not (AWAKE[0] <= datetime.now(TZ).hour < AWAKE[1]):
        return None
    last = brain.store.last(OWNER_ID)
    if last is None:
        return None
    hours = (time.time() - last["ts"]) / 3600
    if hours < SILENCE_HOURS:
        return None
    # If her last message was already an unanswered nudge, leave him alone.
    window = brain.store.window(OWNER_ID)
    if len(window) >= 2 and window[-2]["kind"] == "nudge":
        return None
    return (
        f"about {round(hours)} hours have passed with no message from him; "
        "message him first, about something from your day or a thread worth picking up"
    )


class Companion(discord.Client):
    async def setup_hook(self) -> None:
        if SILENCE_HOURS > 0:
            self.check_silence.start()

    async def on_ready(self) -> None:
        log.info("logged in as %s", self.user)

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not isinstance(message.channel, discord.DMChannel):
            return
        await on_dm(message.author.id, message.channel, message.content.strip())

    @tasks.loop(minutes=30)
    async def check_silence(self) -> None:
        note = silence_note()
        if note is None:
            return
        try:
            user = await self.fetch_user(OWNER_ID)
            channel = user.dm_channel or await user.create_dm()
            await run_turn(channel, brain.nudge(OWNER_ID, note))
        except discord.Forbidden:
            log.warning("cannot DM the owner: share a server with the bot and allow DMs from its members")

    @check_silence.before_loop
    async def _wait_ready(self) -> None:
        await self.wait_until_ready()


def main():
    # Message text in DMs with the bot is delivered without the privileged Message Content intent.
    client = Companion(intents=discord.Intents.default())
    client.run(os.environ["DISCORD_TOKEN"], log_level=logging.INFO, root_logger=True)


if __name__ == "__main__":
    main()
