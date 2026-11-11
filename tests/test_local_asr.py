import asyncio
from threading import Event

import pytest

from ai_japanese_interview_assistant import local_asr
from ai_japanese_interview_assistant.audio import AudioError
from ai_japanese_interview_assistant.local_asr import run_local_transcription
from ai_japanese_interview_assistant.transcription import TranscriptBook


def test_local_decoder_publishes_only_committed_segments():
    async def frames():
        for command in (b"one", b"two", None, b"three", None, b"unfinished"):
            yield command

    expected = {b"onetwo": "こんにちは", b"three": "自己紹介をお願いします。"}
    book = TranscriptBook()
    asyncio.run(run_local_transcription(expected.__getitem__, frames(), book.apply))
    assert [part.text for part in book.parts if part.final] == list(expected.values())


def test_local_subtitle_revises_the_same_row_before_finalizing():
    async def exercise():
        preview = asyncio.Event()
        second_preview = asyncio.Event()
        book = TranscriptBook()
        revisions = []

        def receive(event):
            part = book.apply(event)
            if event["type"].endswith(".revised"):
                revisions.append((part.item_id, part.text, part.final))
                (preview if len(revisions) == 1 else second_preview).set()
            elif event["type"].endswith(".completed"):
                revisions.append((part.item_id, part.text, part.final))

        async def frames():
            yield bytes(48000)
            await preview.wait()
            yield bytes(60000)
            await second_preview.wait()
            yield None

        results = iter(("日本に住む", "日本で働く", "日本で働きたいです。"))
        await asyncio.wait_for(
            run_local_transcription(lambda pcm: next(results), frames(), receive), 3,
        )
        assert revisions == [
            ("local-1", "日本に住む", False),
            ("local-1", "日本で働く", False),
            ("local-1", "日本で働きたいです。", True),
        ]

    asyncio.run(exercise())


def test_cancellation_disposes_frames_and_suppresses_late_decode():
    async def exercise():
        started = asyncio.Event()
        release = Event()
        closed = []
        events = []
        loop = asyncio.get_running_loop()

        def decode(pcm):
            loop.call_soon_threadsafe(started.set)
            release.wait(timeout=2)
            return "古い内容"

        async def frames():
            try:
                yield b"one"
                yield None
                await asyncio.Future()
            finally:
                closed.append(True)

        task = asyncio.create_task(run_local_transcription(decode, frames(), events.append))
        try:
            await asyncio.wait_for(started.wait(), 3)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            release.set()
        assert closed
        assert not any(event["type"].endswith(".completed") for event in events)

    asyncio.run(exercise())


def test_capture_failure_blocks_a_decode_finishing_in_the_same_loop_turn(monkeypatch):
    async def exercise():
        fail = asyncio.Event()
        decoding = asyncio.Event()
        complete = asyncio.Event()
        events = []

        async def frames():
            yield b"audio"
            yield None
            await fail.wait()
            raise AudioError("synthetic disconnection")

        async def decode_in_thread(decode, pcm):
            decoding.set()
            await complete.wait()
            return "late transcript"

        monkeypatch.setattr(local_asr.asyncio, "to_thread", decode_in_thread)
        task = asyncio.create_task(run_local_transcription(None, frames(), events.append))
        await asyncio.wait_for(decoding.wait(), 3)
        fail.set()
        complete.set()
        with pytest.raises(AudioError):
            await task
        assert events == []

    asyncio.run(exercise())
