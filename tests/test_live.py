import asyncio

import pytest

from ai_japanese_interview_assistant.interview import Answer, InterviewService
from ai_japanese_interview_assistant.live import LiveWorker
from ai_japanese_interview_assistant.personal import PersonalInfo
from ai_japanese_interview_assistant.profiles import Fact


def test_revoking_personal_info_cancels_a_scoped_answer():
    async def exercise():
        entered = asyncio.Event()

        class BlockingText:
            async def structured(self, purpose, prompt, value, schema, max_tokens):
                assert purpose == "draft"
                entered.set()
                await asyncio.Future()

        info = PersonalInfo(company="示例株式会社")
        worker = LiveWorker(1, None, "test", personal_info=info)
        worker.loop = asyncio.get_running_loop()
        worker.interview = InterviewService(BlockingText())
        updates = []
        worker.answer.connect(lambda *args: updates.append(args))
        row_id = (0, 1, "test-row")
        worker.start_answer(row_id, "どのように進めますか。")
        task = worker.jobs[("answer", row_id)]
        await asyncio.wait_for(entered.wait(), timeout=1)

        worker.revoke_profile()

        assert not worker.personal_info
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=1)
        assert updates == [
            (row_id, None, "正在生成建议…", True),
            (row_id, None, "回答已取消", True),
        ]

    asyncio.run(exercise())

def test_stopping_worker_releases_its_authorized_snapshot():
    info = PersonalInfo(background="示例背景")
    facts = (Fact("fixture", "skill", "図面を読みます。", "我能读图纸。"),)
    worker = LiveWorker(1, None, "test", facts=facts, personal_info=info)

    worker.stop()

    assert not worker.personal_info
    assert not worker.facts


def test_automatic_suggestion_waits_for_capacity_and_runs_without_clicking(monkeypatch):
    from ai_japanese_interview_assistant import live

    async def exercise():
        release = asyncio.Event()
        answered = asyncio.Event()
        completed = Answer("はい、お願いします。", "好的，请继续。")

        class Replies:
            async def suggest(self, text, *, automatic, **kwargs):
                assert automatic
                return completed

            async def annotate_answer(self, answer):
                return answer

        async def occupying_job():
            await release.wait()

        monkeypatch.setattr(live, "record", lambda *args: None)
        worker = LiveWorker(1, None, "test")
        worker.interview = Replies()
        received = []

        def receive(row_id, answer, status, scoped):
            received.append((row_id, answer, status, scoped))
            if answer:
                answered.set()

        worker.answer.connect(receive)
        for index in range(8):
            worker.start_job(("translation", index), occupying_job)
        row_id = (0, 1, "queued")
        worker.start_answer(row_id, "それでは説明します。", automatic=True)
        worker.start_answer(row_id, "それでは説明します。", automatic=True)
        assert received == [(row_id, None, live.ANSWER_PENDING, False)]
        release.set()
        await asyncio.wait_for(answered.wait(), 1)
        assert [item[1] for item in received if item[1]] == [completed]

    asyncio.run(exercise())


@pytest.mark.parametrize("annotation_fails,with_reading", [(False, True), (False, False), (True, True)])
def test_answer_arrives_before_reading_aids_and_receives_current_difficulty(
    monkeypatch, annotation_fails, with_reading,
):
    from ai_japanese_interview_assistant import live
    from ai_japanese_interview_assistant.answer_format import Highlight, RubyAnnotation

    async def exercise():
        levels = []
        events = []
        annotating = asyncio.Event()
        release = asyncio.Event()
        plain = Answer("実装します。", "我会实现。")
        readings = (RubyAnnotation(0, 2, "じっそう"),) if with_reading else ()
        enriched = Answer(plain.ja, plain.zh, readings, (Highlight(0, 2),))

        class Replies:
            async def suggest(self, text, *, level, **kwargs):
                levels.append(level)
                return plain

            async def annotate_answer(self, answer):
                assert answer == plain
                annotating.set()
                await release.wait()
                if annotation_fails:
                    raise TimeoutError
                return enriched

        monkeypatch.setattr(live, "record", lambda *args: None)
        worker = LiveWorker(1, None, "test", answer_level="N2")
        worker.answer_level = "N1"
        worker.interview = Replies()
        worker.answer.connect(lambda key, answer, state, scoped: events.append(answer) if answer else None)
        row_id = (0, 1, "reading")
        worker.start_answer(row_id, "どうしますか。", automatic=True)
        task = worker.jobs[("answer", row_id)]
        await asyncio.wait_for(annotating.wait(), 1)
        assert levels == ["N1"]
        assert events == [plain]
        release.set()
        await asyncio.wait_for(task, 1)
        assert events == ([plain] if annotation_fails else [plain, enriched])

    asyncio.run(exercise())
def test_final_question_debounce_and_follow_up_context(monkeypatch):
    async def exercise():
        worker = LiveWorker(1, None, "test", auto_answer=True)
        translations = []
        suggestions = []
        monkeypatch.setattr(worker, "start_translation", lambda *args: translations.append(args))
        monkeypatch.setattr(worker, "start_answer", lambda *args: suggestions.append(args))

        def final(item, sentence):
            worker.on_event({"type": "conversation.item.input_audio_transcription.completed",
                             "item_id": item, "transcript": sentence})

        final("partial", "えーと")
        final("first", "SPIの特徴を教えてください。")
        final("duplicate", "SPI の特徴を教えてください！")
        final("followup", "なぜですか？")
        assert len(translations) == 4
        assert [item[0][-1] for item in suggestions] == ["first", "followup"]
        assert worker.preceding((0, 1, "followup"))[-1] == "SPI の特徴を教えてください！"

    asyncio.run(exercise())


def test_timed_out_answer_emits_safe_failure_without_a_draft(monkeypatch):
    from ai_japanese_interview_assistant import live

    async def exercise():
        class Unavailable:
            async def suggest(self, *args, **kwargs):
                await asyncio.Future()

        worker = LiveWorker(1, None, "test")
        worker.interview = Unavailable()
        replies = []
        worker.answer.connect(lambda _, answer, status, scoped: replies.append((answer, status)))
        monkeypatch.setattr(live, "ANSWER_TIMEOUT", 0.01)
        monkeypatch.setattr(live, "record", lambda *args: None)
        await worker.suggest((0, 1, "timeout"), "どのように進めますか。", automatic=True)
        assert replies[0] == (None, live.ANSWER_PENDING)
        assert replies[-1][0] is None and "超时" in replies[-1][1]

    asyncio.run(exercise())
