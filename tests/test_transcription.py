import asyncio
import json
from contextlib import asynccontextmanager

import pytest

from ai_japanese_interview_assistant.transcription import TranscriptBook, TurnCutter, run_transcription


def test_finals_replace_deltas_and_remain_in_commit_order():
    book = TranscriptBook()
    book.apply({"type": "conversation.item.input_audio_transcription.delta", "item_id": "b", "delta": "志望"})
    book.apply({"type": "input_audio_buffer.committed", "item_id": "a", "previous_item_id": None})
    book.apply({"type": "input_audio_buffer.committed", "item_id": "b", "previous_item_id": "a"})
    book.apply({"type": "conversation.item.input_audio_transcription.completed", "item_id": "b", "transcript": "志望動機は？"})
    book.apply({"type": "conversation.item.input_audio_transcription.completed", "item_id": "a", "transcript": "こんにちは"})
    book.apply({"type": "conversation.item.input_audio_transcription.delta", "item_id": "b", "delta": "古い"})
    assert [(part.item_id, part.text) for part in book.parts] == [
        ("a", "こんにちは"), ("b", "志望動機は？"),
    ]


def test_silence_is_ignored_and_speech_is_committed_after_tail():
    silence = bytes(960)
    speech = b"\x01\x00" * 480
    cutter = TurnCutter()
    assert all(not cutter.push(silence, False) for _ in range(50))
    assert cutter.push(speech, True) == [silence * 10 + speech]
    for _ in range(29):
        assert cutter.push(silence, False) == [silence]
    assert cutter.push(silence, False) == [silence, None]
    assert cutter.finish() == []


def test_websocket_appends_pcm_and_waits_for_final_after_commit():
    class Socket:
        def __init__(self):
            self.sent = []
            self.incoming = asyncio.Queue()
            self.incoming.put_nowait({"type": "session.updated"})

        async def recv(self):
            return json.dumps(await self.incoming.get())

        async def send(self, payload):
            event = json.loads(payload)
            self.sent.append(event)
            if event["type"] == "input_audio_buffer.commit":
                self.incoming.put_nowait({
                    "type": "conversation.item.input_audio_transcription.completed",
                    "item_id": "item_1", "transcript": "自己紹介をお願いします。",
                })

    socket = Socket()

    @asynccontextmanager
    async def connect(*args, **kwargs):
        yield socket

    async def frames():
        yield b"\x00\x01"
        yield None

    events = []
    asyncio.run(run_transcription("test", frames(), events.append, connect=connect))
    assert socket.sent[0]["session"]["audio"]["input"]["transcription"]["languages"] == ["ja"]
    assert socket.sent[1] == {"type": "input_audio_buffer.append", "audio": "AAE="}
    assert socket.sent[2] == {"type": "input_audio_buffer.commit"}
    assert events[0]["transcript"] == "自己紹介をお願いします。"


def test_stop_releases_websocket_and_producer():
    async def exercise():
        ready = asyncio.Event()
        closed = []

        class Socket:
            async def send(self, payload):
                pass

            async def recv(self):
                if not ready.is_set():
                    return '{"type":"session.updated"}'
                await asyncio.Future()

        @asynccontextmanager
        async def connect(*args, **kwargs):
            try:
                yield Socket()
            finally:
                closed.append("socket")

        async def frames():
            try:
                await asyncio.Future()
                yield b""
            finally:
                closed.append("producer")

        task = asyncio.create_task(run_transcription("test", frames(), lambda event: None, ready.set, connect=connect))
        await ready.wait()
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert set(closed) == {"socket", "producer"}

    asyncio.run(exercise())
