"""Design Arena – Production Website Builder UI
Dual-option AI generation battle with live preview, code view,
publish-to-URL flow, and ZIP download.

Integrates with app.database.db  and  app.main.stream_llm .
"""

from __future__ import annotations

import asyncio
import base64
import html as html_mod
import importlib.util
import io
import json
import pkgutil
import re
import zipfile
from pathlib import Path

if not hasattr(pkgutil, "find_loader"):
    pkgutil.find_loader = lambda name: importlib.util.find_spec(name)

import uvicorn
from nicegui import app, ui

from app.database import db

# ════════════════════════════════════════════════════════════════════
#  DEFAULTS
# ════════════════════════════════════════════════════════════════════

DEFAULT_FILES: dict[str, str] = {
    "index.html": """<!doctype html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1.0"/>
<title>New website</title>
<link rel="stylesheet" href="style.css"/></head>
<body>
<main class="hero"><h1>Start designing here.</h1><p>Enter a prompt to generate your website.</p></main>
<script src="script.js"></script>
</body></html>""",
    "style.css": """body{margin:0;font-family:Arial,sans-serif}
.hero{min-height:100vh;display:grid;place-content:center;padding:32px;background:#f5efe8;text-align:center}
h1{font-size:48px;margin:0 0 12px}p{color:#6d625a}""",
    "script.js": "// JavaScript goes here\n",
}

# ════════════════════════════════════════════════════════════════════
#  STYLESHEET  (~Design Arena palette & layout)
# ════════════════════════════════════════════════════════════════════

ARENA_CSS = r"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Playfair+Display:ital,wght@0,400;0,600;0,700;1,400&display=swap');
@import url('https://fonts.googleapis.com/icon?family=Material+Icons');

:root{
  --bg-main:#fcfcfb;--bg-sidebar:#f5f4f1;--bg-panel:#fff;
  --border:#e6e4df;--text-main:#2d2d2d;--text-muted:#76746f;
  --accent-teal:#a5c3b8;--accent-hover:#8eb1a4;--accent-dark:#6b9485;
  --brand:#1a1a1a;--sans:'Inter',serif;--serif:'Playfair Display',serif;
}
*,*::before,*::after{box-sizing:border-box}
html,body{margin:0;padding:0;height:100%;width:100%}
body{background:var(--bg-main);color:var(--text-main);font-family:var(--sans);overflow:hidden}
.nicegui-content,.q-page{padding:0!important;max-width:none!important;height:100%!important;width:100%!important}

/* ── Root layout ── */
.a-root{display:flex;width:100vw;height:100vh;overflow:hidden}

/* ── Sidebar ── */
.a-sb{width:240px;height:100%;background:var(--bg-sidebar);border-right:1px solid var(--border);
      display:flex;flex-direction:column;flex-shrink:0}
.a-sb-head{height:64px;display:flex;align-items:center;justify-content:space-between;padding:0 18px}
.a-logo{width:32px;height:32px;border-radius:8px;background:linear-gradient(135deg,#d4d0c4,var(--accent-teal));
        display:flex;align-items:center;justify-content:center;color:#333;font-weight:700;font-size:16px}
.a-nav{padding:8px 10px;display:flex;flex-direction:column;gap:2px}
.a-nav-btn{width:100%;justify-content:flex-start!important;padding:10px 12px!important;
           color:var(--text-main)!important;font-weight:500!important;font-size:13.5px!important;
           border-radius:8px!important;text-transform:none!important;min-height:38px!important;
           background:transparent!important;box-shadow:none!important}
.a-nav-btn:hover{background:#eae8e3!important}
.a-recent{flex:1;overflow-y:auto;padding:12px 10px;min-height:0}
.a-recent::-webkit-scrollbar{width:6px}.a-recent::-webkit-scrollbar-thumb{background:#d0cec9;border-radius:3px}
.a-sect-title{font-size:11px;font-weight:700;color:var(--text-muted);text-transform:uppercase;
               letter-spacing:1px;padding:8px 12px 10px}
.a-rec-item{font-size:13px;color:var(--text-muted);padding:7px 12px;border-radius:6px;cursor:pointer;
            white-space:nowrap;overflow:hidden;text-overflow:ellipsis;display:flex;align-items:center;gap:8px}
.a-rec-item:hover{background:#eae8e3;color:var(--text-main)}
.a-dot{width:6px;height:6px;border-radius:50%;background:var(--accent-teal);flex-shrink:0}
.a-user{padding:14px 16px;border-top:1px solid var(--border);display:flex;align-items:center;gap:10px;cursor:pointer}
.a-avatar{width:30px;height:30px;border-radius:50%;background:#4f46e5;color:#fff;
          display:flex;align-items:center;justify-content:center;font-weight:600;font-size:13px}

/* ── Main ── */
.a-main{flex:1;display:flex;flex-direction:column;height:100%;min-width:0}
.a-topbar{height:64px;display:flex;align-items:center;justify-content:space-between;padding:0 28px}
.brand-text{font-family:var(--serif);font-size:22px;font-weight:600;color:var(--brand)}
.brand-sub{font-family:var(--sans);font-size:13px;color:var(--text-muted);margin-left:6px}
.top-link{color:var(--text-main)!important;font-size:13.5px!important;font-weight:500!important;text-transform:none!important;
          background:transparent!important;box-shadow:none!important;padding:0!important}

/* ── HOME ── */
.a-home{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:0 24px 12vh}
.home-title{font-family:var(--serif);font-size:46px;font-weight:400;margin:0 0 12px;color:var(--brand);text-align:center}
.home-sub{color:var(--text-muted);font-size:14px;margin-bottom:36px;display:flex;align-items:center;gap:6px}
.home-brand{display:inline-flex;align-items:center;gap:4px;font-weight:600;color:var(--text-main)}
.prompt-box{width:100%;max-width:820px;background:#fff;border:2px solid #c0d3cc;border-radius:18px;
            padding:20px 22px 16px;box-shadow:0 8px 30px rgba(0,0,0,.03);transition:.2s}
.prompt-box:focus-within{border-color:var(--accent-dark);box-shadow:0 8px 30px rgba(107,148,133,.15)}
.prompt-input .q-field__control{background:transparent!important;border:none!important;padding:0!important;min-height:140px!important}
.prompt-input .q-field__control:before,.prompt-input .q-field__control:after{display:none!important}
.prompt-input textarea{padding:0!important;font-size:15.5px!important;line-height:1.55!important;
                      color:var(--text-main)!important;font-family:var(--sans)!important;
                      resize:none!important;min-height:130px!important;border:0!important;outline:0!important;background:transparent!important}
.prompt-input textarea::placeholder{color:#a8a6a1!important}
.prompt-tools{display:flex;align-items:center;justify-content:space-between;margin-top:8px;gap:8px}
.tool-grp{display:flex;align-items:center;gap:8px}
.tool-btn{background:transparent!important;color:#666!important;border:1px solid var(--border)!important;
          border-radius:50%!important;width:34px!important;height:34px!important;min-width:34px!important;min-height:34px!important;padding:0!important}
.tool-chip{display:inline-flex;align-items:center;gap:6px;padding:7px 12px;background:#fff;
          border:1px solid var(--border);border-radius:20px;font-size:13px;color:var(--text-main);
          font-weight:500;cursor:pointer}.tool-chip:hover{background:#f9f8f5}
.tool-chip-on{color:var(--accent-dark);border-color:transparent;background:transparent;font-weight:600}
.send-btn{background:var(--accent-teal)!important;color:#fff!important;border-radius:50%!important;
         width:42px!important;height:42px!important;min-width:42px!important;min-height:42px!important;
         box-shadow:0 4px 12px rgba(165,195,184,.4)!important;transition:.2s!important}
.send-btn:hover{background:var(--accent-hover)!important;transform:translateY(-2px);
                box-shadow:0 6px 16px rgba(165,195,184,.5)!important}

/* ── ARENA ── */
.a-arena{flex:1;display:flex;overflow:hidden;min-height:0}

/* Chat panel */
.a-chat{width:400px;border-right:1px solid var(--border);display:flex;flex-direction:column;
         background:var(--bg-main);flex-shrink:0}
.play-banner{height:48px;background:#f0f5f2;border-bottom:1px solid var(--border);
             display:flex;align-items:center;justify-content:center;gap:10px;
             color:var(--accent-dark);font-size:13px;font-weight:500;cursor:pointer}
.chat-scroll{flex:1;overflow-y:auto;padding:24px;display:flex;flex-direction:column;gap:20px;min-height:0}
.chat-scroll::-webkit-scrollbar{width:6px}.chat-scroll::-webkit-scrollbar-thumb{background:#d0cec9;border-radius:3px}
.msg-user{background:#f0efec;padding:14px 16px;border-radius:14px;font-size:14px;line-height:1.55;max-width:100%;
         white-space:pre-wrap;word-wrap:break-word}
.msg-card{background:#fff;border:1px solid #d5e1dc;border-radius:16px;padding:18px;
          box-shadow:0 4px 20px rgba(0,0,0,.02)}
.opt-tabs{display:flex;background:#f5f4f1;border-radius:22px;padding:4px;margin-bottom:14px}
.opt-tab{flex:1;text-align:center;padding:8px 12px;border-radius:18px;font-size:13px;font-weight:500;
         cursor:pointer;color:var(--text-muted);transition:.2s;user-select:none}
.opt-tab.on{background:#fff;color:var(--text-main);box-shadow:0 2px 6px rgba(0,0,0,.06);font-weight:600}
.art-row{display:flex;align-items:center;justify-content:space-between;padding:6px 0;color:var(--accent-dark);font-size:13px;font-weight:500}
.art-timer{color:var(--text-muted);font-size:12px;font-weight:400}
.agent-line{color:var(--text-muted);font-size:12.5px;margin-top:6px;display:flex;align-items:center;gap:6px}
.using-tool{padding:10px 14px;color:var(--text-muted);font-size:13px;display:flex;align-items:center;gap:8px;cursor:pointer}
.chat-input-w{padding:14px;border-top:1px solid var(--border);background:#fff}
.chat-ibox{border:1px solid var(--border);border-radius:14px;padding:10px 12px;background:#fff}
.chat-ibox textarea{border:0!important;outline:0!important;resize:none!important;width:100%!important;min-height:32px!important;
                    font-size:13.5px!important;color:var(--text-main)!important;background:transparent!important;padding:4px 0!important;font-family:var(--sans)!important}
.chat-itools{display:flex;align-items:center;justify-content:space-between;margin-top:6px}
.chat-send-sm{width:32px!important;height:32px!important;min-width:32px!important;min-height:32px!important}

/* Preview panel */
.a-prev{flex:1;display:flex;flex-direction:column;background:var(--bg-main);min-width:0}
.prev-tabs{display:flex;background:var(--bg-sidebar);padding:8px 20px 0;gap:4px;flex-shrink:0;
           border-bottom:1px solid var(--border)}
.prev-tab{padding:12px 20px;font-weight:600;font-size:14px;color:var(--text-muted);cursor:pointer;
          display:flex;align-items:center;gap:8px;border-radius:10px 10px 0 0;
          background:transparent;border:1px solid transparent;border-bottom:none;transition:.2s;user-select:none;margin-bottom:-1px}
.prev-tab.on{color:var(--brand);background:#fff;border-color:var(--border)}
.prev-ticon{font-size:16px;color:#b8b6b0}.prev-tab.on .prev-ticon{color:var(--accent-dark)}

.prev-toolbar{height:56px;background:#fff;border-bottom:1px solid var(--border);
             display:flex;align-items:center;padding:0 16px;gap:8px;flex-shrink:0}
.mode-tog{display:flex;background:#f5f4f1;border-radius:8px;padding:3px;gap:2px}
.mode-btn{width:36px!important;height:30px!important;min-width:36px!important;min-height:30px!important;
          border-radius:6px!important;background:transparent!important;color:var(--text-muted)!important;
          padding:0!important;box-shadow:none!important}
.mode-btn.on{background:#fff!important;color:var(--text-main)!important;box-shadow:0 1px 4px rgba(0,0,0,.08)!important}
.url-bar{flex:1;background:#f5f4f1;border:1px solid var(--border);border-radius:8px;
         padding:8px 14px;font-size:13px;color:var(--text-muted);display:flex;align-items:center;gap:8px;min-height:36px}
.tbar-btn{background:transparent!important;color:var(--text-muted)!important;border:none!important;
          width:34px!important;height:34px!important;min-width:34px!important;min-height:34px!important;border-radius:6px!important}
.tbar-btn:hover{background:#f5f4f1!important}
.pub-btn{background:#fff!important;color:var(--text-main)!important;border:1px solid var(--border)!important;
         border-radius:7px!important;padding:0 14px!important;min-height:34px!important;
         font-size:13px!important;font-weight:600!important;text-transform:none!important;box-shadow:none!important}
.pub-btn:hover{background:#f5f4f1!important}
.pub-btn.ready{background:var(--accent-teal)!important;color:#fff!important;border-color:var(--accent-teal)!important}

.prev-body{flex:1;position:relative;overflow:hidden;background:#fff;min-height:0}
.ifr-wrap{width:100%;height:100%}.ifr-wrap>iframe{width:100%;height:100%;border:none;display:block}
.code-view{width:100%;height:100%;background:#1e1e2e;overflow:auto;padding:0;display:none}
.code-view.show{display:block}
.code-view pre{margin:0;padding:20px 24px;color:#cdd6f4;font-family:'JetBrains Mono',Consolas,monospace;
              font-size:13px;line-height:1.7;white-space:pre-wrap;word-wrap:break-word}
.code-flabel{background:#313244;color:#a6e3a1;padding:8px 24px;
             font-family:'JetBrains Mono',Consolas,monospace;font-size:12px;font-weight:600;
             border-top:1px solid #45475a;border-bottom:1px solid #45475a;margin-top:12px}
.code-flabel:first-child{margin-top:0;border-top:none}

/* Loading overlay */
.load-overlay{position:absolute;inset:0;background:var(--bg-main);
              display:flex;flex-direction:column;align-items:center;justify-content:center;z-index:10;gap:0}
.globe{width:100px;height:100px;background:#eef4f1;border-radius:50%;border:2px solid var(--accent-teal);
       display:flex;align-items:center;justify-content:center;margin-bottom:24px}
.globe .material-icons{font-size:48px;color:var(--accent-dark)}
.load-title{font-family:var(--serif);font-size:28px;color:var(--brand);margin-bottom:8px;font-weight:600}
.load-sub{font-size:14px;color:var(--text-muted);margin-bottom:20px}
.dots{display:flex;gap:8px}
.dot{width:10px;height:10px;border-radius:50%;background:#c0d3cc;
     animation:bounce 1.4s infinite ease-in-out both}
.dot:nth-child(1){animation-delay:-.32s}.dot:nth-child(2){animation-delay:-.16s}
@keyframes bounce{0%,80%,100%{transform:scale(.6);opacity:.4}40%{transform:scale(1);opacity:1;background:var(--accent-dark)}}

/* Toast */
.toast{position:fixed;bottom:24px;right:24px;background:#fff;border:1px solid var(--border);
       border-radius:12px;padding:14px 18px;display:flex;align-items:center;gap:12px;
       box-shadow:0 8px 24px rgba(0,0,0,.08);z-index:9999;max-width:320px}
.toast-ok{width:24px;height:24px;border-radius:6px;background:#d1e7d0;color:#2d6f2d;
          display:flex;align-items:center;justify-content:center;flex-shrink:0}
.toast-tit{font-weight:600;font-size:13px;color:var(--text-main)}.toast-sub{font-size:12px;color:var(--text-muted);margin-top:2px}

@media(max-width:900px){
    .a-sb{width:200px}.a-chat{width:340px}.home-title{font-size:32px}
    .prev-toolbar{flex-wrap:wrap;height:auto;min-height:56px;padding:8px}
    .url-bar{min-width:160px}.a-chat{width:36vw;min-width:260px}
}
@media(max-width:680px){
    body{overflow:auto}.a-root{height:auto;min-height:100vh;flex-direction:column;overflow:visible}
    .a-sb{width:100%;height:auto;max-height:220px;border-right:0;border-bottom:1px solid var(--border)}
    .a-nav{display:grid;grid-template-columns:repeat(2,minmax(0,1fr))}.a-recent{max-height:90px}
    .a-main{min-height:calc(100vh - 220px)}.a-topbar{padding:0 16px}.a-topbar .top-link{display:none}
    .a-arena{flex-direction:column;overflow:visible}.a-chat{width:100%;height:310px;border-right:0;border-bottom:1px solid var(--border)}
    .a-prev{height:calc(100vh - 310px);min-height:520px}.prev-tabs{padding-left:8px}.prev-tab{padding:10px 12px}
    .prev-toolbar{gap:5px}.prev-toolbar .w-40{width:115px!important}.pub-btn{padding:0 8px!important}
    .prompt-box{padding:16px}.prompt-tools{align-items:flex-end}.tool-grp{flex-wrap:wrap}
}
</style>
"""

# ════════════════════════════════════════════════════════════════════
#  HELPERS
# ════════════════════════════════════════════════════════════════════


def _combine_document(files: dict[str, str]) -> str:
    """Inline CSS + JS into HTML so iframe preview is self-contained."""
    # React mode?
    react = files.get("src/App.jsx") or files.get("src/App.js")
    if react:
        css = files.get("src/styles.css", "") + files.get("src/App.css", "")
        react = re.sub(r"^\s*import\s+.*?;?\s*$", "", react, flags=re.M)
        react = re.sub(r"\bexport\s+default\s+", "", react)
        return (
            "<!doctype html><html><head><meta charset=UTF-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<script crossorigin src=https://unpkg.com/react@18/umd/react.development.js></script>"
            f"<script crossorigin src=https://unpkg.com/react-dom@18/umd/react-dom.development.js></script>"
            f"<script src=https://unpkg.com/@babel/standalone/babel.min.js></script>"
            f"<style>{css}</style></head><body><div id=root></div>"
            f"<script type=text/babel>{react}\nconst root=ReactDOM.createRoot(document.getElementById('root'));root.render(<App/>);"
            "</script></body></html>"
        )

    idx = files.get("index.html", "<h1>Waiting…</h1>")
    css = files.get("style.css", "")
    js = files.get("script.js", "")

    idx = re.sub(
        r'<link[^>]+href=["\']style\.css["\'][^>]*>',
        f"<style>{css}</style>", idx, flags=re.I,
    )
    idx = re.sub(
        r'<script[^>]+src=["\']script\.js["\'][^>]*></script>',
        f"<script>{js}</script>", idx, flags=re.I,
    )
    return idx


def _parse_files(raw: str) -> dict[str, str]:
    """Extract ### FILE: … \n``` … ``` blocks."""
    pat = re.compile(
        r"###\s*FILE:\s*([^\n]+)\n```[^\n]*\n(.*?)```",
        re.I | re.S,
    )
    out: dict[str, str] = {}
    allowed = {
        "index.html", "style.css", "script.js", "package.json",
        "src/App.jsx", "src/App.js", "src/styles.css", "src/App.css",
    }
    for path, content in pat.findall(raw):
        p = path.strip().replace("\\", "/")
        if p in allowed:
            out[p] = content.strip() + "\n"
    return out


def _title_from_prompt(prompt: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", prompt)
    return (" ".join(words[:6]).strip().title()) or "Website Project"


def _wants_react(prompt: str) -> bool:
    return bool(re.search(r"\breact(?:\.js)?\b", prompt, re.I))


def _make_zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for path, content in sorted(files.items()):
            z.writestr(path, content)
    return buf.getvalue()


def _parse_generated_files(raw: str) -> dict[str, str]:
    return _parse_files(raw)


def _project_document(files: dict[str, str]) -> str:
    return _combine_document(files)


def _project_title(prompt: str) -> str:
    return _title_from_prompt(prompt)


def _build_project_zip(files: dict[str, str]) -> bytes:
    return _make_zip(files)


def _slug(project_id: int, name: str) -> string:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "website"
    return f"{base}-{project_id}"


def _code_view_html(files: dict[str, str], sel: str | None = None) -> str:
    if not files:
        return "<pre>No code yet.</pre>"
    fn = sel if sel in files else sorted(files)[0]
    return (
        f'<div class="code-flabel">{html_mod.escape(fn)}</div>'
        f'<pre><code>{html_mod.escape(files[fn])}</code></pre>'
    )


# ════════════════════════════════════════════════════════════════════
#  PUBLISHED PAGE ROUTE
# ════════════════════════════════════════════════════════════════════


@ui.page("/published/{slug}")
def published_page(slug: str):
    pub = db.get_publication_by_slug(slug)
    if not pub:
        ui.label("Not found").classes("text-h4 q-pa-xl")
        return
    rows = db.get_project_files(pub["project_id"])
    files = {r["path"]: r["content"] for r in rows}
    doc = html_mod.escape(_combine_document(files), quote=True)
    ui.add_head_html("<style>html,body,#q-app{margin:0;width:100%;height:100%;overflow:hidden}</style>")
    ui.html(
        f'<iframe sandbox="allow-scripts" '
        f'style="border:0;width:100%;height:100vh" srcdoc="{doc}"></iframe>'
    )


# ════════════════════════════════════════════════════════════════════
#  BUILDER PAGE
# ════════════════════════════════════════════════════════════════════


@ui.page("/builder")
def builder_page():
    ui.add_head_html(ARENA_CSS)

    # ---- seed DB if empty ----
    projects = db.get_all_projects()
    if not projects:
        pid = db.create_project()
        for p, c in DEFAULT_FILES.items():
            db.save_project_file(pid, p, c)
        projects = db.get_all_projects()

    # ═══ STATE ═══
    st = {
        "view": "home",
        "status": "idle",
        "opt": "A",
        "mode": "preview",
        "prompt": "",
        "code_A": {},
        "code_B": {},
        "voted": False,
        "url_A": "",
        "url_B": "",
        "pid_A": None,
        "pid_B": None,
        "sel_file": "index.html",
    }
    r: dict = {}  # element refs

    # ═══ LOGIC ═══

    def _refresh_viewer():
        code = st["code_A"] if st["opt"] == "A" else st["code_B"]
        # iframe
        if r.get("ifr_wrap"):
            doc = html_mod.escape(_combine_document(code), quote=True)
            r["ifr_wrap"].set_content(
                f'<iframe sandbox="allow-scripts" srcdoc="{doc}"></iframe>'
            )
        # code view
        if r.get("cview"):
            r["cview"].set_content(_code_view_html(code, st["sel_file"]))
        # url bar
        if r.get("ubar"):
            r["ubar"].clear()
            with r["ubar"]:
                ui.icon("public", size="16px").classes("text-grey-6")
                if st["voted"]:
                    url = st["url_A"] if st["opt"] == "A" else st["url_B"]
                    ui.label(url or f"Publish Option {st['opt']}")
                else:
                    ui.label("Vote to get link")

    def _switch_opt(o: str):
        st["opt"] = o
        code = st["code_A"] if o == "A" else st["code_B"]
        if code and st["sel_file"] not in code:
            st["sel_file"] = sorted(code)[0]
        # left tabs
        for k in ("tab_a", "tab_b"):
            el = r.get(k)
            if el:
                el.classes(add="on" if {"tab_a": "A", "tab_b": "B"}[k] == o else "", remove="on" if {"tab_a": "B", "tab_b": "A"}[k] == o else "")
        # right tabs
        for k in ("ptab_a", "ptab_b"):
            el = r.get(k)
            if el:
                el.classes(add="on" if {"ptab_a": "A", "ptab_b": "B"}[k] == o else "", remove="on" if {"ptab_a": "B", "ptab_b": "A"}[k] == o else "")
        # file select
        if r.get("fsel"):
            r["fsel"].set_options(sorted(code), value=st["sel_file"])
        _refresh_viewer()

    def _set_mode(m: str):
        st["mode"] = m
        if m == "code":
            r["cview"].classes(add="show")
            r["ifr_wrap"].classes(add="hidden")
            r["m_eye"].classes(remove="on"); r["m_code"].classes(add="on")
        else:
            r["cview"].classes(remove="show")
            r["ifr_wrap"].classes(remove="hidden")
            r["m_eye"].classes(add="on"); r["m_code"].classes(remove="on")

    def _pick_file(e):
        st["sel_file"] = e.value
        _refresh_viewer()

    def _download():
        code = st["code_A"] if st["opt"] == "A" else st["code_B"]
        if not code:
            ui.notify("Generate first.", type="warning"); return
        nm = re.sub(r"[^A-Za-z0-9._-]+", "-", st["prompt"][:40]).strip("-") or "website"
        ui.download(_make_zip(code), f"{nm}.zip")
        ui.notify("ZIP downloaded", type="positive")

    def _open_live():
        url = st["url_A"] if st["opt"] == "A" else st["url_B"]
        if not url:
            ui.notify("Publish first.", type="warning"); return
        ui.run_javascript(f"window.open({json.dumps(url)},'_blank')")

    def _fullscreen():
        ui.run_javascript(
            "const e=document.querySelector('.prev-body');"
            "if(document.fullscreenElement)document.exitFullscreen();"
            "else e?.requestFullscreen()"
        )

    def _open_saved(pid: int):
        rows = db.get_project_files(pid)
        if not rows:
            ui.notify("No files.", type="warning"); return
        proj = next((p for p in db.get_all_projects() if p["id"] == pid), None)
        st["prompt"] = proj["name"] if proj else "Saved site"
        st["status"] = "ready"; st["voted"] = True; st["opt"] = "A"
        st["code_A"] = {row["path"]: row["content"] for row in rows}
        st["sel_file"] = sorted(st["code_A"])[0]
        pub = db.get_project_publication(pid)
        st["url_A"] = f"/published/{pub['slug']}" if pub else ""
        r["home"].set_visibility(False)
        r["arena"].set_visibility(True)
        r["umsg"].set_text(st["prompt"])
        _refresh_viewer()

    def _refresh_recent():
        rc = r.get("recent")
        if rc is None:
            return
        rc.clear()
        with rc:
            ps = db.get_all_projects()[:8]
            if not ps:
                ui.label("No saved designs").classes("text-grey-6 text-sm")
            for p in ps:
                with ui.element("div").classes("a-rec-item") as it:
                    ui.element("div").classes("a-dot")
                    ui.label(p["name"])
                it.on("click", lambda _, pid=p["id"]: _open_saved(pid))

    async def _gen_one(name: str, style: str) -> bool:
        try:
            from app.main import stream_llm
        except Exception:
            await asyncio.sleep(2)
            fb = {
                "index.html": f"<h1>Option {name}</h1><p>{style}<p>Prompt: {st['prompt']}</p>",
                "style.css": "body{font-family:sans-serif;padding:40px;background:#f5efe8}",
                "script.js": f"console.log('{name}')",
            }
            (st["code_A"] if name == "A" else st["code_B"]).__dict__.update(fb) if False else None
            if name == "A":
                st["code_A"] = fb
            else:
                st["code_B"] = fb
            return True

        wants_react = _wants_react(st["prompt"])
        if wants_react:
            contract = (
                "Build a real React website. Return ONLY these file blocks, no explanation:\n\n"
                "### FILE: package.json\n```json\n{\"dependencies\":{\"react\":\"^18.0.0\"}}\n```\n\n"
                "### FILE: src/App.jsx\n```jsx\n<complete React component named App>\n```\n\n"
                "### FILE: src/styles.css\n```css\n<complete CSS>\n```\n\n"
                "App.jsx must define `function App()`, use JSX, and must not import local files."
            )
        else:
            contract = (
                "Build a high-quality single-page website. Return ONLY these file blocks, no explanation:\n\n"
                "### FILE: index.html\n```html\n<complete HTML>\n```\n\n"
                "### FILE: style.css\n```css\n<complete CSS>\n```\n\n"
                "### FILE: script.js\n```javascript\n<JS code>\n```"
            )
        instr = (
            "You are a Senior Web Developer. Create a production-ready responsive website.\n"
            f"Design style: {style}\n{contract}\n\n"
            f"User request:\n{st['prompt']}"
        )
        raw = ""
        try:
            async for chunk in stream_llm([{"role": "user", "content": instr}]):
                raw += chunk
            files = _parse_files(raw)
            if not files or "index.html" not in files:
                raise ValueError(
                    "AI did not return the required React files"
                    if wants_react else "No HTML generated"
                )
            if name == "A":
                st["code_A"] = files
            else:
                st["code_B"] = files
            return True
        except Exception as exc:
            fallback = {
                "index.html": f"<h1>Error</h1><pre>{html_mod.escape(str(exc))}</pre>",
                "style.css": "body{padding:40px}",
                "script.js": "",
            }
            if name == "A":
                st["code_A"] = fallback
            else:
                st["code_B"] = fallback
            return False

    async def _submit():
        txt = r["inp"].value if r.get("inp") else ""
        if not txt or not txt.strip():
            ui.notify("Enter a prompt.", type="warning"); return
        st["prompt"] = txt.strip()
        st["status"] = "generating"; st["voted"] = False; st["opt"] = "A"

        r["home"].set_visibility(False); r["arena"].set_visibility(True)
        r["umsg"].set_text(st["prompt"]); r["load"].set_visibility(True)

        _switch_opt("A"); _set_mode("preview")

        results = await asyncio.gather(
            _gen_one("A", "Clean, minimalist, modern, professional with subtle animations"),
            _gen_one("B", "Bold, creative, vibrant colors, playful with strong visuals"),
        )
        st["status"] = "ready"
        ac = st["code_A"]; st["sel_file"] = sorted(ac)[0] if ac else "index.html"
        if r.get("fsel"):
            r["fsel"].set_options(sorted(ac), value=st["sel_file"])
        r["load"].set_visibility(False)
        _refresh_viewer()
        if all(results):
            ui.notify("✨ Both designs ready! Vote for your favorite.", type="positive", position="bottom-right")
        else:
            ui.notify(
                "AI backend is unavailable. Start the LLM service and try again.",
                type="negative",
                timeout=10000,
                position="bottom-right",
            )

    def _vote():
        if st["status"] != "ready":
            ui.notify("Wait for generation.", type="warning"); return
        st["voted"] = True
        ui.notify(f"✓ Voted Option {st['opt']}!", type="positive")
        _refresh_viewer()

    def _publish():
        if st["status"] != "ready":
            ui.notify("Wait for generation.", type="warning"); return
        opt = st["opt"]
        code = st["code_A"] if opt == "A" else st["code_B"]
        pname = f"Arena {opt}: {st['prompt'][:30]}"
        epid = st["pid_A"] if opt == "A" else st["pid_B"]
        pid = epid or db.create_project(name=pname)
        db.update_project_name(pid, pname)
        for p, c in code.items():
            db.save_project_file(pid, p, c)
        slug = _slug(pid, pname)
        db.publish_project(pid, slug)
        url = f"/published/{slug}"
        if opt == "A":
            st["url_A"] = url; st["pid_A"] = pid
        else:
            st["url_B"] = url; st["pid_B"] = pid
        st["voted"] = True; _refresh_viewer()
        ui.notify(f"🚀 Published! {url}", type="positive", position="top")
        _refresh_recent()

    def _go_home():
        st.update(view="home", status="idle", prompt="", code_A={}, code_B={},
                  voted=False, url_A="", url_B="", pid_A=None, pid_B=None)
        if r.get("inp"):
            r["inp"].value = ""
        r["home"].set_visibility(True); r["arena"].set_visibility(False)

    def _copy_url():
        url = st["url_A"] if st["opt"] == "A" else st["url_B"]
        if url:
            ui.run_javascript(f"navigator.clipboard.writeText(new URL({json.dumps(url)},location.origin).href)")
            ui.notify("URL copied!", type="positive")
        else:
            ui.notify("Publish first.", type="warning")

    # ═══ LAYOUT ═══
    with ui.element("div").classes("a-root"):
        # ─── SIDEBAR ───
        with ui.element("div").classes("a-sb"):
            with ui.element("div").classes("a-sb-head"):
                ui.element("div").classes("a-logo"); ui.label("✦").classes("text-white")
                ui.button(icon="view_sidebar").props("flat dense round").classes("text-grey-7")
            with ui.element("div").classes("a-nav"):
                ui.button("New project", icon="edit_square", on_click=_go_home).props("flat no-caps").classes("a-nav-btn")
                ui.button("Search", icon="search").props("flat no-caps").classes("a-nav-btn")
                ui.button("My Projects", icon="folder_open").props("flat no-caps").classes("a-nav-btn")
                ui.button("Leaderboards", icon="leaderboard").props("flat no-caps").classes("a-nav-btn")
                ui.button("Models", icon="view_in_ar").props("flat no-caps").classes("a-nav-btn")
                ui.button("About", icon="info_outline").props("flat no-caps").classes("a-nav-btn")
            with ui.element("div").classes("a-recent"):
                ui.label("Recent Designs").classes("a-sect-title")
                r["recent"] = ui.column().classes("w-full gap-0")
                with r["recent"]:
                    ui.label("Loading…").classes("text-grey-6 text-sm")
            with ui.element("div").classes("a-user"):
                ui.element("div").classes("a-avatar"); ui.label("P").classes("text-white text-bold")
                ui.label("Prashant").classes("font-medium text-sm")
                ui.space(); ui.icon("unfold_more").classes("text-grey-6 text-sm")

        # ─── MAIN AREA ───
        with ui.element("div").classes("a-main"):
            # top bar
            with ui.element("div").classes("a-topbar"):
                with ui.row().classes("items-center gap-0"):
                    ui.label("Design Arena").classes("brand-text")
                    ui.html('<span class="brand-sub">by ✦ Saumya Intelligence</span>')
                with ui.element("div").classes("gap-4 items-center"):
                    ui.button("Leaderboards").props("flat no-caps").classes("top-link")
                    ui.button("Models").props("flat no-caps").classes("top-link")
                    ui.button("EN", icon="language").props("flat no-caps").classes("top-link")

            # ─── HOME SCREEN ───
            r["home"] = ui.element("div").classes("a-home")
            with r["home"]:
                ui.label("What are you creating today?").classes("home-title")
                with ui.element("div").classes("home-sub"):
                    ui.label("by ")
                    ui.element("span").classes("home-brand"); ui.label("✦ Saumya Intelligence")
                    ui.label(" • 6.7M+ users")
                with ui.element("div").classes("prompt-box"):
                    r["inp"] = ui.textarea().props(
                        'autogrow borderless placeholder="Describe the website you want to build... '
                        'e.g. A responsive React beauty parlour website with About, Services and Gallery pages"'
                    ).classes("prompt-input w-full")
                    with ui.element("div").classes("prompt-tools"):
                        with ui.element("div").classes("tool-grp"):
                            ui.button(icon="attach_file").props("flat dense").classes("tool-btn")
                            ui.button(icon="cloud_upload").props("flat dense").classes("tool-btn")
                            ui.element("div").classes("tool-chip"); ui.icon("bolt", size="15px"); ui.label("FAST"); ui.icon("expand_more", size="14px")
                            ui.element("div").classes("tool-chip tool-chip-on"); ui.icon("web", size="15px"); ui.label("Website")
                        ui.button(icon="arrow_upward", on_click=_submit).props("unelevated round").classes("send-btn")

            # ─── ARENA SCREEN ───
            r["arena"] = ui.element("div").classes("a-arena")
            r["arena"].set_visibility(False)

            with r["arena"]:
                # chat panel (left-center)
                with ui.element("div").classes("a-chat"):
                    with ui.element("div").classes("play-banner"):
                        ui.icon("sports_esports", size="18px").classes("text-green-7")
                        ui.label("Play while you wait")
                    with ui.element("div").classes("chat-scroll"):
                        r["umsg"] = ui.label("").classes("msg-user")
                        with ui.element("div").classes("msg-card"):
                            with ui.element("div").classes("opt-tabs"):
                                r["tab_a"] = ui.element("div").classes("opt-tab on"); r["tab_a"].on("click", lambda: _switch_opt("A"))
                                with r["tab_a"]: ui.label("Option A")
                                r["tab_b"] = ui.element("div").classes("opt-tab"); r["tab_b"].on("click", lambda: _switch_opt("B"))
                                with r["tab_b"]: ui.label("Option B")
                            with ui.element("div").classes("art-row"):
                                with ui.row().classes("items-center gap-2"):
                                    ui.icon("web", size="18px").classes("text-green-7")
                                    ui.label("Web Apps artifact")
                                ui.label("⏱ building…").classes("art-timer")
                            with ui.element("div").classes("agent-line"):
                                ui.label("Bringing your vision to life…")
                        with ui.element("div").classes("using-tool"):
                            ui.label("Using batch_create_files")
                            ui.icon("expand_more").classes("text-grey-6 text-sm")
                    # chat input
                    with ui.element("div").classes("chat-input-w"):
                        with ui.element("div").classes("chat-ibox"):
                            ui.textarea().props(
                                'borderless autogrow placeholder="Vote above first..."'
                            ).classes("w-full")
                            with ui.element("div").classes("chat-itools"):
                                with ui.row().classes("gap-1 items-center"):
                                    ui.button(icon="attach_file").props("flat dense round").classes("tool-btn").style("width:28px;height:28px;min-width:28px;min-height:28px")
                                    ui.button(icon="cloud_upload").props("flat dense round").classes("tool-btn").style("width:28px;height:28px;min-width:28px;min-height:28px")
                                ui.button(icon="arrow_upward", on_click=_vote).props("unelevated round dense").classes("send-btn chat-send-sm")

                # preview panel (right)
                with ui.element("div").classes("a-prev"):
                    with ui.element("div").classes("prev-tabs"):
                        r["ptab_a"] = ui.element("div").classes("prev-tab on"); r["ptab_a"].on("click", lambda: _switch_opt("A"))
                        with r["ptab_a"]: ui.icon("emoji_events").classes("prev-ticon"); ui.label("Option A")
                        r["ptab_b"] = ui.element("div").classes("prev-tab"); r["ptab_b"].on("click", lambda: _switch_opt("B"))
                        with r["ptab_b"]: ui.icon("emoji_events").classes("prev-ticon"); ui.label("Option B")

                    with ui.element("div").classes("prev-toolbar"):
                        with ui.element("div").classes("mode-tog"):
                            r["m_eye"] = ui.button(icon="visibility", on_click=lambda: _set_mode("preview")).props("flat").classes("mode-btn on")
                            r["m_code"] = ui.button(icon="code", on_click=lambda: _set_mode("code")).props("flat").classes("mode-btn")
                        r["ubar"] = ui.element("div").classes("url-bar")
                        with r["ubar"]:
                            ui.icon("public", size="16px").classes("text-grey-6")
                            ui.label("Vote to get link")
                        ui.button(icon="content_copy", on_click=_copy_url).props("flat dense").classes("tbar-btn")
                        ui.button(icon="open_in_new", on_click=_open_live).props("flat dense").classes("tbar-btn")
                        ui.button(icon="refresh", on_click=_refresh_viewer).props("flat dense").classes("tbar-btn")
                        ui.button(icon="open_in_full", on_click=_fullscreen).props("flat dense").classes("tbar-btn")
                        r["fsel"] = ui.select(options=[], on_change=_pick_file).props("dense outlined options-dense").classes("w-40")
                        ui.button("Download", icon="download", on_click=_download).props("flat no-caps").classes("tbar-btn")
                        r["pub_btn"] = ui.button("Publish", icon="lock_open", on_click=_publish).props("unelevated no-caps").classes("pub-btn")

                    # body
                    with ui.element("div").classes("prev-body"):
                        r["load"] = ui.element("div").classes("load-overlay")
                        r["load"].set_visibility(False)
                        with r["load"]:
                            with ui.element("div").classes("globe"):
                                ui.icon("language", size="48px").classes("text-green-7")
                            ui.label("Building Preview").classes("load-title")
                            ui.label("The agent is working on your app…").classes("load-sub")
                            with ui.element("div").classes("dots"):
                                for _ in range(3):
                                    ui.element("div").classes("dot")
                        r["ifr_wrap"] = ui.html('<div style="padding:80px;text-align:center;color:#999">Submit a prompt</div>').classes("ifr-wrap w-full h-full")
                        r["cview"] = ui.html("").classes("code-view")

    _refresh_recent()