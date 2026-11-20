import asyncio
from contextlib import asynccontextmanager
import gzip
import json
import wave
from io import BytesIO

import httpx
import pytest

from ai_japanese_interview_assistant.config import DEEPSEEK, OPENAI, QWEN
from ai_japanese_interview_assistant.speech import SPEECH_MODELS, run_deepseek, run_doubao, run_qwen
from ai_japanese_interview_assistant.transcription import AudioProcessor, LOCAL_PREVIEW_EVENT, RealtimeError


COMPLETE = "conversation.item.input_audio_transcription.completed"


def test_speech_models_use_their_own_credentials():
    assert SPEECH_MODELS["openai"].provider is OPENAI
    assert SPEECH_MODELS["qwen-3.1"].provider is SPEECH_MODELS["qwen-3.0"].provider is QWEN
    assert SPEECH_MODELS["deepseek"].provider is DEEPSEEK
    assert SPEECH_MODELS["doubao"].provider.key_env == "DOUBAO_ASR_API_KEY"
    assert "ja" not in SPEECH_MODELS["doubao"].languages
    assert SPEECH_MODELS["local"].provider is None


def test_realtime_audio_keeps_silence_at_the_provider_sample_rate():
    processor = AudioProcessor(16000, 2, continuous=True)
    output = processor.push(bytes(16000 * 2 * 2))
    assert output == [bytes(16000 * 2)]
    assert processor.finish_turn() == []


def test_qwen_streams_audio_between_start_and_finish_and_reuses_sentence_id():
    async def exercise():
        messages = asyncio.Queue()
        events = []
        reached_preview = asyncio.Event()

        def response(event, sentence=None):
            details = {"output": {"sentence": sentence}} if sentence else {}
            messages.put_nowait(json.dumps({"header": {"event": event}, "payload": details}))

        class Socket:
            async def send(self, packet):
                if isinstance(packet, bytes):
                    assert packet == bytes(3200)
                    response("result-generated", {"sentence_id": 1, "text": "面接", "sentence_end": False})
                else:
                    request = json.loads(packet)
                    if request["header"]["action"] == "run-task":
                        assert request["payload"]["model"] == "qwen-audio-3.0-asr-flash-streaming"
                        assert request["payload"]["parameters"]["language_hints"] == ["ja"]
                        assert request["payload"]["parameters"]["sample_rate"] == 16000
                        response("task-started")
                    else:
                        assert request["header"]["action"] == "finish-task"
                        response("result-generated", {"sentence_id": 1, "text": "面接を始めます。", "sentence_end": True})
                        response("task-finished")

            recv = messages.get

        @asynccontextmanager
        async def connect(url, **options):
            assert url == "wss://dashscope.aliyuncs.com/api-ws/v1/inference"
            assert options["additional_headers"]["Authorization"] == "Bearer speech-only"
            yield Socket()

        async def audio():
            yield bytes(3200)
            await reached_preview.wait()

        def on_event(event):
            events.append(event)
            if event["type"] == LOCAL_PREVIEW_EVENT:
                reached_preview.set()

        await asyncio.wait_for(run_qwen(
            "speech-only", audio(), on_event, lambda: None,
            model=SPEECH_MODELS["qwen-3.0"], language="ja", connect=connect,
        ), 2)
        assert [(e["type"], e["item_id"], e["transcript"]) for e in events] == [
            (LOCAL_PREVIEW_EVENT, "qwen-1", "面接"),
            (COMPLETE, "qwen-1", "面接を始めます。"),
        ]

    asyncio.run(exercise())


def test_doubao_uses_binary_audio_and_deduplicates_final_sentences():
    async def exercise():
        messages = asyncio.Queue()
        events = []
        preview = asyncio.Event()

        def response(result, last=False):
            payload = gzip.compress(json.dumps({"result": result}).encode())
            header = bytes([0x11, 0x93 if last else 0x91, 0x11, 0])
            messages.put_nowait(header + (1).to_bytes(4, "big") + len(payload).to_bytes(4, "big") + payload)

        utterance = {"start_time": 15, "end_time": 500, "text": "请介绍反激。", "definite": True}

        class Socket:
            async def send(self, packet):
                assert int.from_bytes(packet[4:8], "big") == len(packet[8:])
                payload = gzip.decompress(packet[8:])
                if packet[1] == 0x10:
                    request = json.loads(payload)
                    assert request["audio"]["rate"] == 16000
                    assert request["request"]["enable_nonstream"] is True
                    response({})
                elif packet[1] == 0x20:
                    assert payload == bytes(6400)
                    response({"text": "请介绍反击"})
                else:
                    assert packet[1] == 0x22
                    response({"text": utterance["text"], "utterances": [utterance]}, last=False)
                    response({"text": utterance["text"], "utterances": [utterance]}, last=True)

            recv = messages.get

        @asynccontextmanager
        async def connect(url, **options):
            assert url.endswith("/bigmodel_async")
            headers = options["additional_headers"]
            assert headers["X-Api-Key"] == "speech-only"
            assert headers["X-Api-Resource-Id"] == "volc.seedasr.sauc.duration"
            yield Socket()

        async def audio():
            yield bytes(6400)
            await preview.wait()

        def on_event(event):
            events.append(event)
            if event["type"] == LOCAL_PREVIEW_EVENT:
                preview.set()

        await asyncio.wait_for(run_doubao("speech-only", audio(), on_event, lambda: None, connect=connect), 2)
        assert [(e["type"], e["item_id"], e["transcript"]) for e in events] == [
            (LOCAL_PREVIEW_EVENT, "doubao-1", "请介绍反击"),
            (COMPLETE, "doubao-1", "请介绍反激。"),
        ]

    asyncio.run(exercise())


@pytest.mark.parametrize("status", (200, 429))
def test_deepseek_posts_only_completed_wav_and_reports_rate_limit(status):
    async def exercise():
        events = []
        requests = []
        pcm = bytes(4800)

        async def audio():
            yield pcm
            yield None
            yield bytes(400)

        async def reply(request):
            requests.append(request)
            assert request.url.path == "/v1/tools/asr"
            assert request.headers["Authorization"] == "Bearer speech-only"
            multipart = await request.aread()
            start = multipart.index(b"RIFF")
            with wave.open(BytesIO(multipart[start:start + 44 + len(pcm)])) as wav:
                assert (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) == (1, 2, 24000)
                assert wav.readframes(wav.getnframes()) == pcm
            return httpx.Response(status, json={"text": "请介绍项目。"})

        async def run():
            async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
                await run_deepseek("speech-only", audio(), events.append, client)

        if status == 429:
            with pytest.raises(RealtimeError, match="限流"):
                await run()
            assert events == []
        else:
            await run()
            assert events == [{"type": COMPLETE, "item_id": "deepseek-1", "transcript": "请介绍项目。"}]
        assert len(requests) == 1

    asyncio.run(exercise())


def test_cancelling_deepseek_closes_audio_and_drops_queued_turns():
    async def exercise():
        requested = asyncio.Event()
        queued = asyncio.Event()
        closed = asyncio.Event()
        events = []
        requests = []

        async def frames():
            try:
                yield bytes(4800)
                yield None
                await requested.wait()
                yield bytes(4800)
                yield None
                queued.set()
                await asyncio.Future()
            finally:
                closed.set()

        async def reply(request):
            requests.append(request)
            requested.set()
            await asyncio.Future()

        async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
            task = asyncio.create_task(run_deepseek("test-key", frames(), events.append, client))
            await asyncio.wait_for(queued.wait(), 2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 2)
        assert len(requests) == 1
        assert closed.is_set()
        assert events == []

    asyncio.run(exercise())
