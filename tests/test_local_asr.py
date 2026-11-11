import asyncio
from threading import Event

import pytest

from ai_japanese_interview_assistant import local_asr
from ai_japanese_interview_assistant.audio import AudioError
from ai_japanese_interview_assistant.local_asr import run_local_transcription
from ai_japanese_interview_assistant.transcription import TranscriptBook


def test_short_turns_finalize_and_the_uncommitted_tail_is_discarded():
    async def frames():
        for command in (b"one", b"two", None, b"three", None, b"unfinished"):
            yield command

    expected = {b"onetwo": "こんにちは", b"three": "自己紹介をお願いします。"}
    book = TranscriptBook()
    asyncio.run(run_local_transcription(expected.__getitem__, frames(), book.apply))
    assert [part.text for part in book.parts] == list(expected.values())
    assert all(part.final for part in book.parts)


@pytest.mark.parametrize("commit", [False, True])
def test_cancellation_disposes_frames_and_suppresses_late_decode(commit):
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
                if commit:
                    yield b"one"
                    yield None
                else:
                    yield b"\x01\x00" * 48000
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
        assert events == []

    asyncio.run(exercise())


@pytest.mark.parametrize("final_text", ["自己紹介をお願いいたします。", ""])
def test_live_partial_grows_before_commit_and_final_uses_all_audio(final_text):
    async def exercise():
        first = b"\x01\x00" * 48000
        second = b"\x02\x00" * 48000
        tail = b"\x03\x00" * 480
        results = {first: "自己紹介。", first + second: "自己紹介をお願いします。",
                   first + second + tail: final_text}
        events = []
        arrived = asyncio.Event()
        book = TranscriptBook()

        def on_event(event):
            events.append(event)
            book.apply(event)
            arrived.set()

        async def frames():
            yield first
            await asyncio.wait_for(arrived.wait(), 2)
            assert book.parts[0].text == "自己紹介"
            assert not book.parts[0].final
            arrived.clear()
            yield second
            await asyncio.wait_for(arrived.wait(), 2)
            assert book.parts[0].text == "自己紹介をお願いします"
            assert not book.parts[0].final
            yield tail
            yield None

        await run_local_transcription(results.__getitem__, frames(), on_event)
        assert [event["type"].rsplit(".", 1)[-1] for event in events] == [
            "delta", "delta", "committed", "completed",
        ]
        assert len({event["item_id"] for event in events}) == 1
        assert book.parts[0].final
        assert book.parts[0].text == final_text

    asyncio.run(exercise())


def test_partial_can_extend_after_an_earlier_spelling_changes():
    async def exercise():
        first = b"\x01\x00" * 48000
        continuation = b"\x02\x00" * 48000
        hypotheses = {first: "最も難しかった課題と", first + continuation: "もっとも難しかった課題とそれを"}
        arrived = asyncio.Event()
        book = TranscriptBook()

        def on_event(event):
            book.apply(event)
            arrived.set()

        async def frames():
            yield first
            await asyncio.wait_for(arrived.wait(), 2)
            arrived.clear()
            yield continuation
            await asyncio.wait_for(arrived.wait(), 2)
            assert book.parts[0].text == "最も難しかった課題とそれを"
            yield None

        await run_local_transcription(hypotheses.__getitem__, frames(), on_event)
        assert book.parts[0].text == "もっとも難しかった課題とそれを"
        assert book.parts[0].final

    asyncio.run(exercise())


def test_commit_supersedes_inflight_partial_and_prioritizes_whole_turn():
    async def exercise():
        first = b"\x01\x00" * 48000
        tail = b"\x02\x00" * 480
        next_turn = b"\x03\x00" * 48000
        started = asyncio.Event()
        captured = asyncio.Event()
        published = asyncio.Event()
        release = Event()
        calls = []
        events = []
        loop = asyncio.get_running_loop()

        def decode(pcm):
            calls.append(pcm)
            if pcm == first:
                loop.call_soon_threadsafe(started.set)
                if not release.wait(3):
                    raise TimeoutError("partial release")
                return "古い字幕"
            return {first + tail: "最初の質問。", next_turn: "次の質問"}[pcm]

        def on_event(event):
            events.append(event)
            if event["type"].endswith(".delta"):
                published.set()

        async def frames():
            yield first
            await asyncio.wait_for(started.wait(), 2)
            yield tail
            yield None
            yield next_turn
            captured.set()
            await asyncio.wait_for(published.wait(), 2)
            yield None

        task = asyncio.create_task(run_local_transcription(decode, frames(), on_event))
        try:
            await asyncio.wait_for(captured.wait(), 3)
            assert calls == [first]
        finally:
            release.set()
        await asyncio.wait_for(task, 3)
        assert calls == [first, first + tail, next_turn, next_turn]
        assert [(event["item_id"], event["delta"]) for event in events if "delta" in event] == [
            ("local-2", "次の質問"),
        ]
        assert [event["transcript"] for event in events if "transcript" in event] == [
            "最初の質問。", "次の質問",
        ]

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
