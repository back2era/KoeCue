import asyncio

import pytest

from ai_japanese_interview_assistant.interview import InterviewService
from ai_japanese_interview_assistant.live import LiveWorker
from ai_japanese_interview_assistant.personal import PersonalInfo
from ai_japanese_interview_assistant.profiles import Fact


def test_revoking_personal_info_cancels_a_scoped_answer():
    async def exercise():
        entered = asyncio.Event()

        class BlockingText:
            async def structured(self, purpose, prompt, value, schema, max_tokens):
                assert purpose == "question"
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
            (row_id, None, "正在检查问题…", True),
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
