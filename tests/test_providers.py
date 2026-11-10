import asyncio
import json

import httpx
import pytest

from ai_japanese_interview_assistant.config import ANTHROPIC, DEEPSEEK, OPENAI
from ai_japanese_interview_assistant.credentials import credential
from ai_japanese_interview_assistant.services import ServiceError, TextService, client_for


@pytest.mark.parametrize("provider, header", [
    (OPENAI, ("Authorization", "Bearer synthetic")),
    (DEEPSEEK, ("Authorization", "Bearer synthetic")),
    (ANTHROPIC, ("x-api-key", "synthetic")),
])
def test_client_uses_selected_provider_authentication(provider, header):
    async def exercise():
        async with client_for("synthetic", provider) as client:
            assert client.headers[header[0]] == header[1]
            assert ("anthropic-version" in client.headers) == (provider is ANTHROPIC)
            assert ("Authorization" in client.headers) == (provider is not ANTHROPIC)
    asyncio.run(exercise())


def test_credential_entries_are_isolated_and_keep_the_legacy_openai_entry(monkeypatch):
    from keyring.backends import Windows

    values = {"OpenAI API Key": "legacy-openai"}

    class Vault:
        def get_password(self, service, account):
            return values.get(account)

        def set_password(self, service, account, value):
            values[account] = value

        def delete_password(self, service, account):
            del values[account]

    monkeypatch.setattr(Windows, "WinVaultKeyring", Vault)
    credential("save", "test-deepseek", DEEPSEEK)
    assert credential("read", provider=OPENAI) == "legacy-openai"
    assert credential("read", provider=DEEPSEEK) == "test-deepseek"
    assert credential("read", provider=ANTHROPIC) == ""
    credential("delete", provider=DEEPSEEK)
    assert values == {"OpenAI API Key": "legacy-openai"}


def test_deepseek_stream_uses_its_own_responses_endpoint():
    def handle(request):
        assert str(request.url) == "https://api.deepseek.com/responses"
        payload = json.loads(request.content)
        assert payload["model"] == "deepseek-flash"
        assert "store" not in payload
        return httpx.Response(200, text=(
            'data: {"type":"response.output_text.delta","delta":"你好"}\n\n'
            'data: {"type":"response.completed"}\n\n'
        ))

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            return [part async for part in TextService(client, DEEPSEEK).translate("こんにちは")]

    assert asyncio.run(exercise()) == ["你好"]


@pytest.mark.parametrize("reason", ["end_turn", "max_tokens"])
def test_anthropic_stream_rejects_an_incomplete_message(reason):
    def handle(request):
        assert str(request.url) == "https://api.anthropic.com/v1/messages"
        payload = json.loads(request.content)
        assert payload["messages"] == [{"role": "user", "content": "こんにちは"}]
        assert payload["thinking"] == {"type": "disabled"}
        return httpx.Response(200, text=(
            'event: content_block_delta\n'
            'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"你好"}}\n\n'
            f'data: {{"type":"message_delta","delta":{{"stop_reason":"{reason}"}}}}\n\n'
            'data: {"type":"message_stop"}\n\n'
        ))

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            return [part async for part in TextService(client, ANTHROPIC).translate("こんにちは")]

    if reason == "end_turn":
        assert asyncio.run(exercise()) == ["你好"]
    else:
        with pytest.raises(ServiceError):
            asyncio.run(exercise())


@pytest.mark.parametrize("provider", [OPENAI, DEEPSEEK, ANTHROPIC])
@pytest.mark.parametrize("valid", [True, False])
def test_structured_outputs_validate_type_and_use_provider_schema(provider, valid):
    properties = {"safe": {"type": "boolean"}}
    raw = json.dumps({"safe": True if valid else "true"})

    def handle(request):
        payload = json.loads(request.content)
        if provider is ANTHROPIC:
            assert payload["output_config"]["format"]["schema"]["required"] == ["safe"]
            return httpx.Response(200, json={"stop_reason": "end_turn", "content": [
                {"type": "text", "text": raw},
            ]})
        assert payload["text"]["format"]["type"] == "json_schema"
        assert payload["text"]["format"].get("strict") is (True if provider is OPENAI else None)
        return httpx.Response(200, json={"status": "completed", "output": [
            {"type": "message", "content": [{"type": "output_text", "text": raw}]},
        ]})

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            return await TextService(client, provider).structured("verify", "Check", "Input", properties, 70)

    if valid:
        assert asyncio.run(exercise()) == {"safe": True}
    else:
        with pytest.raises(ServiceError):
            asyncio.run(exercise())


def test_anthropic_canonicalizes_a_case_insensitive_enum_match():
    def handle(request):
        return httpx.Response(200, json={"stop_reason": "end_turn", "content": [
            {"type": "text", "text": '{"categories":["Education"]}'},
        ]})

    async def exercise():
        properties = {"categories": {"type": "array", "items": {"type": "string", "enum": ["education"]}}}
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            return await TextService(client, ANTHROPIC).structured("verify", "Check", "Input", properties, 70)

    assert asyncio.run(exercise()) == {"categories": ["education"]}
