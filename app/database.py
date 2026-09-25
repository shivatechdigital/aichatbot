"""SQLite persistence for conversations and messages."""

import sqlite3
import re
import hashlib
import hmac
import secrets
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
                    user_id INTEGER,
                    pinned INTEGER NOT NULL DEFAULT 0,
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
                    user_id INTEGER,
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

                CREATE TABLE IF NOT EXISTS project_publications (
                    project_id INTEGER PRIMARY KEY,
                    slug TEXT NOT NULL UNIQUE,
                    published_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (project_id) REFERENCES projects(id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    display_name TEXT NOT NULL DEFAULT 'User',
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS user_sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                );
                """
            )
            conversation_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(conversations)")
            }
            if "user_id" not in conversation_columns:
                connection.execute("ALTER TABLE conversations ADD COLUMN user_id INTEGER")
            if "pinned" not in conversation_columns:
                connection.execute(
                    "ALTER TABLE conversations ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0"
                )
            user_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(users)")
            }
            if "display_name" not in user_columns:
                connection.execute(
                    "ALTER TABLE users ADD COLUMN display_name TEXT NOT NULL DEFAULT 'User'"
                )
            project_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(projects)")
            }
            if "user_id" not in project_columns:
                connection.execute("ALTER TABLE projects ADD COLUMN user_id INTEGER")
            connection.commit()

    @staticmethod
    def _hash_password(password: str, salt: bytes | None = None) -> str:
        salt = salt or secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 120_000)
        return f"{salt.hex()}${digest.hex()}"

    @classmethod
    def _verify_password(cls, password: str, stored: str) -> bool:
        try:
            salt_hex, digest_hex = stored.split("$", 1)
            expected = cls._hash_password(password, bytes.fromhex(salt_hex)).split("$", 1)[1]
            return hmac.compare_digest(expected, digest_hex)
        except (ValueError, TypeError):
            return False

    def create_user(self, email: str, password: str, display_name: str = "User") -> int:
        normalized_email = email.strip().lower()
        display_name = display_name.strip()
        if "@" not in normalized_email or len(password) < 8 or not display_name:
            raise ValueError("Use a name, valid email, and password of at least 8 characters")
        with self.get_connection() as connection:
            try:
                cursor = connection.execute(
                    "INSERT INTO users (email, display_name, password_hash) VALUES (?, ?, ?)",
                    (normalized_email, display_name[:80], self._hash_password(password)),
                )
            except sqlite3.IntegrityError as error:
                raise ValueError("An account with this email already exists") from error
            connection.commit()
            return int(cursor.lastrowid)

    def authenticate_user(self, email: str, password: str) -> dict | None:
        with self.get_connection() as connection:
            row = connection.execute(
                "SELECT id, email, display_name, password_hash FROM users WHERE email = ?",
                (email.strip().lower(),),
            ).fetchone()
        if not row or not self._verify_password(password, row["password_hash"]):
            return None
        return {"id": row["id"], "email": row["email"], "display_name": row["display_name"]}

    @staticmethod
    def _session_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def create_session(self, user_id: int) -> str:
        token = secrets.token_urlsafe(48)
        with self.get_connection() as connection:
            connection.execute(
                "INSERT INTO user_sessions (token_hash, user_id) VALUES (?, ?)",
                (self._session_hash(token), user_id),
            )
            connection.commit()
        return token

    def get_user_by_session(self, token: str) -> dict | None:
        with self.get_connection() as connection:
            row = connection.execute(
                "SELECT users.id, users.email, users.display_name "
                "FROM user_sessions JOIN users ON users.id = user_sessions.user_id "
                "WHERE user_sessions.token_hash = ?",
                (self._session_hash(token),),
            ).fetchone()
        return dict(row) if row else None

    def delete_session(self, token: str) -> None:
        with self.get_connection() as connection:
            connection.execute(
                "DELETE FROM user_sessions WHERE token_hash = ?",
                (self._session_hash(token),),
            )
            connection.commit()

    def update_user_profile(self, user_id: int, display_name: str, email: str) -> dict:
        display_name = display_name.strip()
        email = email.strip().lower()
        if not display_name or "@" not in email:
            raise ValueError("Use a name and valid email")
        with self.get_connection() as connection:
            try:
                connection.execute(
                    "UPDATE users SET display_name = ?, email = ? WHERE id = ?",
                    (display_name[:80], email, user_id),
                )
            except sqlite3.IntegrityError as error:
                raise ValueError("An account with this email already exists") from error
            connection.commit()
        return {"id": user_id, "email": email, "display_name": display_name[:80]}

    def change_password(self, user_id: int, current_password: str, new_password: str) -> None:
        if len(new_password) < 8:
            raise ValueError("New password must be at least 8 characters")
        with self.get_connection() as connection:
            row = connection.execute(
                "SELECT password_hash FROM users WHERE id = ?", (user_id,)
            ).fetchone()
            if not row or not self._verify_password(current_password, row["password_hash"]):
                raise ValueError("Current password is incorrect")
            connection.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (self._hash_password(new_password), user_id),
            )
            connection.commit()

    def create_conversation(self, user_id: int | str = 0, title: str = "New Chat") -> int:
        if isinstance(user_id, str):
            title = user_id
            user_id = 0
        with self.get_connection() as connection:
            cursor = connection.execute(
                "INSERT INTO conversations (user_id, title) VALUES (?, ?)", (user_id, title)
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

    def replace_conversation(
        self,
        user_id: int,
        conversation_id: int | None,
        title: str,
        messages: list[dict],
    ) -> int:
        """Persist a complete chat snapshot and return its database ID."""
        with self.get_connection() as connection:
            if conversation_id is None:
                cursor = connection.execute(
                    "INSERT INTO conversations (user_id, title) VALUES (?, ?)",
                    (user_id, title),
                )
                conversation_id = int(cursor.lastrowid)
            else:
                owned = connection.execute(
                    "SELECT id FROM conversations WHERE id = ? AND user_id = ?",
                    (conversation_id, user_id),
                ).fetchone()
                if not owned:
                    raise ValueError("Conversation does not belong to this user")
                connection.execute(
                    "UPDATE conversations SET title = ?, updated_at = CURRENT_TIMESTAMP "
                    "WHERE id = ? AND user_id = ?",
                    (title, conversation_id, user_id),
                )
                connection.execute(
                    "DELETE FROM messages WHERE conversation_id = ?",
                    (conversation_id,),
                )

            connection.executemany(
                "INSERT INTO messages (conversation_id, role, content) VALUES (?, ?, ?)",
                [
                    (conversation_id, message["role"], message["content"])
                    for message in messages
                    if message.get("role") in {"user", "assistant"}
                ],
            )
            connection.commit()
            return conversation_id

    def get_conversation_snapshots(self, user_id: int) -> list[dict]:
        conversations = self.get_all_conversations(user_id)
        return [
            {
                **conversation,
                "messages": self.get_conversation_messages(user_id, conversation["id"]),
            }
            for conversation in conversations
        ]

    def get_conversation_messages(
        self, user_id: int, conversation_id: int | None = None
    ) -> list[dict]:
        if conversation_id is None:
            conversation_id = user_id
            user_id = 0
        with self.get_connection() as connection:
            if user_id:
                rows = connection.execute(
                    "SELECT role, content FROM messages "
                    "WHERE conversation_id = ? AND conversation_id IN "
                    "(SELECT id FROM conversations WHERE id = ? AND user_id = ?) ORDER BY id",
                    (conversation_id, conversation_id, user_id),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY id",
                    (conversation_id,),
                ).fetchall()
            return [dict(row) for row in rows]

    def get_all_conversations(self, user_id: int | None = None) -> list[dict]:
        with self.get_connection() as connection:
            if user_id is None:
                rows = connection.execute(
                    "SELECT id, title, created_at FROM conversations "
                    "ORDER BY pinned DESC, updated_at DESC, id DESC"
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT id, title, created_at, pinned FROM conversations "
                    "WHERE user_id = ? ORDER BY pinned DESC, updated_at DESC, id DESC",
                    (user_id,),
                ).fetchall()
            return [dict(row) for row in rows]

    def delete_conversation(self, conversation_id: int) -> None:
        with self.get_connection() as connection:
            connection.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
            connection.commit()

    def delete_user_conversation(self, user_id: int, conversation_id: int) -> None:
        with self.get_connection() as connection:
            connection.execute(
                "DELETE FROM conversations WHERE id = ? AND user_id = ?",
                (conversation_id, user_id),
            )
            connection.commit()

    def set_conversation_pinned(
        self, user_id: int, conversation_id: int, pinned: bool
    ) -> None:
        with self.get_connection() as connection:
            connection.execute(
                "UPDATE conversations SET pinned = ?, updated_at = updated_at "
                "WHERE id = ? AND user_id = ?",
                (int(pinned), conversation_id, user_id),
            )
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

    def update_project_name(self, project_id: int, name: str) -> None:
        with self.get_connection() as connection:
            connection.execute(
                "UPDATE projects SET name = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (name.strip() or "Untitled website", project_id),
            )
            connection.commit()

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

    def publish_project(self, project_id: int, slug: str) -> dict:
        normalized_slug = slug.strip().strip("/")
        if not normalized_slug or not re.fullmatch(r"[a-z0-9-]+", normalized_slug):
            raise ValueError("Publication slug is invalid")
        with self.get_connection() as connection:
            connection.execute(
                "INSERT INTO project_publications (project_id, slug) VALUES (?, ?) "
                "ON CONFLICT(project_id) DO UPDATE SET slug = excluded.slug, "
                "published_at = CURRENT_TIMESTAMP",
                (project_id, normalized_slug),
            )
            connection.commit()
            row = connection.execute(
                "SELECT project_id, slug, published_at FROM project_publications "
                "WHERE project_id = ?",
                (project_id,),
            ).fetchone()
            return dict(row)

    def get_project_publication(self, project_id: int) -> dict | None:
        with self.get_connection() as connection:
            row = connection.execute(
                "SELECT project_id, slug, published_at FROM project_publications "
                "WHERE project_id = ?",
                (project_id,),
            ).fetchone()
            return dict(row) if row else None

    def get_publication_by_slug(self, slug: str) -> dict | None:
        with self.get_connection() as connection:
            row = connection.execute(
                "SELECT project_id, slug, published_at FROM project_publications "
                "WHERE slug = ?",
                (slug.strip().strip("/"),),
            ).fetchone()
            return dict(row) if row else None


db = Database()