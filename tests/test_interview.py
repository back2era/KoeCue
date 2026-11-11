import asyncio
import json

import pytest

from ai_japanese_interview_assistant.interview import Answer, InterviewService
from ai_japanese_interview_assistant.personal import PersonalInfo
from ai_japanese_interview_assistant.profiles import Fact
from ai_japanese_interview_assistant.services import ServiceError


class ScriptedText:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []
        self.schemas = {}

    async def structured(self, purpose, prompt, value, schema, max_tokens):
        self.calls.append((purpose, value))
        self.schemas[purpose] = schema
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


def test_interview_context_reaches_only_the_answer_draft():
    text = ScriptedText([
        {"question": True, "personal": False, "categories": []},
        {"before_ja": "優先順位を確認します。", "before_zh": "我会确认优先级。",
         "after_ja": "", "after_zh": "", "fact_ids": []},
        {"safe": True},
    ])
    question = "仕様変更にはどう対応しますか。"
    info = PersonalInfo(
        background="Private sample background", resume="Private sample resume",
        company="示例株式会社", role="开发工程师", scenario="技术面试",
    )

    answer = asyncio.run(InterviewService(text).suggest(question, automatic=True, personal_info=info))

    assert answer == Answer("優先順位を確認します。", "我会确认优先级。")
    assert text.calls[0] == ("question", question)
    assert json.loads(text.calls[1][1]) == {
        "question": question, "facts": [],
        "context": {"company": "示例株式会社", "role": "开发工程师", "scenario": "技术面试"},
    }
    assert json.loads(text.calls[2][1]) == {"ja": ["優先順位を確認します。", ""], "zh": ["我会确认优先级。", ""]}


def excerpt_info():
    return PersonalInfo(resume="I measured radio signals.\nPrivate fixture marker.")


EXCERPT_QUESTION = "無線信号の測定をしたプロジェクトについて教えてください。"
EXCERPT_CLASSIFICATION = {"question": True, "personal": True, "categories": ["project"]}
EXCERPT_DRAFT = {
    "before_ja": "", "before_zh": "", "after_ja": "", "after_zh": "", "fact_ids": [],
    "excerpt_ids": ["excerpt_1"], "excerpt_ja": ["無線信号を測定しました。"], "excerpt_zh": ["我测量了无线电信号。"],
}


def test_bilingual_claim_is_verified_against_the_exact_authorized_excerpt():
    text = ScriptedText([EXCERPT_CLASSIFICATION, EXCERPT_DRAFT, {"safe": True}])
    answer = asyncio.run(InterviewService(text).suggest(EXCERPT_QUESTION, automatic=True, personal_info=excerpt_info()))

    assert answer == Answer("無線信号を測定しました。", "我测量了无线电信号。")
    assert text.calls[0] == ("question", EXCERPT_QUESTION)
    assert json.loads(text.calls[1][1])["excerpts"] == [{"id": "excerpt_1", "text": "I measured radio signals."}]
    assert text.schemas["draft"]["excerpt_ids"]["items"]["enum"] == ["excerpt_1"]
    assert json.loads(text.calls[2][1])["excerpts"] == [{
        "source": "I measured radio signals.", "ja": "無線信号を測定しました。", "zh": "我测量了无线电信号。",
    }]


def test_verified_facts_and_resume_excerpts_share_a_two_item_request_limit():
    fact = Fact("verified", "project", "回路を作りました。", "我制作了电路。")
    draft = dict(EXCERPT_DRAFT, fact_ids=[fact.id])
    text = ScriptedText([EXCERPT_CLASSIFICATION, draft, {"safe": True}])
    info = PersonalInfo(resume="I measured radio signals.\nI developed a separate project.")

    answer = asyncio.run(InterviewService(text).suggest(
        EXCERPT_QUESTION, automatic=True, facts=(fact,), personal_info=info,
    ))

    payload = json.loads(text.calls[1][1])
    assert len(payload["facts"]) + len(payload["excerpts"]) == 2
    assert "I developed a separate project." not in text.calls[1][1]
    assert answer.ja.splitlines()[0] == fact.ja
    assert answer.zh.splitlines()[0] == fact.zh


@pytest.mark.parametrize("ids,ja,zh", [
    (["unknown"], ["無線信号を測定しました。"], ["我测量了无线电信号。"]),
    (["excerpt_1"], ["無線信号を測定しました。"], []),
    ([], [], []),
])
def test_missing_or_invalid_excerpt_attribution_stops_before_verification(ids, ja, zh):
    draft = dict(EXCERPT_DRAFT, excerpt_ids=ids, excerpt_ja=ja, excerpt_zh=zh)
    text = ScriptedText([EXCERPT_CLASSIFICATION, draft])

    with pytest.raises(ServiceError, match="核验"):
        asyncio.run(InterviewService(text).suggest(EXCERPT_QUESTION, automatic=True, personal_info=excerpt_info()))
    assert [purpose for purpose, _ in text.calls] == ["question", "draft"]


def test_answer_is_rejected_when_one_language_overstates_the_excerpt():
    draft = dict(EXCERPT_DRAFT, excerpt_zh=["我带领团队测量了无线电信号。"])
    text = ScriptedText([EXCERPT_CLASSIFICATION, draft, {"safe": False}])

    with pytest.raises(ServiceError, match="核验"):
        asyncio.run(InterviewService(text).suggest(EXCERPT_QUESTION, automatic=True, personal_info=excerpt_info()))
    assert json.loads(text.calls[2][1])["excerpts"] == [{
        "source": "I measured radio signals.", "ja": "無線信号を測定しました。", "zh": "我带领团队测量了无线电信号。",
    }]


@pytest.mark.parametrize("stage,expected", [
    ("question", ["question"]), ("draft", ["question", "draft"]),
])
def test_revocation_stops_further_excerpt_requests(stage, expected):
    authorized = True

    class RevokingText(ScriptedText):
        async def structured(self, purpose, prompt, value, schema, max_tokens):
            nonlocal authorized
            response = await super().structured(purpose, prompt, value, schema, max_tokens)
            if purpose == stage:
                authorized = False
            return response

    text = RevokingText([EXCERPT_CLASSIFICATION, EXCERPT_DRAFT])
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(InterviewService(text).suggest(
            EXCERPT_QUESTION, automatic=True, personal_info=excerpt_info(), allowed=lambda: authorized,
        ))
    assert [purpose for purpose, _ in text.calls] == expected
