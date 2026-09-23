"""Website Builder workspace for creating and previewing small web projects."""

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


@ui.page("/builder")
def builder_page() -> None:
    projects = db.get_all_projects()
    if not projects:
        project_id = db.create_project()
        for path, content in DEFAULT_FILES.items():
            db.save_project_file(project_id, path, content)
        projects = db.get_all_projects()

    state = {"project_id": projects[0]["id"], "path": "index.html"}
    editor = None
    preview = None
    project_select = None
    file_select = None
    status = None

    def load_files() -> dict[str, str]:
        return {item["path"]: item["content"] for item in db.get_project_files(state["project_id"])}

    def update_preview() -> None:
        if preview is not None:
            preview.set_content(
                '<iframe class="builder-preview-frame" sandbox="allow-scripts" '
                f'srcdoc="{html.escape(_project_document(load_files()), quote=True)}"></iframe>'
            )

    def load_editor() -> None:
        files = load_files()
        path = file_select.value if file_select else state["path"]
        state["path"] = path
        if editor is not None:
            editor.value = files.get(path, "")
        update_preview()

    def choose_project(event) -> None:
        state["project_id"] = int(event.value)
        state["path"] = "index.html"
        file_select.value = state["path"]
        load_editor()

    def save_file() -> None:
        db.save_project_file(state["project_id"], state["path"], editor.value)
        status.set_text("Saved")
        update_preview()

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
        status.set_text("Generating files...")
        try:
            instruction = (
                "Create a responsive website using only index.html, style.css, and script.js. "
                "Return only these sections, with no extra explanation:\n"
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
            load_editor()
            status.set_text("Website generated and saved")
        except Exception as error:
            status.set_text("Generation failed")
            ui.notify(str(error), type="negative")
        finally:
            generate_button.enable()

    with ui.row().classes("builder-shell w-full h-screen gap-0 no-wrap"):
        with ui.column().classes("builder-sidebar h-full shrink-0"):
            with ui.row().classes("items-center justify-between"):
                ui.label("Website Builder").classes("text-lg font-semibold")
                ui.button(icon="arrow_back", on_click=lambda: ui.navigate.to("/")) \
                    .props("flat round dense aria-label='Back to chat'")
            ui.label("Projects").classes("small-muted")
            project_select = ui.select(
                options={str(project["id"]): project["name"] for project in projects},
                value=str(state["project_id"]),
                on_change=choose_project,
            ).classes("w-full")
            ui.button("New project", icon="add", on_click=new_project) \
                .props("flat align=left")
            ui.separator()
            ui.label("Files").classes("small-muted")
            file_select = ui.select(
                options=["index.html", "style.css", "script.js"],
                value="index.html",
                on_change=lambda _event: load_editor(),
            ).classes("w-full")
            ui.button("Save file", icon="save", on_click=save_file).props("unelevated")

        with ui.column().classes("builder-main flex-1 min-w-0 h-full"):
            with ui.row().classes("builder-toolbar w-full items-center justify-between"):
                ui.label("Create a website with AI").classes("text-xl font-semibold")
                status = ui.label("Ready").classes("small-muted")
            with ui.row().classes("builder-workspace w-full flex-1 min-h-0 no-wrap"):
                with ui.column().classes("builder-editor-panel flex-1 min-w-0 h-full"):
                    editor = ui.textarea(label="index.html").classes("builder-editor w-full flex-1")
                    builder_prompt = ui.textarea(
                        label="Describe the website or change",
                        placeholder="Create a premium responsive website for a beauty parlour...",
                    ).classes("builder-prompt w-full")
                    generate_button = ui.button(
                        "Generate website", icon="auto_awesome", on_click=generate_project
                    ).props("unelevated")
                with ui.column().classes("builder-preview-panel flex-1 min-w-0 h-full"):
                    ui.label("Live preview").classes("text-sm font-semibold")
                    preview = ui.html().classes("builder-preview flex-1 w-full")

    load_editor()