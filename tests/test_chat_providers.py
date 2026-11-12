import asyncio
import json

import httpx
import pytest

from ai_japanese_interview_assistant.config import PROVIDERS
from ai_japanese_interview_assistant.services import ServiceError, TextService, error_message


CHAT_PROVIDERS = [
    ("qwen", "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
     "qwen3.8-flash", {"enable_thinking": False}),
    ("kimi", "https://api.moonshot.cn/v1/chat/completions", "kimi-k3.1-pro",
     {"reasoning_effort": "low", "max_completion_tokens": 1724}),
    ("glm", "https://open.bigmodel.cn/api/paas/v4/chat/completions", "glm-5.3",
     {"reasoning_effort": "low", "max_tokens": 1724}),
    ("minimax", "https://api.minimax.cn/v1/chat/completions", "MiniMax-M3.1-Flash",
     {"reasoning_split": True, "reasoning_effort": "low", "max_completion_tokens": 1724}),
    ("gemini", "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
     "gemini-3.8-flash", {"reasoning_effort": "low", "max_tokens": 1724}),
]


def run_with_client(handler, operation):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await operation(client)
    return asyncio.run(run())


@pytest.mark.parametrize("code,url,model,options", CHAT_PROVIDERS)
def test_chat_provider_streams_only_subtitle_text(code, url, model, options):
    def handle(request):
        payload = json.loads(request.content)
        assert str(request.url) == url
        assert payload["model"] == model
        assert payload["stream"] is True
        assert payload["messages"][-1] == {"role": "user", "content": "こんにちは"}
        assert all(payload[key] == value for key, value in options.items())
        return httpx.Response(200, text=(
            'data: {"choices":[{"delta":{"reasoning_content":"private"},"finish_reason":null}]}\n\n'
            'data: {"choices":[{"delta":{"content":"你"},"finish_reason":null}]}\n\n'
            'data: {"choices":[{"delta":{"content":"好"},"finish_reason":"stop"}]}\n\n'
            'data: {"choices":[]}\n\n'
            'data: [DONE]\n\n'
        ))

    async def translate(client):
        service = TextService(client, PROVIDERS[code])
        return [part async for part in service.translate("こんにちは")]

    assert run_with_client(handle, translate) == ["你", "好"]


@pytest.mark.parametrize("tail", ["", 'data: [DONE]\n\n',
    'data: {"choices":[{"delta":{},"finish_reason":"length"}]}\n\n'])
def test_chat_provider_reports_an_incomplete_stream(tail):
    def handle(request):
        return httpx.Response(200, text=(
            'data: {"choices":[{"delta":{"content":"你"},"finish_reason":null}]}\n\n' + tail
        ))

    async def translate(client):
        service = TextService(client, PROVIDERS["qwen"])
        return [part async for part in service.translate("こんにちは")]

    with pytest.raises(ServiceError, match="未收到完整译文"):
        run_with_client(handle, translate)


@pytest.mark.parametrize("content,reason,valid", [
    ('{"safe":true}', "stop", True),
    ('{ "safe": "true" }', "stop", False),
    ('{"safe":true,"extra":1}', "stop", False),
    ('{"safe":true}', "length", False),
])
def test_chat_structured_result_requires_a_complete_schema_match(content, reason, valid):
    def handle(request):
        payload = json.loads(request.content)
        assert payload["model"] == "MiniMax-M3"
        assert '"safe"' in payload["messages"][0]["content"]
        assert payload["messages"][-1]["content"] == "Input"
        return httpx.Response(200, json={"choices": [{
            "message": {"content": content, "reasoning_content": "private"}, "finish_reason": reason,
        }]})

    async def structure(client):
        service = TextService(client, PROVIDERS["minimax"], model="MiniMax-M3")
        return await service.structured("verify", "Check", "Input", {"safe": {"type": "boolean"}}, 70)

    if valid:
        assert run_with_client(handle, structure) == {"safe": True}
    else:
        with pytest.raises(ServiceError):
            run_with_client(handle, structure)


def test_openai_model_override_keeps_responses_and_privacy_parameters():
    service = TextService(None, PROVIDERS["openai"], model="gpt-6.1-terra")
    assert service.payload("System", "Input", 32) == {
        "model": "gpt-6.1-terra", "reasoning": {"effort": "none"}, "instructions": "System",
        "input": "Input", "max_output_tokens": 32, "store": False,
    }


def test_deepseek_model_list_presets_use_responses_model_ids():
    assert PROVIDERS["deepseek"].models == ("deepseek-flash", "deepseek-v4-pro")


def test_claude_opus_uses_adaptive_thinking_with_structured_outputs():
    def handle(request):
        payload = json.loads(request.content)
        assert payload["thinking"] == {"type": "adaptive"}
        assert payload["max_tokens"] > 70
        assert payload["output_config"]["effort"] == "low"
        assert payload["output_config"]["format"]["schema"]["required"] == ["safe"]
        return httpx.Response(200, json={"stop_reason": "end_turn", "content": [
            {"type": "thinking", "thinking": ""},
            {"type": "text", "text": '{"safe":true}'},
        ]})

    async def structure(client):
        service = TextService(client, PROVIDERS["anthropic"], model="claude-opus-5-5")
        return await service.structured("verify", "Check", "Input", {"safe": {"type": "boolean"}}, 70)

    assert run_with_client(handle, structure) == {"safe": True}


@pytest.mark.parametrize("code", ["qwen", "kimi", "glm"])
def test_documented_chat_models_request_json_mode(code):
    def handle(request):
        payload = json.loads(request.content)
        assert payload["response_format"] == {"type": "json_object"}
        return httpx.Response(200, json={"choices": [{
            "message": {"content": '{"safe":true}'}, "finish_reason": "stop",
        }]})

    async def structure(client):
        service = TextService(client, PROVIDERS[code])
        return await service.structured("verify", "Check", "Input", {"safe": {"type": "boolean"}}, 70)

    assert run_with_client(handle, structure) == {"safe": True}


def test_qwen_workspace_uses_only_the_official_beijing_endpoint():
    provider = PROVIDERS["qwen"]
    assert provider.endpoint("llm-example") == (
        "https://llm-example.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions"
    )
    with pytest.raises(ValueError):
        provider.endpoint("example.com/")


def test_model_catalog_filters_non_text_openai_models():
    def handle(request):
        assert request.method == "GET"
        assert str(request.url) == "https://api.openai.com/v1/models"
        return httpx.Response(200, json={"data": [
            {"id": "gpt-6.1-terra"}, {"id": "gpt-6.1-sol"}, {"id": "gpt-6.1-terra"},
            {"id": "gpt-live-transcribe"}, {"id": "gpt-image-2"}, {"id": "gpt-6.1-codex"},
        ]})

    async def list_models(client):
        return await TextService(client, PROVIDERS["openai"]).list_models()

    assert run_with_client(handle, list_models) == ("gpt-6.1-sol", "gpt-6.1-terra")


def test_connection_check_sends_only_a_fixed_translation_sample():
    def handle(request):
        assert json.loads(request.content)["messages"][-1]["content"] == "おはようございます。"
        return httpx.Response(200, text=(
            'data: {"choices":[{"delta":{"content":"早上好。"},"finish_reason":"stop"}]}\n\n'
        ))

    async def check(client):
        return await TextService(client, PROVIDERS["qwen"]).check_connection()

    assert run_with_client(handle, check) is None


def test_unavailable_model_error_is_safe_to_display():
    response = httpx.Response(404)
    exc = httpx.HTTPStatusError("private model error", request=httpx.Request("POST", "https://example.com"),
                                response=response)
    assert "模型" in error_message(exc)
