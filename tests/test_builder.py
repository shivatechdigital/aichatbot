from app.builder import DEFAULT_FILES, _parse_generated_files, _project_document


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