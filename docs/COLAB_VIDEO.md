# Colab video worker

Saumya AI can use an LTX-2 worker running in a temporary Colab GPU session.
This is optional: leave `VIDEO_API_URL` empty to keep the normal chat-only UI.

## Colab setup

Use a GPU runtime, clone the official repository, and install its dependencies:

```bash
!git clone https://github.com/Lightricks/LTX-2.git
%cd LTX-2
!curl -LsSf https://astral.sh/uv/install.sh | sh
!source $HOME/.local/bin/env && uv sync --extra natten
```

Download the four model files required by `DistilledPipeline` from the official
Lightricks Hugging Face repository. The repository README says this download is
roughly 66 GiB, so free Colab may run out of disk or VRAM.

Copy `scripts/colab_video_server.py` into the cloned repository, then start it:

```bash
!cp /content/quotation-ai-arena/scripts/colab_video_server.py .
!source $HOME/.local/bin/env && uv run uvicorn colab_video_server:app --host 0.0.0.0 --port 8000
```

Expose port 8000 with a tunnel such as Cloudflare Tunnel, then set the resulting
HTTPS URL in Saumya AI's `.env`:

```env
VIDEO_API_URL=https://your-colab-tunnel.example
VIDEO_TIMEOUT=1800
```

Click the `Think` button in the composer to switch it to `Video`, then send a
prompt. The Colab runtime must remain running and its tunnel URL can change
after a restart. Never expose the worker publicly without authentication; set
`VIDEO_API_KEY` in both the app and a proxy/worker if the tunnel is shared.