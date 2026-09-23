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

                CREATE TABLE IF NOT EXISTS projects (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS project_files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER NOT NULL,
                    path TEXT NOT NULL,
                    content TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(project_id, path),
                    FOREIGN KEY (project_id) REFERENCES projects(id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_project_files_project
                    ON project_files(project_id, path);
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

    def create_project(self, name: str = "Untitled website") -> int:
        with self.get_connection() as connection:
            cursor = connection.execute(
                "INSERT INTO projects (name) VALUES (?)", (name.strip() or "Untitled website",)
            )
            connection.commit()
            if cursor.lastrowid is None:
                raise RuntimeError("Project could not be created")
            return cursor.lastrowid

    def get_all_projects(self) -> list[dict]:
        with self.get_connection() as connection:
            rows = connection.execute(
                "SELECT id, name, created_at, updated_at FROM projects "
                "ORDER BY updated_at DESC, id DESC"
            ).fetchall()
            return [dict(row) for row in rows]

    def delete_project(self, project_id: int) -> None:
        with self.get_connection() as connection:
            connection.execute("DELETE FROM projects WHERE id = ?", (project_id,))
            connection.commit()

    def save_project_file(self, project_id: int, path: str, content: str) -> None:
        normalized_path = path.strip().replace("\\", "/")
        if not normalized_path or normalized_path.startswith("/") or ".." in normalized_path.split("/"):
            raise ValueError("Project file path is invalid")
        with self.get_connection() as connection:
            connection.execute(
                "INSERT INTO project_files (project_id, path, content) VALUES (?, ?, ?) "
                "ON CONFLICT(project_id, path) DO UPDATE SET content = excluded.content, "
                "updated_at = CURRENT_TIMESTAMP",
                (project_id, normalized_path, content),
            )
            connection.execute(
                "UPDATE projects SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (project_id,),
            )
            connection.commit()

    def get_project_files(self, project_id: int) -> list[dict]:
        with self.get_connection() as connection:
            rows = connection.execute(
                "SELECT path, content, updated_at FROM project_files "
                "WHERE project_id = ? ORDER BY path",
                (project_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_project_file(self, project_id: int, path: str) -> dict | None:
        with self.get_connection() as connection:
            row = connection.execute(
                "SELECT path, content, updated_at FROM project_files "
                "WHERE project_id = ? AND path = ?",
                (project_id, path.replace("\\", "/")),
            ).fetchone()
            return dict(row) if row else None


db = Database()