"""Gemini image generation client for Saumya AI."""

from __future__ import annotations

import base64
import binascii
import uuid
from pathlib import Path
from typing import Any


class ImageGenerationService:
    def __init__(
        self,
        api_key: str = "",
        model: str = "gemini-3.1-flash-image",
        output_dir: str | Path = "data/generated_images",
        public_prefix: str = "/generated-images",
    ) -> None:
        self.api_key = api_key.strip()
        self.model = model.strip() or "gemini-3.1-flash-image"
        self.output_dir = Path(output_dir)
        self.public_prefix = public_prefix.rstrip("/")

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def generate(self, prompt: str) -> dict[str, Any]:
        if not self.enabled:
            raise RuntimeError("Image generation is not configured. Set GEMINI_API_KEY in .env.")
        if not prompt.strip():
            raise ValueError("Enter a description for the image.")

        from google import genai

        client = genai.Client(api_key=self.api_key)
        interaction = client.interactions.create(
            model=self.model,
            input=prompt.strip(),
            response_format={
                "type": "image",
                "mime_type": "image/jpeg",
                "aspect_ratio": "1:1",
                "image_size": "1K",
            },
        )
        output_image = getattr(interaction, "output_image", None)
        encoded_image = getattr(output_image, "data", None)
        if not encoded_image:
            raise RuntimeError("Gemini returned no image. Try another prompt or check API access.")

        try:
            image_bytes = base64.b64decode(encoded_image, validate=True)
        except (binascii.Error, ValueError) as error:
            raise RuntimeError("Gemini returned image data that could not be decoded.") from error

        self.output_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{uuid.uuid4().hex}.jpg"
        (self.output_dir / filename).write_bytes(image_bytes)
        return {
            "image_url": f"{self.public_prefix}/{filename}",
            "filename": filename,
            "message": "Image generated.",
        }