"""SQLite persistence for conversations and messages."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app.config import config


class Database:
    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = str(db_path or config.DATABASE_PATH)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def get_connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
        finally:
            connection.close()

    def _init_db(self) -> None:
        with self.get_connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id INTEGER NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (conversation_id) REFERENCES conversations(id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_messages_conversation
                    ON messages(conversation_id, id);
                """
            )
            connection.commit()

    def create_conversation(self, title: str = "New Chat") -> int:
        with self.get_connection() as connection:
            cursor = connection.execute(
                "INSERT INTO conversations (title) VALUES (?)", (title,)
            )
            connection.commit()
            if cursor.lastrowid is None:
                raise RuntimeError("Conversation could not be created")
            return cursor.lastrowid

    def save_message(self, conversation_id: int, role: str, content: str) -> None:
        with self.get_connection() as connection:
            connection.execute(
                "INSERT INTO messages (conversation_id, role, content) VALUES (?, ?, ?)",
                (conversation_id, role, content),
            )
            connection.execute(
                "UPDATE conversations SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (conversation_id,),
            )
            connection.commit()

    def get_conversation_messages(self, conversation_id: int) -> list[dict]:
        with self.get_connection() as connection:
            rows = connection.execute(
                "SELECT role, content FROM messages "
                "WHERE conversation_id = ? ORDER BY id",
                (conversation_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_all_conversations(self) -> list[dict]:
        with self.get_connection() as connection:
            rows = connection.execute(
                "SELECT id, title, created_at FROM conversations "
                "ORDER BY updated_at DESC, id DESC"
            ).fetchall()
            return [dict(row) for row in rows]

    def delete_conversation(self, conversation_id: int) -> None:
        with self.get_connection() as connection:
            connection.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
            connection.commit()


db = Database()