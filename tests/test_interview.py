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
        self.prompts = {}
        self.schemas = {}

    async def structured(self, purpose, prompt, value, schema, max_tokens):
        self.calls.append((purpose, value))
        self.prompts[purpose] = prompt
        self.schemas[purpose] = schema
        return next(self.responses)


def test_automatic_mode_suggests_an_acknowledgement_for_a_statement():
    text = ScriptedText([
        {"question": False, "personal": False, "categories": []},
        {"before_en": "Thanks for having me today.", "before_zh": "今天请多关照。",
         "after_en": "", "after_zh": "", "fact_ids": []},
        {"safe": True},
    ])
    fact = Fact("fixture", "project", "I built a circuit.", "我制作了电路。")

    answer = asyncio.run(InterviewService(text).suggest("それでは面接を始めます。", automatic=True, facts=(fact,)))

    assert answer == Answer("Thanks for having me today.", "今天请多关照。")
    assert json.loads(text.calls[1][1])["facts"] == []


def test_question_yields_bilingual_answer_after_check():
    text = ScriptedText([
        {"before_en": "First, I would check the requirements.", "before_zh": "首先确认需求。",
         "after_en": "Then I would set the priorities.", "after_zh": "接着确定优先级。", "fact_ids": []},
        {"safe": True},
    ])
    answer = asyncio.run(InterviewService(text).suggest("要件が変わったらどうしますか。", automatic=True))
    assert answer == Answer("First, I would check the requirements.\nThen I would set the priorities.", "首先确认需求。\n接着确定优先级。")


def test_unsupported_personal_claim_is_not_shown():
    unsafe = {"before_en": "I graduated from the University of Tokyo.", "before_zh": "我毕业于东京大学。",
              "after_en": "", "after_zh": "", "fact_ids": []}
    text = ScriptedText([unsafe, {"safe": False}, unsafe, {"safe": False}])
    with pytest.raises(ServiceError, match="核验"):
        asyncio.run(InterviewService(text).suggest("どのように進めますか。", automatic=True))
    assert [purpose for purpose, _ in text.calls] == ["draft", "verify_answer", "rewrite", "verify_answer"]


@pytest.mark.parametrize("initial_chinese,initial_safe", [("我学过工学。", False), ("", True)])
def test_self_introduction_is_rewritten_after_a_rejected_or_empty_draft(initial_chinese, initial_safe):
    question = "学歴を含めて、簡単に自己紹介をしてください。"
    initial = {"before_en": "I studied engineering.", "before_zh": initial_chinese,
               "after_en": "", "after_zh": "", "fact_ids": []}
    rewrite = {"before_en": "I studied [major] at [school].", "before_zh": "我在【学校名】学习了【专业】。",
               "after_en": "", "after_zh": "", "fact_ids": []}
    text = ScriptedText([initial, {"safe": initial_safe}, rewrite, {"safe": True}])

    answer = asyncio.run(InterviewService(text).suggest(question, automatic=True, level="B2"))

    assert answer == Answer(rewrite["before_en"], rewrite["before_zh"])
    assert [purpose for purpose, _ in text.calls] == ["draft", "verify_answer", "rewrite", "verify_answer"]
    assert json.loads(text.calls[2][1]) == {"question": question, "facts": []}
    assert "占位符" in text.prompts["rewrite"] and "B2" in text.prompts["rewrite"]


@pytest.mark.parametrize("facts", [(), (Fact("fixture", "education", "I studied engineering.", "我学过工学。"),)])
def test_personal_question_without_relevant_facts_gets_a_generic_suggestion(facts):
    question = "研究の経験を教えてください。"
    draft = {"before_en": "I would start by defining the goal and the hypothesis.",
             "before_zh": "开展研究时，我会先梳理目标和假设。",
             "after_en": "", "after_zh": "", "fact_ids": []}
    classification = [{"question": True, "personal": True, "categories": ["project"]}] if facts else []
    text = ScriptedText([*classification, draft, {"safe": True}])

    answer = asyncio.run(InterviewService(text).suggest(question, automatic=True, facts=facts))

    assert answer == Answer("I would start by defining the goal and the hypothesis.", "开展研究时，我会先梳理目标和假设。")
    assert text.calls[-2][0] == "draft"
    assert json.loads(text.calls[-2][1]) == {"question": question, "facts": []}
    assert text.calls[-1][0] == "verify_answer"


def test_interview_context_reaches_only_the_answer_draft():
    text = ScriptedText([
        {"question": True, "personal": False, "categories": []},
        {"before_en": "I would check the priorities.", "before_zh": "我会确认优先级。",
         "after_en": "", "after_zh": "", "fact_ids": []},
        {"safe": True},
    ])
    question = "仕様変更にはどう対応しますか。"
    info = PersonalInfo(
        background="Private sample background", resume="Private sample resume",
        company="示例株式会社", role="开发工程师", scenario="技术面试",
    )

    answer = asyncio.run(InterviewService(text).suggest(question, automatic=True, personal_info=info))

    assert answer == Answer("I would check the priorities.", "我会确认优先级。")
    assert text.calls[0] == ("question", question)
    assert json.loads(text.calls[1][1]) == {
        "question": question, "facts": [],
        "context": {"company": "示例株式会社", "role": "开发工程师", "scenario": "技术面试"},
    }
    assert json.loads(text.calls[2][1]) == {"en": ["I would check the priorities.", ""], "zh": ["我会确认优先级。", ""]}


def excerpt_info():
    return PersonalInfo(resume="I measured radio signals.\nPrivate fixture marker.")


EXCERPT_QUESTION = "無線信号の測定をしたプロジェクトについて教えてください。"
EXCERPT_CLASSIFICATION = {"question": True, "personal": True, "categories": ["project"]}
EXCERPT_DRAFT = {
    "before_en": "", "before_zh": "", "after_en": "", "after_zh": "", "fact_ids": [],
    "excerpt_ids": ["excerpt_1"], "excerpt_en": ["I measured radio signals."], "excerpt_zh": ["我测量了无线电信号。"],
}


def test_bilingual_claim_is_verified_against_the_exact_authorized_excerpt():
    text = ScriptedText([EXCERPT_CLASSIFICATION, EXCERPT_DRAFT, {"safe": True}])
    answer = asyncio.run(InterviewService(text).suggest(EXCERPT_QUESTION, automatic=True, personal_info=excerpt_info()))

    assert answer == Answer("I measured radio signals.", "我测量了无线电信号。")
    assert text.calls[0] == ("question", EXCERPT_QUESTION)
    assert json.loads(text.calls[1][1])["excerpts"] == [{"id": "excerpt_1", "text": "I measured radio signals."}]
    assert text.schemas["draft"]["excerpt_ids"]["items"]["enum"] == ["excerpt_1"]
    assert json.loads(text.calls[2][1])["excerpts"] == [{
        "source": "I measured radio signals.", "en": "I measured radio signals.", "zh": "我测量了无线电信号。",
    }]


def test_verified_facts_and_resume_excerpts_share_a_two_item_request_limit():
    fact = Fact("verified", "project", "I built a circuit.", "我制作了电路。")
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
    (["unknown"], ["I measured radio signals."], ["我测量了无线电信号。"]),
    (["excerpt_1"], ["I measured radio signals."], []),
    ([], ["I measured radio signals."], ["我测量了无线电信号。"]),
])
def test_missing_or_invalid_excerpt_attribution_stops_before_verification(ids, ja, zh):
    draft = dict(EXCERPT_DRAFT, excerpt_ids=ids, excerpt_en=ja, excerpt_zh=zh)
    text = ScriptedText([EXCERPT_CLASSIFICATION, draft])

    with pytest.raises(ServiceError, match="核验"):
        asyncio.run(InterviewService(text).suggest(EXCERPT_QUESTION, automatic=True, personal_info=excerpt_info()))
    assert [purpose for purpose, _ in text.calls] == ["question", "draft"]


def test_rewrite_does_not_resend_a_rejected_excerpt_or_interview_context():
    draft = dict(EXCERPT_DRAFT, excerpt_zh=["我带领团队测量了无线电信号。"])
    rewrite = {"before_en": "Before taking measurements, I would check the conditions.", "before_zh": "进行测量时，我会先确认条件。",
               "after_en": "", "after_zh": "", "fact_ids": []}
    info = PersonalInfo(resume=excerpt_info().resume, company="示例株式会社")
    text = ScriptedText([EXCERPT_CLASSIFICATION, draft, {"safe": False}, rewrite, {"safe": True}])

    answer = asyncio.run(InterviewService(text).suggest(EXCERPT_QUESTION, automatic=True, personal_info=info))

    assert answer == Answer(rewrite["before_en"], rewrite["before_zh"])
    assert json.loads(text.calls[2][1])["excerpts"] == [{
        "source": "I measured radio signals.", "en": "I measured radio signals.", "zh": "我带领团队测量了无线电信号。",
    }]
    assert json.loads(text.calls[3][1]) == {"question": EXCERPT_QUESTION, "facts": []}
    assert "excerpts" not in json.loads(text.calls[4][1])


def test_draft_can_use_a_generic_suggestion_when_no_excerpt_answers_the_question():
    draft = {
        "before_en": "I would start by checking the measurement conditions.", "before_zh": "进行测量时，我会先确认测量条件。",
        "after_en": "", "after_zh": "", "fact_ids": [], "excerpt_ids": [], "excerpt_en": [], "excerpt_zh": [],
    }
    text = ScriptedText([EXCERPT_CLASSIFICATION, draft, {"safe": True}])

    answer = asyncio.run(InterviewService(text).suggest(EXCERPT_QUESTION, automatic=True, personal_info=excerpt_info()))

    assert answer == Answer("I would start by checking the measurement conditions.", "进行测量时，我会先确认测量条件。")
    assert json.loads(text.calls[-1][1]) == {
        "en": ["I would start by checking the measurement conditions.", ""], "zh": ["进行测量时，我会先确认测量条件。", ""],
    }


@pytest.mark.parametrize("stage,expected", [
    ("question", ["question"]), ("draft", ["question", "draft"]),
    ("verify_answer", ["question", "draft", "verify_answer"]),
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

    text = RevokingText([EXCERPT_CLASSIFICATION, EXCERPT_DRAFT, {"safe": False}])
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(InterviewService(text).suggest(
            EXCERPT_QUESTION, automatic=True, personal_info=excerpt_info(), allowed=lambda: authorized,
        ))
    assert [purpose for purpose, _ in text.calls] == expected


@pytest.mark.parametrize("options,level,guidance", [
    ({}, "B1", "常见工作词汇"),
    ({"level": "C1"}, "C1", "细致的语气"),
])
def test_answer_draft_uses_requested_japanese_level(options, level, guidance):
    text = ScriptedText([
        {"before_en": "I would check the requirements.", "before_zh": "我会确认需求。",
         "after_en": "", "after_zh": "", "fact_ids": []},
        {"safe": True},
    ])

    asyncio.run(InterviewService(text).suggest("まず何をしますか。", automatic=True, **options))

    assert level in text.prompts["draft"]
    assert guidance in text.prompts["draft"]


def test_invalid_japanese_level_stops_before_a_provider_request():
    text = ScriptedText([])

    with pytest.raises(ValueError, match="N7"):
        asyncio.run(InterviewService(text).suggest("まず何をしますか。", automatic=True, level="N7"))

    assert text.calls == []


def test_english_glosses_and_key_phrases_preserve_bilingual_answer():
    answer = Answer("I would ask my sponsor before changing employers.", "换雇主之前我会先问项目机构。")
    text = ScriptedText([{
        "terms": ["sponsor", "changing employers", "before"],
        "labels": ["项目机构", "更换雇主", "before"],
        "contexts": ["", "", ""],
        "focus_terms": ["ask my sponsor", "comes from nowhere"],
    }])
    marked = asyncio.run(InterviewService(text).annotate_answer(answer))
    assert (marked.ja, marked.zh) == (answer.ja, answer.zh)
    assert [(answer.ja[a.start:a.end], a.label) for a in marked.annotations] == [
        ("sponsor", "项目机构"), ("changing employers", "更换雇主"),
    ]
    assert [answer.ja[h.start:h.end] for h in marked.highlights] == ["ask my sponsor"]


def test_repeated_english_term_requires_a_unique_local_context():
    answer = Answer("I'll check the schedule, then share the schedule.", "我会先查看排班，再发给大家。")
    text = ScriptedText([{
        "terms": ["schedule", "schedule"], "labels": ["排班", "时间表"],
        "contexts": ["check the schedule", ""], "focus_terms": [],
    }])
    marked = asyncio.run(InterviewService(text).annotate_answer(answer))
    assert [(a.start, a.label) for a in marked.annotations] == [(answer.ja.index("schedule"), "排班")]


def test_swt_draft_uses_english_level_and_does_not_invent_placement():
    text = ScriptedText([{
        "before_en": "I'm still waiting to hear back about my placement.",
        "before_zh": "我还在等岗位安排的消息。", "after_en": "", "after_zh": "", "fact_ids": [],
    }, {"safe": True}])
    answer = asyncio.run(InterviewService(text).suggest("Who is your employer?", automatic=True))
    assert answer.ja.startswith("I'm still")
    assert all(token in text.prompts["draft"] for token in ("Summer Work Travel", "CEFR B1", "不编造岗位"))


def test_japanese_draft_is_retried_before_it_can_reach_the_ui():
    japanese = {"before_en": "English prefix. いいえ、まだ働いたことはありません。",
                "before_zh": "我还没有工作过。", "after_en": "", "after_zh": "", "fact_ids": []}
    english = dict(japanese, before_en="I'd be happy to talk about the relevant experience I do have.")
    text = ScriptedText([japanese, english, {"safe": True}])
    answer = asyncio.run(InterviewService(text).suggest("Do you have any part-time work experience?", automatic=True))
    assert answer.ja == english["before_en"]
    assert "before_ja" not in text.schemas["draft"]
    assert [purpose for purpose, _ in text.calls] == ["draft", "rewrite", "verify_answer"]


def test_repeated_non_english_draft_is_not_shown():
    bad = {"before_en": "まだ経験がありません。", "before_zh": "我还没有经验。",
           "after_en": "", "after_zh": "", "fact_ids": []}
    text = ScriptedText([bad, bad])
    with pytest.raises(ServiceError, match="不会显示非英文"):
        asyncio.run(InterviewService(text).suggest("Do you have work experience?", automatic=False))
