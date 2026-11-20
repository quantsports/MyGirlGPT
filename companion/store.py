"""SQLite storage: the message log and one evolving memory note per chat."""

import sqlite3
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    role    TEXT    NOT NULL,            -- 'user' or 'assistant'
    content TEXT    NOT NULL,
    ts      INTEGER NOT NULL,            -- unix seconds
    kind    TEXT    NOT NULL DEFAULT 'msg',  -- 'msg' or 'nudge' (app note, not typed by him)
    folded  INTEGER NOT NULL DEFAULT 0   -- 1 once summarised into memory
);
CREATE INDEX IF NOT EXISTS messages_chat ON messages (chat_id, folded, id);
CREATE TABLE IF NOT EXISTS memory (
    chat_id INTEGER PRIMARY KEY,
    notes   TEXT    NOT NULL,
    ts      INTEGER NOT NULL
);
"""


class Store:
    def __init__(self, path: str | Path):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def add(self, chat_id: int, role: str, content: str, kind: str = "msg", ts: int | None = None) -> None:
        self.db.execute(
            "INSERT INTO messages (chat_id, role, content, ts, kind) VALUES (?, ?, ?, ?, ?)",
            (chat_id, role, content, ts or int(time.time()), kind),
        )
        self.db.commit()

    def window(self, chat_id: int) -> list[sqlite3.Row]:
        """Messages not yet folded into memory, oldest first."""
        return self.db.execute(
            "SELECT * FROM messages WHERE chat_id = ? AND folded = 0 ORDER BY id", (chat_id,)
        ).fetchall()

    def mark_folded(self, chat_id: int, up_to_id: int) -> None:
        self.db.execute(
            "UPDATE messages SET folded = 1 WHERE chat_id = ? AND id <= ?", (chat_id, up_to_id)
        )
        self.db.commit()

    def last(self, chat_id: int) -> sqlite3.Row | None:
        return self.db.execute(
            "SELECT * FROM messages WHERE chat_id = ? ORDER BY id DESC LIMIT 1", (chat_id,)
        ).fetchone()

    def notes(self, chat_id: int) -> str:
        row = self.db.execute("SELECT notes FROM memory WHERE chat_id = ?", (chat_id,)).fetchone()
        return row["notes"] if row else ""

    def set_notes(self, chat_id: int, notes: str) -> None:
        self.db.execute(
            "INSERT INTO memory (chat_id, notes, ts) VALUES (?, ?, ?) "
            "ON CONFLICT (chat_id) DO UPDATE SET notes = excluded.notes, ts = excluded.ts",
            (chat_id, notes, int(time.time())),
        )
        self.db.commit()

    def chat_ids(self) -> list[int]:
        return [r[0] for r in self.db.execute("SELECT DISTINCT chat_id FROM messages")]

    def forget(self, chat_id: int) -> None:
        self.db.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))
        self.db.execute("DELETE FROM memory WHERE chat_id = ?", (chat_id,))
        self.db.commit()
