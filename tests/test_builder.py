from app.builder import (
    DEFAULT_FILES,
    _build_project_zip,
    _parse_generated_files,
    _project_document,
    _project_title,
    _wants_react,
)
import io
import zipfile


def test_generated_files_are_parsed_and_limited_to_supported_files():
    response = """### FILE: index.html
```html
<h1>Hello</h1>
```
### FILE: style.css
```css
h1 { color: red; }
```
### FILE: script.js
```javascript
console.log('ready');
```
### FILE: secrets.txt
```text
ignore me
```"""

    assert _parse_generated_files(response) == {
        "index.html": "<h1>Hello</h1>\n",
        "style.css": "h1 { color: red; }\n",
        "script.js": "console.log('ready');\n",
    }


def test_preview_inlines_css_and_javascript():
    document = _project_document({
        "index.html": DEFAULT_FILES["index.html"],
        "style.css": "body > main { color: red; }",
        "script.js": "document.title = 'Preview';",
    })

    assert "<style>body > main { color: red; }</style>" in document
    assert "<script>document.title = 'Preview';</script>" in document
    assert 'href="style.css"' not in document
    assert 'src="script.js"' not in document


def test_react_files_are_parsed_and_previewed():
    response = """### FILE: package.json
```json
{"scripts":{"dev":"vite"}}
```
### FILE: src/App.jsx
```jsx
function App() { return <h1>Salon</h1>; }
```
### FILE: src/styles.css
```css
h1 { color: hotpink; }
```"""

    files = _parse_generated_files(response)
    assert set(files) == {"package.json", "src/App.jsx", "src/styles.css"}
    document = _project_document(files)
    assert "ReactDOM.createRoot" in document
    assert "function App()" in document
    assert "color: hotpink" in document
    assert "from 'react'" not in document


def test_project_title_comes_from_prompt():
    assert _project_title("Build a premium beauty parlour website") == "Build A Premium Beauty Parlour Website"
    assert _project_title("   ") == "Website Project"


def test_react_prompt_is_detected():
    assert _wants_react("Build a React beauty parlour website")
    assert _wants_react("Create a React.js dashboard")
    assert not _wants_react("Build a plain HTML landing page")


def test_project_zip_contains_all_files():
    archive = _build_project_zip({"index.html": "<h1>Hi</h1>", "src/App.jsx": "export default App;"})
    with zipfile.ZipFile(io.BytesIO(archive)) as project_zip:
        assert project_zip.namelist() == ["index.html", "src/App.jsx"]
        assert project_zip.read("index.html") == b"<h1>Hi</h1>"