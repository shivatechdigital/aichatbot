import importlib.util
import pkgutil

if not hasattr(pkgutil, "find_loader"):
    pkgutil.find_loader = lambda name: importlib.util.find_spec(name)

from nicegui import ui, app
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

PRIMARY_MODELS = [
    "Claude Sonnet 5",
    "GPT-5.6 Sol",
    "GPT-5.6 Terra",
    "MAI-Code-1.1-Flash",
]

OTHER_MODELS = [
    "Claude Fable 5",
    "Claude Fable 5.1",
    "Claude Haiku 4.5",
    "Claude Opus 4.7",
    "Claude Opus 4.8",
    "Claude Opus 5",
    "Claude Opus 5.5",
    "Gemini 3.5 Flash",
    "Gemini 3.6 Flash",
    "Gemini 3.7 Flash",
    "Gemini 3.8 Flash",
    "GPT-5 mini",
    "GPT-5.3-Codex",
    "GPT-5.4",
    "GPT-5.4 mini",
    "GPT-5.5",
    "GPT-5.6 Luna",
    "GPT-6 Astra",
    "GPT-6 Luna",
    "GPT-6 Sol",
    "Grok 4.5",
    "Grok 4.6",
    "Grok 4.7",
]


def models_endpoint(completions_url: str) -> str:
    """Return the OpenAI-compatible model listing endpoint."""
    parsed = urlsplit(completions_url)
    path = parsed.path.rstrip("/")
    if path.endswith("/chat/completions"):
        path = path[: -len("/chat/completions")]
    return urlunsplit((parsed.scheme, parsed.netloc, f"{path}/models", "", ""))


async def discover_models() -> list[str]:
    """Read model IDs from the configured Docker/API backend."""
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
    return [
        item["id"]
        for item in models
        if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"].strip()
    ]

selected_model = "Auto" if LLM_MODEL.lower() == "auto" else LLM_MODEL

# If the browser is running on the same Docker host, this Python
# backend can talk to the LLM directly.
# For Docker -> host.docker.internal to work on Linux, run the
# container with:
#   --add-host=host.docker.internal:host-gateway

# ============================================================
# State
# ============================================================

chats = []
current_messages = []
chat_counter = 1
active_chat_id = None
pending_attachments = []

MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
MAX_ATTACHMENT_TOTAL_BYTES = 50 * 1024 * 1024
MAX_ATTACHMENT_FILES = 20
TEXT_EXTENSIONS = {".txt", ".md", ".csv", ".json", ".py", ".log"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


def now_title(text: str) -> str:
    text = " ".join(text.split())
    return text[:35] + ("..." if len(text) > 35 else "")


# ============================================================
# Styling
# ============================================================

ui.add_head_html("""
<style>
:root {
    --sidebar: #f6f5f2;
    --canvas: #fbfaf7;
    --border: #dedbd5;
    --text: #272522;
    --muted: #77736c;
    --hover: #ece9e3;
    --user: #efede8;
    --accent: #242421;
}

html, body, #app {
    height: 100%;
}

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

.sidebar {
    gap: 0 !important;
    width: 190px !important;
    padding: 10px 8px 8px !important;
    background: var(--sidebar);
    border-right: 1px solid var(--border);
}

.sidebar-brand {
    min-height: 44px;
    padding: 0 7px 7px;
}

.sidebar-brand-title {
    color: #171717;
    font-size: 18px;
    font-weight: 650;
    letter-spacing: -.2px;
}

.sidebar-brand .q-btn {
    width: 30px !important;
    min-width: 30px !important;
    min-height: 30px !important;
    padding: 0 !important;
}

.sidebar .q-btn {
    min-height: 38px;
    border: 0 !important;
    border-radius: 7px;
    color: var(--text) !important;
    box-shadow: none !important;
    font-size: 13px;
}

.sidebar .q-btn::before { box-shadow: none !important; }
.sidebar .q-btn:hover { background: var(--hover) !important; }

.sidebar-primary {
    gap: 1px !important;
    margin: 2px 0 0 !important;
}

.sidebar-primary .q-btn {
    width: 100%;
    justify-content: flex-start !important;
    min-height: 38px;
    padding: 0 8px !important;
    text-align: left;
}

.sidebar-primary .q-btn__content,
.sidebar-footer .q-btn__content {
    width: 100%;
    flex-wrap: nowrap !important;
    justify-content: flex-start !important;
    gap: 8px !important;
}

.sidebar .q-icon {
    flex: 0 0 18px;
    width: 18px;
    margin: 0 !important;
    color: #111 !important;
    font-size: 18px !important;
    font-variation-settings: "FILL" 0, "wght" 400, "GRAD" 0, "opsz" 20;
}

.recents-label {
    margin: 18px 8px 6px;
    color: #908c86;
    font-size: 12px;
    font-weight: 600;
}

.chat-list {
    flex: 1 1 auto;
    min-height: 0;
    gap: 2px !important;
    overflow-y: auto;
    scrollbar-width: thin;
    scrollbar-color: #c9c5be transparent;
}

.chat-list .q-btn {
    min-height: 36px;
    padding: 0 9px !important;
    overflow: hidden;
}

.chat-list .q-btn__content {
    display: block;
    overflow: hidden;
    text-align: left;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.chat-item-active {
    background: #e9e7e2 !important;
    font-weight: 500;
}

.sidebar-footer {
    gap: 2px !important;
    margin-top: auto !important;
    padding-top: 8px;
    background: var(--sidebar);
}

.sidebar-footer .q-separator {
    margin: 0 0 8px !important;
    background: var(--border);
}

.profile-row {
    width: 100%;
    gap: 8px !important;
    margin-top: 4px;
    padding: 7px 6px !important;
    border-radius: 8px;
    cursor: pointer;
}

.profile-row:hover { background: var(--hover); }

.sidebar-open-button {
    position: absolute !important;
    top: 12px;
    left: 12px;
    z-index: 8;
    width: 34px !important;
    height: 34px !important;
    min-width: 34px !important;
    min-height: 34px !important;
    padding: 0 !important;
    border: 1px solid var(--border) !important;
    background: rgba(251, 250, 247, .95) !important;
    color: #111 !important;
}

.chat-main {
    position: relative;
    height: 100vh;
    min-height: 0;
    overflow: hidden;
    background: var(--canvas);
}

.chat-header {
    flex: 0 0 60px;
    border-bottom: 1px solid var(--border);
}

.chat-header .q-btn {
    color: var(--text) !important;
}

.model-menu {
    width: 230px;
    padding: 6px 0;
    border: 1px solid var(--border) !important;
    border-radius: 12px !important;
}

.model-menu .q-item {
    min-height: 34px;
    padding: 4px 14px;
    font-size: 13px;
}

.model-menu-scroll {
    max-height: 240px;
    overflow-y: auto;
}

.chat-scroll {
    min-height: 0;
    padding: 24px 28px 190px !important;
    overflow-y: auto;
    scrollbar-width: thin;
    scrollbar-color: #c9c5be transparent;
}

.welcome-state {
    padding-top: clamp(70px, 14vh, 150px) !important;
}

.welcome-state > :first-child {
    border-color: var(--border) !important;
}

.welcome-state .text-3xl {
    color: #34312d;
    font-family: Georgia, "Times New Roman", serif;
    font-size: clamp(34px, 4vw, 54px) !important;
    font-weight: 400 !important;
    letter-spacing: 0;
}

.suggestion-grid .q-btn {
    min-height: 52px;
    border: 1px solid var(--border) !important;
    border-radius: 10px;
    background: rgba(255, 255, 255, .55) !important;
    color: #4c4842 !important;
    box-shadow: none !important;
}

.suggestion-grid .q-btn::before { box-shadow: none !important; }
.suggestion-grid .q-btn:hover { background: white !important; }
}

.message-user {
    background: var(--user);
    border-radius: 18px;
    padding: 10px 15px;
    max-width: 75%;
}

.user-message-group {
    max-width: 78%;
    margin-left: auto;
    gap: 7px !important;
    align-items: flex-end !important;
}

.sent-attachments {
    display: flex;
    flex-wrap: wrap;
    justify-content: flex-end;
    gap: 7px !important;
}

.sent-file-card {
    display: flex;
    align-items: center;
    gap: 9px;
    width: 210px;
    min-height: 58px;
    padding: 8px 10px;
    overflow: hidden;
    border: 1px solid var(--border);
    border-radius: 12px;
    background: white;
}

.sent-file-icon {
    display: flex;
    align-items: center;
    justify-content: center;
    flex: 0 0 36px;
    width: 36px;
    height: 36px;
    border-radius: 8px;
    background: #f0efec;
    color: #222;
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
}

.sent-file-name {
    overflow: hidden;
    color: var(--text);
    font-size: 12px;
    line-height: 1.25;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.sent-image-preview {
    width: 112px !important;
    height: 88px !important;
    overflow: hidden;
    border: 1px solid var(--border);
    border-radius: 12px;
}

.sent-image-preview img {
    width: 100% !important;
    height: 100% !important;
    object-fit: cover !important;
}

.message-ai {
    max-width: 85%;
    line-height: 1.45;
}

.builder-shell {
    background: var(--canvas);
    color: var(--text);
    overflow: hidden;
}

.builder-sidebar {
    width: 250px !important;
    padding: 18px 14px;
    gap: 12px !important;
    border-right: 1px solid var(--border);
    background: var(--sidebar);
}

.builder-main {
    min-width: 0;
    min-height: 0;
    overflow: hidden;
}
.builder-toolbar {
    flex: 0 0 60px;
    min-height: 60px;
    padding: 0 22px;
    border-bottom: 1px solid var(--border);
}

.builder-workspace {
    min-height: 0;
    overflow: hidden;
}
.builder-editor-panel,
.builder-preview-panel {
    flex: 1 1 0 !important;
    gap: 10px !important;
    min-height: 0;
    padding: 16px;
    overflow: hidden;
}

.builder-editor-panel { border-right: 1px solid var(--border); }
.builder-editor,
.builder-prompt { min-height: 0; }
.builder-editor { flex: 1 1 auto; }
.builder-prompt { flex: 0 0 150px; }
.builder-editor textarea,
.builder-prompt textarea {
    min-height: 0 !important;
    resize: none !important;
    font-family: Consolas, "Cascadia Code", monospace;
    font-size: 13px;
    line-height: 1.5;
}
.builder-editor textarea { height: 100% !important; }
.builder-prompt textarea { height: 150px !important; }
.builder-prompt textarea { font-family: "Segoe UI", Arial, sans-serif; }
.builder-preview {
    flex: 1 1 auto;
    min-height: 0;
    overflow: hidden;
    border: 1px solid var(--border);
    border-radius: 10px;
    background: white;
}
.builder-preview-frame {
    display: block;
    width: 100%;
    height: 100%;
    min-height: 0;
    border: 0;
    background: white;
}

@media (max-width: 800px) {
    .builder-shell { overflow: auto; }
    .builder-sidebar {
        width: 190px !important;
        padding: 14px 10px;
    }
    .builder-workspace { overflow: auto; }
    .builder-editor-panel,
    .builder-preview-panel {
        min-width: 48vw;
        padding: 10px;
    }
    .builder-toolbar { padding: 0 12px; }
}

.message-ai .code-block {
    width: min(100%, 760px);
    margin: 8px 0;
    overflow: hidden;
    border: 1px solid #2f3338;
    border-radius: 9px;
    background: #17191c;
    color: #e8eaed;
    line-height: 1.45;
}

.message-ai .code-toolbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    min-height: 36px;
    padding: 0 10px 0 14px;
    border-bottom: 1px solid #2f3338;
    background: #202328;
    color: #aeb4bd;
    font-family: "Segoe UI", Arial, sans-serif;
    font-size: 12px;
}

.message-ai .code-copy {
    padding: 5px 8px;
    border: 0;
    border-radius: 5px;
    background: transparent;
    color: #c6cbd2;
    cursor: pointer;
    font-size: 12px;
}

.message-ai .code-copy:hover { background: #343941; color: white; }

.message-ai .code-block pre {
    margin: 0;
    padding: 10px 14px;
    overflow-x: auto;
    white-space: pre;
}

.message-ai .code-block code {
    color: inherit;
    font-family: Consolas, "Cascadia Code", monospace;
    font-size: 13px;
}

.message-ai.streaming::after {
    display: inline-block;
    width: 7px;
    height: 1.05em;
    margin-left: 3px;
    border-radius: 2px;
    background: #555;
    vertical-align: -.15em;
    content: "";
    animation: typing-cursor 1s steps(2, start) infinite;
}

.thinking-label {
    color: var(--muted);
    font-style: italic;
}

@keyframes typing-cursor {
    50% { opacity: 0; }
}

.composer {
    gap: 6px !important;
    border: 1px solid #d9d9d9;
    border-radius: 18px;
    background: white;
    box-shadow: 0 8px 30px rgba(35, 32, 28, .08);
}

.composer:focus-within {
    border-color: #aaa;
    box-shadow: 0 2px 12px rgba(0,0,0,.08);
}

.composer-layer {
    position: absolute;
    right: 0;
    bottom: 0;
    left: 0;
    z-index: 5;
    padding: 32px 24px 12px !important;
    background: linear-gradient(to top, var(--canvas) 66%, rgba(251, 250, 247, 0));
    pointer-events: none;
}

.composer-layer > * { pointer-events: auto; }

.composer {
    min-height: 0;
    padding: 10px 12px !important;
}

.composer-input {
    width: 100%;
    min-height: 46px;
    gap: 8px !important;
}

.composer .q-field__control,
.composer .q-field__native {
    height: 46px !important;
    min-height: 46px !important;
    max-height: 46px !important;
    color: var(--text);
    font-size: 17px;
    line-height: 1.45;
}

.composer textarea.q-field__native {
    padding: 9px 0 7px !important;
    resize: none !important;
}

.composer .q-btn {
    align-self: center !important;
    width: 40px !important;
    height: 40px !important;
    min-width: 40px !important;
    min-height: 40px !important;
    max-width: 40px !important;
    max-height: 40px !important;
    padding: 0 !important;
}

.composer .bg-black { background: var(--accent) !important; }

.attachment-list {
    display: flex;
    flex-wrap: nowrap !important;
    gap: 6px !important;
    width: 100%;
    max-width: 100%;
    margin: 0;
    padding: 0 0 5px;
    overflow-x: auto;
    overflow-y: hidden;
    scrollbar-width: thin;
    scrollbar-color: #c9c5be transparent;
}

.attachment-list::-webkit-scrollbar {
    height: 5px;
}

.attachment-list::-webkit-scrollbar-thumb {
    border-radius: 999px;
    background: #c9c5be;
}

.attachment-item {
    position: relative;
    flex: 0 0 72px;
    width: 72px;
    min-width: 72px;
    max-width: 72px;
    height: 72px;
    overflow: hidden;
    border: 1px solid var(--border);
    border-radius: 12px;
    background: var(--soft, #f3f1ed);
}

.attachment-image {
    width: 100% !important;
    height: 100% !important;
}

.attachment-image img {
    width: 100% !important;
    height: 100% !important;
    object-fit: cover !important;
}

.attachment-document {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 100%;
    height: 100%;
    padding: 7px;
    color: var(--muted);
    font-size: 10px;
    line-height: 1.2;
    text-align: center;
    word-break: break-word;
}

.composer .attachment-remove {
    position: absolute !important;
    top: 3px;
    right: 3px;
    z-index: 2;
    width: 20px !important;
    height: 20px !important;
    min-width: 20px !important;
    min-height: 20px !important;
    max-width: 20px !important;
    max-height: 20px !important;
    padding: 0 !important;
    border: 1px solid rgba(255, 255, 255, .85) !important;
    background: rgba(25, 25, 25, .78) !important;
    color: white !important;
    font-size: 12px !important;
}

.chat-item {
    border-radius: 8px;
}

.chat-item:hover {
    background: var(--hover);
}

.small-muted {
    color: var(--muted);
    font-size: 12px;
}

pre {
    background: #171717;
    color: #f3f3f3;
    border-radius: 10px;
    padding: 14px;
    overflow-x: auto;
}

code {
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}

@media (max-width: 800px) {
    .desktop-sidebar {
        display: none !important;
    }

    .message-user {
        max-width: 90%;
    }

    .chat-scroll { padding: 16px 12px 170px !important; }
    .composer-layer { padding: 42px 12px 10px !important; }
    .welcome-state { padding-top: 12vh !important; }
    .suggestion-grid { grid-template-columns: 1fr !important; }
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
    chat_list.clear()

    for chat in chats:
        with chat_list:
            button = ui.button(
                chat["title"],
                on_click=lambda c=chat: load_chat(c),
            ).props("flat align=left").classes(
                "chat-item w-full normal-case justify-start"
            )
            if chat["id"] == active_chat_id:
                button.classes(add="chat-item-active")


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
                ui.label("How can I help you?").classes(
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
                    # Quasar's HTML rendering is useful for displaying
                    # formatted model output. Content is escaped first.
                    last_assistant_element = ui.html(
                        format_ai_html(msg["content"])
                    ).classes(
                        "message-ai"
                    )
    return last_assistant_element


def format_ai_html(text: str) -> str:
    import html
    import re

    # Very small Markdown-like renderer.
    # For a production app you can replace this with markdown-it.
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
                return

    active_chat_id = chat_counter
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


def load_chat(chat):
    global current_messages, active_chat_id, pending_attachments
    save_current_chat()
    current_messages = chat["messages"].copy()
    active_chat_id = chat["id"]
    pending_attachments = []
    render_attachments()
    render_messages()
    add_chat_to_sidebar("")


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

    timeout = httpx.Timeout(config.REQUEST_TIMEOUT, connect=min(config.REQUEST_TIMEOUT, 10))
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("POST", LLM_URL, json=payload) as response:
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

    text = message_input.value.strip()

    if not text and not pending_attachments:
        return

    if not text:
        text = "Describe and analyze the attached file."

    message_input.value = ""

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

    send_button.disable()

    try:
        api_messages = [
            {
                "role": message["role"],
                "content": message.get("api_content", message["content"]),
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

    except Exception as e:
        assistant_message["content"] = (
            "⚠️ **LLM connection error**\n\n"
            f"`{str(e)}`\n\n"
            f"Endpoint: `{LLM_URL}`"
        )
        assistant_element.set_content(format_ai_html(assistant_message["content"]))

    finally:
        assistant_element.classes(remove="streaming")
        send_button.enable()


# ============================================================
# UI
# ============================================================

sidebar_collapsed = False


def toggle_sidebar():
    global sidebar_collapsed
    sidebar_collapsed = not sidebar_collapsed
    sidebar_panel.set_visibility(not sidebar_collapsed)
    sidebar_open_button.set_visibility(sidebar_collapsed)


def select_model(name: str):
    global selected_model
    selected_model = name
    model_button.set_text(f"{name}  ▾")
    model_menu.close()


async def refresh_model_menu():
    model_ids = await discover_models()
    model_options_container.clear()
    with model_options_container:
        ui.menu_item("Auto", on_click=lambda: select_model("Auto"))
        if model_ids:
            ui.separator()
            for model_id in model_ids:
                ui.menu_item(
                    model_id,
                    on_click=lambda n=model_id: select_model(n),
                )
        else:
            ui.separator()
            ui.label("No models found in API").classes("small-muted px-3 py-1")

with ui.row().classes("w-full h-screen gap-0 no-wrap"):

    # ---------------- Sidebar ----------------
    sidebar_panel = ui.column().classes(
        "desktop-sidebar sidebar h-full shrink-0"
    )
    with sidebar_panel:

        with ui.row().classes(
            "sidebar-brand w-full items-center justify-between no-wrap"
        ):
            ui.label("Saumya AI").classes("sidebar-brand-title")
            ui.button(icon="side_navigation", on_click=toggle_sidebar).props(
                "flat round dense aria-label='Toggle sidebar'"
            )

        with ui.column().classes("sidebar-primary w-full"):
            ui.button(
                "New chat",
                icon="edit_square",
                on_click=new_chat,
            ).props("flat align=left").classes(
                "w-full normal-case"
            )

            ui.button(
                "Search chats",
                icon="search",
                on_click=lambda: search_dialog.open(),
            ).props("flat align=left").classes(
                "w-full normal-case"
            )

            ui.button(
                "Projects",
                icon="folder_open",
                on_click=lambda: ui.navigate.to("/builder"),
            ).props("flat align=left").classes(
                "w-full normal-case"
            )

        ui.label("Recents").classes("recents-label")

        chat_list = ui.column().classes("chat-list w-full")

        with ui.column().classes("sidebar-footer w-full"):
            ui.separator()

            ui.button(
                "Settings",
                icon="settings",
                on_click=lambda: settings_dialog.open(),
            ).props("flat align=left").classes(
                "w-full normal-case"
            )

            with ui.row().classes("profile-row items-center"):
                ui.label("P").classes(
                    "bg-black text-white rounded-full "
                    "w-8 h-8 flex items-center justify-center font-bold"
                )
                with ui.column().classes("gap-0"):
                    ui.label("Saumya").classes("text-sm font-semibold")
                    ui.label("Saumya AI").classes("small-muted")

    # ---------------- Main ----------------
    with ui.column().classes("chat-main flex-1 h-full min-w-0 gap-0"):

        sidebar_open_button = ui.button(
            icon="side_navigation",
            on_click=toggle_sidebar,
        ).props(
            "flat round dense aria-label='Open sidebar'"
        ).classes("sidebar-open-button")
        sidebar_open_button.set_visibility(False)

        with ui.row().classes(
            "chat-header w-full items-center px-5"
        ):
            model_button = ui.button(f"{selected_model}  ▾").props("flat").classes(
                "font-semibold normal-case"
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
        with ui.column().classes(
            "composer-layer"
        ):
            with ui.column().classes("composer w-full max-w-3xl mx-auto"):
                attachment_list = ui.row().classes("attachment-list")
                with ui.row().classes("composer-input items-center no-wrap"):
                    ui.button(
                        "+",
                        on_click=lambda: attachment_dialog.open(),
                    ).props("flat round").classes(
                        "text-2xl"
                    )

                    message_input = ui.textarea(
                        placeholder="Message Saumya AI..."
                    ).props(
                        "autogrow outlined=false borderless"
                    ).classes(
                        "message-input flex-1"
                    )

                    send_button = ui.button(
                        "↑",
                        on_click=send_message,
                    ).props("round unelevated").classes(
                        "send-message-button bg-black text-white"
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
    ).classes("w-full")


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


# ============================================================
# Settings
# ============================================================

with ui.dialog() as settings_dialog, ui.card().classes("w-[500px] max-w-[90vw]"):
    ui.label("Settings").classes("text-lg font-semibold")

    ui.separator()

    ui.switch(
        "Dark mode",
        value=False,
    )

    ui.switch(
        "Enter to send",
        value=True,
    )


# ============================================================
# Run
# ============================================================

ui.run(
    title="Saumya AI",
    host="0.0.0.0",
    port=int(os.getenv("PORT", os.getenv("APP_PORT", "7860"))),
    reload=False,
)
