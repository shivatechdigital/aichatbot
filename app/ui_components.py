"""Formatting helpers used by the Gradio UI."""

import gradio as gr

from app.database import db


def conversation_choices() -> list[tuple[str, int]]:
    return [(item["title"], item["id"]) for item in db.get_all_conversations()]


def conversation_list_update(*, value: int | None = None):
    return gr.update(choices=conversation_choices(), value=value)


def messages_to_history(messages: list[dict]) -> list[tuple[str, str]]:
    history: list[tuple[str, str]] = []
    pending_user: str | None = None
    for message in messages:
        if message["role"] == "user":
            pending_user = message["content"]
        elif pending_user is not None:
            history.append((pending_user, message["content"]))
            pending_user = None
    return history