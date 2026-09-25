# Quotation AI Arena

A private Gradio chat interface for an OpenAI-compatible local LLM on port 3010.

## Features

- Streaming responses
- Automatic model discovery with `MODEL_NAME=auto`
- Persistent SQLite chat history
- Per-browser conversation state
- Optional API authentication
- Docker support

## Windows setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python run.py
```

Open http://localhost:7860. The default API endpoint is
`http://localhost:3010/v1/chat/completions`.

## Configuration

Edit `.env`. Leave `API_KEY` empty for a local server without authentication.
Keep `MODEL_NAME=auto` to select the first model returned by `/v1/models`, or set
an explicit model ID.

`REQUEST_TIMEOUT=600` allows the Builder to finish large multi-file generations.

When the app runs in Docker, Compose automatically uses
`http://host.docker.internal:3010/v1/chat/completions`.

This project expects the host-based `copilot-api` service on port `3010`; its
GitHub CLI authentication stays on the host and is not copied into this app.

```powershell
docker compose up --build -d
```

## Tests

```powershell
python -m pytest
```