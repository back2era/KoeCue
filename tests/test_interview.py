import asyncio

import pytest

from ai_japanese_interview_assistant.interview import Answer, InterviewService
from ai_japanese_interview_assistant.services import ServiceError


class ScriptedText:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    async def structured(self, purpose, prompt, value, schema, max_tokens):
        self.calls.append((purpose, value))
        return next(self.responses)


def test_automatic_mode_does_not_generate_for_a_statement():
    text = ScriptedText([{"question": False, "personal": False, "categories": []}])
    assert asyncio.run(InterviewService(text).suggest("今日は面接の日です。", automatic=True)) is None
    assert [call[0] for call in text.calls] == ["question"]


def test_question_yields_bilingual_answer_after_check():
    text = ScriptedText([
        {"question": True, "personal": False, "categories": []},
        {"before_ja": "まず、要件を確認します。", "before_zh": "首先确认需求。",
         "after_ja": "次に、優先順位を決めます。", "after_zh": "接着确定优先级。", "fact_ids": []},
        {"safe": True},
    ])
    answer = asyncio.run(InterviewService(text).suggest("要件が変わったらどうしますか。", automatic=True))
    assert answer == Answer("まず、要件を確認します。\n次に、優先順位を決めます。", "首先确认需求。\n接着确定优先级。")


def test_unsupported_personal_claim_is_not_shown():
    text = ScriptedText([
        {"question": True, "personal": False, "categories": []},
        {"before_ja": "私は東京大学を卒業しました。", "before_zh": "我毕业于东京大学。",
         "after_ja": "", "after_zh": "", "fact_ids": []},
        {"safe": False},
    ])
    with pytest.raises(ServiceError, match="核验"):
        asyncio.run(InterviewService(text).suggest("どのように進めますか。", automatic=True))


def test_personal_question_without_facts_does_not_request_a_draft():
    text = ScriptedText([{"question": True, "personal": True, "categories": ["project"]}])
    with pytest.raises(ServiceError, match="真实"):
        asyncio.run(InterviewService(text).suggest("研究の経験を教えてください。", automatic=True))
    assert len(text.calls) == 1
