"""Telegram front end. Run: python bot.py"""

import asyncio
import logging
import os
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

import anthropic  # noqa: E402
from telegram import Update  # noqa: E402
from telegram.constants import ChatAction  # noqa: E402
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters  # noqa: E402

from brain import TZ, Brain, Refused  # noqa: E402
from store import Store  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("bot")

OWNER_ID = int(os.getenv("OWNER_ID", "0"))
SILENCE_HOURS = float(os.getenv("SILENCE_HOURS", "20"))  # she texts first after this long; 0 disables
AWAKE = (8, 21)  # local hours in which she may text first

brain = Brain(Store(Path(__file__).parent / "companion.db"))


def owner_only(handler):
    """Only the owner may talk to her. With no owner set, tell the sender their ID and stop."""

    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id
        if not OWNER_ID:
            await update.effective_message.reply_text(f"Set OWNER_ID={uid} in .env and restart.")
        elif uid == OWNER_ID and update.effective_chat.type == "private":
            await handler(update, context)

    return wrapped


async def send(context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str) -> None:
    """Blank lines become separate bubbles, like someone sending a few texts in a row."""
    bubbles = [b.strip() for b in text.split("\n\n") if b.strip()]
    for i, bubble in enumerate(bubbles):
        if i:
            await context.bot.send_chat_action(chat_id, ChatAction.TYPING)
            await asyncio.sleep(min(2.5, 0.4 + len(bubble) / 60))
        await context.bot.send_message(chat_id, bubble)


async def run_turn(context, chat_id: int, turn) -> None:
    await context.bot.send_chat_action(chat_id, ChatAction.TYPING)
    try:
        text = await turn
    except Refused as e:
        log.warning("model declined: %s", e)
        await context.bot.send_message(chat_id, "(The model declined to answer that one. Nothing was saved.)")
    except anthropic.RateLimitError:
        await context.bot.send_message(chat_id, "(Rate limited. Try again in a minute.)")
    except anthropic.APIStatusError as e:
        log.error("API error %s: %s", e.status_code, e.message)
        await context.bot.send_message(chat_id, f"(API error {e.status_code}. Check the log.)")
    except anthropic.APIConnectionError:
        await context.bot.send_message(chat_id, "(Could not reach the API. Try again.)")
    else:
        await send(context, chat_id, text)


@owner_only
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await run_turn(context, chat_id, brain.reply(chat_id, update.message.text))


@owner_only
async def on_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    first = brain.store.last(chat_id) is None
    note = "this is the first message in this chat; you two already know each other, so just say hi the way you would" if first else "he has just reopened the chat"
    await run_turn(context, chat_id, brain.nudge(chat_id, note))


@owner_only
async def on_memory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    notes = brain.store.notes(update.effective_chat.id)
    await update.message.reply_text(notes or "No memory notes yet. They are written once the chat gets long enough.")


@owner_only
async def on_forget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    brain.store.forget(update.effective_chat.id)
    await update.message.reply_text("Wiped: all messages and memory notes for this chat.")


async def check_silence(context: ContextTypes.DEFAULT_TYPE):
    """She texts first after a long silence, once, during waking hours."""
    if not (AWAKE[0] <= datetime.now(TZ).hour < AWAKE[1]) or not OWNER_ID:
        return
    last = brain.store.last(OWNER_ID)
    if last is None:
        return
    hours = (time.time() - last["ts"]) / 3600
    if hours < SILENCE_HOURS:
        return
    # If her last message was already an unanswered nudge, leave him alone.
    window = brain.store.window(OWNER_ID)
    if len(window) >= 2 and window[-2]["kind"] == "nudge":
        return
    note = f"about {round(hours)} hours have passed with no message from him; text him first, about something from your day or a thread worth picking up"
    await run_turn(context, OWNER_ID, brain.nudge(OWNER_ID, note))


def main():
    app = Application.builder().token(os.environ["BOT_TOKEN"]).build()
    app.add_handler(CommandHandler("start", on_start))
    app.add_handler(CommandHandler("memory", on_memory))
    app.add_handler(CommandHandler("forget", on_forget))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    if SILENCE_HOURS > 0:
        app.job_queue.run_repeating(check_silence, interval=1800, first=60)
    app.run_polling(allowed_updates=["message"])


if __name__ == "__main__":
    main()
