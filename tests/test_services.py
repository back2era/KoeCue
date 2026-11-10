import asyncio
import json

import httpx
import pytest

from ai_japanese_interview_assistant.services import TextService, ServiceError


def test_translation_streams_deltas_without_storing_response():
    def handle(request):
        payload = json.loads(request.content)
        assert payload["store"] is False
        assert payload["stream"] is True
        assert payload["input"] == "こんにちは"
        return httpx.Response(200, text=(
            'data: {"type":"response.output_text.delta","delta":"你"}\n\n'
            'data: {"type":"response.output_text.delta","delta":"好"}\n\n'
            'data: {"type":"response.completed"}\n\n'
        ))

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            service = TextService(client)
            return [delta async for delta in service.translate("こんにちは")]

    assert asyncio.run(exercise()) == ["你", "好"]


def test_truncated_stream_does_not_become_a_successful_translation():
    async def exercise():
        transport = httpx.MockTransport(lambda request: httpx.Response(200, text=(
            'data: {"type":"response.output_text.delta","delta":"未完"}\n\n'
        )))
        async with httpx.AsyncClient(transport=transport) as client:
            return [delta async for delta in TextService(client).translate("こんにちは")]

    with pytest.raises(ServiceError):
        asyncio.run(exercise())
