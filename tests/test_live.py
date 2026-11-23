import asyncio

import pytest

from ai_japanese_interview_assistant.interview import Answer, InterviewService
from ai_japanese_interview_assistant.live import LiveWorker
from ai_japanese_interview_assistant.personal import PersonalInfo
from ai_japanese_interview_assistant.profiles import Fact


def test_chinese_transcript_automatically_suggests_without_translation(monkeypatch):
    from ai_japanese_interview_assistant import live

    async def exercise():
        expected = Answer("", "我会先听取大家的意见。")

        class Reply:
            async def suggest(self, question, *, automatic, **kwargs):
                assert automatic
                assert question == "团队意见不一致时怎么办？"
                return expected

        worker = LiveWorker(1, None, "test", language="zh", auto_answer=True)
        worker.interview = Reply()
        suggestions = []
        worker.answer.connect(lambda row_id, answer, status, scoped: suggestions.append(answer))
        worker.on_event({
            "type": "conversation.item.input_audio_transcription.completed",
            "item_id": "question",
            "transcript": "团队意见不一致时怎么办？",
        })
        assert set(worker.jobs) == {("answer", (0, 1, "question"))}
        await asyncio.gather(*worker.jobs.values())
        assert suggestions == [None, expected]

    monkeypatch.setattr(live, "record", lambda *args: None)
    asyncio.run(exercise())


@pytest.mark.parametrize("target,expected", [("ja", [("Good morning.", "en", "ja")]), ("en", []), ("", [])])
def test_english_transcript_dispatches_only_the_selected_translation(target, expected, monkeypatch):
    from ai_japanese_interview_assistant import live

    async def exercise():
        calls = []

        class Translator:
            async def translate(self, text, *, source_language, target_language):
                calls.append((text, source_language, target_language))
                yield "おはようございます。"

        worker = LiveWorker(1, None, "test", language="en", translation_language=target,
                            answer_language="zh")
        worker.service = Translator()
        worker.on_event({"type": "conversation.item.input_audio_transcription.completed",
                         "item_id": "sample", "transcript": "Good morning."})
        await asyncio.gather(*worker.jobs.values())
        assert calls == expected

    monkeypatch.setattr(live, "record", lambda *args: None)
    asyncio.run(exercise())


def test_follow_up_uses_only_the_previous_final_transcripts_in_this_session(monkeypatch):
    from ai_japanese_interview_assistant import live

    async def exercise():
        calls = []

        class Replies:
            async def suggest(self, text, *, recent_transcript, **kwargs):
                calls.append((text, recent_transcript))
                return Answer("", "好的。")

        worker = LiveWorker(2, None, "test", language="zh", auto_answer=True,
                            previous_transcript=("上一次暂停前谈到电源项目。",))
        worker.interview = Replies()
        for index, text in enumerate(("先介绍反激电源项目。", "这个项目怎么测试？")):
            worker.on_event({"type": "conversation.item.input_audio_transcription.completed",
                             "item_id": str(index), "transcript": text})
        await asyncio.gather(*worker.jobs.values())

        assert calls == [
            ("先介绍反激电源项目。", ("上一次暂停前谈到电源项目。",)),
            ("这个项目怎么测试？", ("上一次暂停前谈到电源项目。", "先介绍反激电源项目。")),
        ]

    monkeypatch.setattr(live, "record", lambda *args: None)
    asyncio.run(exercise())


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


def test_annotations_disabled_skips_the_model_call(monkeypatch):
    from ai_japanese_interview_assistant import live

    async def exercise():
        plain = Answer("実装します。", "我会实现。")

        class Replies:
            async def suggest(self, *args, **kwargs):
                return plain

            async def annotate_answer(self, answer):
                pytest.fail("annotations were disabled")

        worker = LiveWorker(1, None, "test", show_answer_annotations=False)
        worker.interview = Replies()
        answers = []
        worker.answer.connect(lambda key, answer, *_: answers.append(answer) if answer else None)
        worker.start_answer((0, 1, "sample"), "どうしますか。")
        await asyncio.gather(*worker.jobs.values())
        assert answers == [plain]

    monkeypatch.setattr(live, "record", lambda *args: None)
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
