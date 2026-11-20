# Companion

A private AI companion on Telegram: one persona, long-term memory, and she texts first after a long silence. About 350 lines of Python on the Claude API. It replaces the abandoned stack in the rest of this repository and shares no code with it.

## Run it

```
cd companion
python3 -m venv venv && ./venv/bin/pip install -r requirements.txt
cp .env.example .env
```

1. In Telegram, message `@BotFather`, send `/newbot`, and copy the token into `BOT_TOKEN`.
2. Put an Anthropic API key in `ANTHROPIC_API_KEY`.
3. Start it with `./venv/bin/python bot.py` and message your bot. It replies with your Telegram ID.
4. Put that ID in `OWNER_ID`, restart, and send `/start`.

It uses long polling, so it runs anywhere with outbound internet and needs no public address. To try it without Telegram, run `./venv/bin/python cli.py`.

## Commands

| Command | Effect |
|---|---|
| `/start` | She opens the conversation |
| `/memory` | Shows her current memory notes |
| `/forget` | Deletes all messages and memory for the chat |

## How it works

- `persona.md` is the whole character. Edit it freely; it is read at start-up.
- Every message is stored in `companion.db` (SQLite) with its time. Each of your messages reaches the model with a timestamp, so she knows the time of day and how long you were away.
- Once 40 messages are in view, the oldest 20 are rewritten into a memory note (about you, about the two of you, what she has said about her own life, open threads). The note is part of every later request. Tune with `FOLD_AT` and `FOLD_BATCH`.
- Every 30 minutes the bot checks for silence. After `SILENCE_HOURS` (default 20) with no messages, between 08:00 and 21:00 local time, she texts first, once. Set `SILENCE_HOURS=0` to turn this off.
- Only `OWNER_ID` can talk to her, and only in a private chat. Everyone else is ignored.

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `MODEL` | `claude-opus-5-5` | Any current Claude model ID |
| `TZ_NAME` | `Africa/Johannesburg` | Time zone for timestamps and waking hours |
| `SILENCE_HOURS` | `20` | Hours of silence before she texts first |
| `FOLD_AT` / `FOLD_BATCH` | `40` / `20` | When and how much history is folded into memory |

Messages and memory notes live only in `companion.db` on the machine running the bot, and are sent to the Anthropic API on each turn.
