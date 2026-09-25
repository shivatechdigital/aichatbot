import importlib.util
import pkgutil

if not hasattr(pkgutil, "find_loader"):
    pkgutil.find_loader = lambda name: importlib.util.find_spec(name)

from nicegui import app as nicegui_app, ui
from nicegui.context import context as nicegui_context
import httpx
import asyncio
import base64
import io
import json
import os
from pathlib import Path
from datetime import datetime
from urllib.parse import urlsplit, urlunsplit

from docx import Document
from pypdf import PdfReader
from app.config import config
from app.database import db

import app.builder  # noqa: F401 - registers the Website Builder page

# ============================================================
# Configuration
# ============================================================

LLM_URL = os.getenv(
    "LLM_URL",
    os.getenv(
        "API_BASE_URL",
        "http://host.docker.internal:3010/v1/chat/completions",
    ),
)

LLM_MODEL = os.getenv("LLM_MODEL", os.getenv("MODEL_NAME", "auto"))

MODEL_OPTIONS = {
    "gpt-5.4": "gpt-5.4",
    "gpt-5-mini": "gpt-5-mini",
    "gpt-5.3-codex": "gpt-5.3-codex",
    "gpt-5.4-mini": "gpt-5.4-mini",
    "gpt-5.5": "gpt-5.5",
    "gpt-5.6-luna": "gpt-5.6-luna",
    "gpt-6-astra": "gpt-6-astra",
    "gpt-6-luna": "gpt-6-luna",
    "gpt-6-sol": "gpt-6-sol",
    "claude-sonnet-5": "claude-sonnet-5",
    "claude-fable-5": "claude-fable-5",
    "claude-fable-5.1": "claude-fable-5.1",
    "claude-haiku-4.5": "claude-haiku-4.5",
    "claude-opus-4.7": "claude-opus-4.7",
    "claude-opus-4.8": "claude-opus-4.8",
    "claude-opus-5": "claude-opus-5",
    "claude-opus-5.5": "claude-opus-5.5",
    "gemini-3.5-flash": "gemini-3.5-flash",
    "gemini-3.6-flash": "gemini-3.6-flash",
    "gemini-3.7-flash": "gemini-3.7-flash",
    "gemini-3.8-flash": "gemini-3.8-flash",
    "grok-4.5": "grok-4.5",
    "grok-4.6": "grok-4.6",
    "grok-4.7": "grok-4.7",
}


def configured_model_options() -> dict[str, str]:
    """Read model IDs confirmed by the host's Copilot CLI checks."""
    configured = os.getenv("COPILOT_MODELS", "").split(",")
    model_ids = [model.strip() for model in configured if model.strip()]
    if not model_ids:
        return MODEL_OPTIONS
    return {model: model for model in model_ids}


def models_endpoint(completions_url: str) -> str:
    """Return the OpenAI-compatible model listing endpoint."""
    parsed = urlsplit(completions_url)
    path = parsed.path.rstrip("/")
    if path.endswith("/chat/completions"):
        path = path[: -len("/chat/completions")]
    return urlunsplit((parsed.scheme, parsed.netloc, f"{path}/models", "", ""))


async def discover_models() -> list[str]:
    """Read model IDs when the backend supports model discovery."""
    headers = {}
    api_key = config.API_KEY.strip()
    if api_key and api_key.lower() != "not-needed":
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(10, connect=5)
        ) as client:
            response = await client.get(models_endpoint(LLM_URL), headers=headers)
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, ValueError, TypeError):
        return []

    models = data.get("data", []) if isinstance(data, dict) else []
    discovered_models = [
        item["id"]
        for item in models
        if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"].strip()
    ]
    return discovered_models

selected_model = "Auto" if LLM_MODEL.lower() == "auto" else LLM_MODEL

# ============================================================
# State
# ============================================================

chats = []
current_messages = []
chat_counter = 1
active_chat_id = None
pending_attachments = []
generation_task = None
generation_cancelled = False

MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
MAX_ATTACHMENT_TOTAL_BYTES = 50 * 1024 * 1024
MAX_ATTACHMENT_FILES = 20
TEXT_EXTENSIONS = {".txt", ".md", ".csv", ".json", ".py", ".log"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


def load_persisted_chats(user_id: int) -> list[dict]:
    return db.get_conversation_snapshots(user_id)


def logged_in_user() -> dict | None:
    storage = nicegui_context.client.storage
    user_id = storage.get("user_id")
    email = storage.get("email")
    display_name = storage.get("display_name", "User")
    return (
        {"id": user_id, "email": email, "display_name": display_name}
        if user_id and email
        else None
    )


def current_user_id() -> int:
    user = logged_in_user()
    if not user:
        raise RuntimeError("Sign in is required")
    return int(user["id"])


def logout():
    nicegui_context.client.storage.clear()
    refresh_profile_display()
    ui.run_javascript("location.reload()")


def open_auth_dialog():
    auth_dialog.open()


def handle_auth_action():
    if logged_in_user():
        logout()
    else:
        open_auth_dialog()


def refresh_profile_display():
    user = logged_in_user()
    if user:
        profile_rail_avatar.set_text(user["display_name"][:2].upper())
        profile_menu_name.set_text(user["display_name"])
        profile_menu_email.set_text(user["email"])
        auth_menu_container.clear()
        with auth_menu_container:
            ui.menu_item("Log out", on_click=handle_auth_action).classes("text-[13px] py-2")
    else:
        profile_rail_avatar.set_text("U")
        profile_menu_name.set_text("Guest")
        profile_menu_email.set_text("Sign in to save chats")
        auth_menu_container.clear()
        with auth_menu_container:
            ui.menu_item("Sign in", on_click=handle_auth_action).classes("text-[13px] py-2")


def open_settings():
    user = logged_in_user()
    if not user:
        auth_dialog.open()
        return
    profile_name_input.value = user["display_name"]
    profile_email_input.value = user["email"]
    settings_dialog.open()


chats = []
chat_counter = 1


def now_title(text: str) -> str:
    text = " ".join(text.split())
    return text[:35] + ("..." if len(text) > 35 else "")


def api_text_content(content):
    """Normalize message content while preserving image parts for copilot-api."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        has_image = False
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(str(item.get("text", "")))
                elif item.get("type") == "image_url":
                    parts.append(item)
                    has_image = True
                else:
                    parts.append(str(item.get("text", "")))
        return parts if has_image else "\n".join(part for part in parts if part)
    return str(content)


# ============================================================
# Styling
# ============================================================

ui.add_head_html("""
<style>
:root {
    --sidebar-bg: #f9f9f9;
    --canvas: #ffffff;
    --border: #ececec;
    --hover: #ebebeb;
    --active: #e3e3e3;
    --text: #0d0d0d;
    --muted: #8e8e8e;
    --user: #f4f4f4;
}

html, body, #app { height: 100%; }

body {
    margin: 0;
    overflow: hidden;
    background: var(--canvas);
    color: var(--text);
    font-family: "Segoe UI", Arial, sans-serif;
}

.nicegui-content {
    width: 100%;
    height: 100vh;
    padding: 0 !important;
    max-width: none !important;
}

/* =====================================
   ChatGPT Dual Sidebar Layout
   ===================================== */
.desktop-sidebar {
    background: var(--sidebar-bg);
}

.sidebar-rail {
    width: 60px !important;
    background: var(--sidebar-bg);
    border-right: 1px solid transparent;
}

.rail-btn {
    width: 44px !important;
    height: 44px !important;
    min-width: 44px !important;
    min-height: 44px !important;
    border-radius: 12px !important;
    color: #666 !important;
    background: transparent !important;
}
.rail-btn::before { box-shadow: none !important; }
.rail-btn:hover { background: var(--hover) !important; color: #111 !important; }
.rail-btn-active { background: #e3e3e3 !important; color: #111 !important; }
.rail-btn .q-icon { font-size: 22px !important; }

.rail-avatar {
    width: 38px !important;
    height: 38px !important;
    min-width: 38px !important;
    min-height: 38px !important;
    border-radius: 50% !important;
    background: #343541 !important; 
    color: white !important;
    font-weight: 600 !important;
    font-size: 14px !important;
    padding: 0 !important;
}
.rail-avatar:hover { opacity: 0.85; }
.rail-avatar::before { box-shadow: none !important; }

.sidebar-panel {
    width: 260px !important;
    background: var(--sidebar-bg);
    border-right: 1px solid var(--border);
}

.panel-header-icon {
    width: 36px !important;
    height: 36px !important;
    min-width: 36px !important;
    border-radius: 8px !important;
    color: #555 !important;
}
.panel-header-icon:hover { background: var(--hover) !important; color: #000 !important; }
.panel-header-icon::before { box-shadow: none !important; }

.section-label {
    font-size: 12px;
    font-weight: 600;
    color: #a3a3a3;
    padding: 12px 8px 6px 8px;
    margin: 0;
}

.sidebar-scroll {
    overflow-y: auto;
    overflow-x: hidden;
    scrollbar-width: thin;
    scrollbar-color: #d1d1d1 transparent;
}

.sidebar-btn {
    width: 100%;
    min-height: 38px !important;
    padding: 0 10px !important;
    border-radius: 8px !important;
    color: #333 !important;
    background: transparent !important;
    justify-content: flex-start !important;
    font-size: 13.5px !important;
    box-shadow: none !important;
    text-transform: none !important;
}
.sidebar-btn::before { box-shadow: none !important; }
.sidebar-btn:hover { background: var(--hover) !important; color: #000 !important; }
.sidebar-btn .q-icon { font-size: 18px !important; margin-right: 8px !important; color: #666 !important; }
.sidebar-btn .q-btn__content { flex-wrap: nowrap !important; justify-content: flex-start !important; min-width: 0 !important; }
.sidebar-btn .block { overflow: hidden !important; text-overflow: ellipsis !important; white-space: nowrap !important; text-align: left !important; }

/* ---- Chat list items: robust truncation ---- */
.chat-list {
    flex: 1 1 auto;
    min-height: 0;
    gap: 2px !important;
    overflow-x: hidden !important;
    width: 100% !important;
}

.chat-item {
    display: flex !important;
    flex-direction: row !important;
    flex-wrap: nowrap !important;
    align-items: center !important;
    width: 100% !important;
    max-width: 100% !important;
    min-width: 0 !important;
    height: 36px !important;
    padding: 0 4px !important;
    margin: 0 !important;
    border-radius: 8px !important;
    box-sizing: border-box !important;
    overflow: hidden !important;
}

.chat-item:hover {
    background: var(--hover) !important;
}

.chat-item-active {
    background: var(--active) !important;
}

.chat-title {
    flex: 1 1 auto !important;
    min-width: 0 !important;
    max-width: 100% !important;
    overflow: hidden !important;
    text-overflow: ellipsis !important;
    white-space: nowrap !important;
    font-size: 13.5px !important;
    line-height: 36px !important;
    height: 36px !important;
    padding: 0 8px !important;
    color: #333 !important;
    cursor: pointer !important;
    border-radius: 8px !important;
    user-select: none !important;
}

.chat-item-active .chat-title {
    font-weight: 500 !important;
    color: #000 !important;
}

.chat-actions {
    display: flex !important;
    flex: 0 0 auto !important;
    flex-shrink: 0 !important;
    align-items: center !important;
    gap: 0 !important;
    margin-left: 2px !important;
}

.chat-action {
    flex: 0 0 28px !important;
    width: 28px !important;
    min-width: 28px !important;
    max-width: 28px !important;
    height: 28px !important;
    min-height: 28px !important;
    padding: 0 !important;
    color: #65615b !important;
    background: transparent !important;
    border-radius: 6px !important;
}
.chat-action::before { box-shadow: none !important; }
.chat-action .q-btn__content {
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    padding: 0 !important;
    width: 100% !important;
}
.chat-action .q-icon {
    font-size: 16px !important;
    margin: 0 !important;
}
.chat-action:hover {
    background: rgba(0,0,0,0.08) !important;
    color: #111 !important;
}

.sidebar-open-button {
    position: absolute !important;
    top: 12px;
    left: 12px;
    z-index: 8;
    width: 36px !important;
    height: 36px !important;
    min-width: 36px !important;
    min-height: 36px !important;
    padding: 0 !important;
    border-radius: 8px !important;
    background: transparent !important;
    color: #555 !important;
}
.sidebar-open-button:hover { background: var(--hover) !important; color: #000 !important; }
.sidebar-open-button::before { box-shadow: none !important; }

/* =====================================
   Main Chat Canvas
   ===================================== */
.chat-main { position: relative; height: 100vh; min-height: 0; overflow: hidden; background: var(--canvas); }
.chat-header { flex: 0 0 60px; }
.chat-header .q-btn { color: var(--text) !important; font-size: 16px !important; font-weight: 600 !important; }
.chat-header .q-btn::before { box-shadow: none !important; }
.chat-header .q-btn:hover { background: var(--hover) !important; border-radius: 10px !important; }

.model-menu { width: 230px; padding: 6px 0; border: 1px solid var(--border) !important; border-radius: 12px !important; }
.model-menu .q-item { min-height: 34px; padding: 4px 14px; font-size: 13px; }
.model-menu-scroll { max-height: 240px; overflow-y: auto; }
.chat-scroll { min-height: 0; padding: 24px 28px 190px !important; overflow-y: auto; scrollbar-width: thin; scrollbar-color: #c9c5be transparent; }

.welcome-state { padding-top: clamp(70px, 14vh, 150px) !important; }
.welcome-state > :first-child { border-color: var(--border) !important; }
.welcome-state .text-3xl { color: #222; font-family: Georgia, "Times New Roman", serif; font-size: clamp(34px, 4vw, 54px) !important; font-weight: 400 !important; letter-spacing: 0; }
.suggestion-grid .q-btn { min-height: 52px; border: 1px solid var(--border) !important; border-radius: 14px; background: #ffffff !important; color: #555 !important; box-shadow: none !important; }
.suggestion-grid .q-btn::before { box-shadow: none !important; }
.suggestion-grid .q-btn:hover { background: var(--hover) !important; }

.message-user { background: var(--user); border-radius: 20px; padding: 12px 18px; max-width: 75%; min-width: 0; overflow-wrap: anywhere; white-space: pre-wrap; font-size: 15px; }
.user-message-group { width: 100%; max-width: 78%; margin-left: auto; gap: 7px !important; align-items: flex-end !important; }
.sent-attachments { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 7px !important; }
.sent-file-card { display: flex; align-items: center; gap: 9px; width: 210px; min-height: 58px; padding: 8px 10px; overflow: hidden; border: 1px solid var(--border); border-radius: 12px; background: white; }
.sent-file-icon { display: flex; align-items: center; justify-content: center; flex: 0 0 36px; width: 36px; height: 36px; border-radius: 8px; background: #f0efec; color: #222; font-size: 11px; font-weight: 700; text-transform: uppercase; }
.sent-file-name { overflow: hidden; color: var(--text); font-size: 12px; line-height: 1.25; text-overflow: ellipsis; white-space: nowrap; }
.sent-image-preview { width: 112px !important; height: 88px !important; overflow: hidden; border: 1px solid var(--border); border-radius: 12px; }
.sent-image-preview img { width: 100% !important; height: 100% !important; object-fit: cover !important; }

.message-ai { max-width: 85%; min-width: 0; overflow-wrap: anywhere; line-height: 1.6; font-size: 15px; color: #222; }
.chat-scroll > .q-column, .chat-scroll > .q-row { width: 100%; min-width: 0; }
.chat-scroll .message-ai { flex: 1 1 auto; }
.message-ai .code-block { width: min(100%, 760px); margin: 12px 0; overflow: hidden; border: 1px solid #2f3338; border-radius: 12px; background: #17191c; color: #e8eaed; line-height: 1.45; }
.message-ai .code-toolbar { display: flex; align-items: center; justify-content: space-between; min-height: 36px; padding: 0 10px 0 14px; border-bottom: 1px solid #2f3338; background: #202328; color: #aeb4bd; font-family: "Segoe UI", Arial, sans-serif; font-size: 12px; }
.message-ai .code-copy { padding: 5px 8px; border: 0; border-radius: 5px; background: transparent; color: #c6cbd2; cursor: pointer; font-size: 12px; }
.message-ai .code-copy:hover { background: #343941; color: white; }
.message-ai .code-block pre { margin: 0; padding: 14px; overflow-x: auto; white-space: pre; }
.message-ai .code-block code { color: inherit; font-family: Consolas, "Cascadia Code", monospace; font-size: 13px; }
.message-ai.streaming::after { display: inline-block; width: 7px; height: 1.05em; margin-left: 3px; border-radius: 2px; background: #555; vertical-align: -.15em; content: ""; animation: typing-cursor 1s steps(2, start) infinite; }
.thinking-label { color: var(--muted); font-style: italic; }
@keyframes typing-cursor { 50% { opacity: 0; } }

/* =====================================
   ChatGPT-style single-line composer
   ===================================== */
.composer-layer {
    position: absolute;
    right: 0;
    bottom: 0;
    left: 0;
    z-index: 5;
    padding: 24px 24px 12px !important;
    background: linear-gradient(to top, var(--canvas) 70%, rgba(251, 250, 247, 0));
    pointer-events: none;
}
.composer-layer > * { pointer-events: auto; }

.composer {
    display: flex;
    flex-direction: column;
    gap: 0 !important;
    border: 1px solid #e5e5e5 !important;
    border-radius: 26px !important;
    background: #f4f4f4 !important;
    box-shadow: none !important;
    padding: 0 !important;
    min-height: 0 !important;
    overflow: hidden;
}

.composer:focus-within {
    border-color: #d0d0d0 !important;
    box-shadow: 0 2px 10px rgba(0,0,0,0.05) !important;
    background: #f4f4f4 !important;
}

.attachment-list {
    display: flex;
    flex-wrap: nowrap !important;
    gap: 6px !important;
    width: 100%;
    max-width: 100%;
    margin: 0;
    padding: 8px 12px 0;
    overflow-x: auto;
    overflow-y: hidden;
    scrollbar-width: thin;
}
.attachment-list:empty {
    display: none !important;
    padding: 0 !important;
}

.composer-input {
    display: flex !important;
    align-items: flex-end !important;
    width: 100% !important;
    min-width: 0;
    min-height: 52px !important;
    padding: 6px 8px 6px 4px !important;
    gap: 2px !important;
    box-sizing: border-box;
}

.composer-add-btn,
.composer-action-btn {
    width: 36px !important;
    height: 36px !important;
    min-width: 36px !important;
    min-height: 36px !important;
    max-width: 36px !important;
    max-height: 36px !important;
    padding: 0 !important;
    border-radius: 50% !important;
    color: #5a5a5a !important;
    background: transparent !important;
    align-self: flex-end !important;
    margin-bottom: 2px !important;
}
.composer-add-btn .q-icon,
.composer-action-btn .q-icon {
    font-size: 22px !important;
}
.composer-add-btn:hover,
.composer-action-btn:hover {
    background: rgba(0,0,0,0.06) !important;
}

/* Stripping Quasar classes to allow textarea to be single line */
.composer .message-input,
.composer .message-input.q-field,
.composer .message-input .q-field__inner {
    flex: 1 1 auto !important;
    height: auto !important;
    min-height: 0 !important;
    max-height: none !important;
    background: transparent !important;
}

.composer .q-field__control {
    height: auto !important;
    min-height: 0 !important;
    max-height: none !important;
    padding: 0 !important;
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
}

.composer .q-field__control-container {
    height: auto !important;
    min-height: 0 !important;
    padding: 0 !important;
    overflow: visible !important;
}

/* The actual textarea element */
textarea.composer-textarea,
.composer .q-field__native,
.composer textarea.q-field__native {
    min-height: 24px !important;
    height: 24px !important;
    max-height: 200px !important;
    padding: 8px 6px !important;
    margin: 0 !important;
    margin-bottom: 4px !important;
    resize: none !important;
    overflow-y: hidden !important;
    font-size: 16px !important;
    line-height: 1.5 !important;
    color: #0d0d0d !important;
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
}

.composer-right-actions {
    display: flex !important;
    align-items: center !important;
    align-self: flex-end !important;
    gap: 1px !important;
    height: 36px !important;
    margin: 0 2px 2px 0 !important;
}

.composer-think-btn {
    height: 32px !important;
    min-height: 32px !important;
    padding: 0 8px !important;
    border-radius: 16px !important;
    color: #6b6b6b !important;
    font-size: 13px !important;
    font-weight: 500 !important;
    text-transform: none !important;
    background: transparent !important;
    letter-spacing: 0 !important;
}
.composer-think-btn .q-icon {
    font-size: 17px !important;
    margin-right: 2px !important;
    color: #8e8e8e !important;
}
.composer-think-btn:hover {
    background: rgba(0,0,0,0.05) !important;
}

.composer .send-message-button {
    width: 32px !important;
    height: 32px !important;
    min-width: 32px !important;
    min-height: 32px !important;
    max-width: 32px !important;
    max-height: 32px !important;
    padding: 0 !important;
    border-radius: 50% !important;
    background: #0d6efd !important;
    color: white !important;
    box-shadow: none !important;
    align-self: flex-end !important;
}
.composer .send-message-button .q-icon {
    font-size: 18px !important;
    color: white !important;
}
.composer .send-message-button:hover {
    background: #0b5ed7 !important;
}
.composer .send-message-button.stop-generation {
    background: #111 !important;
}

.attachment-item { position: relative; flex: 0 0 72px; width: 72px; min-width: 72px; max-width: 72px; height: 72px; overflow: hidden; border: 1px solid var(--border); border-radius: 12px; background: var(--soft, #f3f1ed); }
.attachment-image { width: 100% !important; height: 100% !important; }
.attachment-image img { width: 100% !important; height: 100% !important; object-fit: cover !important; }
.attachment-document { display: flex; align-items: center; justify-content: center; width: 100%; height: 100%; padding: 7px; color: var(--muted); font-size: 10px; line-height: 1.2; text-align: center; word-break: break-word; }
.composer .attachment-remove { position: absolute !important; top: 3px; right: 3px; z-index: 2; width: 20px !important; height: 20px !important; min-width: 20px !important; min-height: 20px !important; max-width: 20px !important; max-height: 20px !important; padding: 0 !important; border: 1px solid rgba(255, 255, 255, .85) !important; background: rgba(25, 25, 25, .78) !important; color: white !important; font-size: 12px !important; }
.small-muted { color: var(--muted); font-size: 12px; }
pre { background: #171717; color: #f3f3f3; border-radius: 10px; padding: 14px; overflow-x: auto; }
code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }

@media (max-width: 800px) {
    html, body, #app, .nicegui-content { overflow-x: hidden !important; }
    .desktop-sidebar { display: flex; }
    .sidebar-rail { width: 52px !important; }
    .sidebar-panel {
        position: fixed !important;
        top: 0;
        bottom: 0;
        left: 52px;
        z-index: 20;
        width: calc(100vw - 52px) !important;
        max-width: calc(100vw - 52px) !important;
        min-width: 0 !important;
        overflow-x: hidden !important;
        box-shadow: 8px 0 24px rgba(0, 0, 0, .12);
    }
    .sidebar-open-button {
        margin-top: 4px !important;
        margin-left: -45px !important;
        top: 10px;
        left: 62px;
        z-index: 25;
        background: rgba(255, 255, 255, .94) !important;
    }
    .chat-main { width: calc(100vw - 52px) !important; }
    .message-user { max-width: 90%; }
    .chat-scroll { padding: 16px 12px 170px !important; }
    .composer-layer { padding: 42px 12px 10px !important; }
    .welcome-state { padding-top: 12vh !important; }
    .suggestion-grid { grid-template-columns: 1fr !important; }
    .composer-think-btn .block { display: none !important; }
    .composer-think-btn .q-icon { margin-right: 0 !important; }
}
</style>
""")

ui.add_body_html("""
<script>
document.addEventListener('keydown', (event) => {
    const isComposer = event.target.matches('.message-input textarea');
    if (isComposer && event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        event.stopImmediatePropagation();
        document.querySelector('.send-message-button')?.click();
    }
}, true);

const resizeComposer = (textarea) => {
    if (!textarea) return;
    
    textarea.style.setProperty('height', '24px', 'important');
    textarea.style.setProperty('overflow-y', 'hidden', 'important');
    
    const maxHeight = 200;
    const scrollH = textarea.scrollHeight;
    const nextHeight = Math.min(Math.max(scrollH, 24), maxHeight);
    
    textarea.style.setProperty('height', `${nextHeight}px`, 'important');
    textarea.style.setProperty(
        'overflow-y', 
        scrollH > maxHeight ? 'auto' : 'hidden', 
        'important'
    );
    
    const field = textarea.closest('.message-input');
    if (field) {
        field.style.setProperty('height', 'auto', 'important');
        field.style.setProperty('min-height', '0', 'important');
        field.querySelectorAll('.q-field__inner, .q-field__control, .q-field__control-container')
            .forEach((element) => {
                element.style.setProperty('height', 'auto', 'important');
                element.style.setProperty('min-height', '0', 'important');
            });
    }
};

document.addEventListener('input', (event) => {
    if (event.target.matches('.message-input textarea')) {
        resizeComposer(event.target);
    }
}, true);

window.addEventListener('load', () => {
    const ta = document.querySelector('.message-input textarea');
    if (ta) resizeComposer(ta);
});

document.addEventListener('paste', (event) => {
    const clipboard = event.clipboardData;
    const files = Array.from(clipboard?.files || []);
    if (!files.length) {
        Array.from(clipboard?.items || []).forEach((item) => {
            if (item.kind === 'file') {
                const file = item.getAsFile();
                if (file) files.push(file);
            }
        });
    }
    if (!files.length) return;

    const uploadInput = document.querySelector('.attachment-upload input[type="file"]');
    if (!uploadInput) return;

    event.preventDefault();
    const transfer = new DataTransfer();
    files.forEach((file, index) => {
        const extension = file.type.split('/')[1] || 'bin';
        const name = file.name || `pasted-file-${index + 1}.${extension}`;
        transfer.items.add(new File([file], name, {type: file.type}));
    });
    uploadInput.files = transfer.files;
    uploadInput.dispatchEvent(new Event('change', {bubbles: true}));
}, true);

const observeChat = () => {
    const chat = document.querySelector('.chat-scroll');
    if (!chat || chat.dataset.autoScrollReady) return;
    chat.dataset.autoScrollReady = 'true';
    new MutationObserver(() => {
        chat.scrollTop = chat.scrollHeight;
    }).observe(chat, {childList: true, subtree: true, characterData: true});
};

new MutationObserver(observeChat).observe(document.body, {
    childList: true,
    subtree: true,
});
observeChat();
</script>
""")


# ============================================================
# Helpers
# ============================================================

def add_chat_to_sidebar(title: str):
    """Rebuild the Recents list with proper text truncation (no Quasar button text)."""
    chat_list.clear()

    for chat in chats:
        with chat_list:
            # One row per chat: [title ........] [pin] [delete]
            row = ui.row().classes("chat-item")
            if chat["id"] == active_chat_id:
                row.classes(add="chat-item-active")

            with row:
                # Proper label element so the text actually renders!
                title_el = ui.label(chat["title"]).classes("chat-title")
                title_el.on("click", lambda _e=None, c=chat: load_chat(c))

                with ui.row().classes("chat-actions"):
                    ui.button(
                        icon="delete_outline",
                        on_click=lambda c=chat: delete_chat(c),
                    ).props(
                        "flat round dense aria-label='Delete chat' title='Delete chat'"
                    ).classes("chat-action")


def toggle_pin(chat: dict):
    pinned = not bool(chat.get("pinned"))
    db.set_conversation_pinned(current_user_id(), chat["id"], pinned)
    chat["pinned"] = int(pinned)
    chats.sort(key=lambda item: (not bool(item.get("pinned")), item["id"] != active_chat_id, -item["id"]))
    add_chat_to_sidebar("")


def delete_chat(chat: dict):
    global active_chat_id, current_messages
    db.delete_user_conversation(current_user_id(), chat["id"])
    chats[:] = [item for item in chats if item["id"] != chat["id"]]
    if active_chat_id == chat["id"]:
        active_chat_id = None
        current_messages = []
        render_messages()
    add_chat_to_sidebar("")
    ui.notify("Chat deleted", type="positive")


def render_messages():
    messages_container.clear()
    last_assistant_element = None

    if not current_messages:
        with messages_container:
            with ui.column().classes(
                "welcome-state w-full max-w-3xl mx-auto items-center"
            ):
                ui.label("✦").classes(
                    "text-3xl border rounded-full w-12 h-12 "
                    "flex items-center justify-center"
                )
                ui.label("How can I help you buddy?").classes(
                    "text-3xl font-semibold mt-4"
                )
                ui.label(
                    "Ask anything. Your messages are sent to your Saumya AI model."
                ).classes("small-muted")

                with ui.grid(columns=2).classes("suggestion-grid w-full mt-8 gap-3"):
                    suggestions = [
                        "Explain something to me",
                        "Write some Python code",
                        "Help me debug an error",
                        "Create a project plan",
                    ]

                    for suggestion in suggestions:
                        ui.button(
                            suggestion,
                            on_click=lambda s=suggestion: use_suggestion(s),
                        ).props("outline").classes("normal-case text-left")
        return None

    with messages_container:
        for msg in current_messages:
            if msg["role"] == "user":
                with ui.column().classes("user-message-group"):
                    attachments = msg.get("attachments", [])
                    if attachments:
                        with ui.row().classes("sent-attachments"):
                            for attachment in attachments:
                                if attachment["kind"] == "image":
                                    ui.image(attachment["data_url"]).classes(
                                        "sent-image-preview"
                                    )
                                else:
                                    with ui.row().classes("sent-file-card no-wrap"):
                                        extension = (
                                            Path(attachment["name"])
                                            .suffix.lstrip(".")[:4]
                                            or "file"
                                        )
                                        ui.label(extension).classes("sent-file-icon")
                                        ui.label(attachment["name"]).classes(
                                            "sent-file-name"
                                        )
                    ui.label(msg["content"]).classes("message-user")
            else:
                with ui.row().classes("w-full gap-3"):
                    ui.label("✦").classes(
                        "bg-black text-white rounded-full "
                        "w-8 h-8 flex items-center justify-center shrink-0"
                    )
                    last_assistant_element = ui.html(
                        format_ai_html(msg["content"])
                    ).classes(
                        "message-ai"
                    )
    return last_assistant_element


def format_ai_html(text: str) -> str:
    import html
    import re

    parts = text.split("```")

    if len(parts) == 1:
        compact = re.sub(r"\n{3,}", "\n\n", parts[0])
        escaped = html.escape(compact)
        return (
            escaped
            .replace("\n", "<br>")
            .replace("**", "<strong>", 1)
        )

    output = ""
    for index, part in enumerate(parts):
        if index % 2 == 0:
            compact = re.sub(r"\n{3,}", "\n\n", part)
            output += html.escape(compact).replace("\n", "<br>")
        else:
            lines = part.split("\n", 1)
            language = lines[0].strip() if len(lines) > 1 else ""
            code = lines[1] if len(lines) > 1 else part
            language = html.escape(language or "text")
            code = html.escape(code.strip("\n"))
            output += (
                '<div class="code-block">'
                f'<div class="code-toolbar"><span>{language}</span>'
                '<button class="code-copy" type="button" '
                'onclick="navigator.clipboard.writeText(this.parentElement'
                '.nextElementSibling.textContent).then(() => { this.textContent = '
                '&#39;Copied&#39;; setTimeout(() => this.textContent = &#39;Copy&#39;, 1200); })">'
                'Copy</button></div>'
                f'<pre><code>{code}</code></pre></div>'
            )

    return output


def extract_document_text(name: str, content: bytes) -> str:
    extension = Path(name).suffix.lower()
    if extension in TEXT_EXTENSIONS:
        return content.decode("utf-8", errors="replace")
    if extension == ".pdf":
        reader = PdfReader(io.BytesIO(content))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    if extension == ".docx":
        document = Document(io.BytesIO(content))
        return "\n".join(paragraph.text for paragraph in document.paragraphs)
    raise ValueError("Supported files: images, PDF, DOCX, TXT, MD, CSV, JSON")


def render_attachments():
    attachment_list.clear()
    with attachment_list:
        for index, attachment in enumerate(pending_attachments):
            with ui.element("div").classes("attachment-item"):
                if attachment["kind"] == "image":
                    ui.image(attachment["data_url"]).classes("attachment-image")
                else:
                    ui.label(attachment["name"]).classes("attachment-document")
                ui.button(
                    "x",
                    on_click=lambda _event=None, attachment_index=index: remove_attachment(
                        attachment_index
                    ),
                ).props("round dense unelevated").classes("attachment-remove")


def remove_attachment(index: int):
    if 0 <= index < len(pending_attachments):
        pending_attachments.pop(index)
        render_attachments()


def add_attachment(name: str, mime_type: str, content: bytes):
    if len(content) > MAX_ATTACHMENT_BYTES:
        raise ValueError(f"{name}: file must be smaller than 10 MB")

    extension = Path(name).suffix.lower()
    if extension in IMAGE_EXTENSIONS:
        pending_attachments.append({
            "name": name,
            "kind": "image",
            "data_url": (
                f"data:{mime_type or 'image/jpeg'};base64,"
                f"{base64.b64encode(content).decode('ascii')}"
            ),
        })
        return

    text = extract_document_text(name, content).strip()
    if not text:
        raise ValueError(f"{name}: no readable text was found")
    pending_attachments.append({
        "name": name,
        "kind": "document",
        "text": text[:100_000],
    })


async def handle_upload(event):
    try:
        add_attachment(event.name, event.type, event.content.read())
        render_attachments()
        ui.timer(0.4, attachment_dialog.close, once=True)
    except Exception as error:
        ui.notify(str(error), type="negative")


def use_suggestion(text: str):
    message_input.value = text
    message_input.run_method("focus")
    ui.run_javascript("setTimeout(() => resizeComposer(document.querySelector('.message-input textarea')), 100);")


def save_current_chat():
    global active_chat_id, chat_counter

    if not current_messages:
        return

    title = next(
        (
            message["content"]
            for message in current_messages
            if message["role"] == "user"
        ),
        f"Chat {chat_counter}",
    )

    if active_chat_id is not None:
        for chat in chats:
            if chat["id"] == active_chat_id:
                chat["title"] = now_title(title)
                chat["messages"] = current_messages.copy()
                db.replace_conversation(
                    current_user_id(), active_chat_id, chat["title"], chat["messages"]
                )
                return

    active_chat_id = db.replace_conversation(
        current_user_id(),
        None,
        now_title(title),
        current_messages,
    )
    chats.insert(
        0,
        {
            "id": active_chat_id,
            "title": now_title(title),
            "messages": current_messages.copy(),
        },
    )
    chat_counter += 1


def new_chat():
    global current_messages, active_chat_id, pending_attachments

    save_current_chat()

    current_messages = []
    active_chat_id = None
    pending_attachments = []
    render_attachments()
    render_messages()
    add_chat_to_sidebar("")
    ui.run_javascript("resizeComposer(document.querySelector('.message-input textarea'));")


def load_chat(chat):
    global current_messages, active_chat_id, pending_attachments
    save_current_chat()
    current_messages = db.get_conversation_messages(current_user_id(), chat["id"])
    active_chat_id = chat["id"]
    pending_attachments = []
    render_attachments()
    render_messages()
    add_chat_to_sidebar("")
    ui.run_javascript("resizeComposer(document.querySelector('.message-input textarea'));")


# ============================================================
# LLM
# ============================================================

class ModelUnavailableError(RuntimeError):
    """Raised when the backend rejects the requested model."""


async def stream_llm(messages, model=None):
    payload = {
        "messages": messages,
        "temperature": 0.2,
        "stream": True,
    }
    requested_model = selected_model if model is None else model
    if requested_model.lower() != "auto":
        payload["model"] = requested_model

    headers = {}
    api_key = config.API_KEY.strip()
    if api_key and api_key.lower() != "not-needed":
        headers["Authorization"] = f"Bearer {api_key}"

    timeout = httpx.Timeout(config.REQUEST_TIMEOUT, connect=min(config.REQUEST_TIMEOUT, 10))
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("POST", LLM_URL, json=payload, headers=headers) as response:
            if response.is_error:
                details = (await response.aread()).decode(errors="replace")[:1000]
                if "not available" in details.lower() and "model" in payload:
                    raise ModelUnavailableError(
                        f"Model \"{requested_model}\" is not available on this server."
                    )
                raise RuntimeError(
                    f"LLM API returned {response.status_code}: {details}"
                )

            if "application/json" in response.headers.get("content-type", ""):
                data = json.loads(await response.aread())
                content = (
                    data.get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                )
                if content:
                    for index in range(0, len(content), 8):
                        yield content[index:index + 8]
                        await asyncio.sleep(0.015)
                return

            async for line in response.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data_text = line.removeprefix("data:").strip()
                if data_text == "[DONE]":
                    break
                try:
                    data = json.loads(data_text)
                    choice = data["choices"][0]
                    content = choice.get("delta", {}).get("content")
                    if content is None:
                        content = choice.get("message", {}).get("content")
                except (json.JSONDecodeError, KeyError, IndexError, TypeError):
                    continue
                if content:
                    yield content


async def send_message():
    global current_messages, pending_attachments, selected_model
    global generation_task, generation_cancelled

    text = message_input.value.strip()

    if not text and not pending_attachments:
        return

    if not logged_in_user():
        nicegui_context.client.storage["pending_auth_prompt"] = text
        auth_dialog.open()
        ui.notify("Please sign in to send this message.", type="warning")
        return

    if generation_task is not None and not generation_task.done():
        generation_cancelled = True
        generation_task.cancel()
        return

    generation_task = asyncio.current_task()
    generation_cancelled = False

    if not text:
        text = "Describe and analyze the attached file."

    message_input.value = ""
    ui.run_javascript("resizeComposer(document.querySelector('.message-input textarea'));")

    attachments = pending_attachments.copy()
    pending_attachments = []
    render_attachments()

    api_content = []
    document_sections = []
    for attachment in attachments:
        if attachment["kind"] == "image":
            api_content.append({
                "type": "image_url",
                "image_url": {"url": attachment["data_url"]},
            })
        else:
            document_sections.append(
                f"--- {attachment['name']} ---\n{attachment['text']}"
            )

    prompt_text = text
    if document_sections:
        prompt_text += (
            "\n\nUse the following attached document content to answer the user:\n\n"
            + "\n\n".join(document_sections)
        )
    api_content.insert(0, {"type": "text", "text": prompt_text})
    has_images = any(
        attachment["kind"] == "image" for attachment in attachments
    )
    api_message_content = api_content if has_images else prompt_text

    display_attachments = [
        {
            "name": attachment["name"],
            "kind": attachment["kind"],
            **(
                {"data_url": attachment["data_url"]}
                if attachment["kind"] == "image"
                else {}
            ),
        }
        for attachment in attachments
    ]

    current_messages.append(
        {
            "role": "user",
            "content": text,
            "api_content": api_message_content,
            "attachments": display_attachments,
        }
    )

    assistant_message = {"role": "assistant", "content": ""}
    current_messages.append(assistant_message)
    assistant_element = render_messages()
    assistant_element.set_content(
        '<span class="thinking-label">Thinking...</span>'
    )
    assistant_element.classes(add="streaming")

    send_button._props['icon'] = 'stop'
    send_button.update()
    send_button.classes(add="stop-generation")

    try:
        api_messages = [
            {
                "role": message["role"],
                "content": api_text_content(
                    message.get("api_content", message["content"])
                ),
            }
            for message in current_messages[:-1]
        ]
        try:
            async for chunk in stream_llm(api_messages):
                assistant_message["content"] += chunk
                assistant_element.set_content(
                    format_ai_html(assistant_message["content"])
                )
                await asyncio.sleep(0)
        except ModelUnavailableError as model_error:
            ui.notify(f"{model_error} Switching to Auto.", type="warning")
            selected_model = "Auto"
            model_button.set_text("Auto  ▾")
            async for chunk in stream_llm(api_messages, model="Auto"):
                assistant_message["content"] += chunk
                assistant_element.set_content(
                    format_ai_html(assistant_message["content"])
                )
                await asyncio.sleep(0)

        if not assistant_message["content"]:
            assistant_message["content"] = "The model returned an empty response."
            assistant_element.set_content(
                format_ai_html(assistant_message["content"])
            )

    except asyncio.CancelledError:
        if not assistant_message["content"]:
            assistant_message["content"] = "Generation stopped."
        assistant_element.set_content(format_ai_html(assistant_message["content"]))
    except Exception as e:
        assistant_message["content"] = (
            "⚠️ **LLM connection error**\n\n"
            f"`{str(e)}`\n\n"
            f"Endpoint: `{LLM_URL}`"
        )
        assistant_element.set_content(format_ai_html(assistant_message["content"]))

    finally:
        assistant_element.classes(remove="streaming")
        send_button._props['icon'] = 'arrow_upward'
        send_button.update()
        send_button.classes(remove="stop-generation")
        save_current_chat()
        add_chat_to_sidebar("")
        generation_task = None


# ============================================================
# UI
# ============================================================

sidebar_collapsed = False


def toggle_sidebar():
    global sidebar_collapsed
    sidebar_collapsed = not sidebar_collapsed
    sidebar_container.set_visibility(not sidebar_collapsed)
    sidebar_open_button.set_visibility(sidebar_collapsed)


def select_model(name: str):
    global selected_model
    selected_model = name
    model_button.set_text(f"{name}  ▾")
    model_menu.close()


async def refresh_model_menu():
    model_ids = await discover_models()
    configured_options = configured_model_options()
    model_options_container.clear()
    with model_options_container:
        ui.menu_item("Auto", on_click=lambda: select_model("Auto"))
        if model_ids:
            ui.separator()
            for model_id in model_ids:
                ui.menu_item(
                    MODEL_OPTIONS.get(model_id, model_id),
                    on_click=lambda n=model_id: select_model(n),
                )
        else:
            ui.separator()
            for label, model_id in configured_options.items():
                ui.menu_item(
                    label,
                    on_click=lambda n=model_id: select_model(n),
                )

with ui.row().classes("w-full h-screen gap-0 no-wrap"):

    # ---------------- Dual Sidebar Container ----------------
    sidebar_container = ui.row().classes("desktop-sidebar h-full shrink-0 no-wrap gap-0")
    
    with sidebar_container:
        # 1. Left Thin Rail
        with ui.column().classes("sidebar-rail h-full justify-between items-center py-3 px-1.5 shrink-0"):
            with ui.column().classes("gap-2 items-center w-full"):
                ui.button(icon="home").props("flat dense").classes("rail-btn rail-btn-active")
                ui.button(icon="schedule").props("flat dense").classes("rail-btn")
                ui.button(icon="library_books").props("flat dense").classes("rail-btn")
                ui.button(icon="image").props("flat dense").classes("rail-btn")
                ui.button(icon="extension").props("flat dense").classes("rail-btn")
                ui.button(icon="more_horiz").props("flat dense").classes("rail-btn")
            
            with ui.column().classes("gap-3 items-center w-full mt-auto"):
                ui.button(icon="help_outline").props("flat dense").classes("rail-btn")
                
                profile_rail_avatar = ui.button("U").props("flat dense").classes("rail-avatar")
                with profile_rail_avatar:
                    with ui.menu().classes("w-48 shadow-lg rounded-xl overflow-hidden mt-2 ml-2"):
                        with ui.column().classes("w-full p-3 gap-0 bg-white"):
                            profile_menu_name = ui.label("Guest").classes("text-sm font-semibold text-gray-900")
                            profile_menu_email = ui.label("Sign in to save chats").classes("text-xs text-gray-500 mb-2")
                        ui.separator()
                        ui.menu_item("Settings", on_click=open_settings).classes("text-[13px] py-2")
                        auth_menu_container = ui.element("div")
                        with auth_menu_container:
                            ui.menu_item("Sign in", on_click=handle_auth_action).classes("text-[13px] py-2")

        # 2. Right Wide Panel
        sidebar_panel = ui.column().classes("sidebar-panel h-full py-3 px-3")
        with sidebar_panel:
            
            # Header row (Title + icons)
            with ui.row().classes("w-full items-center justify-between mb-3 no-wrap px-1"):
                ui.label("Saumya AI").classes("text-lg font-semibold tracking-tight text-[#222]")
                with ui.row().classes("gap-0.5 no-wrap"):
                    ui.button(icon="search", on_click=lambda: search_dialog.open()).props("flat round dense").classes("panel-header-icon")
                    ui.button(icon="menu_open", on_click=toggle_sidebar).props("flat round dense aria-label='Close menu'").classes("panel-header-icon")

            # Scrollable section content
            with ui.column().classes("w-full flex-1 sidebar-scroll gap-0"):
                ui.button("New chat", icon="edit_square", on_click=new_chat).props("flat align=left").classes("sidebar-btn")
                
                ui.label("Pinned").classes("section-label")
                ui.button("Important Notes", icon="folder_open").props("flat align=left").classes("sidebar-btn")
                
                ui.label("Projects").classes("section-label")
                ui.button("Workspace", icon="folder_open", on_click=lambda: ui.navigate.to("/builder")).props("flat align=left").classes("sidebar-btn")
                
                ui.label("Recents").classes("section-label")
                chat_list = ui.column().classes("chat-list w-full")

    # ---------------- Main Chat Canvas ----------------
    with ui.column().classes("chat-main flex-1 h-full min-w-0 gap-0"):

        sidebar_open_button = ui.button(
            icon="menu",
            on_click=toggle_sidebar,
        ).props(
            "flat round dense aria-label='Open sidebar'"
        ).classes("sidebar-open-button")
        sidebar_open_button.set_visibility(False)

        with ui.row().classes(
            "chat-header w-full items-center px-5"
        ):
            # Model selection at the top left of the chat canvas
            with ui.row().classes("ml-8 mt-1"):  # Offset slightly to allow space for the open-sidebar button
                model_button = ui.button(f"{selected_model}  ▾").props("flat").classes(
                    "font-semibold normal-case text-gray-600"
                )
                with model_button:
                    with ui.menu().classes("model-menu") as model_menu:
                        with ui.column().classes("model-menu-scroll gap-0") as model_options_container:
                            ui.menu_item("Auto", on_click=lambda: select_model("Auto"))

        messages_container = ui.column().classes(
            "chat-scroll flex-1 w-full px-4 pb-32"
        )

        render_messages()

        # ---------------- Composer ----------------
        with ui.column().classes("composer-layer"):
            with ui.column().classes("composer w-full max-w-3xl mx-auto"):
                attachment_list = ui.row().classes("attachment-list")
                
                with ui.row().classes("composer-input items-end no-wrap"):
                    ui.button(
                        icon="add",
                        on_click=lambda: attachment_dialog.open(),
                    ).props("flat round dense").classes(
                        "composer-add-btn"
                    )

                    message_input = ui.textarea(
                        placeholder="Ask Saumya AI"
                    ).props(
                        "outlined=false borderless input-class='composer-textarea'"
                    ).classes(
                        "message-input flex-1"
                    )
                    
                    with ui.row().classes("composer-right-actions items-center no-wrap"):
                        ui.button(
                            "Think",
                            icon="psychology",
                        ).props("flat dense").classes("composer-think-btn")
                        
                        ui.button(
                            icon="mic",
                        ).props("flat round dense").classes("composer-action-btn")

                        send_button = ui.button(
                            icon="arrow_upward",
                            on_click=send_message,
                        ).props("round unelevated dense").classes(
                            "send-message-button"
                        )

            ui.label(
                "Saumya AI can make mistakes. Check important information."
            ).classes(
                "small-muted text-center w-full mt-2"
            )


with ui.dialog() as attachment_dialog, ui.card().classes("w-[520px] max-w-[90vw]"):
    ui.label("Attach a file").classes("text-lg font-semibold")
    ui.label(
        "Images, PDF, DOCX and text files up to 10 MB. "
        "Image understanding requires a vision-capable model."
    ).classes("small-muted")
    ui.upload(
        label="Choose files",
        multiple=True,
        auto_upload=True,
        max_file_size=MAX_ATTACHMENT_BYTES,
        max_total_size=MAX_ATTACHMENT_TOTAL_BYTES,
        max_files=MAX_ATTACHMENT_FILES,
        on_upload=handle_upload,
        on_rejected=lambda: ui.notify("File rejected", type="negative"),
    ).props(
        'accept="image/*,.pdf,.docx,.txt,.md,.csv,.json,.py,.log"'
    ).classes("w-full attachment-upload")


# ============================================================
# Search dialog
# ============================================================

with ui.dialog() as search_dialog, ui.card().classes("w-[600px] max-w-[90vw]"):
    ui.label("Search chats").classes("text-lg font-semibold")

    search_input = ui.input(
        placeholder="Search conversations..."
    ).classes("w-full")

    search_results = ui.column().classes("w-full")

    def perform_search():
        search_results.clear()
        q = (search_input.value or "").lower()

        found = [
            c for c in chats
            if q in c["title"].lower()
        ]

        with search_results:
            if not found:
                ui.label("No conversations found.").classes("small-muted")
            else:
                for chat in found:
                    ui.button(
                        chat["title"],
                        on_click=lambda c=chat: load_chat(c),
                    ).props("flat align=left").classes(
                        "w-full normal-case"
                    )

    search_input.on("update:model-value", perform_search)


ui.timer(0.1, refresh_model_menu, once=True)
ui.timer(0.2, refresh_profile_display, once=True) # Run to populate initial profile state


# ============================================================
# Settings
# ============================================================


def save_profile():
    user = logged_in_user()
    if not user:
        auth_dialog.open()
        return
    try:
        updated = db.update_user_profile(
            user["id"], profile_name_input.value, profile_email_input.value
        )
        nicegui_context.client.storage.update(updated)
        refresh_profile_display()
        ui.notify("Profile updated", type="positive")
    except ValueError as error:
        ui.notify(str(error), type="negative")


def save_password():
    user = logged_in_user()
    if not user:
        auth_dialog.open()
        return
    try:
        db.change_password(
            user["id"], current_password_input.value, new_password_input.value
        )
        current_password_input.value = ""
        new_password_input.value = ""
        ui.notify("Password changed", type="positive")
    except ValueError as error:
        ui.notify(str(error), type="negative")

with ui.dialog() as settings_dialog, ui.card().classes("w-[500px] max-w-[90vw]"):
    ui.label("Settings").classes("text-lg font-semibold")

    ui.separator()

    ui.label("Profile").classes("font-semibold")
    profile_name_input = ui.input("Name").classes("w-full")
    profile_email_input = ui.input("Email").props("type=email").classes("w-full")
    ui.button("Save profile", on_click=save_profile).props("unelevated").classes(
        "normal-case bg-black text-white"
    )

    ui.separator()
    ui.label("Change password").classes("font-semibold")
    current_password_input = ui.input("Current password").props("type=password").classes("w-full")
    new_password_input = ui.input("New password").props("type=password").classes("w-full")
    ui.button("Change password", on_click=save_password).props("unelevated").classes(
        "normal-case bg-black text-white"
    )

    ui.switch(
        "Dark mode",
        value=False,
    )

    ui.switch(
        "Enter to send",
        value=True,
    )


auth_mode = {"value": "signin"}


def update_auth_mode(mode: str):
    auth_mode["value"] = mode
    auth_title.set_text("Create account" if mode == "signup" else "Sign in")
    auth_submit.set_text("Sign up" if mode == "signup" else "Sign in")
    auth_name.set_visibility(mode == "signup")
    auth_signin_toggle.set_visibility(mode == "signup")
    auth_signup_toggle.set_visibility(mode == "signin")
    auth_hint.set_text(
        "Use at least 8 characters for your password."
        if mode == "signup"
        else "Sign in to access your private chats."
    )


def submit_auth():
    global chats, current_messages, active_chat_id, chat_counter
    try:
        if auth_mode["value"] == "signup":
            user_id = db.create_user(
                auth_email.value, auth_password.value, auth_name.value
            )
            email = auth_email.value.strip().lower()
            display_name = auth_name.value.strip()
        else:
            user = db.authenticate_user(auth_email.value, auth_password.value)
            if not user:
                raise ValueError("Invalid email or password")
            user_id, email, display_name = user["id"], user["email"], user["display_name"]
        nicegui_context.client.storage["user_id"] = user_id
        nicegui_context.client.storage["email"] = email
        nicegui_context.client.storage["display_name"] = display_name
        chats = load_persisted_chats(user_id)
        current_messages = []
        active_chat_id = None
        chat_counter = max((chat["id"] for chat in chats), default=0) + 1
        add_chat_to_sidebar("")
        render_messages()
        auth_dialog.close()
        pending_auth_prompt = nicegui_context.client.storage.pop("pending_auth_prompt", "")
        if pending_auth_prompt:
            message_input.value = pending_auth_prompt
            message_input.run_method("focus")
        refresh_profile_display()
        ui.notify(f"Signed in as {email}", type="positive")
    except ValueError as error:
        ui.notify(str(error), type="negative")


with ui.dialog().props("persistent") as auth_dialog, ui.card().classes(
    "w-[420px] max-w-[92vw] p-7"
):
    auth_title = ui.label("Sign in").classes("text-2xl font-semibold")
    auth_hint = ui.label("Sign in to access your private chats.").classes("small-muted")
    auth_name = ui.input("Name (for signup)").props("autocomplete=name").classes("w-full")
    auth_name.set_visibility(False)
    auth_email = ui.input("Email").props("type=email autocomplete=username").classes("w-full mt-4")
    auth_password = ui.input("Password").props(
        "type=password autocomplete=current-password"
    ).classes("w-full")
    auth_submit = ui.button("Sign in", on_click=submit_auth).props("unelevated").classes(
        "w-full normal-case bg-black text-white mt-3"
    )
    with ui.row().classes("w-full justify-center gap-2 mt-2"):
        auth_signin_toggle = ui.button("Sign in", on_click=lambda: update_auth_mode("signin")).props(
            "flat dense"
        ).classes("normal-case")
        auth_signup_toggle = ui.button("Create account", on_click=lambda: update_auth_mode("signup")).props(
            "flat dense"
        ).classes("normal-case")
        auth_signin_toggle.set_visibility(False)

# ============================================================
# Run
# ============================================================

ui.run(
    title="Saumya AI",
    host="0.0.0.0",
    port=int(os.getenv("PORT", os.getenv("APP_PORT", "7860"))),
    storage_secret=os.getenv("STORAGE_SECRET", "change-this-in-production"),
    reload=False,
)