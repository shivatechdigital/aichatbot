"""Website Builder workspace - Production Level UI."""

import html
import importlib.util
import pkgutil
import re

if not hasattr(pkgutil, "find_loader"):
    pkgutil.find_loader = lambda name: importlib.util.find_spec(name)

from nicegui import ui

from app.database import db


DEFAULT_FILES = {
    "index.html": """<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>New website</title>
    <link rel="stylesheet" href="style.css" />
  </head>
  <body>
    <main class="hero">
      <p class="eyebrow">Your new project</p>
      <h1>Start designing here.</h1>
      <p>Edit the files on the left and preview the result instantly.</p>
    </main>
    <script src="script.js"></script>
  </body>
</html>
""",
    "style.css": """* { box-sizing: border-box; }
body { margin: 0; font-family: Arial, sans-serif; color: #222; }
.hero { min-height: 100vh; display: grid; place-content: center; padding: 32px; background: #f5efe8; }
.eyebrow { color: #9b5d45; text-transform: uppercase; letter-spacing: .12em; font-size: 12px; }
h1 { max-width: 620px; margin: 8px 0; font-size: clamp(42px, 8vw, 88px); line-height: .95; }
.hero p:last-child { color: #6d625a; font-size: 18px; }
""",
    "script.js": """// Add small interactions here when your design needs them.
""",
}

FILE_ICONS = {
    "index.html": ("HTML", "#e34c26"),
    "style.css": ("CSS", "#2965f1"),
    "script.js": ("JS", "#f7df1e"),
}


def _project_document(files: dict[str, str]) -> str:
    index = files.get("index.html", DEFAULT_FILES["index.html"])
    css = files.get("style.css", "")
    js = files.get("script.js", "")
    index = re.sub(
        r'<link[^>]+href=["\']style\.css["\'][^>]*>',
        f"<style>{css}</style>",
        index,
        flags=re.IGNORECASE,
    )
    index = re.sub(
        r'<script[^>]+src=["\']script\.js["\'][^>]*></script>',
        f"<script>{js}</script>",
        index,
        flags=re.IGNORECASE,
    )
    return index


def _parse_generated_files(response: str) -> dict[str, str]:
    pattern = re.compile(
        r"###\s*FILE:\s*([^\n]+)\n```[^\n]*\n(.*?)```",
        re.IGNORECASE | re.DOTALL,
    )
    files = {}
    for path, content in pattern.findall(response):
        normalized = path.strip().replace("\\", "/")
        if normalized in {"index.html", "style.css", "script.js"}:
            files[normalized] = content.strip() + "\n"
    return files


BUILDER_CSS = """
<style>
/* ============ BUILDER GLOBAL ============ */
.builder-root {
    height: 100vh;
    background: #0a0a0f;
    color: #e8e8ed;
    font-family: 'Inter', -apple-system, 'Segoe UI', sans-serif;
    overflow: hidden;
}

.builder-root * {
    box-sizing: border-box;
}

/* ============ SIDEBAR ============ */
.b-sidebar {
    width: 30% !important;
    min-width: 320px;
    max-width: 400px;
    height: 100vh;
    padding: 0 !important;
    background: #0f0f16;
    border-right: 1px solid #1e1e2a;
    display: flex;
    flex-direction: column;
    gap: 0 !important;
    flex-shrink: 0;
}

.b-sidebar-header {
    padding: 18px 20px;
    border-bottom: 1px solid #1e1e2a;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
}

.b-brand {
    display: flex;
    align-items: center;
    gap: 10px;
}

.b-brand-icon {
    width: 32px;
    height: 32px;
    border-radius: 8px;
    background: linear-gradient(135deg, #8b5cf6, #6366f1);
    display: flex;
    align-items: center;
    justify-content: center;
    color: white;
    font-size: 16px;
    box-shadow: 0 4px 12px rgba(139, 92, 246, 0.3);
}

.b-brand-text {
    color: #fff;
    font-weight: 700;
    font-size: 15px;
    letter-spacing: -0.2px;
}

.b-back-btn {
    width: 32px !important;
    height: 32px !important;
    min-width: 32px !important;
    min-height: 32px !important;
    color: #8b8b98 !important;
    background: transparent !important;
    border-radius: 8px !important;
}
.b-back-btn:hover {
    color: #fff !important;
    background: #1e1e2a !important;
}

.b-section {
    padding: 18px 20px 12px;
}

.b-sidebar-scroll {
    flex: 1 1 auto;
    min-height: 0;
    overflow-y: auto;
    padding-bottom: 18px;
}

.b-section-label {
    color: #6b6b7e;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.8px;
    margin-bottom: 10px;
}

/* Select styling */
.b-select .q-field__control {
    background: #16161f !important;
    border: 1px solid #24243a !important;
    border-radius: 10px !important;
    color: #e8e8ed !important;
    min-height: 42px !important;
    padding: 0 12px !important;
}
.b-select .q-field__control:hover {
    border-color: #33334f !important;
}
.b-select .q-field__control:before,
.b-select .q-field__control:after {
    display: none !important;
}
.b-select .q-field__native,
.b-select .q-field__input {
    color: #e8e8ed !important;
    font-size: 13px !important;
    font-weight: 500 !important;
}
.b-select .q-icon {
    color: #8b8b98 !important;
}

/* New Project Button */
.b-new-btn {
    width: 100%;
    margin-top: 10px !important;
    background: linear-gradient(135deg, #8b5cf6, #6366f1) !important;
    color: white !important;
    border-radius: 10px !important;
    min-height: 42px !important;
    font-size: 13px !important;
    font-weight: 600 !important;
    letter-spacing: 0.2px !important;
    text-transform: none !important;
    box-shadow: 0 4px 15px rgba(139, 92, 246, 0.3) !important;
    transition: all 0.2s ease !important;
}
.b-new-btn:hover {
    transform: translateY(-1px) !important;
    box-shadow: 0 6px 20px rgba(139, 92, 246, 0.45) !important;
}

/* File List */
.b-file-list {
    display: flex;
    flex-direction: column;
    gap: 4px;
    padding: 0 12px;
}

.b-file-item {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 10px 12px;
    border-radius: 8px;
    cursor: pointer;
    transition: all 0.15s ease;
    color: #b8b8c8;
    font-size: 13px;
    border: 1px solid transparent;
}

.b-file-item:hover {
    background: #16161f;
    color: #fff;
}

.b-file-item.active {
    background: #1a1a2e;
    color: #fff;
    border-color: #33335a;
}

.b-file-tag {
    width: 30px;
    height: 22px;
    border-radius: 5px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 9px;
    font-weight: 800;
    color: white;
    flex-shrink: 0;
}

/* Save button */
.b-save-btn {
    width: 100%;
    background: #16161f !important;
    color: #e8e8ed !important;
    border: 1px solid #24243a !important;
    border-radius: 10px !important;
    min-height: 40px !important;
    font-size: 12px !important;
    font-weight: 600 !important;
    text-transform: none !important;
    letter-spacing: 0.2px !important;
    margin-top: 12px !important;
    transition: all 0.2s ease !important;
}
.b-save-btn:hover {
    background: #1e1e2a !important;
    border-color: #33335a !important;
}

.b-sidebar-footer {
    margin-top: auto;
    padding: 16px 20px;
    border-top: 1px solid #1e1e2a;
}

.b-footer-info {
    color: #5b5b6e;
    font-size: 11px;
    line-height: 1.5;
}

/* ============ MAIN AREA ============ */
.b-main {
    flex: 1 1 auto;
    min-width: 0;
    height: 100vh;
    display: flex;
    flex-direction: column;
    background: #0a0a0f;
    overflow: hidden;
}

.b-toolbar {
    height: 62px;
    flex-shrink: 0;
    padding: 0 24px;
    background: #0f0f16;
    border-bottom: 1px solid #1e1e2a;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
}

.b-toggle-group {
    display: flex;
    gap: 4px;
    padding: 4px;
    border: 1px solid #24243a;
    border-radius: 10px;
    background: #16161f;
}

.b-toggle-btn {
    min-height: 32px !important;
    padding: 0 18px !important;
    border-radius: 7px !important;
    background: transparent !important;
    color: #8b8b98 !important;
    font-size: 12px !important;
    font-weight: 600 !important;
    text-transform: none !important;
    box-shadow: none !important;
}

.b-toggle-btn.active {
    background: #2a2942 !important;
    color: white !important;
}

.b-toolbar-title {
    display: flex;
    align-items: center;
    gap: 12px;
}

.b-toolbar-icon {
    width: 34px;
    height: 34px;
    border-radius: 9px;
    background: linear-gradient(135deg, #f97316, #ec4899);
    display: flex;
    align-items: center;
    justify-content: center;
    color: white;
    font-size: 16px;
}

.b-toolbar-heading {
    color: #fff;
    font-size: 15px;
    font-weight: 700;
    letter-spacing: -0.2px;
}

.b-toolbar-sub {
    color: #6b6b7e;
    font-size: 12px;
    margin-top: 2px;
}

.b-status {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 6px 14px;
    background: #16161f;
    border: 1px solid #24243a;
    border-radius: 20px;
    color: #a8a8b8;
    font-size: 12px;
    font-weight: 500;
}

.b-status-dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: #10b981;
    box-shadow: 0 0 8px #10b98188;
}

/* ============ WORKSPACE ============ */
.b-workspace {
    flex: 1 1 auto;
    min-height: 0;
    display: flex;
    gap: 0;
    overflow: hidden;
}

.b-view-container {
    flex: 1 1 auto;
    width: 100%;
    min-height: 0;
    min-width: 0;
    overflow: hidden;
    padding: 18px;
}

.b-editor-col {
    flex: 1 1 50%;
    min-width: 0;
    height: 100%;
    display: flex;
    flex-direction: column;
    background: #0a0a0f;
    border-right: 1px solid #1e1e2a;
    overflow: hidden;
}

.b-preview-col {
    flex: 1 1 50%;
    min-width: 0;
    height: 100%;
    display: flex;
    flex-direction: column;
    background: #0a0a0f;
    overflow: hidden;
}

.b-editor-wrap,
.b-preview-wrap {
    flex: 1 1 auto;
    width: 100% !important;
    min-width: 0;
    min-height: 0;
    height: 100%;
    overflow: hidden;
}

/* Panel headers */
.b-panel-head {
    height: 44px;
    flex-shrink: 0;
    padding: 0 18px;
    background: #0f0f16;
    border-bottom: 1px solid #1e1e2a;
    display: flex;
    align-items: center;
    justify-content: space-between;
}

.b-panel-title {
    display: flex;
    align-items: center;
    gap: 8px;
    color: #b8b8c8;
    font-size: 12px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.8px;
}

.b-panel-dot {
    display: inline-flex;
    gap: 5px;
}
.b-panel-dot span {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    background: #33334f;
}
.b-panel-dot span:nth-child(1) { background: #ff5f57; }
.b-panel-dot span:nth-child(2) { background: #febc2e; }
.b-panel-dot span:nth-child(3) { background: #28c840; }

.b-current-file {
    color: #6b6b7e;
    font-size: 12px;
    font-family: 'JetBrains Mono', Consolas, monospace;
}

/* Editor */
.b-editor-body {
    flex: 1 1 auto;
    min-height: 0;
    padding: 0 !important;
    display: flex;
    overflow: hidden;
    background: #0d0d15;
}

.b-editor-body .q-field {
    width: 100%;
    height: 100%;
}

.b-editor-body .q-field__control {
    background: transparent !important;
    padding: 0 !important;
    border: 0 !important;
    height: 100% !important;
    min-height: 0 !important;
    box-shadow: none !important;
}

.b-editor-body .q-field__control:before,
.b-editor-body .q-field__control:after {
    display: none !important;
}

.b-editor-body .q-field__label {
    display: none !important;
}

.b-editor-body textarea {
    width: 100% !important;
    height: 100% !important;
    padding: 18px 22px !important;
    background: #0d0d15 !important;
    color: #e8e8ed !important;
    font-family: 'JetBrains Mono', 'Cascadia Code', Consolas, monospace !important;
    font-size: 13px !important;
    line-height: 1.7 !important;
    border: 0 !important;
    outline: none !important;
    resize: none !important;
    caret-color: #8b5cf6;
}

.b-editor-body textarea::-webkit-scrollbar { width: 10px; }
.b-editor-body textarea::-webkit-scrollbar-track { background: #0d0d15; }
.b-editor-body textarea::-webkit-scrollbar-thumb {
    background: #24243a;
    border-radius: 5px;
    border: 2px solid #0d0d15;
}
.b-editor-body textarea::-webkit-scrollbar-thumb:hover { background: #33335a; }

/* AI Prompt Bar */
.b-prompt-bar {
    flex-shrink: 0;
    padding: 14px 18px;
    background: #0f0f16;
    border-top: 1px solid #1e1e2a;
    display: flex;
    flex-direction: column;
    gap: 10px;
}

.b-prompt-label {
    display: flex;
    align-items: center;
    gap: 8px;
    color: #b8b8c8;
    font-size: 12px;
    font-weight: 600;
}

.b-prompt-badge {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 3px 8px;
    background: linear-gradient(135deg, #8b5cf622, #6366f122);
    border: 1px solid #8b5cf655;
    border-radius: 6px;
    color: #a78bfa;
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}

.b-prompt-input {
    width: 100%;
}

.b-prompt-input .q-field__control {
    background: #16161f !important;
    border: 1px solid #24243a !important;
    border-radius: 12px !important;
    padding: 0 !important;
    min-height: 80px !important;
    transition: border-color 0.2s ease !important;
}

.b-prompt-input .q-field__control:hover {
    border-color: #33335a !important;
}

.b-prompt-input:focus-within .q-field__control {
    border-color: #8b5cf6 !important;
    box-shadow: 0 0 0 3px rgba(139, 92, 246, 0.12) !important;
}

.b-prompt-input .q-field__control:before,
.b-prompt-input .q-field__control:after {
    display: none !important;
}

.b-prompt-input .q-field__label {
    display: none !important;
}

.b-prompt-input textarea {
    padding: 12px 14px !important;
    background: transparent !important;
    color: #e8e8ed !important;
    font-family: 'Inter', sans-serif !important;
    font-size: 13px !important;
    line-height: 1.6 !important;
    border: 0 !important;
    outline: none !important;
    resize: none !important;
    min-height: 60px !important;
}

.b-prompt-input textarea::placeholder {
    color: #5b5b6e !important;
}

.b-generate-btn {
    align-self: flex-end;
    background: linear-gradient(135deg, #8b5cf6, #ec4899) !important;
    color: white !important;
    border-radius: 10px !important;
    padding: 0 20px !important;
    min-height: 40px !important;
    font-size: 13px !important;
    font-weight: 600 !important;
    text-transform: none !important;
    letter-spacing: 0.2px !important;
    box-shadow: 0 4px 15px rgba(139, 92, 246, 0.3) !important;
    transition: all 0.2s ease !important;
}

.b-generate-btn:hover {
    transform: translateY(-1px) !important;
    box-shadow: 0 6px 22px rgba(236, 72, 153, 0.4) !important;
}

.b-generate-btn:disabled {
    opacity: 0.6 !important;
    transform: none !important;
}

/* Preview */
.b-preview-body {
    flex: 1 1 auto;
    width: 100%;
    min-height: 0;
    min-width: 0;
    padding: 18px;
    background: #0a0a0f;
    overflow: hidden;
}

.b-preview-frame-wrap {
    width: 100%;
    height: 100%;
    min-width: 0;
    min-height: 0;
    background: white;
    border-radius: 12px;
    overflow: hidden;
    box-shadow: 0 10px 40px rgba(0, 0, 0, 0.4);
    border: 1px solid #1e1e2a;
}

.builder-preview-frame {
    display: block;
    width: 100%;
    height: 100%;
    min-width: 0;
    min-height: 0;
    border: 0;
    background: white;
}

/* Responsive */
@media (max-width: 900px) {
    .b-sidebar { width: 250px !important; min-width: 250px; }
    .b-toolbar { padding: 0 14px; }
    .b-toggle-btn { padding: 0 10px !important; }
}

/* Menu (dropdown) dark */
.q-menu {
    background: #16161f !important;
    border: 1px solid #24243a !important;
    color: #e8e8ed !important;
}
.q-menu .q-item {
    color: #e8e8ed !important;
    min-height: 38px !important;
}
.q-menu .q-item:hover {
    background: #1e1e2a !important;
}

/* Loading state */
.b-generate-btn.loading {
    background: #33335a !important;
    cursor: wait !important;
}
</style>
"""


@ui.page("/builder")
def builder_page() -> None:
    ui.add_head_html(BUILDER_CSS)
    ui.add_head_html(
        '<link rel="preconnect" href="https://fonts.googleapis.com">'
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
        '<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">'
    )

    projects = db.get_all_projects()
    if not projects:
        project_id = db.create_project()
        for path, content in DEFAULT_FILES.items():
            db.save_project_file(project_id, path, content)
        projects = db.get_all_projects()

    state = {"project_id": projects[0]["id"], "path": "index.html", "view": "preview"}
    editor = None
    preview = None
    status = None
    status_dot = None
    current_file_label = None
    file_items = {}

    def load_files() -> dict[str, str]:
        return {item["path"]: item["content"] for item in db.get_project_files(state["project_id"])}

    def update_preview() -> None:
        if preview is not None:
            preview.set_content(
                '<div class="b-preview-frame-wrap">'
                '<iframe class="builder-preview-frame" sandbox="allow-scripts" '
                f'srcdoc="{html.escape(_project_document(load_files()), quote=True)}"></iframe>'
                '</div>'
            )

    def set_status(text: str, color: str = "#10b981") -> None:
        if status is not None:
            status.clear()
            with status:
                ui.html(f'<span class="b-status-dot" style="background:{color};box-shadow:0 0 8px {color}88"></span>')
                ui.label(text)

    def set_view(mode: str) -> None:
        state["view"] = mode
        if mode == "code":
            code_button.classes(add="active")
            preview_button.classes(remove="active")
            editor_container.set_visibility(True)
            preview_container.set_visibility(False)
        else:
            preview_button.classes(add="active")
            code_button.classes(remove="active")
            editor_container.set_visibility(False)
            preview_container.set_visibility(True)
            db.save_project_file(state["project_id"], state["path"], editor.value)
            update_preview()

    def refresh_file_highlights():
        for path, item in file_items.items():
            if path == state["path"]:
                item.classes(add="active")
            else:
                item.classes(remove="active")
        if current_file_label:
            current_file_label.set_content(
                f'<span class="b-current-file">{html.escape(state["path"])}</span>'
            )

    def select_file(path: str):
        state["path"] = path
        files = load_files()
        if editor is not None:
            editor.value = files.get(path, "")
        refresh_file_highlights()
        if state["view"] != "code":
            set_view("code")

    def choose_project(event) -> None:
        state["project_id"] = int(event.value)
        state["path"] = "index.html"
        select_file("index.html")
        update_preview()

    def save_file() -> None:
        db.save_project_file(state["project_id"], state["path"], editor.value)
        set_status("Saved", "#10b981")
        update_preview()
        ui.notify(f"✓ {state['path']} saved", type="positive", position="bottom-right")

    def new_project() -> None:
        project_id = db.create_project()
        for path, content in DEFAULT_FILES.items():
            db.save_project_file(project_id, path, content)
        ui.navigate.to("/builder")

    async def generate_project() -> None:
        from app.main import stream_llm

        prompt = builder_prompt.value.strip()
        if not prompt:
            ui.notify("Describe the website you want to build.", type="warning")
            return
        generate_button.disable()
        generate_button.classes(add="loading")
        generate_button.set_text("Generating...")
        set_status("AI is generating...", "#8b5cf6")
        try:
            instruction = (
                "Create a responsive, modern, production-quality website using only "
                "index.html, style.css, and script.js. Use beautiful typography, "
                "spacing, and colors. Return only these sections, with no extra explanation:\n"
                "### FILE: index.html\n```html\n...\n```\n"
                "### FILE: style.css\n```css\n...\n```\n"
                "### FILE: script.js\n```javascript\n...\n```\n\n"
                f"User request: {prompt}"
            )
            response = ""
            async for chunk in stream_llm([{"role": "user", "content": instruction}]):
                response += chunk
            files = _parse_generated_files(response)
            if not files:
                raise ValueError("The model did not return valid website files.")
            for path, content in files.items():
                db.save_project_file(state["project_id"], path, content)
            select_file(state["path"])
            update_preview()
            set_status("Generated successfully", "#10b981")
            ui.notify("✨ Website generated!", type="positive", position="bottom-right")
        except Exception as error:
            set_status("Generation failed", "#ef4444")
            ui.notify(str(error), type="negative")
        finally:
            generate_button.enable()
            generate_button.classes(remove="loading")
            generate_button.set_text("Generate")

    # ============ UI STRUCTURE ============
    with ui.row().classes("builder-root w-full no-wrap gap-0"):

        # ---------- SIDEBAR ----------
        with ui.column().classes("b-sidebar"):

            # Header
            with ui.element("div").classes("b-sidebar-header"):
                with ui.element("div").classes("b-brand"):
                    ui.html('<div class="b-brand-icon">✦</div>')
                    ui.html('<span class="b-brand-text">Website Builder</span>')
                ui.button(icon="arrow_back", on_click=lambda: ui.navigate.to("/")) \
                    .props("flat dense").classes("b-back-btn")

            with ui.column().classes("b-sidebar-scroll"):
                # Projects Section
                with ui.element("div").classes("b-section"):
                    ui.html('<div class="b-section-label">Project</div>')
                    ui.select(
                        options={str(project["id"]): project["name"] for project in projects},
                        value=str(state["project_id"]),
                        on_change=choose_project,
                    ).props("outlined dense options-dense").classes("b-select w-full")

                    ui.button("＋  New Project", on_click=new_project) \
                        .props("unelevated no-caps").classes("b-new-btn")

                # Files Section
                with ui.element("div").classes("b-section"):
                    ui.html('<div class="b-section-label">Files</div>')
                    with ui.element("div").classes("b-file-list").style("padding:0"):
                        for path in ["index.html", "style.css", "script.js"]:
                            tag, color = FILE_ICONS[path]
                            item = ui.element("div").classes(
                                "b-file-item" + (" active" if path == "index.html" else "")
                            )
                            with item:
                                ui.html(f'<div class="b-file-tag" style="background:{color}">{tag}</div>')
                                ui.label(path)
                            item.on("click", lambda _e=None, p=path: select_file(p))
                            file_items[path] = item

                    ui.button("💾  Save File", on_click=save_file) \
                        .props("unelevated no-caps").classes("b-save-btn")

                with ui.element("div").classes("b-prompt-bar"):
                    with ui.element("div").classes("b-prompt-label"):
                        ui.html('<span class="b-prompt-badge">✨ AI</span>')
                        ui.label("Describe your website or changes")
                    builder_prompt = ui.textarea(
                        placeholder="Create a premium responsive website for a beauty parlour..."
                    ).classes("b-prompt-input")
                    generate_button = ui.button(
                        "✨  Generate", on_click=generate_project
                    ).props("unelevated no-caps").classes("b-generate-btn")

            # Footer
            with ui.element("div").classes("b-sidebar-footer"):
                ui.html('<div class="b-footer-info">Build beautiful websites<br>with AI in seconds ✨</div>')

        # ---------- MAIN AREA ----------
        with ui.column().classes("b-main gap-0"):

            # Toolbar
            with ui.element("div").classes("b-toolbar"):
                with ui.element("div").classes("b-toggle-group"):
                    code_button = ui.button("Code Editor", on_click=lambda: set_view("code")) \
                        .props("unelevated no-caps").classes("b-toggle-btn")
                    preview_button = ui.button("Live Preview", on_click=lambda: set_view("preview")) \
                        .props("unelevated no-caps").classes("b-toggle-btn active")

                status = ui.element("div").classes("b-status")
                with status:
                    ui.html('<span class="b-status-dot"></span>')
                    ui.label("Ready")

            # Workspace
            with ui.element("div").classes("b-view-container w-full"):

                # LEFT: Editor + AI Prompt
                with ui.column().classes("b-editor-wrap w-full") as editor_container:

                    # Editor Header
                    with ui.element("div").classes("b-panel-head"):
                        with ui.element("div").classes("b-panel-title"):
                            ui.html('<div class="b-panel-dot"><span></span><span></span><span></span></div>')
                            ui.label("Code Editor")
                        current_file_label = ui.html('<span class="b-current-file">index.html</span>')

                    # Editor Body
                    with ui.element("div").classes("b-editor-body"):
                        editor = ui.textarea().classes("w-full h-full")


                # RIGHT: Preview
                with ui.column().classes("b-preview-wrap w-full") as preview_container:
                    with ui.element("div").classes("b-panel-head"):
                        with ui.element("div").classes("b-panel-title"):
                            ui.html('<div class="b-panel-dot"><span></span><span></span><span></span></div>')
                            ui.label("Live Preview")
                        ui.html('<span class="b-current-file">localhost / preview</span>')

                    with ui.element("div").classes("b-preview-body"):
                        preview = ui.html().classes("w-full h-full")

    # Initial load
    select_file("index.html")
    update_preview()
    set_view("preview")