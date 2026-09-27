import base64
import sys
import types
from types import SimpleNamespace

import pytest

from app.image_service import ImageGenerationService


def test_image_generation_requires_api_key(tmp_path):
    service = ImageGenerationService(output_dir=tmp_path)

    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        service.generate("A red kite in a blue sky")


def test_generate_saves_jpeg_and_returns_public_url(tmp_path, monkeypatch):
    image_bytes = b"fake-jpeg-data"
    interaction = SimpleNamespace(
        output_image=SimpleNamespace(data=base64.b64encode(image_bytes).decode("ascii"))
    )
    captured = {}

    def create_interaction(**kwargs):
        captured.update(kwargs)
        return interaction

    fake_client = SimpleNamespace(
        interactions=SimpleNamespace(
            create=create_interaction
        )
    )
    fake_genai = types.ModuleType("google.genai")
    fake_genai.Client = lambda api_key: fake_client
    fake_google = types.ModuleType("google")
    fake_google.genai = fake_genai
    monkeypatch.setitem(sys.modules, "google", fake_google)
    monkeypatch.setitem(sys.modules, "google.genai", fake_genai)

    service = ImageGenerationService(
        api_key="test-key",
        output_dir=tmp_path,
    )
    result = service.generate("A red kite in a blue sky")

    assert result["image_url"].startswith("/generated-images/")
    assert result["filename"].endswith(".jpg")
    assert captured["response_format"]["mime_type"] == "image/jpeg"
    saved_image = tmp_path / result["filename"]
    assert saved_image.read_bytes() == image_bytes
