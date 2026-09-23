import json
from unittest.mock import Mock, patch

from app.api_client import LLMClient


@patch("app.api_client.requests.post")
def test_auto_model_uses_server_default(mock_post):
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.raise_for_status.return_value = None
    response.iter_lines.return_value = [
        json.dumps(
            {"choices": [{"message": {"role": "assistant", "content": "Hello"}}]}
        )
    ]
    mock_post.return_value = response

    client = LLMClient()
    client.configured_model = "auto"

    assert list(client.stream_chat([{"role": "user", "content": "Hi"}])) == ["Hello"]
    payload = mock_post.call_args.kwargs["json"]
    assert "model" not in payload
    response.iter_lines.assert_called_once_with(chunk_size=1, decode_unicode=True)


def test_not_needed_key_does_not_send_authorization():
    client = LLMClient()
    client.api_key = "not-needed"

    assert client._get_headers() == {"Content-Type": "application/json"}