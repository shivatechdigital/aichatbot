"""OpenAI-compatible local LLM API client."""

import json
import socket
from collections.abc import Generator
from urllib.parse import urlparse

import requests
from loguru import logger

from app.config import config


class LLMClient:
    def __init__(self) -> None:
        self.api_url = config.API_BASE_URL.rstrip("/")
        self.api_key = config.API_KEY.strip()
        self.configured_model = config.MODEL_NAME.strip() or "auto"
        self.temperature = config.TEMPERATURE
        self.max_tokens = config.MAX_TOKENS
        self.timeout = config.REQUEST_TIMEOUT

    def _get_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key and self.api_key.lower() != "not-needed":
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def stream_chat(self, messages: list[dict]) -> Generator[str, None, None]:
        try:
            payload = {
                "messages": messages,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
                "stream": True,
            }
            if self.configured_model.lower() != "auto":
                payload["model"] = self.configured_model

            with requests.post(
                self.api_url,
                json=payload,
                headers=self._get_headers(),
                stream=True,
                timeout=self.timeout,
            ) as response:
                response.raise_for_status()
                received_content = False
                for line in response.iter_lines(chunk_size=1, decode_unicode=True):
                    if not line:
                        continue
                    data = line.removeprefix("data:").strip()
                    if data == "[DONE]":
                        break
                    try:
                        event = json.loads(data)
                        choice = event["choices"][0]
                        content = choice.get("delta", {}).get("content")
                        if content is None:
                            content = choice.get("message", {}).get("content")
                    except (json.JSONDecodeError, KeyError, IndexError, TypeError):
                        logger.debug("Ignoring malformed stream event: {}", data)
                        continue
                    if content:
                        received_content = True
                        yield content
                if not received_content:
                    logger.warning("The API returned no assistant content")
        except (requests.RequestException, RuntimeError) as error:
            logger.error("LLM request failed: {}", error)
            yield f"API connection failed: {error}"

    def health_check(self) -> bool:
        parsed_url = urlparse(self.api_url)
        port = parsed_url.port or (443 if parsed_url.scheme == "https" else 80)
        try:
            with socket.create_connection((parsed_url.hostname or "localhost", port), timeout=2):
                return True
        except OSError:
            return False


llm_client = LLMClient()