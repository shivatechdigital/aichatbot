"""Minimal LTX-2 worker for a Colab GPU runtime.

Run this from the LTX-2 repository after downloading the model files. Expose
port 8000 with a tunnel and set that public URL as VIDEO_API_URL in Saumya AI.
"""

from __future__ import annotations

import os
import subprocess
import threading
import uuid
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel


ROOT = Path(os.getenv("LTX_ROOT", ".")).resolve()
OUTPUT_DIR = ROOT / os.getenv("LTX_OUTPUT_DIR", "colab_outputs")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
WORKER_API_KEY = os.getenv("VIDEO_API_KEY", "").strip()

TRANSFORMER = ROOT / os.getenv(
    "LTX_TRANSFORMER",
    "models/ltx-2.5/diffusion_models/ltx-2.5-22b-distilled-transformer-bf16.safetensors",
)
TEXT_ENCODER = ROOT / os.getenv(
    "LTX_TEXT_ENCODER",
    "models/ltx-2.5/text_encoders/gemma4-12b-with-proj-ltx-2.5-bf16.safetensors",
)
VIDEO_VAE = ROOT / os.getenv(
    "LTX_VIDEO_VAE",
    "models/ltx-2.5/vae/ltx-2.5-video-vae-conv-bf16.safetensors",
)
AUDIO_VAE = ROOT / os.getenv(
    "LTX_AUDIO_VAE",
    "models/ltx-2.5/vae/ltx-2.5-audio-vae-bf16.safetensors",
)

app = FastAPI(title="Saumya LTX-2 Video Worker")
app.mount("/outputs", StaticFiles(directory=OUTPUT_DIR), name="outputs")
jobs: dict[str, dict] = {}


def check_key(authorization: str | None) -> None:
    if WORKER_API_KEY and authorization != f"Bearer {WORKER_API_KEY}":
        raise HTTPException(status_code=401, detail="invalid video worker key")


class GenerateRequest(BaseModel):
    prompt: str


def run_job(job_id: str, prompt: str) -> None:
    output_name = f"{job_id}.mp4"
    output_path = OUTPUT_DIR / output_name
    command = [
        "uv", "run", "python", "-m", "ltx_pipelines.distilled",
        "--transformer-path", str(TRANSFORMER),
        "--text-encoder-path", str(TEXT_ENCODER),
        "--video-vae-path", str(VIDEO_VAE),
        "--audio-vae-path", str(AUDIO_VAE),
        "--num-frames", os.getenv("LTX_NUM_FRAMES", "49"),
        "--seed", "42",
        "--output-path", str(output_path),
        "--prompt", prompt,
    ]
    if os.getenv("LTX_QUANTIZATION"):
        command.extend(["--quantization", os.environ["LTX_QUANTIZATION"]])
    if os.getenv("LTX_OFFLOAD"):
        command.extend(["--offload", os.environ["LTX_OFFLOAD"]])

    try:
        jobs[job_id]["status"] = "running"
        completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        if completed.returncode:
            jobs[job_id].update(status="failed", error=completed.stderr[-2000:])
            return
        jobs[job_id].update(
            status="completed",
            video_url=f"/outputs/{output_name}",
        )
    except Exception as error:
        jobs[job_id].update(status="failed", error=str(error))


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/generate", status_code=202)
def generate(request: GenerateRequest, authorization: str | None = Header(default=None)) -> dict[str, str]:
    check_key(authorization)
    prompt = request.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt is required")
    job_id = uuid.uuid4().hex
    jobs[job_id] = {"status": "queued"}
    threading.Thread(target=run_job, args=(job_id, prompt), daemon=True).start()
    return {"job_id": job_id}


@app.get("/jobs/{job_id}")
def job_status(job_id: str, authorization: str | None = Header(default=None)) -> dict:
    check_key(authorization)
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    result = dict(job)
    if result.get("video_url"):
        result["video_url"] = f"{PUBLIC_BASE_URL}{result['video_url']}"
    return result
