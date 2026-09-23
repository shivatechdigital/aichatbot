"""Design Arena - Production Level UI for AI Website Generation Battle."""

import html
import importlib.util
import io
import pkgutil
import re
import asyncio
import zipfile

if not hasattr(pkgutil, "find_loader"):
    pkgutil.find_loader = lambda name: importlib.util.find_spec(name)

from nicegui import ui
from app.database import db


# ============================================================
# DEFAULTS
# ============================================================

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
      <h1>Start designing here.</h1>
      <p>Enter a prompt to generate your website.</p>
    </main>
    <script src="script.js"></script>
  </body>
</html>
""",
    "style.css": """body { margin: 0; font-family: Arial, sans-serif; }
.hero { min-height: 100vh; display: grid; place-content: center; padding: 32px; background: #f5efe8; text-align: center; }
h1 { font-size: 48px; margin: 0 0 12px 0; }
p { color: #6d625a; }
""",
    "script.js": "// JavaScript goes here\n",
}


# ============================================================
# CSS STYLES
# ============================================================

ARENA_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Playfair+Display:ital,wght@0,400;0,600;0,700;1,400&display=swap');

:root {
    --bg-main: #fcfcfb;
    --bg-sidebar: #f5f4f1;
    --bg-panel: #ffffff;
    --border-color: #e6e4df;
    --text-main: #2d2d2d;
    --text-muted: #76746f;
    --accent-teal: #a5c3b8;
    --accent-teal-hover: #8eb1a4;
    --accent-teal-dark: #6b9485;
    --brand-text: #1a1a1a;
    --font-sans: 'Inter', sans-serif;
    --font-serif: 'Playfair Display', serif;
}

* { box-sizing: border-box; }

body, html {
    margin: 0; padding: 0; height: 100vh; width: 100vw;
    background: var(--bg-main);
    color: var(--text-main);
    font-family: var(--font-sans);
    overflow: hidden;
}

.nicegui-content {
    padding: 0 !important;
    max-width: none !important;
    height: 100vh !important;
    width: 100vw !important;
}

.q-page-container { padding: 0 !important; }

/* =========== LAYOUT =========== */
.arena-root {
    display: flex;
    width: 100vw;
    height: 100vh;
    overflow: hidden;
    gap: 0 !important;
}

/* =========== SIDEBAR =========== */
.a-sidebar {
    width: 240px;
    height: 100%;
    background: var(--bg-sidebar);
    border-right: 1px solid var(--border-color);
    display: flex;
    flex-direction: column;
    flex-shrink: 0;
    gap: 0 !important;
}

.a-sidebar-header {
    height: 64px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 18px;
    flex-shrink: 0;
}

.a-logo {
    width: 32px; height: 32px; border-radius: 8px;
    background: linear-gradient(135deg, #d4d0c4, #a5c3b8);
    display: flex; align-items: center; justify-content: center;
    color: #333; font-size: 16px; font-weight: 700;
}

.a-nav {
    padding: 8px 10px;
    display: flex;
    flex-direction: column;
    gap: 2px;
    flex-shrink: 0;
}

.a-nav-btn {
    width: 100% !important;
    justify-content: flex-start !important;
    padding: 10px 12px !important;
    color: var(--text-main) !important;
    font-weight: 500 !important;
    font-size: 13.5px !important;
    border-radius: 8px !important;
    text-transform: none !important;
    min-height: 38px !important;
    background: transparent !important;
    box-shadow: none !important;
}

.a-nav-btn:hover { background: #eae8e3 !important; }

.a-nav-btn .q-btn__content {
    justify-content: flex-start !important;
    gap: 12px !important;
    flex-wrap: nowrap !important;
}

.a-nav-btn .q-icon {
    color: #555 !important;
    font-size: 18px !important;
}

.a-recent {
    flex: 1;
    overflow-y: auto;
    padding: 12px 10px;
    min-height: 0;
}

.a-recent::-webkit-scrollbar { width: 6px; }
.a-recent::-webkit-scrollbar-thumb { background: #d0cec9; border-radius: 3px; }

.a-section-title {
    font-size: 11px;
    font-weight: 700;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 1px;
    padding: 8px 12px 10px;
}

.a-recent-item {
    font-size: 13px;
    color: var(--text-muted);
    padding: 7px 12px;
    border-radius: 6px;
    cursor: pointer;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    display: flex;
    align-items: center;
    gap: 8px;
}

.a-recent-item:hover {
    background: #eae8e3;
    color: var(--text-main);
}

.a-recent-dot {
    width: 6px; height: 6px; border-radius: 50%;
    background: #a5c3b8; flex-shrink: 0;
}

.a-recent-dot.gray { background: #b8b6b0; }

.a-user {
    padding: 14px 16px;
    border-top: 1px solid var(--border-color);
    display: flex;
    align-items: center;
    gap: 10px;
    cursor: pointer;
    flex-shrink: 0;
}

.a-avatar {
    width: 30px; height: 30px; border-radius: 50%;
    background: #4f46e5; color: white;
    display: flex; align-items: center; justify-content: center;
    font-weight: 600; font-size: 13px;
}

/* =========== MAIN AREA =========== */
.a-main {
    flex: 1;
    display: flex;
    flex-direction: column;
    height: 100%;
    min-width: 0;
    gap: 0 !important;
}

.a-topnav {
    height: 64px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 28px;
    flex-shrink: 0;
    border-bottom: 1px solid transparent;
}

.a-brand-title {
    font-family: var(--font-serif);
    font-size: 22px;
    font-weight: 600;
    color: var(--brand-text);
}

.a-brand-sub {
    font-family: var(--font-sans);
    font-size: 13px;
    color: var(--text-muted);
    font-weight: 400;
    margin-left: 6px;
}

.a-top-links {
    display: flex;
    align-items: center;
    gap: 24px;
}

.a-top-link {
    color: var(--text-main) !important;
    font-size: 13.5px !important;
    font-weight: 500 !important;
    text-transform: none !important;
    background: transparent !important;
    box-shadow: none !important;
    padding: 0 !important;
    min-height: auto !important;
}

/* =========== HOME SCREEN =========== */
.a-home {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 0 24px 12vh;
    gap: 0 !important;
}

.a-hero-title {
    font-family: var(--font-serif);
    font-size: 46px;
    font-weight: 400;
    margin: 0 0 12px 0;
    color: var(--brand-text);
    text-align: center;
}

.a-hero-sub {
    color: var(--text-muted);
    font-size: 14px;
    margin-bottom: 36px;
    display: flex;
    align-items: center;
    gap: 6px;
}

.a-hero-sub-brand {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-weight: 600;
    color: var(--text-main);
}

.a-prompt-box {
    width: 100%;
    max-width: 820px;
    background: white;
    border: 2px solid #c0d3cc;
    border-radius: 18px;
    padding: 20px 22px 16px;
    box-shadow: 0 8px 30px rgba(0,0,0,0.03);
    transition: all 0.2s;
}

.a-prompt-box:focus-within {
    border-color: var(--accent-teal-dark);
    box-shadow: 0 8px 30px rgba(107, 148, 133, 0.15);
}

.a-prompt-input .q-field__control {
    background: transparent !important;
    border: none !important;
    padding: 0 !important;
    min-height: 140px !important;
}

.a-prompt-input .q-field__control:before,
.a-prompt-input .q-field__control:after { display: none !important; }

.a-prompt-input textarea {
    padding: 0 !important;
    font-size: 15.5px !important;
    line-height: 1.55 !important;
    color: var(--text-main) !important;
    font-family: var(--font-sans) !important;
    resize: none !important;
    min-height: 130px !important;
    border: 0 !important;
    outline: none !important;
    background: transparent !important;
}

.a-prompt-input textarea::placeholder {
    color: #a8a6a1 !important;
}

.a-prompt-tools {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-top: 8px;
    gap: 8px;
}

.a-tool-group {
    display: flex;
    align-items: center;
    gap: 8px;
}

.a-tool-icon-btn {
    background: transparent !important;
    color: #666 !important;
    border: 1px solid var(--border-color) !important;
    border-radius: 50% !important;
    width: 34px !important;
    height: 34px !important;
    min-width: 34px !important;
    min-height: 34px !important;
    padding: 0 !important;
}

.a-tool-chip {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 7px 12px;
    background: white;
    border: 1px solid var(--border-color);
    border-radius: 20px;
    font-size: 13px;
    color: var(--text-main);
    font-weight: 500;
    cursor: pointer;
    user-select: none;
}

.a-tool-chip:hover { background: #f9f8f5; }

.a-tool-chip-active {
    color: var(--accent-teal-dark);
    border-color: transparent;
    background: transparent;
    font-weight: 600;
}

.a-send-btn {
    background: var(--accent-teal) !important;
    color: white !important;
    border-radius: 50% !important;
    width: 42px !important;
    height: 42px !important;
    min-width: 42px !important;
    min-height: 42px !important;
    box-shadow: 0 4px 12px rgba(165, 195, 184, 0.4) !important;
    transition: all 0.2s !important;
}

.a-send-btn:hover {
    background: var(--accent-teal-hover) !important;
    transform: translateY(-2px);
    box-shadow: 0 6px 16px rgba(165, 195, 184, 0.5) !important;
}

/* =========== ARENA SCREEN =========== */
.a-arena {
    flex: 1;
    display: flex;
    overflow: hidden;
    min-height: 0;
    gap: 0 !important;
}

.a-chat-panel {
    width: 400px;
    border-right: 1px solid var(--border-color);
    display: flex;
    flex-direction: column;
    background: var(--bg-main);
    flex-shrink: 0;
    gap: 0 !important;
}

.a-play-banner {
    height: 48px;
    background: #f0f5f2;
    border-bottom: 1px solid var(--border-color);
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 10px;
    color: var(--accent-teal-dark);
    font-size: 13px;
    font-weight: 500;
    cursor: pointer;
    flex-shrink: 0;
}

.a-chat-history {
    flex: 1;
    overflow-y: auto;
    padding: 24px;
    display: flex;
    flex-direction: column;
    gap: 20px;
    min-height: 0;
}

.a-chat-history::-webkit-scrollbar { width: 6px; }
.a-chat-history::-webkit-scrollbar-thumb { background: #d0cec9; border-radius: 3px; }

.a-msg-user {
    background: #f0efec;
    padding: 14px 16px;
    border-radius: 14px;
    font-size: 14px;
    line-height: 1.55;
    color: var(--text-main);
    max-width: 100%;
    white-space: pre-wrap;
    word-wrap: break-word;
}

.a-msg-card {
    background: white;
    border: 1px solid #d5e1dc;
    border-radius: 16px;
    padding: 18px;
    box-shadow: 0 4px 20px rgba(0,0,0,0.02);
}

.a-option-tabs {
    display: flex;
    background: #f5f4f1;
    border-radius: 22px;
    padding: 4px;
    margin-bottom: 14px;
}

.a-opt-tab {
    flex: 1;
    text-align: center;
    padding: 8px 12px;
    border-radius: 18px;
    font-size: 13px;
    font-weight: 500;
    cursor: pointer;
    color: var(--text-muted);
    transition: all 0.2s;
    user-select: none;
}

.a-opt-tab.active {
    background: white;
    color: var(--text-main);
    box-shadow: 0 2px 6px rgba(0,0,0,0.06);
    font-weight: 600;
}

.a-artifact-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 6px 0;
    color: var(--accent-teal-dark);
    font-size: 13px;
    font-weight: 500;
}

.a-artifact-timer {
    color: var(--text-muted);
    font-size: 12px;
    font-weight: 400;
}

.a-agent-status-line {
    color: var(--text-muted);
    font-size: 12.5px;
    margin-top: 6px;
    display: flex;
    align-items: center;
    gap: 6px;
}

.a-using-tool {
    padding: 10px 14px;
    color: var(--text-muted);
    font-size: 13px;
    display: flex;
    align-items: center;
    gap: 8px;
    cursor: pointer;
}

.a-chat-input-wrap {
    padding: 14px;
    border-top: 1px solid var(--border-color);
    background: white;
    flex-shrink: 0;
}

.a-chat-input-box {
    border: 1px solid var(--border-color);
    border-radius: 14px;
    padding: 10px 12px;
    background: white;
}

.a-chat-input-box textarea {
    border: 0 !important;
    outline: none !important;
    resize: none !important;
    width: 100% !important;
    min-height: 32px !important;
    font-size: 13.5px !important;
    color: var(--text-main) !important;
    background: transparent !important;
    padding: 4px 0 !important;
    font-family: var(--font-sans) !important;
}

.a-chat-input-tools {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-top: 6px;
}

/* =========== PREVIEW PANEL =========== */
.a-preview-panel {
    flex: 1;
    display: flex;
    flex-direction: column;
    background: var(--bg-main);
    min-width: 0;
    gap: 0 !important;
}

.a-preview-tabs {
    display: flex;
    background: var(--bg-sidebar);
    padding: 8px 20px 0;
    gap: 4px;
    flex-shrink: 0;
    border-bottom: 1px solid var(--border-color);
}

.a-preview-tab {
    padding: 12px 20px;
    font-weight: 600;
    font-size: 14px;
    color: var(--text-muted);
    cursor: pointer;
    display: flex;
    align-items: center;
    gap: 8px;
    border-radius: 10px 10px 0 0;
    background: transparent;
    border: 1px solid transparent;
    border-bottom: none;
    transition: all 0.2s;
    user-select: none;
    margin-bottom: -1px;
}

.a-preview-tab.active {
    color: var(--brand-text);
    background: white;
    border-color: var(--border-color);
}

.a-preview-tab-icon {
    font-size: 16px;
    color: #b8b6b0;
}

.a-preview-tab.active .a-preview-tab-icon {
    color: var(--accent-teal-dark);
}

.a-preview-toolbar {
    height: 56px;
    background: white;
    border-bottom: 1px solid var(--border-color);
    display: flex;
    align-items: center;
    padding: 0 16px;
    gap: 8px;
    flex-shrink: 0;
}

.a-mode-toggle {
    display: flex;
    background: #f5f4f1;
    border-radius: 8px;
    padding: 3px;
    gap: 2px;
}

.a-mode-btn {
    width: 36px !important;
    height: 30px !important;
    min-width: 36px !important;
    min-height: 30px !important;
    border-radius: 6px !important;
    background: transparent !important;
    color: var(--text-muted) !important;
    padding: 0 !important;
    box-shadow: none !important;
}

.a-mode-btn.active {
    background: white !important;
    color: var(--text-main) !important;
    box-shadow: 0 1px 4px rgba(0,0,0,0.08) !important;
}

.a-url-bar {
    flex: 1;
    background: #f5f4f1;
    border: 1px solid var(--border-color);
    border-radius: 8px;
    padding: 8px 14px;
    font-size: 13px;
    color: var(--text-muted);
    display: flex;
    align-items: center;
    gap: 8px;
    min-height: 36px;
}

.a-url-bar .material-icons {
    font-size: 16px;
    color: #b8b6b0;
}

.a-toolbar-btn {
    background: transparent !important;
    color: var(--text-muted) !important;
    border: none !important;
    width: 34px !important;
    height: 34px !important;
    min-width: 34px !important;
    min-height: 34px !important;
    border-radius: 6px !important;
}

.a-toolbar-btn:hover { background: #f5f4f1 !important; }

.a-publish-btn {
    background: white !important;
    color: var(--text-main) !important;
    border: 1px solid var(--border-color) !important;
    border-radius: 7px !important;
    padding: 0 14px !important;
    min-height: 34px !important;
    font-size: 13px !important;
    font-weight: 600 !important;
    text-transform: none !important;
    box-shadow: none !important;
}

.a-publish-btn:hover { background: #f5f4f1 !important; }

.a-publish-btn.ready {
    background: var(--accent-teal) !important;
    color: white !important;
    border-color: var(--accent-teal) !important;
}

.a-preview-body {
    flex: 1;
    position: relative;
    overflow: hidden;
    background: white;
    min-height: 0;
}

.a-preview-iframe {
    width: 100%;
    height: 100%;
    border: none;
    display: block;
}

.a-code-view {
    width: 100%;
    height: 100%;
    background: #1e1e2e;
    overflow: auto;
    padding: 0;
    display: none;
}

.a-code-view.visible { display: block; }
.a-preview-iframe-wrap.hidden { display: none; }

.a-code-view pre {
    margin: 0;
    padding: 20px 24px;
    color: #cdd6f4;
    font-family: 'JetBrains Mono', Consolas, monospace;
    font-size: 13px;
    line-height: 1.7;
    white-space: pre-wrap;
    word-wrap: break-word;
}

.a-code-view .code-file-label {
    background: #313244;
    color: #a6e3a1;
    padding: 8px 24px;
    font-family: 'JetBrains Mono', Consolas, monospace;
    font-size: 12px;
    font-weight: 600;
    border-top: 1px solid #45475a;
    border-bottom: 1px solid #45475a;
    margin-top: 12px;
}

.a-code-view .code-file-label:first-child { margin-top: 0; border-top: none; }

/* Loading Overlay */
.a-loading {
    position: absolute;
    inset: 0;
    background: var(--bg-main);
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    z-index: 10;
    gap: 0;
}

.a-globe {
    width: 100px;
    height: 100px;
    background: #eef4f1;
    border-radius: 50%;
    border: 2px solid var(--accent-teal);
    display: flex;
    align-items: center;
    justify-content: center;
    margin-bottom: 24px;
}

.a-globe .material-icons {
    font-size: 48px;
    color: var(--accent-teal-dark);
}

.a-load-title {
    font-family: var(--font-serif);
    font-size: 28px;
    color: var(--brand-text);
    margin-bottom: 8px;
    font-weight: 600;
}

.a-load-sub {
    font-size: 14px;
    color: var(--text-muted);
    margin-bottom: 20px;
}

.a-dots {
    display: flex;
    gap: 8px;
}

.a-dot {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    background: #c0d3cc;
    animation: a-bounce 1.4s infinite ease-in-out both;
}

.a-dot:nth-child(1) { animation-delay: -0.32s; }
.a-dot:nth-child(2) { animation-delay: -0.16s; }

@keyframes a-bounce {
    0%, 80%, 100% { transform: scale(0.6); opacity: 0.4; }
    40% { transform: scale(1); opacity: 1; background: var(--accent-teal-dark); }
}

/* Toast Notification */
.a-toast {
    position: fixed;
    bottom: 24px;
    right: 24px;
    background: white;
    border: 1px solid var(--border-color);
    border-radius: 12px;
    padding: 14px 18px;
    display: flex;
    align-items: center;
    gap: 12px;
    box-shadow: 0 8px 24px rgba(0,0,0,0.08);
    z-index: 1000;
    max-width: 320px;
}

.a-toast-check {
    width: 24px; height: 24px; border-radius: 6px;
    background: #d1e7d0; color: #2d6f2d;
    display: flex; align-items: center; justify-content: center;
    flex-shrink: 0;
}

.a-toast-title { font-weight: 600; font-size: 13px; color: var(--text-main); }
.a-toast-sub { font-size: 12px; color: var(--text-muted); margin-top: 2px; }

/* Responsive */
@media (max-width: 900px) {
    .a-sidebar { width: 200px; }
    .a-chat-panel { width: 340px; }
    .a-hero-title { font-size: 32px; }
}
</style>
"""


# ============================================================
# HELPERS
# ============================================================

def _project_document(files: dict[str, str]) -> str:
    """Combine HTML, CSS, JS into a single self-contained doc."""
    react_code = files.get("src/App.jsx") or files.get("src/App.js")
    if react_code:
        css = files.get("src/styles.css", "") + files.get("src/App.css", "")
        react_code = re.sub(r"^\s*import\s+.*?;\s*$", "", react_code, flags=re.MULTILINE)
        react_code = re.sub(r"\bexport\s+default\s+", "", react_code)
        return f"""<!doctype html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<script crossorigin src="https://unpkg.com/react@18/umd/react.development.js"></script>
<script crossorigin src="https://unpkg.com/react-dom@18/umd/react-dom.development.js"></script>
<script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
<style>{css}</style></head><body><div id="root"></div>
<script type="text/babel">{react_code}
const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(<App />);
</script></body></html>"""
    index = files.get("index.html", "<h1>Waiting for content...</h1>")
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
    """Extract file blocks from LLM response."""
    pattern = re.compile(
        r"###\s*FILE:\s*([^\n]+)\n```[^\n]*\n(.*?)```",
        re.IGNORECASE | re.DOTALL,
    )
    files = {}
    for path, content in pattern.findall(response):
        normalized = path.strip().replace("\\", "/")
        if normalized in {
            "index.html", "style.css", "script.js", "package.json",
            "src/App.jsx", "src/App.js", "src/styles.css", "src/App.css",
        }:
            files[normalized] = content.strip() + "\n"
    return files


def _project_title(prompt: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", prompt)
    return " ".join(words[:6]).strip().title() or "Website Project"


def _build_project_zip(files: dict[str, str]) -> bytes:
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as project_zip:
        for path, content in sorted(files.items()):
            project_zip.writestr(path, content)
    return archive.getvalue()


def _publication_slug(project_id: int, name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "website"
    return f"{base}-{project_id}"


@ui.page("/published/{slug}")
def published_page(slug: str) -> None:
    publication = db.get_publication_by_slug(slug)
    if not publication:
        ui.label("Published website not found").classes("text-h4 q-pa-xl")
        return
    files = {
        item["path"]: item["content"]
        for item in db.get_project_files(publication["project_id"])
    }
    ui.add_head_html("<style>html,body,#q-app{margin:0;width:100%;height:100%;overflow:hidden}</style>")
    ui.html(
        '<iframe title="Published website" style="border:0;width:100%;height:100vh" '
        f'srcdoc="{html.escape(_project_document(files), quote=True)}"></iframe>'
    )


def _render_code_view(files: dict[str, str]) -> str:
    """Render files as HTML for the code view."""
    parts = []
    for filename in ["index.html", "style.css", "script.js"]:
        content = files.get(filename, "")
        if content:
            escaped = html.escape(content)
            parts.append(
                f'<div class="code-file-label">📄 {filename}</div>'
                f'<pre><code>{escaped}</code></pre>'
            )
    return "".join(parts) if parts else '<pre>Waiting for code generation...</pre>'


# ============================================================
# PAGE
# ============================================================

@ui.page("/builder")
def builder_page() -> None:
    ui.add_head_html(ARENA_CSS)

    # Load or create initial project
    projects = db.get_all_projects()
    if not projects:
        pid = db.create_project()
        for p, c in DEFAULT_FILES.items():
            db.save_project_file(pid, p, c)
        projects = db.get_all_projects()

    # ========================================
    # STATE
    # ========================================
    state = {
        "view": "home",              # 'home' or 'arena'
        "status": "idle",            # 'idle', 'generating', 'ready'
        "active_option": "A",        # 'A' or 'B'
        "display_mode": "preview",   # 'preview' or 'code'
        "prompt": "",
        "code_A": {},
        "code_B": {},
        "voted": False,
        "published_url_A": "",
        "published_url_B": "",
        "project_id_A": None,
        "project_id_B": None,
    }

    # UI element refs (populated during build)
    refs = {}

    # ========================================
    # LOGIC
    # ========================================

    def update_viewer():
        """Update iframe & code view based on active option."""
        active_code = state["code_A"] if state["active_option"] == "A" else state["code_B"]

        # Iframe
        if refs.get("preview_iframe"):
            doc_html = html.escape(_project_document(active_code), quote=True)
            refs["preview_iframe"].set_content(
                f'<iframe class="a-preview-iframe" sandbox="allow-scripts" srcdoc="{doc_html}"></iframe>'
            )

        # Code view
        if refs.get("code_view"):
            refs["code_view"].set_content(_render_code_view(active_code))

        # URL Bar
        if refs.get("url_bar"):
            if state["voted"]:
                url = state["published_url_A"] if state["active_option"] == "A" else state["published_url_B"]
                refs["url_bar"].clear()
                with refs["url_bar"]:
                    ui.html('<i class="material-icons">public</i>')
                    ui.label(url if url else f"Click Publish for Option {state['active_option']}")
            else:
                refs["url_bar"].clear()
                with refs["url_bar"]:
                    ui.html('<i class="material-icons">public</i>')
                    ui.label("Vote to get link")

    def toggle_option(opt: str):
        state["active_option"] = opt
        # Update left panel tabs
        if refs.get("opt_A_tab"):
            refs["opt_A_tab"].classes(add="active" if opt == "A" else "", remove="active" if opt == "B" else "")
        if refs.get("opt_B_tab"):
            refs["opt_B_tab"].classes(add="active" if opt == "B" else "", remove="active" if opt == "A" else "")
        # Update right panel tabs
        if refs.get("preview_tab_A"):
            refs["preview_tab_A"].classes(add="active" if opt == "A" else "", remove="active" if opt == "B" else "")
        if refs.get("preview_tab_B"):
            refs["preview_tab_B"].classes(add="active" if opt == "B" else "", remove="active" if opt == "A" else "")
        update_viewer()

    def set_display_mode(mode: str):
        state["display_mode"] = mode
        if mode == "code":
            refs["code_view"].classes(add="visible")
            refs["preview_iframe"].classes(add="hidden")
            refs["mode_btn_preview"].classes(remove="active")
            refs["mode_btn_code"].classes(add="active")
        else:
            refs["code_view"].classes(remove="visible")
            refs["preview_iframe"].classes(remove="hidden")
            refs["mode_btn_preview"].classes(add="active")
            refs["mode_btn_code"].classes(remove="active")

    async def generate_option(option_name: str, personality: str):
        """Generate one version by calling the LLM."""
        try:
            from app.main import stream_llm
        except Exception:
            # Fallback if stream_llm is not available
            await asyncio.sleep(2)
            fallback = {
                "index.html": f'<!DOCTYPE html><html><head><title>Option {option_name}</title></head>'
                              f'<body><h1>Option {option_name}</h1><p>{personality}</p><p>Prompt: {state["prompt"]}</p></body></html>',
                "style.css": "body { font-family: sans-serif; padding: 40px; background: #f5efe8; }",
                "script.js": "console.log('Option " + option_name + "');"
            }
            if option_name == "A":
                state["code_A"] = fallback
            else:
                state["code_B"] = fallback
            return

        instruction = (
            f"You are a Senior Web Developer. Create a high-quality, production-ready single-page website. "
            f"Design style: {personality}. "
            "Return ONLY these three code blocks in this exact format, no other text:\n\n"
            "### FILE: index.html\n```html\n<complete HTML>\n```\n\n"
            "### FILE: style.css\n```css\n<complete CSS>\n```\n\n"
            "### FILE: script.js\n```javascript\n<JS code>\n```\n\n"
            f"User request:\n{state['prompt']}"
        )

        try:
            response = ""
            async for chunk in stream_llm([{"role": "user", "content": instruction}]):
                response += chunk

            files = _parse_generated_files(response)
            if not files or not files.get("index.html"):
                raise ValueError("No valid HTML generated")

            if option_name == "A":
                state["code_A"] = files
            else:
                state["code_B"] = files
        except Exception as e:
            fallback = {
                "index.html": f'<!DOCTYPE html><html><body><h1>Generation Error</h1><p>{html.escape(str(e))}</p></body></html>',
                "style.css": "body { padding: 40px; font-family: sans-serif; }",
                "script.js": ""
            }
            if option_name == "A":
                state["code_A"] = fallback
            else:
                state["code_B"] = fallback

    async def submit_prompt():
        text = refs["prompt_input"].value if refs.get("prompt_input") else ""
        if not text or not text.strip():
            ui.notify("Please enter a prompt.", type="warning")
            return

        state["prompt"] = text.strip()
        state["status"] = "generating"
        state["voted"] = False
        state["active_option"] = "A"

        # Swap views
        refs["home_container"].set_visibility(False)
        refs["arena_container"].set_visibility(True)
        refs["user_msg"].set_text(state["prompt"])
        refs["loading_overlay"].set_visibility(True)

        # Reset toggles
        toggle_option("A")
        set_display_mode("preview")

        # Generate both options in parallel
        await asyncio.gather(
            generate_option("A", "Clean, minimalist, modern, professional with subtle animations"),
            generate_option("B", "Bold, creative, vibrant colors, playful with strong visuals"),
        )

        state["status"] = "ready"
        refs["loading_overlay"].set_visibility(False)
        update_viewer()

        ui.notify("✨ Both designs ready! Vote for your favorite.", type="positive", position="bottom-right")

    def cast_vote():
        """Mark that the user has 'voted' - unlocks publish URL."""
        if state["status"] != "ready":
            ui.notify("Wait for generation to finish", type="warning")
            return
        state["voted"] = True
        ui.notify(f"✓ Voted for Option {state['active_option']}!", type="positive")
        update_viewer()

    def publish_site():
        if state["status"] != "ready":
            ui.notify("Wait for generation to complete", type="warning")
            return

        opt = state["active_option"]
        code = state["code_A"] if opt == "A" else state["code_B"]

        # Save the selected option and create a stable local publication.
        project_name = f"Arena {opt}: {state['prompt'][:30]}"
        pid = db.create_project(name=project_name)
        for p, c in code.items():
            db.save_project_file(pid, p, c)

        slug = _publication_slug(pid, project_name)
        db.publish_project(pid, slug)
        url = f"/published/{slug}"

        if opt == "A":
            state["published_url_A"] = url
            state["project_id_A"] = pid
        else:
            state["published_url_B"] = url
            state["project_id_B"] = pid

        state["voted"] = True
        update_viewer()

        ui.notify(f"🚀 Option {opt} Published! {url}", type="positive", position="top")

    def go_home():
        state["view"] = "home"
        state["status"] = "idle"
        state["prompt"] = ""
        state["code_A"] = {}
        state["code_B"] = {}
        state["voted"] = False
        state["published_url_A"] = ""
        state["published_url_B"] = ""
        if refs.get("prompt_input"):
            refs["prompt_input"].value = ""
        refs["home_container"].set_visibility(True)
        refs["arena_container"].set_visibility(False)

    def refresh_preview():
        update_viewer()
        ui.notify("Preview refreshed", type="info", position="bottom-right")

    def copy_url():
        opt = state["active_option"]
        url = state["published_url_A"] if opt == "A" else state["published_url_B"]
        if url:
            ui.run_javascript(f'navigator.clipboard.writeText("{url}")')
            ui.notify("URL copied!", type="positive")
        else:
            ui.notify("Publish first to get URL", type="warning")

    # ============================================================
    # LAYOUT
    # ============================================================

    with ui.element("div").classes("arena-root"):

        # --- LEFT SIDEBAR ---
        with ui.element("div").classes("a-sidebar"):
            # Header
            with ui.element("div").classes("a-sidebar-header"):
                ui.html('<div class="a-logo">✦</div>')
                ui.button(icon="view_sidebar").props("flat dense round").classes("text-grey-7")

            # Nav
            with ui.element("div").classes("a-nav"):
                ui.button("New project", icon="edit_square", on_click=go_home).props("flat no-caps").classes("a-nav-btn")
                ui.button("Search", icon="search").props("flat no-caps").classes("a-nav-btn")
                ui.button("My Projects", icon="folder_open").props("flat no-caps").classes("a-nav-btn")
                ui.button("Leaderboards", icon="leaderboard").props("flat no-caps").classes("a-nav-btn")
                ui.button("Models", icon="view_in_ar").props("flat no-caps").classes("a-nav-btn")
                ui.button("About", icon="info_outline").props("flat no-caps").classes("a-nav-btn")

            # Recent
            with ui.element("div").classes("a-recent"):
                ui.label("RECENT DESIGNS").classes("a-section-title")
                for name, cls in [
                    ("React Real Estate Plat...", ""),
                    ("Responsive Parlour W...", ""),
                    ("Checkinn Homes Web E...", "gray"),
                    ("Affordable OTT Subscri...", "gray"),
                    ("Futuristic Corporate Vid...", "gray"),
                ]:
                    with ui.element("div").classes("a-recent-item"):
                        ui.html(f'<div class="a-recent-dot {cls}"></div>')
                        ui.label(name)

            # User
            with ui.element("div").classes("a-user"):
                ui.html('<div class="a-avatar">P</div>')
                ui.label("Prashant").classes("font-medium text-sm")
                ui.space()
                ui.icon("unfold_more").classes("text-grey-6 text-sm")

        # --- MAIN AREA ---
        with ui.element("div").classes("a-main"):

            # Top Nav
            with ui.element("div").classes("a-topnav"):
                with ui.row().classes("items-center gap-0"):
                    ui.label("Design Arena").classes("a-brand-title")
                    ui.html('<span class="a-brand-sub">by ✦ Saumya Intelligence</span>')

                with ui.element("div").classes("a-top-links"):
                    ui.button("Leaderboards").props("flat no-caps").classes("a-top-link")
                    ui.button("Models").props("flat no-caps").classes("a-top-link")
                    ui.button("EN", icon="language").props("flat no-caps").classes("a-top-link")

            # ============ HOME SCREEN ============
            refs["home_container"] = ui.element("div").classes("a-home")
            with refs["home_container"]:
                ui.label("What are you creating today?").classes("a-hero-title")
                with ui.element("div").classes("a-hero-sub"):
                    ui.label("by")
                    ui.html('<span class="a-hero-sub-brand">✦ Saumya Intelligence</span>')
                    ui.label("• 6.7M+ users")

                with ui.element("div").classes("a-prompt-box"):
                    refs["prompt_input"] = ui.textarea(
                        placeholder="Describe the website you want to build...\n\ne.g. Create a responsive React parlour website with:\n- Separate pages for About, Services, Gallery\n- Admin panel for content management\n- Modern, production-quality design"
                    ).props("borderless").classes("a-prompt-input w-full")

                    with ui.element("div").classes("a-prompt-tools"):
                        with ui.element("div").classes("a-tool-group"):
                            ui.button(icon="attach_file").props("flat dense").classes("a-tool-icon-btn")
                            ui.button(icon="cloud_upload").props("flat dense").classes("a-tool-icon-btn")
                            with ui.element("div").classes("a-tool-chip"):
                                ui.html('<i class="material-icons" style="font-size:15px;">bolt</i>')
                                ui.label("FAST")
                                ui.html('<i class="material-icons" style="font-size:14px;">expand_more</i>')
                            with ui.element("div").classes("a-tool-chip a-tool-chip-active"):
                                ui.html('<i class="material-icons" style="font-size:15px;">web</i>')
                                ui.label("Website")

                        ui.button(icon="arrow_upward", on_click=submit_prompt).props("unelevated round").classes("a-send-btn")

            # ============ ARENA SCREEN ============
            refs["arena_container"] = ui.element("div").classes("a-arena")
            refs["arena_container"].set_visibility(False)

            with refs["arena_container"]:

                # LEFT CHAT PANEL
                with ui.element("div").classes("a-chat-panel"):
                    with ui.element("div").classes("a-play-banner"):
                        ui.html('<i class="material-icons" style="font-size:18px;">sports_esports</i>')
                        ui.label("Play while you wait")

                    with ui.element("div").classes("a-chat-history"):
                        refs["user_msg"] = ui.label("").classes("a-msg-user")

                        with ui.element("div").classes("a-msg-card"):
                            with ui.element("div").classes("a-option-tabs"):
                                refs["opt_A_tab"] = ui.element("div").classes("a-opt-tab active")
                                refs["opt_A_tab"].on("click", lambda: toggle_option("A"))
                                with refs["opt_A_tab"]:
                                    ui.label("Option A")

                                refs["opt_B_tab"] = ui.element("div").classes("a-opt-tab")
                                refs["opt_B_tab"].on("click", lambda: toggle_option("B"))
                                with refs["opt_B_tab"]:
                                    ui.label("Option B")

                            with ui.element("div").classes("a-artifact-row"):
                                with ui.row().classes("items-center gap-2 no-wrap"):
                                    ui.html('<i class="material-icons" style="font-size:18px;">web</i>')
                                    ui.label("Web Apps artifact")
                                ui.label("6m 18.0s").classes("a-artifact-timer")

                            with ui.element("div").classes("a-agent-status-line"):
                                ui.label("Bringing your vision to life...")

                        with ui.element("div").classes("a-using-tool"):
                            ui.label("Using batch_create_files")
                            ui.icon("expand_more").classes("text-grey-6 text-sm")

                    # Chat input at bottom
                    with ui.element("div").classes("a-chat-input-wrap"):
                        with ui.element("div").classes("a-chat-input-box"):
                            ui.textarea(placeholder="Vote on the design above first...").props("borderless").classes("w-full")
                            with ui.element("div").classes("a-chat-input-tools"):
                                with ui.row().classes("gap-1 items-center"):
                                    ui.button(icon="attach_file").props("flat dense round").classes("a-tool-icon-btn").style("width:28px; height:28px; min-width:28px; min-height:28px;")
                                    ui.button(icon="cloud_upload").props("flat dense round").classes("a-tool-icon-btn").style("width:28px; height:28px; min-width:28px; min-height:28px;")
                                ui.button(icon="arrow_upward", on_click=cast_vote).props("unelevated round dense").classes("a-send-btn").style("width:32px; height:32px; min-width:32px; min-height:32px;")

                # RIGHT PREVIEW PANEL
                with ui.element("div").classes("a-preview-panel"):

                    # Tabs
                    with ui.element("div").classes("a-preview-tabs"):
                        refs["preview_tab_A"] = ui.element("div").classes("a-preview-tab active")
                        refs["preview_tab_A"].on("click", lambda: toggle_option("A"))
                        with refs["preview_tab_A"]:
                            ui.html('<i class="material-icons a-preview-tab-icon">emoji_events</i>')
                            ui.label("Option A")

                        refs["preview_tab_B"] = ui.element("div").classes("a-preview-tab")
                        refs["preview_tab_B"].on("click", lambda: toggle_option("B"))
                        with refs["preview_tab_B"]:
                            ui.html('<i class="material-icons a-preview-tab-icon">emoji_events</i>')
                            ui.label("Option B")

                    # Toolbar
                    with ui.element("div").classes("a-preview-toolbar"):
                        with ui.element("div").classes("a-mode-toggle"):
                            refs["mode_btn_preview"] = ui.button(icon="visibility", on_click=lambda: set_display_mode("preview")).props("flat").classes("a-mode-btn active")
                            refs["mode_btn_code"] = ui.button(icon="code", on_click=lambda: set_display_mode("code")).props("flat").classes("a-mode-btn")

                        refs["url_bar"] = ui.element("div").classes("a-url-bar")
                        with refs["url_bar"]:
                            ui.html('<i class="material-icons">public</i>')
                            ui.label("Vote to get link")

                        ui.button(icon="content_copy", on_click=copy_url).props("flat dense").classes("a-toolbar-btn")
                        ui.button(icon="open_in_new").props("flat dense").classes("a-toolbar-btn")
                        ui.button(icon="refresh", on_click=refresh_preview).props("flat dense").classes("a-toolbar-btn")
                        ui.button(icon="open_in_full").props("flat dense").classes("a-toolbar-btn")
                        ui.button("Publish", icon="lock_open", on_click=publish_site).props("unelevated no-caps").classes("a-publish-btn")

                    # Preview Body
                    with ui.element("div").classes("a-preview-body"):

                        # Loading state
                        refs["loading_overlay"] = ui.element("div").classes("a-loading")
                        refs["loading_overlay"].set_visibility(False)
                        with refs["loading_overlay"]:
                            with ui.element("div").classes("a-globe"):
                                ui.html('<i class="material-icons">language</i>')
                            ui.label("Building Preview").classes("a-load-title")
                            ui.label("The agent is working on your app...").classes("a-load-sub")
                            with ui.element("div").classes("a-dots"):
                                ui.html('<div class="a-dot"></div><div class="a-dot"></div><div class="a-dot"></div>')

                        # Iframe
                        refs["preview_iframe"] = ui.html('<div style="padding:80px; text-align:center; color:#999;">Submit a prompt to see your website here</div>').classes("a-preview-iframe-wrap w-full h-full")

                        # Code view
                        refs["code_view"] = ui.html('').classes("a-code-view")