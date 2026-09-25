"""Design Arena style Website Builder  ->  app/builder.py

Flow : Home prompt -> two AI options (A/B) generated in parallel -> vote ->
       live preview / code explorer / terminal -> refine by chat -> publish URL / ZIP.

* Sab kuch dynamic hai: real LLM streaming (app.main.stream_llm), live progress,
  auto-verify + auto-repair of missing files, DB persistence, real publish routes,
  vote store + leaderboard, model picker per option.
* CSS is file ke andar hi hai (ARENA_CSS) -- koi Tailwind / Quasar utility class use nahi hui.
"""
from __future__ import annotations

import asyncio
import html as html_mod
import importlib
import importlib.util
import io
import json
import os
import pkgutil
import posixpath
import re
import secrets
import sys
import time
import zipfile
from collections import OrderedDict
from pathlib import Path

if not hasattr(pkgutil, "find_loader"):
    pkgutil.find_loader = lambda name: importlib.util.find_spec(name)

from fastapi import Response
from fastapi.responses import HTMLResponse, RedirectResponse
from nicegui import app, ui

from app.database import db

# ════════════════════════════════════════════════════════════════════
#  CONFIG
# ════════════════════════════════════════════════════════════════════

DATA_DIR = Path(os.getenv("ARENA_DATA_DIR", "data"))
VOTES_FILE = DATA_DIR / "arena_votes.json"
MAX_CONTEXT_CHARS = 90_000
ALLOWED_EXT = {"html", "htm", "css", "js", "jsx", "ts", "tsx", "json", "svg", "md", "txt", "xml", "mjs"}
SANDBOX = "allow-scripts allow-forms allow-modals allow-popups allow-downloads"

KINDS = {"website": "Website", "webapp": "Web Apps", "fullstack": "Fullstack"}

STYLE = {
    "A": "Refined and minimal: generous whitespace, an editorial serif/sans type pairing, a muted "
         "considered palette, precise spacing, subtle purposeful motion.",
    "B": "Bold and expressive: high contrast, confident oversized typography, saturated colour, "
         "layered visuals, playful micro-interactions.",
}

SUGGESTIONS = [
    "Elegant beauty parlour React website with services, gallery and admin panel",
    "Real-estate website with property listings and a full admin panel",
    "SaaS landing page with pricing, testimonials and FAQ",
    "Photographer portfolio with masonry gallery and contact form",
    "Restaurant website with online menu and table booking",
    "Sales analytics dashboard with charts and filters",
]

PHRASES = [
    "Designing at the speed of thought…",
    "Choosing typography and colour…",
    "Laying out sections…",
    "Writing real copy…",
    "Wiring up interactions…",
    "Polishing the details…",
]

BASE_RULES = """You are a world-class senior product designer and front-end engineer.
Build a PRODUCTION-QUALITY, fully responsive result for the request below.

HARD RULES
- Return ONLY file blocks in the exact format shown below. No explanations, nothing outside file blocks.
- Every file must be COMPLETE. No placeholders, no "...", no TODO, no lorem ipsum. Write rich, believable copy and data.
- Beautiful typography (Google Fonts through <link> is fine), consistent spacing scale, hover/focus states, accessible markup, mobile-first responsive layout.
- Images: use https://images.unsplash.com/photo-<id>?auto=format&fit=crop&w=1200&q=80 style URLs, inline SVG or CSS gradients. Never reference local image files you do not create.
- If the request mentions an admin panel / dashboard / CRUD: build a FULLY WORKING admin (login screen with demo credentials shown, add / edit / delete for every entity, form validation, and changes must appear on the public site). Persist in localStorage (wrap access in try/catch, fall back to in-memory) and seed it with realistic data.
- No build tooling, no CDN frameworks besides what is explicitly allowed below.

OUTPUT FORMAT (repeat for every file):
### FILE: path/to/file.ext
```lang
<complete file content>
```"""


def _contract(kind: str) -> str:
    if kind == "website":
        return (
            "PROJECT TYPE: multi-file static website.\n"
            "Files: index.html, style.css, script.js (+ optional extra pages such as about.html or admin.html that share style.css/script.js). "
            "Max 8 files. Use relative links only (href=\"style.css\", href=\"about.html\"). Plain HTML/CSS/vanilla JS."
        )
    extra = ""
    if kind == "fullstack":
        extra = (
            "\nFULLSTACK: also create src/api/db.js - an async REST-like client (list/get/create/update/remove per entity, "
            "auth login/logout with roles, seeded data) persisted in localStorage. All pages read/write ONLY through this api layer. "
            "Include a protected /admin area with dashboards and full CRUD."
        )
    return (
        "PROJECT TYPE: React 18 single page app.\n"
        "Files: index.html (only <div id=\"root\"></div>, meta tags and font links), package.json, src/main.jsx "
        "(createRoot(...).render(<App/>)), src/App.jsx, src/styles.css (imported from main.jsx), plus src/components/*.jsx, "
        "src/pages/*.jsx, src/data/*.js as needed. Max 16 files.\n"
        "IMPORT RULES: the ONLY package imports allowed are 'react', 'react-dom' and 'react-dom/client'. "
        "Do NOT use react-router or any other package - implement routing yourself with window.location.hash + useState/useEffect. "
        "Every relative import must point to a file you output. Use function components and hooks." + extra
    )


# ════════════════════════════════════════════════════════════════════
#  FILE PARSING / VALIDATION / HIGHLIGHT
# ════════════════════════════════════════════════════════════════════

_FILE_HDR = re.compile(r"^\s*(?:#{1,6}\s*)?(?:\*\*)?FILE:\s*(.+?)\s*(?:\*\*)?\s*$", re.I)
_FILE_TAIL = re.compile(r"^[ \t]*#{1,6}[ \t]*FILE:[ \t]*`?([^\s`]+)`?[ \t]*\n", re.M | re.I)


def _clean_path(p: str) -> str | None:
    p = p.strip().strip("`*'\"").replace("\\", "/")
    p = re.sub(r"^\.?/+", "", p)
    if not p or ".." in p.split("/") or len(p) > 120:
        return None
    if not re.fullmatch(r"[A-Za-z0-9._@+\-/]+", p):
        return None
    ext = p.rsplit(".", 1)[-1].lower() if "." in p else ""
    return p if ext in ALLOWED_EXT else None


def _parse_files(raw: str) -> dict[str, str]:
    """### FILE: path  +  ```lang ... ```  blocks -> {path: content}."""
    out: dict[str, str] = {}
    cur: str | None = None
    buf: list[str] = []
    state = 0  # 0 idle, 1 waiting for fence, 2 inside fence

    def flush():
        if cur is not None:
            text = "\n".join(buf).strip("\n")
            if text.strip():
                out[cur] = text + "\n"

    for line in raw.splitlines():
        m = _FILE_HDR.match(line)
        if m and _clean_path(m.group(1)):
            flush()
            cur, buf, state = _clean_path(m.group(1)), [], 1
            continue
        if state == 1:
            if line.strip().startswith("```"):
                state = 2
            elif line.strip():
                state = 2
                buf.append(line)
            continue
        if state == 2:
            if line.strip() == "```":
                flush()
                cur, buf, state = None, [], 0
            else:
                buf.append(line)
    flush()
    return out


def _is_react(files: dict[str, str]) -> bool:
    return any(re.match(r"^src/.*\.(jsx|tsx)$", p) for p in files) or "src/App.js" in files


def _entry_file(files: dict[str, str]) -> str:
    for p in ("index.html", "src/main.jsx", "src/App.jsx", "src/App.js", "src/main.tsx"):
        if p in files:
            return "src/App.jsx" if (p == "index.html" and _is_react(files) and "src/App.jsx" in files) else p
    return sorted(files)[0] if files else "index.html"


_IMP = re.compile(r"""(?:from\s+|import\s+|require\(\s*)['"](\.{1,2}/[^'"\n]+)['"]""")
_PKG = re.compile(r"""(?:from\s+|import\s+)['"]([^'"./][^'"]*)['"]""")
_REF = re.compile(r"""(?:src|href)\s*=\s*["']([^"'#?]+\.(?:css|js|html|jsx))["']""", re.I)
_RESOLVE_EXT = ("", ".jsx", ".js", ".tsx", ".ts", ".json", ".css", "/index.jsx", "/index.js")


def _resolve(files: dict[str, str], base: str, spec: str) -> str | None:
    t = posixpath.normpath(posixpath.join(posixpath.dirname(base), spec))
    for ext in _RESOLVE_EXT:
        if t + ext in files:
            return t + ext
    return None


def _problems(files: dict[str, str]) -> list[str]:
    out: list[str] = []
    if _is_react(files):
        entries = ("src/main.jsx", "src/main.js", "src/main.tsx", "src/index.jsx", "src/index.js", "src/App.jsx", "src/App.js", "src/App.tsx")
        if not any(p in files for p in entries):
            out.append("entry file missing: src/main.jsx or src/App.jsx")
        for p, c in files.items():
            if re.search(r"\.(jsx?|tsx?)$", p):
                for spec in _IMP.findall(c):
                    if not _resolve(files, p, spec):
                        out.append(f"{p}: cannot resolve '{spec}'")
                for pkg in _PKG.findall(c):
                    if pkg not in ("react", "react-dom", "react-dom/client"):
                        out.append(f"{p}: package '{pkg}' is not allowed (only react and react-dom)")
    else:
        if "index.html" not in files:
            out.append("index.html missing")
        for p, c in files.items():
            if p.endswith((".html", ".htm")):
                for ref in _REF.findall(c):
                    if re.match(r"(?:https?:)?//|data:|mailto:|tel:", ref, re.I):
                        continue
                    t = posixpath.normpath(posixpath.join(posixpath.dirname(p), ref.lstrip("/")))
                    if t not in files:
                        out.append(f"{p}: references missing file '{ref}'")
    return out[:20]


def _files_context(files: dict[str, str], cap: int = MAX_CONTEXT_CHARS) -> str:
    parts, used, skipped = [], 0, []
    for p in sorted(files):
        block = f"### FILE: {p}\n```\n{files[p]}\n```\n"
        if used + len(block) > cap:
            skipped.append(p)
            continue
        parts.append(block)
        used += len(block)
    if skipped:
        parts.append("(files omitted for length: " + ", ".join(skipped) + ")")
    return "\n".join(parts)


_HL = {
    "js": r"(?P<c>//[^\n]*|/\*.*?\*/)|(?P<s>\"(?:\\.|[^\"\\\n])*\"|'(?:\\.|[^'\\\n])*'|`(?:\\.|[^`\\])*`)"
          r"|(?P<k>\b(?:import|export|from|default|const|let|var|function|return|if|else|for|while|switch|case|break|continue|new|class|extends|async|await|try|catch|finally|throw|typeof|instanceof|in|of|null|undefined|true|false|this)\b)"
          r"|(?P<n>\b\d+(?:\.\d+)?\b)",
    "css": r"(?P<c>/\*.*?\*/)|(?P<s>\"[^\"\n]*\"|'[^'\n]*')|(?P<k>@[\w-]+)|(?P<a>[\w-]+(?=\s*:))"
           r"|(?P<n>#[0-9a-fA-F]{3,8}\b|\b\d+(?:\.\d+)?(?:px|rem|em|%|vh|vw|s|ms|deg)?\b)",
    "html": r"(?P<c><!--.*?-->)|(?P<t></?[A-Za-z][\w:-]*|/?>)|(?P<s>\"[^\"\n]*\")|(?P<a>\b[\w:-]+(?==))",
    "json": r"(?P<a>\"(?:\\.|[^\"\\\n])*\"(?=\s*:))|(?P<s>\"(?:\\.|[^\"\\\n])*\")|(?P<k>\b(?:true|false|null)\b)"
            r"|(?P<n>-?\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b)",
}
_HLC = {k: re.compile(v, re.S) for k, v in _HL.items()}
_LANG = {"js": "js", "jsx": "js", "ts": "js", "tsx": "js", "mjs": "js", "css": "css",
         "html": "html", "htm": "html", "svg": "html", "xml": "html", "json": "json"}


def _highlight(code: str, name: str) -> str:
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    lang = _LANG.get(ext)
    if not lang or len(code) > 150_000:
        return html_mod.escape(code)
    out, pos = [], 0
    for m in _HLC[lang].finditer(code):
        out.append(html_mod.escape(code[pos:m.start()]))
        out.append(f'<span class="t{m.lastgroup}">{html_mod.escape(m.group())}</span>')
        pos = m.end()
    out.append(html_mod.escape(code[pos:]))
    return "".join(out)


def _code_html(code: str, name: str) -> str:
    n = code.count("\n") + 1
    gut = "\n".join(str(i) for i in range(1, n + 1))
    return (f'<div class="da-cg"><pre class="da-gut">{gut}</pre>'
            f'<pre class="da-src"><code>{_highlight(code, name)}</code></pre></div>')


def _flatten(paths, collapsed: set, q: str):
    tree: dict = {}
    for p in paths:
        if q and q not in p.lower():
            continue
        node, parts = tree, p.split("/")
        for d in parts[:-1]:
            node = node.setdefault(d + "/", {})
        node[parts[-1]] = p
    out: list[tuple[int, str, str, str]] = []

    def walk(node, depth, prefix):
        for d in sorted(k for k, v in node.items() if isinstance(v, dict)):
            dp = prefix + d
            out.append((depth, "dir", dp, d[:-1]))
            if q or dp not in collapsed:
                walk(node[d], depth + 1, dp)
        for f in sorted(k for k, v in node.items() if isinstance(v, str)):
            out.append((depth, "file", node[f], f))

    walk(tree, 0, "")
    return out


def _title_from_prompt(prompt: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", prompt)
    return (" ".join(words[:5]).strip().title()) or "New Website"


def _slug(project_id: int, name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "website"
    return f"{base}-{project_id}"


def _make_zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for path, content in sorted(files.items()):
            z.writestr(path, content)
    return buf.getvalue()


def _read_zip(data: bytes) -> dict[str, str]:
    files: dict[str, str] = {}
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = [n for n in z.namelist() if not n.endswith("/") and "__MACOSX" not in n and "node_modules" not in n]
        tops = {n.split("/", 1)[0] for n in names if "/" in n}
        strip = len(tops) == 1 and all("/" in n for n in names)
        for n in names[:200]:
            p = _clean_path(n.split("/", 1)[1] if strip else n)
            if p and z.getinfo(n).file_size < 1_500_000:
                files[p] = z.read(n).decode("utf-8", "replace")
    return files


# ════════════════════════════════════════════════════════════════════
#  VOTES / LEADERBOARD
# ════════════════════════════════════════════════════════════════════

def _load_votes() -> list[dict]:
    try:
        return json.loads(VOTES_FILE.read_text("utf-8"))
    except Exception:
        return []


def _save_vote(entry: dict) -> None:
    votes = _load_votes()
    votes.append(entry)
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        VOTES_FILE.write_text(json.dumps(votes[-5000:], ensure_ascii=False), "utf-8")
    except OSError:
        pass


def _leaderboard() -> list[tuple[str, int, int, int]]:
    stats: dict[str, dict[str, int]] = {}
    for v in _load_votes():
        a, b, w = v.get("A"), v.get("B"), v.get("winner")
        if not a or not b or a == b or w not in ("A", "B"):
            continue
        for opt, m in (("A", a), ("B", b)):
            s = stats.setdefault(m, {"w": 0, "n": 0})
            s["n"] += 1
            s["w"] += 1 if opt == w else 0
    rows = [(m, s["w"], s["n"], round(100 * s["w"] / s["n"])) for m, s in stats.items()]
    return sorted(rows, key=lambda r: (-r[3], -r[2]))


# ════════════════════════════════════════════════════════════════════
#  PREVIEW / PUBLISH SERVER  (real URLs, real files)
# ════════════════════════════════════════════════════════════════════

_PREVIEWS: "OrderedDict[str, dict[str, str]]" = OrderedDict()


def _register_preview(files: dict[str, str]) -> str:
    token = secrets.token_urlsafe(9)
    _PREVIEWS[token] = dict(files)
    while len(_PREVIEWS) > 80:
        _PREVIEWS.popitem(last=False)
    return token


def _update_preview(token: str, files: dict[str, str]) -> None:
    _PREVIEWS[token] = dict(files)
    _PREVIEWS.move_to_end(token)


_SHIM = r"""<script id="__da_shim">(function(){
var st={l:{},s:{}};try{var n=window.name;if(n&&n.indexOf('__da:')===0)st=JSON.parse(n.slice(5))}catch(e){}
function sync(){try{window.name='__da:'+JSON.stringify(st)}catch(e){}}
function mk(k){var d=st[k];var o={getItem:function(a){return Object.prototype.hasOwnProperty.call(d,a)?d[a]:null},setItem:function(a,v){d[a]=String(v);sync()},removeItem:function(a){delete d[a];sync()},clear:function(){for(var a in d)delete d[a];sync()},key:function(i){return Object.keys(d)[i]||null}};Object.defineProperty(o,'length',{get:function(){return Object.keys(d).length}});return o}
[['localStorage','l'],['sessionStorage','s']].forEach(function(p){var ok=true;try{var s=window[p[0]];s.setItem('__t','1');s.removeItem('__t')}catch(e){ok=false}
if(!ok){try{Object.defineProperty(window,p[0],{value:mk(p[1]),configurable:true})}catch(e){}}});
window.addEventListener('message',function(ev){var d=ev.data;if(!d||!d.da)return;
if(d.da==='edit'){document.designMode=d.on?'on':'off'}
if(d.da==='collect'){document.designMode='off';var c=document.documentElement.cloneNode(true);c.querySelectorAll('#__da_shim').forEach(function(x){x.remove()});parent.postMessage({da:'html',path:location.pathname,html:'<!doctype html>\n'+c.outerHTML},'*')}});
})();</script>"""

_REACT_LOADER = r"""(function(){
var F=__FILES__,cache={};
var EXT=['','.jsx','.js','.tsx','.ts','.json','.css','/index.jsx','/index.js'];
function norm(p){var o=[];p.split('/').forEach(function(s){if(!s||s==='.')return;if(s==='..')o.pop();else o.push(s)});return o.join('/')}
function resolve(from,r){var b=from.split('/').slice(0,-1).join('/');var t=norm(r.charAt(0)==='.'?b+'/'+r:r);for(var i=0;i<EXT.length;i++){if(F[t+EXT[i]]!==undefined)return t+EXT[i]}return null}
var EXTL={'react':window.React,'react-dom':window.ReactDOM,'react-dom/client':window.ReactDOM};
function fail(e){var d=document.createElement('pre');d.style.cssText='position:fixed;inset:0;margin:0;padding:24px;background:#1b1020;color:#ffb4c1;font:13px/1.55 monospace;white-space:pre-wrap;overflow:auto;z-index:99999';d.textContent='Preview error\n\n'+((e&&e.stack)||e);document.body.appendChild(d)}
function load(path){
 if(cache[path])return cache[path].exports;
 var m={exports:{}};cache[path]=m;var src=F[path];
 if(/\.css$/.test(path))return m.exports;
 if(/\.json$/.test(path)){m.exports=JSON.parse(src);return m.exports}
 var presets=['react'];if(/\.tsx?$/.test(path))presets.unshift(['typescript',{allExtensions:true,isTSX:/x$/.test(path)}]);
 var code=Babel.transform(src,{filename:path,presets:presets,plugins:['transform-modules-commonjs']}).code;
 var req=function(r){if(EXTL[r])return EXTL[r];if(r.charAt(0)!=='.')throw new Error("Package '"+r+"' is not available (only react and react-dom)");var t=resolve(path,r);if(!t)throw new Error("Cannot resolve '"+r+"' from "+path);return load(t)};
 new Function('require','module','exports',code)(req,m,m.exports);
 return m.exports}
window.addEventListener('error',function(ev){fail(ev.error||ev.message)});
try{
 var entry=null,c=['src/main.jsx','src/main.js','src/main.tsx','src/index.jsx','src/index.js','src/index.tsx'];
 for(var i=0;i<c.length;i++){if(F[c[i]]!==undefined){entry=c[i];break}}
 if(entry){load(entry)}else{
  var ap=['src/App.jsx','src/App.js','src/App.tsx'].filter(function(x){return F[x]!==undefined})[0];
  var A=load(ap);A=A.default||A;ReactDOM.createRoot(document.getElementById('root')).render(React.createElement(A))}
}catch(e){fail(e)}
})();"""

_DEFAULT_SHELL = ('<!doctype html><html lang="en"><head><meta charset="UTF-8">'
                  '<meta name="viewport" content="width=device-width,initial-scale=1"><title>App</title></head>'
                  '<body><div id="root"></div></body></html>')

_HEADERS = {
    "Content-Security-Policy": "sandbox allow-scripts allow-forms allow-modals allow-popups allow-popups-to-escape-sandbox allow-downloads",
    "Access-Control-Allow-Origin": "*",
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
}

_MIME = {"html": "text/html", "htm": "text/html", "css": "text/css", "js": "text/javascript", "mjs": "text/javascript",
         "jsx": "text/javascript", "ts": "text/javascript", "tsx": "text/javascript", "json": "application/json",
         "svg": "image/svg+xml", "xml": "application/xml", "md": "text/plain", "txt": "text/plain"}


def _inject(doc: str) -> str:
    if re.search(r"<head[^>]*>", doc, re.I):
        return re.sub(r"(<head[^>]*>)", lambda m: m.group(1) + _SHIM, doc, count=1, flags=re.I)
    return _SHIM + doc


def _react_shell(files: dict[str, str]) -> str:
    base = files.get("index.html") or _DEFAULT_SHELL
    base = re.sub(r"<script\b[^>]*\bsrc=[\"'][^\"']*(?:main|index)\.[jt]sx?[\"'][^>]*>\s*</script>", "", base, flags=re.I)
    if not re.search(r"""id=["']root["']""", base):
        if re.search(r"<body[^>]*>", base, re.I):
            base = re.sub(r"(<body[^>]*>)", lambda m: m.group(1) + '<div id="root"></div>', base, count=1, flags=re.I)
        else:
            base += '<div id="root"></div>'
    css = "".join(f"<style>{c}</style>" for p, c in sorted(files.items()) if p.endswith(".css"))
    data = {p: c for p, c in files.items() if re.search(r"\.(jsx?|tsx?|json|css|mjs)$", p)}
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    scripts = (
        '<script crossorigin src="https://cdn.jsdelivr.net/npm/react@18/umd/react.production.min.js"></script>'
        '<script crossorigin src="https://cdn.jsdelivr.net/npm/react-dom@18/umd/react-dom.production.min.js"></script>'
        '<script src="https://cdn.jsdelivr.net/npm/@babel/standalone@7/babel.min.js"></script>'
        "<script>" + _REACT_LOADER.replace("__FILES__", payload) + "</script>"
    )
    if re.search(r"</head>", base, re.I):
        base = re.sub(r"</head>", lambda m: css + "</head>", base, count=1, flags=re.I)
    else:
        base = css + base
    if re.search(r"</body>", base, re.I):
        base = re.sub(r"</body>", lambda m: scripts + "</body>", base, count=1, flags=re.I)
    else:
        base += scripts
    return base


def _serve(files: dict[str, str], path: str):
    path = (path or "").strip("/") or "index.html"
    react = _is_react(files)
    if path == "index.html" and react:
        return HTMLResponse(_inject(_react_shell(files)), headers=_HEADERS)
    if path not in files and (path + "/index.html") in files:
        path += "/index.html"
    if path not in files:
        if react and "." not in path.rsplit("/", 1)[-1]:
            return HTMLResponse(_inject(_react_shell(files)), headers=_HEADERS)
        return HTMLResponse("<h3 style='font-family:sans-serif'>404 - file not found</h3>", status_code=404, headers=_HEADERS)
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    body = files[path]
    if ext in ("html", "htm"):
        return HTMLResponse(_inject(body), headers=_HEADERS)
    return Response(content=body, media_type=_MIME.get(ext, "text/plain"), headers=_HEADERS)


@app.get("/p/{token}")
async def _preview_redirect(token: str):
    return RedirectResponse(f"/p/{token}/")


@app.get("/p/{token}/{path:path}")
async def _preview_route(token: str, path: str = ""):
    files = _PREVIEWS.get(token)
    if files is None:
        return HTMLResponse("<h3 style='font-family:sans-serif'>Preview expired - generate again.</h3>", status_code=404)
    return _serve(files, path)


@app.get("/published/{slug}")
async def _published_redirect(slug: str):
    return RedirectResponse(f"/published/{slug}/")


@app.get("/published/{slug}/{path:path}")
async def _published_route(slug: str, path: str = ""):
    pub = db.get_publication_by_slug(slug)
    if not pub:
        return HTMLResponse("<h3 style='font-family:sans-serif'>Not found</h3>", status_code=404)
    rows = db.get_project_files(pub["project_id"])
    return _serve({r["path"]: r["content"] for r in rows}, path)


# ════════════════════════════════════════════════════════════════════
#  LLM ACCESS (app.main)
# ════════════════════════════════════════════════════════════════════

def _main_mod():
    for name in ("app.main", "__main__"):
        m = sys.modules.get(name)
        if m is not None and hasattr(m, "stream_llm"):
            return m
    return importlib.import_module("app.main")


_MODEL_CACHE: list[str] = []


async def _load_models() -> list[str]:
    global _MODEL_CACHE
    if _MODEL_CACHE:
        return _MODEL_CACHE
    try:
        m = _main_mod()
        ids = await m.discover_models()
        if not ids:
            ids = list(m.configured_model_options().keys())
    except Exception:
        ids = []
    _MODEL_CACHE = ids
    return ids


def _resolve_model(sel: str | None) -> str:
    if sel and sel != "default":
        return sel
    try:
        return getattr(_main_mod(), "selected_model", "Auto") or "Auto"
    except Exception:
        return "Auto"


def _model_arg(sel: str | None):
    return None if (not sel or sel == "default") else sel


async def _stream_text(messages, sel, on_chunk=None) -> str:
    stream = _main_mod().stream_llm
    raw = ""
    async for chunk in stream(messages, model=_model_arg(sel)):
        raw += chunk
        if on_chunk:
            on_chunk(raw, chunk)
    return raw


# ════════════════════════════════════════════════════════════════════
#  SMALL UI HELPERS (icons / buttons)
# ════════════════════════════════════════════════════════════════════

ICONS = {
    "clip": '<path d="M21 11.5l-8.6 8.6a5 5 0 0 1-7.1-7.1l8.6-8.6a3.3 3.3 0 0 1 4.7 4.7l-8.6 8.6a1.7 1.7 0 0 1-2.4-2.4l7.9-7.9"/>',
    "cloud": '<path d="M16 16l-4-4-4 4M12 12v9"/><path d="M20.4 18.5A5 5 0 0 0 18 9h-1.3A8 8 0 1 0 4 16.3"/>',
    "up": '<path d="M12 19V5M5 12l7-7 7 7"/>',
    "eye": '<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    "code": '<path d="M16 18l6-6-6-6M8 6l-6 6 6 6"/>',
    "globe": '<circle cx="12" cy="12" r="10"/><path d="M2 12h20M12 2a15 15 0 0 1 0 20M12 2a15 15 0 0 0 0 20"/>',
    "copy": '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h9"/>',
    "ext": '<path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
    "refresh": '<path d="M21 12a9 9 0 1 1-3-6.7L21 8M21 3v5h-5"/>',
    "full": '<path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7"/>',
    "x": '<path d="M18 6L6 18M6 6l12 12"/>',
    "lock": '<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
    "unlock": '<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 7.5-1.5"/>',
    "pad": '<rect x="2" y="6" width="20" height="12" rx="6"/><path d="M6 12h4M8 10v4M15 13h.01M18 11h.01"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/>',
    "folder": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "file": '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>',
    "dl": '<path d="M12 3v12M7 10l5 5 5-5M4 21h16"/>',
    "gh": '<path d="M9 19c-4 1.3-4-2-6-2.5m12 5v-3.5a3 3 0 0 0-.8-2.3c2.8-.3 5.8-1.4 5.8-6.2A4.8 4.8 0 0 0 18.7 4.8 4.5 4.5 0 0 0 18.6 1.5S17.5 1.2 15 2.9a12 12 0 0 0-6 0C6.5 1.2 5.4 1.5 5.4 1.5a4.5 4.5 0 0 0-.1 3.3A4.8 4.8 0 0 0 4 8.2c0 4.8 3 5.9 5.8 6.2A3 3 0 0 0 9 16.7V21"/>',
    "panel": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/>',
    "term": '<path d="M4 17l6-6-6-6M12 19h8"/>',
    "down": '<path d="M6 9l6 6 6-6"/>',
    "right": '<path d="M9 6l6 6-6 6"/>',
    "pen": '<path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>',
    "trophy": '<path d="M8 21h8M12 17v4M7 4h10v5a5 5 0 0 1-10 0z"/><path d="M17 5h3v2a3 3 0 0 1-3 3M7 5H4v2a3 3 0 0 0 3 3"/>',
    "spark": '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/>',
    "check": '<path d="M20 6L9 17l-5-5"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "menu": '<path d="M3 12h18M3 6h18M3 18h18"/>',
}

TYPE_SVG = ('<svg viewBox="0 0 44 30" width="44" height="30"><rect width="44" height="30" rx="4" fill="#d5e6e3"/>'
            '<rect width="44" height="7" rx="3" fill="#a4c8c4"/><circle cx="5" cy="3.5" r="1.2" fill="#fff"/>'
            '<circle cx="9" cy="3.5" r="1.2" fill="#fff"/><rect x="6" y="11" width="20" height="3.2" rx="1.6" fill="#22322f"/>'
            '<rect x="12" y="17" width="26" height="3.2" rx="1.6" fill="#22322f"/><rect x="8" y="23" width="18" height="3" rx="1.5" fill="#22322f"/></svg>')

CLOUD_SVG = ('<svg viewBox="0 0 170 140" width="170" height="140"><defs><linearGradient id="dacg" x1="0" y1="0" x2="0" y2="1">'
             '<stop offset="0" stop-color="#f1f5fc"/><stop offset="1" stop-color="#b7c7e2"/></linearGradient></defs>'
             '<g fill="url(#dacg)"><circle cx="58" cy="62" r="24"/><circle cx="86" cy="46" r="30"/><circle cx="116" cy="64" r="24"/>'
             '<rect x="46" y="62" width="92" height="26" rx="13"/></g>'
             '<circle class="dd d1" cx="70" cy="66" r="6" fill="#3b4451"/><circle class="dd d2" cx="92" cy="66" r="6" fill="#3b4451"/>'
             '<circle class="dd d3" cx="114" cy="66" r="6" fill="#3b4451"/>'
             '<circle cx="120" cy="106" r="11" fill="#c2d0e8"/><circle cx="100" cy="116" r="6" fill="#c9d6ec"/><circle cx="88" cy="123" r="3.5" fill="#d3ddf0"/></svg>')


def _svg(name: str, size: int = 18, sw: float = 1.8) -> str:
    return (f'<svg viewBox="0 0 24 24" width="{size}" height="{size}" fill="none" stroke="currentColor" '
            f'stroke-width="{sw}" stroke-linecap="round" stroke-linejoin="round">{ICONS[name]}</svg>')


def _html(content: str = ""):
    try:
        return ui.html(content, sanitize=False)  # NiceGUI 3
    except TypeError:
        return ui.html(content)


def _icon(name: str, size: int = 18, cls: str = ""):
    return _html(_svg(name, size)).classes(f"da-ic {cls}".strip())


def _div(cls: str = ""):
    return ui.element("div").classes(cls)


def _show(el, flag: bool) -> None:
    if el is None:
        return
    if flag:
        el.classes(remove="da-off")
    else:
        el.classes(add="da-off")


def _cls(el, name: str, flag: bool) -> None:
    if el is None:
        return
    if flag:
        el.classes(add=name)
    else:
        el.classes(remove=name)


def _btn(cls: str, icon: str | None = None, text: str | None = None, on_click=None, title: str = "", size: int = 18, js: str | None = None):
    b = ui.element("button").classes(f"da-btn {cls}".strip())
    b._props["type"] = "button"
    if title:
        b._props["title"] = title
    if on_click:
        b.on("click", on_click)
    if js:
        b.on("click", js_handler=js)
    with b:
        if icon:
            _icon(icon, size)
        if text:
            ui.label(text).classes("da-bt")
    return b


def _set(el, text: str) -> None:
    if el is None:
        return
    try:
        el.set_text(text)
    except Exception:
        pass


def _download_bytes(data: bytes, name: str) -> None:
    try:
        ui.download(data, name)
    except TypeError:
        ui.download.content(data, name)


async def _read_upload(e):
    if hasattr(e, "content"):
        return e.name, (e.type or ""), e.content.read()
    f = e.file
    return f.name, (getattr(f, "content_type", "") or ""), await f.read()


def _user_display() -> tuple[str, str]:
    try:
        from nicegui.context import context as _ctx
        s = _ctx.client.storage
        name = s.get("display_name") or ""
        if s.get("user_id") and name:
            return name, name[:1].upper()
    except Exception:
        pass
    return "Guest", "G"


# ════════════════════════════════════════════════════════════════════
#  STYLESHEET + JS  (poora custom, koi predefined css nahi)
# ════════════════════════════════════════════════════════════════════

FONT_LINK = ('<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
             '<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Newsreader:ital,opsz,wght@0,6..72,400;0,6..72,500;0,6..72,600;1,6..72,400&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">')

ARENA_CSS = r"""
:root{--bg:#f7f6f4;--card:#fffefd;--ink:#1c1b19;--ink2:#4d4b46;--mute:#8b8882;--line:#e6e3dc;--line2:#d6d2c9;
--teal:#79aaa5;--tealD:#3f7c77;--tealBg:#e5f1ef;--bub:#ece9e4;--tab:#e9e7e2;--sel:#dfeceb;
--serif:'Newsreader','Iowan Old Style',Georgia,serif;--sans:'Inter',system-ui,-apple-system,'Segoe UI',sans-serif;
--mono:'JetBrains Mono',ui-monospace,Consolas,monospace}
html,body{margin:0;height:100%;background:var(--bg);overflow:hidden}
body{font-family:var(--sans);color:var(--ink);-webkit-font-smoothing:antialiased}
.q-page,.nicegui-content{padding:0!important;margin:0!important;min-height:100vh!important;max-width:none!important;width:100%!important;gap:0!important}
.nicegui-content{display:block!important}
.da-off{display:none!important}
.da-app{position:fixed;inset:0;background:var(--bg);overflow:hidden}
.da-app *{box-sizing:border-box}
.da-ic{display:inline-flex;align-items:center;justify-content:center;flex:none;line-height:0}
.da-bt{display:inline;line-height:1.2}

/* generic button */
.da-btn{font-family:inherit;cursor:pointer;display:inline-flex;align-items:center;justify-content:center;gap:8px;border:1px solid var(--line);
background:#fff;color:var(--ink2);border-radius:12px;height:44px;padding:0 14px;font-size:15px;font-weight:500;transition:.15s;outline:none}
.da-btn:hover{background:#f3f1ed;color:var(--ink)}
.da-btn:focus-visible{box-shadow:0 0 0 3px rgba(121,170,165,.45)}
.da-btn.is-disabled{opacity:.45;pointer-events:none}
.da-round{width:44px;height:44px;padding:0;border-radius:50%;background:transparent;color:#6b6963}
.da-sq{width:48px;height:48px;padding:0;border-radius:12px}
.da-flat{border-color:transparent;background:transparent}

/* header & responsive nav */
.da-top{height:76px;flex:0 0 76px;display:flex;align-items:center;justify-content:space-between;padding:0 40px;position:sticky;top:0;z-index:100;background:rgba(247,246,244,0.85);backdrop-filter:blur(10px)}
.da-brand{display:flex;align-items:baseline;gap:9px;cursor:pointer;user-select:none}
.da-brand .b1{font-family:var(--serif);font-size:28px;font-weight:500;letter-spacing:-.5px}
.da-brand .b2{font-size:13px;color:var(--mute);display:inline-flex;align-items:center;gap:5px;font-family:var(--serif)}
.da-nav-wrap{display:flex;align-items:center;gap:16px}
.da-nav-menu{display:flex;align-items:center;gap:28px}
.da-nl{font-family:inherit;font-size:16px;color:var(--ink2);cursor:pointer;display:inline-flex;align-items:center;gap:8px;background:none;border:0;padding:6px 0}
.da-nl:hover{color:var(--ink)}
.da-menu-btn{display:none;background:transparent;border:none;cursor:pointer;color:var(--ink);padding:8px;margin-right:-8px}

@media(max-width:900px){
  .da-menu-btn{display:inline-flex}
  .da-nav-menu{display:flex;flex-direction:column;position:absolute;top:76px;left:0;right:0;background:#fff;padding:24px;border-bottom:1px solid var(--line);box-shadow:0 10px 20px rgba(0,0,0,0.08);clip-path:inset(0 0 100% 0);opacity:0;pointer-events:none;transition:0.3s;align-items:center;gap:16px}
  .da-nav-menu.open{clip-path:inset(0 0 0 0);opacity:1;pointer-events:auto}
  .da-work.split .da-nav-wrap{display:none}
}

/* home */
.da-home{position:absolute;inset:0;display:flex;flex-direction:column;overflow-y:auto}
.da-hero{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:20px 24px 48px;min-height:560px}
.da-h1{font-family:var(--serif);font-size:56px;font-weight:500;letter-spacing:-1.3px;margin:0 0 14px;text-align:center;line-height:1.05}
.da-sub{display:flex;align-items:center;gap:9px;color:var(--mute);font-size:16px;margin-bottom:34px}
.da-sub b{font-family:var(--serif);font-weight:500;color:#3a3935;font-size:18px}
.da-dot{width:4px;height:4px;border-radius:50%;background:var(--mute)}
.da-box{width:min(860px,92vw);border:1px solid var(--line2);border-radius:24px;background:#fff;padding:12px 18px;box-shadow:0 4px 20px rgba(0,0,0,0.03);transition:all 0.2s ease;display:flex;flex-direction:column}
.da-box:focus-within{border-color:var(--teal);box-shadow:0 6px 25px rgba(121,170,165,0.15)}
.da-field{width:100%}
.da-field .q-field__control{background:transparent!important;padding:0!important;height:auto!important;min-height:0!important}
.da-field .q-field__control:before,.da-field .q-field__control:after{display:none!important}
.da-field .q-field__native{padding:0!important;min-height:0!important}
.da-field.q-field--disabled{opacity:1!important}
.da-ta{font-family:var(--sans)!important;font-size:17px!important;line-height:1.5!important;color:var(--ink)!important;min-height:26px!important;max-height:300px!important;padding:4px 0!important;resize:none!important;overflow-y:auto!important}
.da-ta::placeholder{color:#a4a19a!important;opacity:1!important}
.da-tools{display:flex;align-items:flex-end;justify-content:space-between;margin-top:8px}
.da-tools-l{display:flex;gap:4px;align-items:center}
.da-send{width:40px;height:40px;padding:0;border-radius:50%;background:#e9e7e3;border:1px solid var(--line);color:#8c8a85;margin-bottom:2px}
.da-send:hover{background:var(--teal);color:#fff;border-color:var(--teal)}
.da-attached{display:flex;flex-wrap:wrap;gap:8px;margin-top:6px}
.da-attached:empty{display:none}
.da-att{display:inline-flex;align-items:center;gap:8px;border:1px solid var(--line);background:#fff;border-radius:999px;padding:5px 8px 5px 12px;font-size:13px;color:var(--ink2)}
.da-att .da-btn{height:22px;width:22px;padding:0;border-radius:50%;border:0}
.da-modes{display:flex;gap:12px;margin-top:22px;flex-wrap:wrap;justify-content:center}
.da-mode,.da-type{display:inline-flex;align-items:center;gap:10px;border:1px solid var(--line);background:#fbfaf8;border-radius:12px;padding:7px 18px 7px 8px;cursor:pointer;font-size:16px;color:#8d8a84;transition:.15s}
.da-mode:hover{background:#f1efea}
.da-mode.on,.da-type.on{background:#e8e6e1;color:var(--ink);border-color:#cfcbc2;font-weight:500}
.da-sugs{display:flex;flex-wrap:wrap;gap:10px;justify-content:center;margin-top:20px;max-width:900px}
.da-sug{font-family:inherit;border:1px solid var(--line);background:#fff;border-radius:999px;padding:8px 16px;font-size:13.5px;color:var(--ink2);cursor:pointer;transition:.15s}
.da-sug:hover{border-color:var(--teal);color:var(--ink)}
.da-recent{width:min(860px,92vw);margin-top:38px}
.da-recent-h{font-family:var(--serif);font-size:20px;margin-bottom:12px;color:var(--ink)}
.da-rgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:12px}
.da-rc{border:1px solid var(--line);background:#fff;border-radius:14px;padding:14px 16px;cursor:pointer;font-size:14px;color:var(--ink2);display:flex;align-items:center;gap:10px;transition:.2s;box-shadow:0 4px 15px rgba(0,0,0,0.02)}
.da-rc:hover{border-color:var(--teal);background:#fbfdfc;transform:translateY(-2px);box-shadow:0 8px 25px rgba(0,0,0,0.06)}
.da-rc .nm{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1}
.da-rc .pill{font-size:11px;color:var(--tealD);background:var(--tealBg);border-radius:999px;padding:2px 8px}

/* work layout */
.da-work{position:absolute;inset:0;display:flex;--chat-w:42%}
.da-chatcol{flex:1 1 auto;min-width:0;display:flex;flex-direction:column;background:var(--bg)}
.da-work.split .da-chatcol{flex:0 0 var(--chat-w)}
.da-work.split .da-nav-wrap,.da-work.split .da-titlebar,.da-work.split .da-banner{display:none}
.da-work.split .da-top{padding:0 26px}
.da-titlebar{flex:0 0 54px;display:flex;align-items:center;padding:0 26px;font-size:18px;font-weight:500;border-top:1px solid var(--line);border-bottom:1px solid var(--line);background:#faf9f7}
.da-banner{flex:0 0 58px;display:flex;align-items:center;justify-content:center;gap:12px;background:var(--tealBg);color:var(--tealD);font-size:17px;cursor:pointer;border-bottom:1px solid #d3e5e2}
.da-banner:hover{background:#dcebe8}
.da-scroll{flex:1;min-height:0;overflow-y:auto;scrollbar-width:thin;scrollbar-color:#b9b6ae transparent}
.da-thread{max-width:900px;margin:0 auto;padding:22px 34px 30px;display:flex;flex-direction:column;gap:22px}
.da-work.split .da-thread{max-width:none;padding:10px 26px 24px}
.da-umsg{align-self:flex-end;max-width:78%;background:var(--bub);border-radius:22px;padding:15px 22px;font-size:17px;line-height:1.55;white-space:pre-wrap;overflow-wrap:anywhere}
.da-work.split .da-umsg{max-width:100%;font-size:16px;border-radius:20px}
.da-amsg{display:flex;flex-direction:column;gap:12px;padding-left:4px}
.da-q{font-size:19px;color:var(--ink)}
.da-types{display:flex;gap:12px;flex-wrap:wrap}
.da-type{cursor:default;padding:6px 16px 6px 6px}
.da-type:not(.on){opacity:.6}
.da-arow{display:flex;gap:16px;align-items:flex-start}
.da-orb{flex:none;width:22px;height:22px;margin:16px 0 0 4px;border:2.5px solid #cfe0dd;border-top-color:var(--tealD);border-radius:50%;animation:dasp 1s linear infinite}
.da-avatar{flex:none;width:36px;height:36px;margin-top:6px;color:var(--ink);display:flex;align-items:center;justify-content:center}
.da-card{flex:1;min-width:0;background:var(--card);border:1.5px solid #d3e3e0;border-radius:28px;padding:22px 26px;box-shadow:0 6px 28px rgba(60,90,85,.05);position:relative}
.da-card-t{font-size:17px;font-weight:600;margin-bottom:12px}
.da-art{display:flex;align-items:center;gap:12px;color:var(--tealD);font-size:18px;margin-bottom:10px}
.da-card-foot{display:flex;justify-content:space-between;align-items:center;gap:10px;color:#a29f98;font-size:17px}
.da-timer{font-family:var(--mono);font-size:13px;color:#8f8c85}
.da-prog{display:flex;flex-direction:column;gap:9px;margin-top:16px;padding-top:14px;border-top:1px dashed var(--line)}
.da-prow{display:flex;align-items:center;gap:10px;font-size:14px}
.da-pdot{width:11px;height:11px;border-radius:50%;border:2px solid #cfe0dd;border-top-color:var(--tealD);animation:dasp 1s linear infinite;flex:none}
.da-pdot.done{animation:none;border-color:var(--tealD);background:var(--tealD)}
.da-pdot.err{animation:none;border-color:#c96a5b;background:#c96a5b}
.da-pname{font-weight:600;min-width:74px}
.da-pst{color:var(--mute);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.da-seg{display:inline-flex;background:var(--bub);border-radius:999px;padding:4px;margin-bottom:16px}
.da-segb{padding:9px 24px;border-radius:999px;font-size:16px;color:var(--ink2);cursor:pointer;transition:.15s;user-select:none}
.da-segb.on{background:#fff;color:var(--ink);box-shadow:0 1px 5px rgba(0,0,0,.08);font-weight:500}
.da-cardrow{display:flex;gap:16px;align-items:flex-start;justify-content:space-between}
.da-cardl{min-width:0}
.da-cstatus{font-size:17px;margin:8px 0 6px}
.da-cmeta{font-size:13px;color:var(--mute);line-height:1.6}
.da-thumb{flex:none;width:196px;height:124px;border-radius:14px;overflow:hidden;background:#fff;border:1px solid var(--line);box-shadow:0 10px 26px rgba(0,0,0,.12);transform:rotate(3deg);position:relative;pointer-events:none}
.da-thumb-frame{position:absolute;left:0;top:0;width:1280px;height:800px;border:0;transform:scale(.153);transform-origin:0 0;background:#fff}
.da-bubble{align-self:flex-start;max-width:92%;background:var(--card);border:1px solid var(--line);border-radius:20px;padding:13px 18px;font-size:15px;line-height:1.55;overflow-wrap:anywhere;white-space:pre-wrap}
.da-bubble.ok{border-color:#cfe4dc;background:#f3faf7}
.da-bubble.bad{border-color:#eccbc4;background:#fdf5f3;color:#8a3a2c}
.da-pending{display:inline-flex;align-items:center;gap:10px;color:var(--mute);font-size:14px}
.da-retry{margin-top:12px;height:40px}

.da-dock{flex:none;padding:10px 26px 20px;max-width:1000px;width:100%;margin:0 auto;position:relative}
.da-work.split .da-dock{max-width:none}
.da-tray{display:flex;align-items:center;justify-content:space-between;gap:10px;background:var(--card);border:1px solid var(--line);border-radius:26px;padding:14px 18px 34px;margin-bottom:-24px}
.da-votebtn{height:66px;padding:0 24px;border-radius:33px;background:#fff;font-size:17px;font-weight:500;line-height:1.15;text-align:center;color:var(--ink)}
.da-votebtn:hover{border-color:var(--teal);background:#f7fbfa}
.da-trophy{color:#222}
.da-cbox{position:relative;width:100%;max-width:none;border:1px solid var(--line2);border-radius:24px;background:#fff;padding:12px 18px 12px;box-shadow:0 4px 20px rgba(0,0,0,.03)}
.da-cbox:focus-within{border-color:var(--teal);box-shadow:0 6px 25px rgba(121,170,165,.15)}
.da-cbox .da-tools{margin-top:8px}
.da-cbox .q-field--disabled .q-field__native,.da-cbox .q-field--disabled textarea{color:#a4a19a!important}

/* splitter + preview */
.da-splitter{display:none;flex:0 0 12px;cursor:col-resize;align-items:center;justify-content:center;background:var(--bg);border-left:1px solid var(--line)}
.da-splitter:after{content:'';width:4px;height:26px;background:radial-gradient(circle,#8b8882 1.4px,transparent 1.6px) center/4px 8px repeat-y}
.da-work.split .da-splitter{display:flex}
.da-prevcol{display:none;flex:1 1 0;min-width:0;flex-direction:column;background:var(--bg)}
.da-work.split .da-prevcol{display:flex}
.da-dragging iframe{pointer-events:none}
.da-dragging{cursor:col-resize;user-select:none}
.da-ptabs{flex:0 0 84px;display:flex;align-items:stretch;background:var(--tab)}
.da-ptab{display:flex;align-items:center;gap:12px;padding:0 20px;cursor:pointer;color:#5f5d57;transition:.15s;background:var(--tab)}
.da-ptab.on{background:var(--bg);color:var(--ink);font-weight:600}
.da-ptab .nm{font-size:19px;white-space:nowrap}
.da-vpill{font-family:inherit;height:46px;border-radius:23px;padding:0 20px;background:#fff;border:1px solid var(--line);font-size:17px;color:var(--ink);cursor:pointer;white-space:nowrap}
.da-vpill:hover{border-color:var(--teal)}
.da-ptabs .grow{flex:1;background:var(--tab)}
.da-xbtn{width:64px;background:var(--tab);border:0;cursor:pointer;color:#55534e;display:flex;align-items:center;justify-content:center}
.da-xbtn:hover{color:#000}
.da-toolbar{flex:0 0 84px;display:flex;align-items:center;gap:12px;padding:0 18px 0 16px;background:var(--bg)}
.da-mtog{display:flex;background:#fff;border:1px solid var(--line);border-radius:14px;padding:5px;gap:4px}
.da-mtog .da-btn{width:50px;height:42px;border:0;border-radius:10px;background:transparent;color:#77746e}
.da-mtog .da-btn.on{background:var(--bub);color:var(--ink)}
.da-vsep{width:1px;height:38px;background:var(--line2)}
.da-url{flex:1;min-width:0;height:52px;background:#fff;border:1px solid var(--line);border-radius:14px;display:flex;align-items:center;gap:10px;padding:0 8px 0 16px;color:#9a978f;font-style:italic;font-size:16px}
.da-url .u{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.da-url .da-btn{width:36px;height:36px;border:0;background:transparent;color:#a4a19a;padding:0}
.da-url.live{color:var(--ink2);font-style:normal}
.da-pub{height:52px;padding:0 20px;border-radius:14px;font-weight:500;color:#a8a59e}
.da-pub:not(.is-disabled){color:var(--ink);background:#fff}
.da-pub:not(.is-disabled):hover{background:var(--tealBg);border-color:var(--teal)}
.da-pbody{flex:1;min-height:0;position:relative;background:#dededc;border-top:1px solid var(--line)}
.da-fwrap{position:absolute;inset:0;background:#fff}
.da-frame{width:100%;height:100%;border:0;display:block;background:#fff}
.da-loader{position:absolute;inset:0;z-index:5;background:#dcdcda;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:16px;color:#66645e;font-size:14px}
.da-loader svg{animation:dafloat 3s ease-in-out infinite}
.da-loader .dd{animation:dadot 1.2s infinite}.da-loader .d2{animation-delay:.2s}.da-loader .d3{animation-delay:.4s}
.da-editpill{position:absolute;left:50%;bottom:26px;transform:translateX(-50%);z-index:6;height:54px;padding:0 26px;border-radius:27px;background:#fff;box-shadow:0 8px 26px rgba(0,0,0,.14);font-size:17px;color:#6d6a64}
.da-editpill.active{background:var(--tealD);color:#fff;border-color:var(--tealD)}

/* code explorer */
.da-codewrap{position:absolute;inset:0;display:flex;background:#fff}
.da-treecol{flex:0 0 310px;display:flex;flex-direction:column;background:var(--bg);border-right:1px solid var(--line);min-width:0}
.da-treecol.closed{display:none}
.da-thead{flex:none;display:flex;gap:8px;padding:12px;align-items:center}
.da-sbox{flex:1;min-width:0;display:flex;align-items:center;gap:8px;height:46px;border:1px solid var(--line);border-radius:12px;background:#f0eeea;color:#8b8882;padding:0 10px}
.da-search{flex:1;min-width:0}
.da-search .q-field__control{height:auto!important;min-height:0!important;padding:0!important;background:transparent!important}
.da-search .q-field__control:before,.da-search .q-field__control:after{display:none!important}
.da-search .q-field__native{padding:0!important;font-size:15px!important;color:var(--ink)!important;min-height:0!important}
.da-thead .da-btn{width:46px;height:46px;padding:0;border-radius:12px;background:#f0eeea;color:#77746e}
.da-tree{flex:1;overflow:auto;padding:4px 0 12px;font-size:15.5px;scrollbar-width:thin}
.da-tr{display:flex;align-items:center;gap:9px;height:38px;padding-right:10px;cursor:pointer;color:#3c3a36;white-space:nowrap;border-radius:0}
.da-tr:hover{background:#efede8}
.da-tr.on{background:var(--sel)}
.da-tr .da-ic{color:#8b8882}
.da-tr.dir{color:#2d2b27}
.da-editor{flex:1;min-width:0;display:flex;flex-direction:column;background:#fff}
.da-etabs{flex:none;display:flex;overflow-x:auto;background:#f6f5f2;border-bottom:1px solid var(--line);min-height:56px;scrollbar-width:none}
.da-etab{display:flex;align-items:center;gap:10px;padding:0 16px;font-size:16px;color:#66645e;cursor:pointer;border-right:1px solid var(--line);white-space:nowrap}
.da-etab.on{background:#fff;color:var(--ink);box-shadow:inset 0 -2px 0 var(--tealD)}
.da-etab .bd{font-size:11px;font-weight:700;color:#3b6ea8;letter-spacing:.2px}
.da-etab .da-btn{width:24px;height:24px;padding:0;border:0;background:transparent;border-radius:6px}
.da-code{flex:1;min-height:0;overflow:auto;background:#fff}
.da-empty{padding:40px;text-align:center;color:var(--mute);font-size:15px}
.da-cg{display:flex;min-width:max-content;font-family:var(--mono);font-size:15.5px;line-height:27px;padding:10px 0}
.da-gut{margin:0;padding:0 18px 0 22px;text-align:right;color:#2a5db0;user-select:none;position:sticky;left:0;background:#fff}
.da-src{margin:0;padding:0 24px 0 6px;color:#1f2933;white-space:pre;tab-size:2}
.da-src code{font-family:inherit}
.tc{color:#7a8a99;font-style:italic}.ts{color:#a14a2a}.tk{color:#8a2be2}.tn{color:#0b7a5b}.tt{color:#1f6fb5}.ta{color:#7a3e9d}
.da-term{flex:none;border-top:1px solid var(--line);background:#fff;display:flex;flex-direction:column;max-height:44%}
.da-term-h{height:52px;display:flex;align-items:center;gap:10px;padding:0 18px;cursor:pointer;font-size:16px;color:#3c3a36;flex:none}
.da-term-h .sp{flex:1}
.da-term-b{overflow:auto;padding:6px 18px 16px;min-height:130px;font-family:var(--mono);font-size:13.5px;background:#fbfaf8}
.da-term.closed .da-term-b{display:none}
.da-tnone{color:#aaa79f;text-align:center;font-family:var(--sans);margin-top:8px}
.da-term-b .da-ic{display:flex;margin:14px auto 0;color:#c5c2ba}
.da-tl{line-height:1.7;white-space:pre-wrap;overflow-wrap:anywhere;color:#55534e}
.da-tl.cmd{color:#1f2933;font-weight:500}.da-tl.ok{color:#2f7a5c}.da-tl.err{color:#b4483a}

/* modal */
.da-modal-bg{position:fixed;inset:0;z-index:50;background:rgba(28,27,25,.38);display:flex;align-items:center;justify-content:center;padding:20px}
.da-modal{width:min(720px,100%);max-height:86vh;overflow:auto;background:var(--bg);border-radius:24px;box-shadow:0 30px 80px rgba(0,0,0,.25);padding:26px 28px}
.da-modal-h{display:flex;align-items:center;justify-content:space-between;margin-bottom:16px}
.da-modal-h .t{font-family:var(--serif);font-size:28px;font-weight:500}
.da-mnote{color:var(--mute);font-size:14px;margin-bottom:14px}
.da-mcols{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.da-mh{font-weight:600;margin-bottom:8px}
.da-mlist{display:flex;flex-direction:column;gap:6px;max-height:48vh;overflow:auto;padding-right:4px}
.da-pill{font-family:inherit;text-align:left;border:1px solid var(--line);background:#fff;border-radius:12px;padding:9px 13px;font-size:14px;color:var(--ink2);cursor:pointer}
.da-pill:hover{border-color:var(--teal)}
.da-pill.on{background:var(--tealBg);border-color:var(--teal);color:var(--tealD);font-weight:600}
.da-lb{width:100%;border-collapse:collapse;font-size:15px}
.da-lb th{text-align:left;color:var(--mute);font-weight:500;padding:8px 10px;border-bottom:1px solid var(--line)}
.da-lb td{padding:12px 10px;border-bottom:1px solid var(--line)}
.da-lb .bar{height:7px;border-radius:4px;background:var(--tealBg);overflow:hidden;min-width:90px}
.da-lb .bar i{display:block;height:100%;background:var(--teal)}
.da-snake{display:block;margin:0 auto;border-radius:14px;border:1px solid var(--line);background:#f4f1ec;max-width:100%}
.da-score{text-align:center;margin-top:10px;color:var(--ink2);font-size:14px}
.da-up{position:fixed;left:-9999px;top:0;width:10px;height:10px;overflow:hidden}

@keyframes dasp{to{transform:rotate(360deg)}}
@keyframes dafloat{50%{transform:translateY(-8px)}}
@keyframes dadot{0%,100%{opacity:.35}50%{opacity:1}}
@media(prefers-reduced-motion:reduce){.da-orb,.da-pdot,.da-loader svg,.da-loader .dd{animation:none}}
@media(max-width:900px){
 .da-top{padding:0 18px}.da-h1{font-size:38px}.da-box{padding:12px 16px}
 .da-work.split{flex-direction:column;overflow-y:auto}
 .da-work.split .da-chatcol{flex:0 0 auto;height:70vh}
 .da-work.split .da-prevcol{min-height:100vh;flex:0 0 auto}
 .da-work.split .da-splitter{display:none}
 .da-nav-menu{gap:14px}.da-nl{font-size:14px}.da-treecol{flex-basis:200px}.da-mcols{grid-template-columns:1fr}
 .da-toolbar{flex-wrap:wrap;height:auto;padding:10px}.da-ptabs{flex-basis:auto;min-height:64px}.da-ptab .nm{font-size:15px}.da-vpill{font-size:13px;padding:0 12px;height:38px}
}
"""

ARENA_JS = r"""
<script>
window.daCopy=function(t){if(navigator.clipboard&&window.isSecureContext){navigator.clipboard.writeText(t)}else{var a=document.createElement('textarea');a.value=t;document.body.appendChild(a);a.select();try{document.execCommand('copy')}catch(e){}a.remove()}};
window.daFull=function(){var e=document.querySelector('.da-pbody');if(document.fullscreenElement)document.exitFullscreen();else if(e)e.requestFullscreen()};
window.daFrame=function(m){var f=document.querySelector('.da-frame');if(f&&f.contentWindow)f.contentWindow.postMessage(m,'*')};
window.daBottom=function(){setTimeout(function(){var s=document.querySelector('.da-scroll');if(s)s.scrollTop=s.scrollHeight},90)};
window.addEventListener('message',function(e){var d=e.data;if(d&&d.da==='html'){window.__daEdited={path:d.path,html:d.html}}});
document.addEventListener('keydown',function(e){var t=e.target;if(e.key==='Enter'&&!e.shiftKey&&t&&t.classList&&t.classList.contains('da-ta')){e.preventDefault();e.stopPropagation();var b=t.closest('.da-box');if(b){var s=b.querySelector('.da-send');if(s)s.click()}}},true);
(function(){var P=["Ask Design Arena to build a dashboard for tracking sales…","Build a responsive React beauty parlour website with an admin panel…","A real-estate site with listings, filters and a property admin…","A restaurant website with online menu and table booking…"];var i=0,j=0,del=false;
function tick(){var ta=document.querySelector('.da-home .da-ta');var wait=del?16:36;
if(ta&&!ta.value&&document.activeElement!==ta){var s=P[i];if(!del){j++;if(j>=s.length){del=true;wait=1500}}else{j--;if(j<=0){del=false;i=(i+1)%P.length;wait=300}}ta.placeholder=s.slice(0,j)+'|'}
setTimeout(tick,wait)}tick()})();
(function(){var drag=false;
document.addEventListener('mousedown',function(e){if(e.target.closest&&e.target.closest('.da-splitter')){drag=true;document.body.classList.add('da-dragging');e.preventDefault()}});
document.addEventListener('mousemove',function(e){if(!drag)return;var w=Math.max(320,Math.min(e.clientX,window.innerWidth-480));var k=document.querySelector('.da-work');if(k)k.style.setProperty('--chat-w',w+'px')});
document.addEventListener('mouseup',function(){drag=false;document.body.classList.remove('da-dragging')})})();
window.daSnake=function(){var c=document.getElementById('da-snake');if(!c)return;var x=c.getContext('2d'),N=20,S=c.width/N,sn=[{x:8,y:10}],d={x:1,y:0},f={x:14,y:10},sc=0;
function place(){f={x:Math.floor(Math.random()*N),y:Math.floor(Math.random()*N)}}
document.onkeydown=function(e){var m={ArrowUp:[0,-1],ArrowDown:[0,1],ArrowLeft:[-1,0],ArrowRight:[1,0]}[e.key];if(m&&!(m[0]==-d.x&&m[1]==-d.y)){d={x:m[0],y:m[1]};e.preventDefault()}};
if(window.__snk)clearInterval(window.__snk);
window.__snk=setInterval(function(){if(!document.getElementById('da-snake')){clearInterval(window.__snk);document.onkeydown=null;return}
var h={x:(sn[0].x+d.x+N)%N,y:(sn[0].y+d.y+N)%N};
if(sn.some(function(p){return p.x==h.x&&p.y==h.y})){sn=[{x:8,y:10}];sc=0}
sn.unshift(h);if(h.x==f.x&&h.y==f.y){sc++;place()}else sn.pop();
x.fillStyle='#f4f1ec';x.fillRect(0,0,c.width,c.height);x.fillStyle='#d9694f';x.fillRect(f.x*S+2,f.y*S+2,S-4,S-4);
sn.forEach(function(p,i){x.fillStyle=i?'#79aaa5':'#2f6f69';x.fillRect(p.x*S+1,p.y*S+1,S-2,S-2)});
var el=document.getElementById('da-score');if(el)el.textContent='Score: '+sc+'  ·  arrow keys se khelo'},110)};
</script>
"""


# ════════════════════════════════════════════════════════════════════
#  BUILDER PAGE
# ════════════════════════════════════════════════════════════════════

@ui.page("/builder", title="Design Arena")
def builder_page():
    ui.add_head_html(FONT_LINK + "<style>" + ARENA_CSS + "</style>")
    ui.add_body_html(ARENA_JS)

    user_name, user_initial = _user_display()

    S: dict = {
        "type": "website", "kind": "website", "status": "idle", "opt": "A", "view": "preview",
        "prompt": "", "title": "", "voted": None, "single": False, "refining": False, "editing": False,
        "models": {"A": "default", "B": "default"}, "mname": {"A": "Auto", "B": "Auto"},
        "files": {"A": {}, "B": {}}, "tokens": {"A": "", "B": ""}, "urls": {"A": "", "B": ""},
        "pids": {"A": None, "B": None}, "tabs": {"A": [], "B": []}, "sel": {"A": None, "B": None},
        "logs": {"A": [], "B": []}, "prog": {}, "chat": [], "attach": [],
        "collapsed": set(), "filter": "", "term_open": True, "tree_open": True,
        "t0": 0.0, "phrase_i": 0, "ver": 1, "loading": False,
    }
    R: dict = {}

    # ─────────────────────────── helpers ───────────────────────────
    def _frame_url(opt: str) -> str:
        return f"/p/{S['tokens'][opt]}/?v={S['ver']}"

    def _wait_page(opt: str) -> str:
        return ("<body style='margin:0;display:grid;place-items:center;height:100vh;font-family:system-ui;color:#777;background:#fafafa'>"
                f"<div>Option {opt} is being generated…</div></body>")

    def _log(opt: str, line: str) -> None:
        S["logs"][opt].append(line)

    def _scroll_bottom() -> None:
        ui.run_javascript("daBottom()")

    # ─────────────────────────── persistence ───────────────────────────
    def _persist(opt: str):
        files = S["files"][opt]
        if not files:
            return None
        name = f"{S['title'] or 'Website'} ({opt})"[:80]
        pid = S["pids"][opt]
        if pid is None:
            pid = db.create_project(name=name)
            S["pids"][opt] = pid
        else:
            db.update_project_name(pid, name)
        for p, c in files.items():
            db.save_project_file(pid, p, c)
        return pid

    def _refresh_stats() -> None:
        try:
            n_proj = len(db.get_all_projects())
        except Exception:
            n_proj = 0
        _set(R.get("stats"), f"{len(_load_votes())} votes • {n_proj} saved designs")

    # ─────────────────────────── recents / attach ───────────────────────────
    def _render_recent() -> None:
        box = R.get("recent")
        if box is None:
            return
        box.clear()
        try:
            projects = list(db.get_all_projects())[:6]
        except Exception:
            projects = []
        _show(box, bool(projects))
        if not projects:
            return
        with box:
            ui.label("Recent designs").classes("da-recent-h")
            with _div("da-rgrid"):
                for p in projects:
                    rc = _div("da-rc")
                    rc.on("click", lambda _e=None, pid=p["id"]: _open_saved(pid))
                    with rc:
                        _icon("folder", 18)
                        ui.label(str(p.get("name", "Untitled"))).classes("nm")
                        ui.label("open").classes("pill")

    def _render_attach() -> None:
        box = R["attached"]
        box.clear()
        with box:
            for i, a in enumerate(S["attach"]):
                with _div("da-att"):
                    ui.label(a["name"])
                    _btn("", "x", on_click=lambda _e=None, i=i: _remove_attach(i), size=13, title="Remove")

    def _remove_attach(i: int) -> None:
        if 0 <= i < len(S["attach"]):
            S["attach"].pop(i)
            _render_attach()

    async def _on_ref_upload(e):
        try:
            name, mime, data = await _read_upload(e)
            ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
            if ext in ("png", "jpg", "jpeg", "webp", "gif"):
                import base64
                S["attach"].append({"name": name, "kind": "image",
                                    "data_url": f"data:{mime or 'image/png'};base64,{base64.b64encode(data).decode()}"})
            else:
                S["attach"].append({"name": name, "kind": "text", "text": data.decode("utf-8", "replace")[:40000]})
            _render_attach()
        except Exception as exc:
            ui.notify(f"Attach failed: {exc}", type="negative")

    async def _on_import_upload(e):
        try:
            name, _mime, data = await _read_upload(e)
            if name.lower().endswith(".zip"):
                files = _read_zip(data)
            else:
                p = _clean_path(name) or "index.html"
                files = {("index.html" if p.endswith((".htm", ".html")) else p): data.decode("utf-8", "replace")}
            if not files:
                raise ValueError("koi supported file nahi mili")
            _open_files(files, title=Path(name).stem.replace("-", " ").title() or "Imported site")
        except Exception as exc:
            ui.notify(f"Import failed: {exc}", type="negative")

    # ─────────────────────────── modal ───────────────────────────
    def _close_modal() -> None:
        m = R.pop("modal", None)
        if m is not None:
            try:
                m.delete()
            except Exception:
                pass
        ui.run_javascript("clearInterval(window.__snk);document.onkeydown=null")

    def _open_modal(title: str, fill) -> None:
        _close_modal()
        with R["root"]:
            bg = _div("da-modal-bg")
            with bg:
                with _div("da-modal"):
                    with _div("da-modal-h"):
                        ui.label(title).classes("t")
                        _btn("da-round", "x", on_click=_close_modal, title="Close")
                    body = _div("da-modal-body")
                    fill(body)
        R["modal"] = bg

    def _open_board() -> None:
        def fill(body):
            rows = _leaderboard()
            with body:
                if not rows:
                    ui.label("Abhi koi head-to-head vote nahi hai. Models me Option A aur B ke liye alag alag model choose karo, "
                             "generate karo aur vote do — leaderboard yahin banega.").classes("da-mnote")
                    return
                out = ['<table class="da-lb"><tr><th>#</th><th>Model</th><th>Win rate</th><th>Wins</th><th>Battles</th></tr>']
                for i, (m, w, n, pct) in enumerate(rows, 1):
                    out.append(f'<tr><td>{i}</td><td>{html_mod.escape(m)}</td><td><div class="bar"><i style="width:{pct}%"></i></div> {pct}%</td><td>{w}</td><td>{n}</td></tr>')
                out.append("</table>")
                _html("".join(out))
        _open_modal("Leaderboards", fill)

    async def _open_models() -> None:
        ids = await _load_models()
        options = ["default"] + ids

        def render_lists():
            for o in "AB":
                lst = R.get(f"mlist_{o}")
                if lst is None:
                    continue
                lst.clear()
                with lst:
                    for mid in options:
                        b = ui.element("button").classes("da-pill" + (" on" if S["models"][o] == mid else ""))
                        b._props["type"] = "button"
                        b.on("click", lambda _e=None, o=o, mid=mid: _pick_model(o, mid))
                        with b:
                            ui.label("Default (chat model)" if mid == "default" else mid)

        def _pick_model(o, mid):
            S["models"][o] = mid
            render_lists()

        def fill(body):
            with body:
                ui.label("Har option ke liye model chuno. Alag models rakhoge to vote leaderboard me count hoga.").classes("da-mnote")
                with _div("da-mcols"):
                    for o in "AB":
                        with _div("da-mcol"):
                            ui.label(f"Option {o}").classes("da-mh")
                            R[f"mlist_{o}"] = _div("da-mlist")
            render_lists()

        _open_modal("Models", fill)

    def _open_snake() -> None:
        def fill(body):
            with body:
                _html('<canvas id="da-snake" class="da-snake" width="360" height="360"></canvas><div id="da-score" class="da-score">Score: 0</div>')
        _open_modal("Play while you wait", fill)
        with R["root"]:
            ui.timer(0.3, lambda: ui.run_javascript("daSnake()"), once=True)

    # ─────────────────────────── chat rendering ───────────────────────────
    def _render_chat() -> None:
        box = R["thread"]
        box.clear()
        with box:
            with _div("da-umsg"):
                ui.label(S["prompt"])
            if not S["single"]:
                with _div("da-amsg"):
                    ui.label("What would you like to create?").classes("da-q")
                    with _div("da-types"):
                        for k, lab in KINDS.items():
                            with _div("da-type" + (" on" if k == S["kind"] else "")):
                                _html(TYPE_SVG)
                                ui.label(lab)
            st = S["status"]
            if st == "generating":
                _gen_card()
            elif st == "ready":
                _ready_card()
            elif st == "failed":
                _fail_card()
            for m in S["chat"]:
                cls = "da-bubble" + (" ok" if m.get("tone") == "ok" else " bad" if m.get("tone") == "bad" else "")
                if m["role"] == "user":
                    with _div("da-umsg"):
                        ui.label(m["text"])
                else:
                    with _div(cls):
                        ui.label(m["text"])
            if S["refining"]:
                with _div("da-pending"):
                    _div("da-pdot")
                    ui.label("Applying your changes…")
        _scroll_bottom()

    def _gen_card() -> None:
        with _div("da-arow"):
            _div("da-orb")
            with _div("da-card"):
                ui.label("Generating websites…").classes("da-card-t")
                with _div("da-art"):
                    _html(TYPE_SVG)
                    ui.label(f"{KINDS[S['kind']]} artifact")
                with _div("da-card-foot"):
                    R["phrase"] = ui.label(PHRASES[S["phrase_i"] % len(PHRASES)])
                    R["timer"] = ui.label(f"{max(time.time() - S['t0'], 0):.1f}s").classes("da-timer")
                with _div("da-prog"):
                    for o in "AB":
                        with _div("da-prow"):
                            R[f"pdot_{o}"] = _div("da-pdot")
                            ui.label(f"Option {o}").classes("da-pname")
                            R[f"pst_{o}"] = ui.label("Queued").classes("da-pst")
        _tick(force=True)

    def _ready_card() -> None:
        opt = S["opt"]
        P = S["prog"].get(opt, {})
        files = S["files"][opt]
        with _div("da-arow"):
            with _div("da-avatar"):
                _icon("trophy", 30, "")
            with _div("da-card"):
                if not S["single"]:
                    with _div("da-seg"):
                        for o in "AB":
                            sb = _div("da-segb" + (" on" if o == opt else ""))
                            sb.on("click", lambda _e=None, o=o: _switch_opt(o))
                            with sb:
                                ui.label(f"Option {o}")
                with _div("da-cardrow"):
                    with _div("da-cardl"):
                        with _div("da-art"):
                            _html(TYPE_SVG)
                            ui.label(f"{KINDS[S['kind']]} artifact")
                        bad = P.get("state") == "error"
                        ui.label("Failed - check the terminal" if bad else "Deployed successfully").classes("da-cstatus")
                        meta = f"{len(files)} files"
                        if P.get("dur"):
                            meta += f" · {P['dur']:.1f}s"
                        if S["voted"] or S["single"]:
                            meta += f" · {S['mname'][opt]}"
                        ui.label(meta).classes("da-cmeta")
                    if not bad and S["tokens"][opt]:
                        with _div("da-thumb"):
                            fr = ui.element("iframe").classes("da-thumb-frame")
                            fr._props["src"] = _frame_url(opt)
                            fr._props["sandbox"] = SANDBOX
                            fr._props["tabindex"] = "-1"

    def _fail_card() -> None:
        with _div("da-arow"):
            with _div("da-card"):
                ui.label("Generation failed").classes("da-card-t")
                errs = [S["prog"][o].get("error", "") for o in "AB" if S["prog"][o].get("error")]
                ui.label(" | ".join(errs)[:500] or "Model ne koi valid file nahi di.").classes("da-cmeta")
                ui.label("LLM service chal rahi hai ya nahi check karo, phir dobara try karo.").classes("da-cmeta")
                _btn("da-retry", text="Try again", on_click=lambda: _start(S["prompt"]))

    def _render_tray() -> None:
        t = R["tray"]
        t.clear()
        show = S["status"] == "ready" and not S["voted"] and not S["single"]
        _show(t, show)
        if not show:
            return
        with t:
            _btn("da-votebtn", text="Option A is better", on_click=lambda: _vote("A"))
            _icon("trophy", 32, "da-trophy")
            _btn("da-votebtn", text="Option B is better", on_click=lambda: _vote("B"))

    def _sync_input() -> None:
        st = S["status"]
        can = st == "ready" and (bool(S["voted"]) or S["single"]) and not S["refining"]
        if st == "generating":
            ph = "The agent is generating your creation…"
        elif S["refining"]:
            ph = "Applying your changes…"
        elif st == "ready" and not can:
            ph = "Vote on the design above first…"
        else:
            ph = "Ask for changes - e.g. make the hero darker, add a pricing section…"
        inp = R["inp2"]
        inp._props["placeholder"] = ph
        inp.set_enabled(can)
        inp.update()
        _cls(R["send2"], "is-disabled", not can)

    # ─────────────────────────── tabs / url / publish ───────────────────────────
    def _sync_tabs() -> None:
        can_vote = S["status"] == "ready" and not S["voted"] and not S["single"]
        for o in "AB":
            _cls(R[f"ptab_{o}"], "on", S["opt"] == o)
            _show(R[f"vote_{o}"], can_vote)
            label = f"Option {o}"
            if S["voted"] or S["single"]:
                label += f" · {S['mname'][o]}"
                if S["voted"] == o:
                    label += " ✓"
            _set(R[f"ptxt_{o}"], label)
        _show(R["ptab_B"], not S["single"])

    def _sync_url() -> None:
        o = S["opt"]
        url = S["urls"][o]
        if url:
            txt = url
        elif S["voted"] or S["single"]:
            txt = f"Publish Option {o} to get link"
        else:
            txt = "Vote to get link"
        _set(R["url_txt"], txt)
        _cls(R["url"], "live", bool(url))

    def _sync_publish() -> None:
        enabled = S["status"] == "ready" and (bool(S["voted"]) or S["single"])
        _cls(R["pub"], "is-disabled", not enabled)
        _set(R["pub_lbl"], "Update" if S["urls"][S["opt"]] else "Publish")
        _show(R["pub_lock"], not enabled)
        _show(R["pub_open"], enabled)

    def _set_loading(flag: bool) -> None:
        S["loading"] = flag
        _show(R.get("loader"), flag)

    def _load_frame() -> None:
        f = R["frame"]
        f._props["src"] = _frame_url(S["opt"])
        f.update()
        _set_loading(True)
        with R["pbody"]:
            ui.timer(7, lambda: _set_loading(False), once=True)

    def _set_view(mode: str) -> None:
        S["view"] = mode
        _show(R["fwrap"], mode == "preview")
        _show(R["codewrap"], mode == "code")
        _cls(R["m_eye"], "on", mode == "preview")
        _cls(R["m_code"], "on", mode == "code")
        _show(R["editpill"], mode == "preview" and S["status"] == "ready")
        if mode == "code":
            _set_loading(False)

    def _switch_opt(o: str) -> None:
        if o not in "AB" or (S["single"] and o == "B"):
            return
        S["opt"] = o
        S["editing"] = False
        _sync_tabs()
        _render_chat()
        _render_tree()
        _render_editor()
        _render_term()
        _sync_url()
        _sync_publish()
        _reset_edit_btn()
        _load_frame()

    # ─────────────────────────── code explorer ───────────────────────────
    def _open_file(p: str) -> None:
        o = S["opt"]
        if p not in S["tabs"][o]:
            S["tabs"][o].append(p)
        S["sel"][o] = p
        _render_tree()
        _render_editor()

    def _close_tab(p: str) -> None:
        o = S["opt"]
        tabs = S["tabs"][o]
        if p in tabs:
            i = tabs.index(p)
            tabs.remove(p)
            if S["sel"][o] == p:
                S["sel"][o] = tabs[min(i, len(tabs) - 1)] if tabs else None
        _render_tree()
        _render_editor()

    def _toggle_dir(dp: str) -> None:
        if dp in S["collapsed"]:
            S["collapsed"].discard(dp)
        else:
            S["collapsed"].add(dp)
        _render_tree()

    def _on_filter(v) -> None:
        S["filter"] = (v or "").strip().lower()
        _render_tree()

    def _render_tree() -> None:
        box = R["tree"]
        box.clear()
        files = S["files"][S["opt"]]
        sel = S["sel"][S["opt"]]
        with box:
            rows = _flatten(sorted(files), S["collapsed"], S["filter"])
            if not rows:
                ui.label("No files").classes("da-empty")
            for depth, kind, path, name in rows:
                tr = _div("da-tr" + (" dir" if kind == "dir" else "") + (" on" if kind == "file" and path == sel else ""))
                tr.style(f"padding-left:{14 + depth * 18}px")
                if kind == "dir":
                    tr.on("click", lambda _e=None, dp=path: _toggle_dir(dp))
                else:
                    tr.on("click", lambda _e=None, p=path: _open_file(p))
                with tr:
                    if kind == "dir":
                        _icon("down" if (path not in S["collapsed"] or S["filter"]) else "right", 15)
                        _icon("folder", 18)
                    else:
                        _icon("file", 18)
                    ui.label(name)

    def _render_editor() -> None:
        o = S["opt"]
        files = S["files"][o]
        tabs = R["etabs"]
        tabs.clear()
        sel = S["sel"][o]
        with tabs:
            for p in S["tabs"][o]:
                if p not in files:
                    continue
                t = _div("da-etab" + (" on" if p == sel else ""))
                t.on("click", lambda _e=None, p=p: _open_file(p))
                with t:
                    ext = p.rsplit(".", 1)[-1].upper() if "." in p else "TXT"
                    ui.label({"JSON": "{}", "JSX": "JS", "MJS": "JS"}.get(ext, ext[:4])).classes("bd")
                    ui.label(p.rsplit("/", 1)[-1])
                    _btn("", "x", on_click=lambda _e=None, p=p: _close_tab(p), size=13)
        if sel and sel in files:
            R["code"].set_content(_code_html(files[sel], sel))
        else:
            R["code"].set_content('<div class="da-empty">Select a file from the explorer</div>')

    def _render_term() -> None:
        b = R["term_body"]
        b.clear()
        _set(R["term_title"], f"Terminal - Option {S['opt']}")
        lines = S["logs"][S["opt"]]
        with b:
            if not lines:
                _icon("term", 26)
                ui.label("No commands executed yet").classes("da-tnone")
            for ln in lines:
                tone = "cmd" if ln.startswith("$") else "ok" if ln.startswith("✓") else "err" if ln.startswith("✗") else ""
                ui.label(ln).classes(f"da-tl {tone}".strip())

    def _toggle_term() -> None:
        S["term_open"] = not S["term_open"]
        _cls(R["term"], "closed", not S["term_open"])

    def _toggle_tree() -> None:
        S["tree_open"] = not S["tree_open"]
        _cls(R["treecol"], "closed", not S["tree_open"])

    # ─────────────────────────── toolbar actions ───────────────────────────
    def _abs_js(url: str) -> str:
        return f"new URL({json.dumps(url)}, location.origin).href"

    def _copy_url() -> None:
        url = S["urls"][S["opt"]]
        if not url:
            ui.notify("Pehle Publish karo, phir link copy hoga.", type="warning")
            return
        ui.run_javascript(f"daCopy({_abs_js(url)})")
        ui.notify("Link copied", type="positive")

    def _open_live() -> None:
        url = S["urls"][S["opt"]]
        if not url:
            ui.notify("Pehle Publish karo.", type="warning")
            return
        ui.run_javascript(f"window.open({_abs_js(url)},'_blank')")

    def _refresh_frame() -> None:
        S["ver"] += 1
        _load_frame()

    def _fullscreen() -> None:
        ui.run_javascript("daFull()")

    def _download() -> None:
        files = S["files"][S["opt"]]
        if not files:
            ui.notify("Generate karo pehle.", type="warning")
            return
        nm = re.sub(r"[^A-Za-z0-9._-]+", "-", S["title"] or "website").strip("-") or "website"
        _download_bytes(_make_zip(files), f"{nm}-option-{S['opt']}.zip")
        ui.notify("ZIP downloaded", type="positive")

    def _publish() -> None:
        if S["status"] != "ready" or not (S["voted"] or S["single"]):
            ui.notify("Pehle vote karo.", type="warning")
            return
        opt = S["opt"]
        try:
            pid = _persist(opt)
            slug = _slug(pid, S["title"] or "website")
            db.publish_project(pid, slug)
        except Exception as exc:
            ui.notify(f"Publish failed: {exc}", type="negative")
            return
        S["urls"][opt] = f"/published/{slug}/"
        _log(opt, f"$ arena publish --slug {slug}")
        _log(opt, f"✓ live at /published/{slug}/")
        _sync_url()
        _sync_publish()
        _render_term()
        _render_recent()
        _refresh_stats()
        ui.notify(f"🚀 Published: /published/{slug}/", type="positive", position="top")

    def _reset_edit_btn() -> None:
        S["editing"] = False
        _set(R["edit_lbl"], "Edit text")
        _cls(R["editpill"], "active", False)

    async def _toggle_edit() -> None:
        if S["status"] != "ready" or S["view"] != "preview":
            return
        opt = S["opt"]
        files = S["files"][opt]
        if _is_react(files):
            ui.notify("Edit text abhi sirf Website (static) mode me hai. React app me chat se change maango.", type="warning")
            return
        if not S["editing"]:
            S["editing"] = True
            _set(R["edit_lbl"], "Save text")
            _cls(R["editpill"], "active", True)
            ui.run_javascript("daFrame({da:'edit',on:true})")
            ui.notify("Preview me kisi bhi text par click karke edit karo, phir Save text dabao.")
            return
        ui.run_javascript("window.__daEdited=null;daFrame({da:'collect'})")
        await asyncio.sleep(0.7)
        res = await ui.run_javascript("window.__daEdited")
        _reset_edit_btn()
        if not res or not res.get("html"):
            ui.notify("Text save nahi ho paya - dobara try karo.", type="negative")
            return
        prefix = f"/p/{S['tokens'][opt]}/"
        path = res.get("path", "")
        rel = path[len(prefix):] if path.startswith(prefix) else ""
        rel = rel or "index.html"
        if rel not in files:
            rel = "index.html"
        files[rel] = res["html"]
        _update_preview(S["tokens"][opt], files)
        if S["pids"][opt] is not None:
            try:
                _persist(opt)
            except Exception:
                pass
        _log(opt, f"$ arena edit-text {rel}")
        _log(opt, "✓ text changes saved")
        S["ver"] += 1
        _render_editor()
        _render_term()
        _load_frame()
        ui.notify("Text changes saved", type="positive")

    # ─────────────────────────── generation ───────────────────────────
    def _detect_kind(text: str) -> str:
        if S["type"] == "fullstack":
            return "fullstack"
        if S["type"] == "webapp" or re.search(r"\breact(?:\.js)?\b|\bnext\.?js\b", text, re.I):
            return "webapp"
        return "website"

    def _gen_messages(opt: str):
        text = (f"{BASE_RULES}\n\nDESIGN DIRECTION: {STYLE[opt]}\n\n{_contract(S['kind'])}\n\nUSER REQUEST:\n{S['prompt']}")
        docs = [a for a in S["attach"] if a["kind"] == "text"]
        if docs:
            text += "\n\nREFERENCE MATERIAL FROM THE USER:\n" + "\n\n".join(f"--- {a['name']} ---\n{a['text'][:20000]}" for a in docs)
        imgs = [a for a in S["attach"] if a["kind"] == "image"]
        if imgs:
            content = [{"type": "text", "text": text}] + [{"type": "image_url", "image_url": {"url": a["data_url"]}} for a in imgs]
        else:
            content = text
        return [{"role": "user", "content": content}]

    def _repair_messages(files, probs):
        text = (f"{BASE_RULES}\n\n{_contract(S['kind'])}\n\nThe project below has problems:\n- " + "\n- ".join(probs) +
                "\n\nReturn ONLY the missing or fixed files, each COMPLETE, in the ### FILE format. Do not repeat unchanged files.\n\n"
                "CURRENT PROJECT:\n" + _files_context(files))
        return [{"role": "user", "content": text}]

    async def _gen_one(opt: str) -> None:
        P = S["prog"][opt]
        model = S["models"][opt]
        t0 = time.time()
        P.update(state="running", chars=0, files=0, cur="", error="")

        def on_chunk(raw: str, chunk: str) -> None:
            P["chars"] = len(raw)
            if "\n" in chunk:
                hits = _FILE_TAIL.findall(raw[-240:])
                if hits and hits[-1] != P["cur"]:
                    P["cur"] = hits[-1]
                    P["files"] += 1

        _log(opt, f"$ arena generate --option {opt} --model {S['mname'][opt]} --type {S['kind']}")
        try:
            raw = await _stream_text(_gen_messages(opt), model, on_chunk)
            _log(opt, f"✓ received {len(raw) / 1000:.1f}k chars in {time.time() - t0:.1f}s")
            files = _parse_files(raw)
            if not files:
                raise ValueError("model ne ### FILE blocks return nahi kiye")
            _log(opt, "$ parse-files")
            _log(opt, f"✓ {len(files)} files: " + ", ".join(sorted(files)))
            _log(opt, "$ verify-project")
            probs = _problems(files)
            if probs:
                for pr in probs:
                    _log(opt, f"✗ {pr}")
                P["cur"] = "repairing…"
                _log(opt, "$ arena repair")
                fixed = _parse_files(await _stream_text(_repair_messages(files, probs), model))
                if fixed:
                    files = {**files, **fixed}
                    _log(opt, f"✓ repaired: " + ", ".join(sorted(fixed)))
                probs = _problems(files)
            if probs:
                _log(opt, f"✗ {len(probs)} issue(s) still open - preview may show an error")
            else:
                _log(opt, "✓ all imports / references resolved")
            if not any(p in files for p in ("index.html", "src/App.jsx", "src/App.js", "src/main.jsx", "src/App.tsx")):
                raise ValueError("entry file (index.html / src/App.jsx) missing")
            S["files"][opt] = files
            _update_preview(S["tokens"][opt], files)
            P.update(state="done", files=len(files), dur=time.time() - t0)
        except Exception as exc:
            msg = str(exc) or exc.__class__.__name__
            _log(opt, f"✗ {msg}")
            err = ("<body style='font-family:system-ui;padding:40px;color:#6b2d22'><h2>Generation failed</h2>"
                   f"<pre style='white-space:pre-wrap'>{html_mod.escape(msg)}</pre></body>")
            S["files"][opt] = {"index.html": err}
            _update_preview(S["tokens"][opt], S["files"][opt])
            P.update(state="error", error=msg[:300], dur=time.time() - t0)

    async def _gen_title(prompt: str) -> None:
        try:
            out = await asyncio.wait_for(_stream_text(
                [{"role": "user", "content": "Give a 2 to 5 word Title Case name for this website request. Reply with the title only, no quotes, no punctuation:\n" + prompt[:400]}],
                "default"), 30)
            t = re.sub(r"[^\w\s&'-]", "", out).strip().split("\n")[0][:48].strip()
            if t and S["prompt"] == prompt:
                S["title"] = t
                _set(R.get("titlebar"), t)
        except Exception:
            pass

    def _tick(force: bool = False) -> None:
        if S["status"] != "generating" and not force:
            return
        el = time.time() - S["t0"]
        _set(R.get("timer"), f"{el:.1f}s")
        idx = int(el // 3.2) % len(PHRASES)
        if idx != S["phrase_i"] or force:
            S["phrase_i"] = idx
            _set(R.get("phrase"), PHRASES[idx])
        for o in "AB":
            P = S["prog"].get(o)
            if not P:
                continue
            st = P["state"]
            if st == "queued":
                txt = "Queued"
            elif st == "running":
                base = f"writing {P['cur']}" if P["cur"] else "thinking…"
                txt = f"{S['mname'][o]} · {base} · {P['chars'] / 1000:.1f}k chars"
            elif st == "done":
                txt = f"✓ {P['files']} files · {P['dur']:.1f}s"
            else:
                txt = f"✗ {P.get('error', 'failed')[:80]}"
            _set(R.get(f"pst_{o}"), txt)
            d = R.get(f"pdot_{o}")
            _cls(d, "done", st == "done")
            _cls(d, "err", st == "error")

    async def _start(text: str) -> None:
        if S["status"] == "generating":
            return
        S.update(prompt=text, title=_title_from_prompt(text), kind=_detect_kind(text), status="generating",
                 voted=None, single=False, opt="A", chat=[], refining=False, editing=False,
                 urls={"A": "", "B": ""}, pids={"A": None, "B": None}, files={"A": {}, "B": {}},
                 tabs={"A": [], "B": []}, sel={"A": None, "B": None}, logs={"A": [], "B": []},
                 filter="", t0=time.time(), phrase_i=0, ver=S["ver"] + 1)
        S["mname"] = {o: _resolve_model(S["models"][o]) for o in "AB"}
        S["prog"] = {o: {"state": "queued", "chars": 0, "files": 0, "cur": "", "dur": 0.0, "error": ""} for o in "AB"}
        for o in "AB":
            S["tokens"][o] = _register_preview({"index.html": _wait_page(o)})
        _show(R["home"], False)
        _show(R["work"], True)
        R["work"].classes(remove="split")
        _set(R["titlebar"], S["title"])
        _show(R["banner"], True)
        _render_chat()
        _render_tray()
        _sync_input()
        _sync_tabs()
        R["tick"].active = True
        S["title_task"] = asyncio.create_task(_gen_title(text))
        await asyncio.gather(_gen_one("A"), _gen_one("B"))
        R["tick"].active = False
        _show(R["banner"], False)
        ok = [o for o in "AB" if S["prog"][o]["state"] == "done"]
        if not ok:
            S["status"] = "failed"
            _render_chat()
            _sync_input()
            ui.notify("Dono options fail hue - LLM service check karo.", type="negative", timeout=9000)
            return
        S["status"] = "ready"
        for o in "AB":
            f = S["files"][o]
            e = _entry_file(f)
            S["tabs"][o] = [e]
            S["sel"][o] = e
        R["work"].classes(add="split")
        _set_view("preview")
        _render_tray()
        _sync_input()
        _switch_opt(ok[0])
        if len(ok) == 2:
            ui.notify("✨ Dono designs ready - vote karo!", type="positive", position="bottom-right")
        else:
            ui.notify("Sirf ek option ban paya, dusre ka terminal check karo.", type="warning")

    async def _submit() -> None:
        text = (R["inp"].value or "").strip()
        if not text:
            ui.notify("Pehle prompt likho.", type="warning")
            return
        R["inp"].value = ""
        await _start(text)

    # ─────────────────────────── vote / refine ───────────────────────────
    def _vote(w: str) -> None:
        if S["status"] != "ready" or S["voted"] or S["single"]:
            return
        S["voted"] = w
        _save_vote({"ts": time.time(), "prompt": S["prompt"][:300], "kind": S["kind"],
                    "A": S["mname"]["A"], "B": S["mname"]["B"], "winner": w})
        try:
            _persist(w)
        except Exception as exc:
            ui.notify(f"Save failed: {exc}", type="warning")
        S["chat"].append({"role": "ai", "tone": "ok",
                          "text": f"Vote saved - Option {w} ({S['mname'][w]}) won. Ab neeche likhkar changes maango, "
                                  "phir Publish dabao link ke liye."})
        _switch_opt(w)
        _render_tray()
        _sync_input()
        _sync_publish()
        _refresh_stats()
        _render_recent()

    async def _send_chat() -> None:
        if S["status"] != "ready" or not (S["voted"] or S["single"]) or S["refining"]:
            return
        text = (R["inp2"].value or "").strip()
        if not text:
            return
        R["inp2"].value = ""
        opt = S["opt"]
        files = S["files"][opt]
        S["chat"].append({"role": "user", "text": text})
        S["refining"] = True
        _render_chat()
        _sync_input()
        _log(opt, f'$ arena edit "{text[:70]}"')
        try:
            prompt = (f"{BASE_RULES}\n\n{_contract(S['kind'])}\n\nYou are EDITING an existing project. Apply the change below. "
                      "Return ONLY the files that changed or are new, each COMPLETE, in the ### FILE format. "
                      "Keep everything else working and keep every relative import resolvable.\n\n"
                      f"CHANGE REQUEST:\n{text}\n\nCURRENT PROJECT:\n{_files_context(files)}")
            raw = await _stream_text([{"role": "user", "content": prompt}], S["models"][opt])
            new = _parse_files(raw)
            if not new:
                raise ValueError("model ne koi file return nahi ki")
            merged = {**files, **new}
            probs = _problems(merged)
            if probs:
                for pr in probs:
                    _log(opt, f"✗ {pr}")
                fixed = _parse_files(await _stream_text(_repair_messages(merged, probs), S["models"][opt]))
                merged = {**merged, **fixed}
                new = {**new, **fixed}
            S["files"][opt] = merged
            _update_preview(S["tokens"][opt], merged)
            for p in new:
                if p not in S["tabs"][opt]:
                    S["tabs"][opt].append(p)
            S["sel"][opt] = sorted(new)[0]
            S["ver"] += 1
            _log(opt, f"✓ updated {len(new)} file(s): " + ", ".join(sorted(new)))
            if S["pids"][opt] is not None:
                _persist(opt)
            S["chat"].append({"role": "ai", "text": f"Updated {len(new)} file(s): " + ", ".join(sorted(new)) +
                              (" - Publish > Update se live link refresh karo." if S["urls"][opt] else "")})
        except Exception as exc:
            _log(opt, f"✗ {exc}")
            S["chat"].append({"role": "ai", "tone": "bad", "text": f"Change apply nahi hua: {exc}"})
        S["refining"] = False
        _render_chat()
        _render_tree()
        _render_editor()
        _render_term()
        _sync_input()
        _sync_publish()
        _load_frame()

    # ─────────────────────────── navigation ───────────────────────────
    def _open_files(files: dict[str, str], title: str, pid=None, url: str = "") -> None:
        S.update(prompt=title, title=title, kind="webapp" if _is_react(files) else "website", status="ready",
                 voted="A", single=True, opt="A", chat=[], refining=False, editing=False,
                 urls={"A": url, "B": ""}, pids={"A": pid, "B": None}, files={"A": dict(files), "B": {}},
                 logs={"A": [f"$ arena open {title}", f"✓ {len(files)} files loaded"], "B": []},
                 filter="", ver=S["ver"] + 1)
        S["mname"] = {"A": "saved", "B": ""}
        S["prog"] = {"A": {"state": "done", "dur": 0.0}, "B": {"state": "queued"}}
        S["tokens"]["A"] = _register_preview(files)
        e = _entry_file(files)
        S["tabs"]["A"], S["sel"]["A"] = [e], e
        _show(R["home"], False)
        _show(R["work"], True)
        _show(R["banner"], False)
        R["work"].classes(add="split")
        _set(R["titlebar"], title)
        _set_view("preview")
        _render_tray()
        _sync_input()
        _switch_opt("A")

    def _open_saved(pid: int) -> None:
        try:
            rows = db.get_project_files(pid)
            proj = next((p for p in db.get_all_projects() if p["id"] == pid), None)
            pub = db.get_project_publication(pid)
        except Exception as exc:
            ui.notify(f"Open failed: {exc}", type="negative")
            return
        if not rows:
            ui.notify("Is project me files nahi hain.", type="warning")
            return
        files = {r["path"]: r["content"] for r in rows}
        _open_files(files, (proj or {}).get("name", "Saved site"), pid=pid,
                    url=f"/published/{pub['slug']}/" if pub else "")

    def _go_home() -> None:
        S.update(status="idle", prompt="", voted=None, single=False, refining=False, editing=False, chat=[], attach=[],
                 files={"A": {}, "B": {}}, urls={"A": "", "B": ""}, pids={"A": None, "B": None})
        R["tick"].active = False
        _render_attach()
        _show(R["work"], False)
        _show(R["home"], True)
        R["work"].classes(remove="split")
        _render_recent()
        _refresh_stats()

    def _set_type(k: str) -> None:
        S["type"] = k
        for key in KINDS:
            _cls(R[f"mode_{key}"], "on", key == k)

    def _use_suggestion(text: str) -> None:
        R["inp"].value = text
        R["inp"].run_method("focus")

    # ═════════════════════════════════════════════════════════════════
    #  LAYOUT
    # ═════════════════════════════════════════════════════════════════
    def _brand():
        with _div("da-brand") as b:
            ui.label("Design Arena").classes("b1")
            with _div("b2"):
                ui.label("by")
                _icon("spark", 14)
                ui.label("Saumya Intelligence")
        b.on("click", _go_home)

    def _nav():
        with _div("da-nav-wrap"):
            with _div("da-nav-menu") as nav:
                for label, fn in (("Leaderboards", _open_board), ("Models", _open_models)):
                    nb = ui.element("button").classes("da-nl")
                    nb._props["type"] = "button"
                    nb.on("click", fn)
                    with nb:
                        ui.label(label)
                with _div("da-nl"):
                    _icon("globe", 20)
                    ui.label("EN")
                with _div("da-nl"):
                    ui.label(user_name)
            hb = ui.element("button").classes("da-menu-btn")
            hb._props["type"] = "button"
            hb.on("click", lambda: ui.run_javascript("document.querySelector('.da-nav-menu').classList.toggle('open')"))
            with hb:
                _icon("menu", 26)

    with _div("da-app") as root:
        R["root"] = root
        R["tick"] = ui.timer(0.2, _tick, active=False)

        # hidden uploaders (attach / import)
        R["up_ref"] = ui.upload(on_upload=_on_ref_upload, multiple=True, auto_upload=True,
                                max_file_size=10 * 1024 * 1024).props('accept=".png,.jpg,.jpeg,.webp,.gif,.txt,.md,.html,.css,.js,.json,.csv"').classes("da-up da-up-ref")
        R["up_imp"] = ui.upload(on_upload=_on_import_upload, auto_upload=True,
                                max_file_size=20 * 1024 * 1024).props('accept=".zip,.html,.htm"').classes("da-up da-up-imp")

        # ───────── HOME ─────────
        R["home"] = _div("da-home")
        with R["home"]:
            with _div("da-top"):
                _brand()
                _nav()
            with _div("da-hero"):
                ui.label("What are you creating today?").classes("da-h1")
                with _div("da-sub"):
                    ui.label("by")
                    _icon("spark", 18)
                    ui.label("Saumya Intelligence").style("font-family:var(--serif);font-size:18px;color:#3a3935")
                    _div("da-dot")
                    R["stats"] = ui.label("")
                with _div("da-box"):
                    R["inp"] = ui.textarea(placeholder="Ask Design Arena to build a dashboard for tracking sales…").props(
                        "borderless autogrow input-class=da-ta").classes("da-field")
                    R["attached"] = _div("da-attached")
                    with _div("da-tools"):
                        with _div("da-tools-l"):
                            _btn("da-round", "clip", title="Attach reference files / images",
                                 js="() => document.querySelector('.da-up-ref input[type=file]').click()", size=22)
                            _btn("da-round", "cloud", title="Import a .zip / .html project",
                                 js="() => document.querySelector('.da-up-imp input[type=file]').click()", size=22)
                        _btn("da-send", "up", on_click=_submit, title="Generate", size=24)
                with _div("da-modes"):
                    for k, lab in KINDS.items():
                        m = _div("da-mode" + (" on" if k == S["type"] else ""))
                        R[f"mode_{k}"] = m
                        m.on("click", lambda _e=None, k=k: _set_type(k))
                        with m:
                            _html(TYPE_SVG)
                            ui.label(lab)
                with _div("da-sugs"):
                    for s in SUGGESTIONS:
                        sb = ui.element("button").classes("da-sug")
                        sb._props["type"] = "button"
                        sb.on("click", lambda _e=None, s=s: _use_suggestion(s))
                        with sb:
                            ui.label(s)
                R["recent"] = _div("da-recent")

        # ───────── WORK (chat + preview) ─────────
        R["work"] = _div("da-work da-off")
        with R["work"]:
            with _div("da-chatcol"):
                with _div("da-top"):
                    _brand()
                    _nav()
                with _div("da-titlebar"):
                    R["titlebar"] = ui.label("")
                R["banner"] = _div("da-banner da-off")
                R["banner"].on("click", _open_snake)
                with R["banner"]:
                    _icon("pad", 24)
                    ui.label("Play while you wait")
                with _div("da-scroll"):
                    R["thread"] = _div("da-thread")
                with _div("da-dock"):
                    R["tray"] = _div("da-tray da-off")
                    with _div("da-box da-cbox"):
                        R["inp2"] = ui.textarea(placeholder="The agent is generating your creation…").props(
                            "borderless autogrow input-class=da-ta").classes("da-field")
                        with _div("da-tools"):
                            with _div("da-tools-l"):
                                _btn("da-round", "clip", title="Attach", size=20,
                                     js="() => document.querySelector('.da-up-ref input[type=file]').click()")
                                _btn("da-round", "cloud", title="Import", size=20,
                                     js="() => document.querySelector('.da-up-imp input[type=file]').click()")
                            R["send2"] = _btn("da-send is-disabled", "up", on_click=_send_chat, title="Send", size=22)

            _div("da-splitter")

            with _div("da-prevcol"):
                # option tabs
                with _div("da-ptabs"):
                    for o in "AB":
                        tab = _div("da-ptab" + (" on" if o == "A" else ""))
                        R[f"ptab_{o}"] = tab
                        tab.on("click", lambda _e=None, o=o: _switch_opt(o))
                        with tab:
                            _icon("trophy", 26)
                            R[f"ptxt_{o}"] = ui.label(f"Option {o}").classes("nm")
                            vp = ui.element("button").classes("da-vpill")
                            vp._props["type"] = "button"
                            vp.on("click.stop", lambda _e=None, o=o: _vote(o))
                            R[f"vote_{o}"] = vp
                            with vp:
                                ui.label(f"Option {o} is better")
                    R["ptab_grow_B"] = _div("grow")
                    xb = ui.element("button").classes("da-xbtn")
                    xb._props["type"] = "button"
                    xb._props["title"] = "Close"
                    xb.on("click", _go_home)
                    with xb:
                        _icon("x", 24)

                # toolbar
                with _div("da-toolbar"):
                    with _div("da-mtog"):
                        R["m_eye"] = _btn("on", "eye", on_click=lambda: _set_view("preview"), title="Preview", size=22)
                        R["m_code"] = _btn("", "code", on_click=lambda: _set_view("code"), title="Code", size=22)
                    _div("da-vsep")
                    R["url"] = _div("da-url")
                    with R["url"]:
                        _icon("globe", 20)
                        R["url_txt"] = ui.label("Vote to get link").classes("u")
                        _btn("", "copy", on_click=_copy_url, title="Copy link", size=19)
                        _btn("", "ext", on_click=_open_live, title="Open live site", size=19)
                    _btn("da-sq", "refresh", on_click=_refresh_frame, title="Reload preview", size=22)
                    _btn("da-sq", "full", on_click=_fullscreen, title="Fullscreen", size=22)
                    R["pub"] = _btn("da-pub is-disabled", on_click=_publish, title="Publish")
                    with R["pub"]:
                        R["pub_lock"] = _icon("lock", 18)
                        R["pub_open"] = _icon("unlock", 18)
                        R["pub_lbl"] = ui.label("Publish").classes("da-bt")
                    _show(R["pub_open"], False)

                # body
                R["pbody"] = _div("da-pbody")
                with R["pbody"]:
                    R["fwrap"] = _div("da-fwrap")
                    with R["fwrap"]:
                        fr = ui.element("iframe").classes("da-frame")
                        fr._props["src"] = "about:blank"
                        fr._props["sandbox"] = SANDBOX
                        fr.on("load", lambda: _set_loading(False))
                        R["frame"] = fr

                    R["codewrap"] = _div("da-codewrap da-off")
                    with R["codewrap"]:
                        R["treecol"] = _div("da-treecol")
                        with R["treecol"]:
                            with _div("da-thead"):
                                with _div("da-sbox"):
                                    _icon("search", 18)
                                    ui.input(placeholder="Search", on_change=lambda e: _on_filter(e.value)).props("borderless dense").classes("da-search")
                                _btn("", "gh", title="GitHub export (coming soon)", size=19).classes("is-disabled")
                                _btn("", "dl", on_click=_download, title="Download ZIP", size=19)
                                _btn("", "panel", on_click=_toggle_tree, title="Hide explorer", size=19)
                            R["tree"] = _div("da-tree")
                        with _div("da-editor"):
                            R["etabs"] = _div("da-etabs")
                            R["code"] = _html("").classes("da-code")
                            R["term"] = _div("da-term")
                            with R["term"]:
                                th = _div("da-term-h")
                                th.on("click", _toggle_term)
                                with th:
                                    _icon("term", 20)
                                    R["term_title"] = ui.label("Terminal - Option A")
                                    _div("sp")
                                    _icon("down", 20)
                                R["term_body"] = _div("da-term-b")

                    R["loader"] = _div("da-loader da-off")
                    with R["loader"]:
                        _html(CLOUD_SVG)
                        ui.label("Building preview…")

                    R["editpill"] = ui.element("button").classes("da-btn da-editpill da-off")
                    R["editpill"]._props["type"] = "button"
                    R["editpill"].on("click", _toggle_edit)
                    with R["editpill"]:
                        _icon("pen", 20)
                        R["edit_lbl"] = ui.label("Edit text").classes("da-bt")

    # first paint
    _render_recent()
    _refresh_stats()