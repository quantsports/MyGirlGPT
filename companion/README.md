# Companion

A private AI companion in your Discord direct messages: one persona, long-term memory, and she messages first after a long silence. About 350 lines of Python on the Claude API. It replaces the abandoned stack in the rest of this repository and shares no code with it.

## Run it

```
cd companion
python3 -m venv venv && ./venv/bin/pip install -r requirements.txt
cp .env.example .env
```

1. At discord.com/developers/applications, create an application, open **Bot**, press **Reset Token**, and copy the token into `DISCORD_TOKEN`. No privileged intents are needed.
2. Under **OAuth2 > URL Generator**, tick the `bot` scope, open the generated link, and add the bot to a server you own. A private server with only you in it is fine; it exists so the two of you can exchange direct messages.
3. Put an Anthropic API key in `ANTHROPIC_API_KEY`.
4. Start it with `./venv/bin/python bot.py`, then send the bot a direct message. It replies with your Discord user ID.
5. Put that ID in `OWNER_ID`, restart, and send `!start`.

The bot connects outbound to Discord, so it runs anywhere with internet access and needs no public address. To try it without Discord, run `./venv/bin/python cli.py`.

## Commands

| Command | Effect |
|---|---|
| `!start` | She opens the conversation |
| `!memory` | Shows her current memory notes |
| `!forget` | Deletes all messages and memory for the chat |

## How it works

- `persona.md` is the whole character. Edit it freely; it is read at start-up.
- Every message is stored in `companion.db` (SQLite) with its time. Each of your messages reaches the model with a timestamp, so she knows the time of day and how long you were away.
- Once 40 messages are in view, the oldest 20 are rewritten into a memory note (about you, about the two of you, what she has said about her own life, open threads). The note is part of every later request. Tune with `FOLD_AT` and `FOLD_BATCH`.
- Every 30 minutes the bot checks for silence. After `SILENCE_HOURS` (default 20) with no messages, between 08:00 and 21:00 local time, she messages first, once. Set `SILENCE_HOURS=0` to turn this off.
- Only `OWNER_ID` can talk to her, and only by direct message. Server channels and everyone else are ignored.

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `MODEL` | `claude-opus-5-5` | Any current Claude model ID |
| `TZ_NAME` | `Africa/Johannesburg` | Time zone for timestamps and waking hours |
| `SILENCE_HOURS` | `20` | Hours of silence before she messages first |
| `FOLD_AT` / `FOLD_BATCH` | `40` / `20` | When and how much history is folded into memory |

Messages and memory notes live only in `companion.db` on the machine running the bot, and are sent to the Anthropic API on each turn.
