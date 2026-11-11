import asyncio
from contextlib import asynccontextmanager
import json

from ai_japanese_interview_assistant.live import LiveWorker
from ai_japanese_interview_assistant.transcription import TranscriptPart, run_transcription


def test_openai_deltas_arrive_while_speaking_and_only_final_runs_text_jobs(monkeypatch):
    async def exercise():
        worker = LiveWorker(4, None, "fixture", session_id=7, auto_answer=True)
        row = (7, 4, "item-1")
        received = asyncio.Event()
        partials, finals, orders, translations, answers = [], [], [], [], []

        def show_partial(payload):
            partials.append(payload)
            if len(partials) == 2:
                received.set()

        worker.partial_transcript.connect(show_partial)
        worker.transcript.connect(finals.append)
        worker.order.connect(orders.append)
        monkeypatch.setattr(worker, "start_translation", lambda *args: translations.append(args))
        monkeypatch.setattr(worker, "start_answer", lambda *args: answers.append(args))

        class Socket:
            def __init__(self):
                self.incoming = asyncio.Queue()
                self.incoming.put_nowait({"type": "session.updated"})

            async def recv(self):
                return json.dumps(await self.incoming.get())

            def emit(self, kind, **fields):
                self.incoming.put_nowait({"type": kind, "item_id": "item-1", **fields})

            async def send(self, payload):
                kind = json.loads(payload)["type"]
                if kind == "input_audio_buffer.append":
                    self.emit("conversation.item.input_audio_transcription.delta", delta="ご経")
                    self.emit("conversation.item.input_audio_transcription.delta", delta="験を")
                elif kind == "input_audio_buffer.commit":
                    self.emit("input_audio_buffer.committed", previous_item_id=None)
                    self.emit("conversation.item.input_audio_transcription.completed", transcript="ご経験を教えてください。")
                    self.emit("conversation.item.input_audio_transcription.delta", delta="古い内容")

        @asynccontextmanager
        async def connect(*args, **kwargs):
            yield Socket()

        async def frames():
            yield b"\x01\x00" * 24000
            await asyncio.wait_for(received.wait(), 2)
            assert partials == [(row, TranscriptPart("item-1", "ご経")),
                                (row, TranscriptPart("item-1", "ご経験を"))]
            assert not any((finals, orders, translations, answers))
            yield None

        await run_transcription("fixture", frames(), worker.on_event, connect=connect)
        assert len(partials) == 2
        assert finals == [(row, TranscriptPart("item-1", "ご経験を教えてください。", final=True))]
        assert orders == [(row,), (row,)]
        assert translations == [(row, "ご経験を教えてください。")]
        assert answers == [(row, "ご経験を教えてください。", True)]

    asyncio.run(exercise())


def test_late_delta_from_an_older_turn_does_not_take_over_live_preview():
    worker = LiveWorker(1, None, "fixture")
    partials = []
    worker.partial_transcript.connect(partials.append)
    worker.on_event({"type": "input_audio_buffer.committed", "item_id": "older"})
    for item, text in (("newer", "次の"), ("older", "前の"), ("newer", "発言")):
        worker.on_event({
            "type": "conversation.item.input_audio_transcription.delta",
            "item_id": item, "delta": text,
        })
    assert [(part.item_id, part.text) for _, part in partials] == [
        ("newer", "次の"), ("newer", "次の発言"),
    ]
