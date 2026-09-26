"""Client for an optional LTX video worker running on Colab or another GPU host."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx


class VideoService:
    def __init__(self, base_url: str = "", api_key: str = "", timeout: int = 900) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key.strip()
        self.timeout = timeout

    @property
    def enabled(self) -> bool:
        return bool(self.base_url)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    async def generate(self, prompt: str, *, timeout: int | None = None) -> dict[str, Any]:
        if not self.enabled:
            raise RuntimeError("Video generation is not configured. Set VIDEO_API_URL.")

        request_timeout = timeout or self.timeout
        async with httpx.AsyncClient(timeout=httpx.Timeout(request_timeout, connect=15)) as client:
            response = await client.post(
                f"{self.base_url}/generate",
                json={"prompt": prompt},
                headers=self._headers(),
            )
            response.raise_for_status()
            result = response.json()
            if result.get("video_url"):
                return result

            job_id = result.get("job_id")
            if not job_id:
                raise RuntimeError("Video worker did not return job_id or video_url.")

            while True:
                await asyncio.sleep(3)
                status_response = await client.get(
                    f"{self.base_url}/jobs/{job_id}",
                    headers=self._headers(),
                )
                status_response.raise_for_status()
                status = status_response.json()
                if status.get("status") == "completed" and status.get("video_url"):
                    return status
                if status.get("status") == "failed":
                    raise RuntimeError(status.get("error") or "Video generation failed.")
