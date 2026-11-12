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
        {"before_ja": "本日はよろしくお願いいたします。", "before_zh": "今天请多关照。",
         "after_ja": "", "after_zh": "", "fact_ids": []},
        {"safe": True},
    ])
    fact = Fact("fixture", "project", "回路を作りました。", "我制作了电路。")

    answer = asyncio.run(InterviewService(text).suggest("それでは面接を始めます。", automatic=True, facts=(fact,)))

    assert answer == Answer("本日はよろしくお願いいたします。", "今天请多关照。")
    assert json.loads(text.calls[1][1])["facts"] == []


def test_question_yields_bilingual_answer_after_check():
    text = ScriptedText([
        {"before_ja": "まず、要件を確認します。", "before_zh": "首先确认需求。",
         "after_ja": "次に、優先順位を決めます。", "after_zh": "接着确定优先级。", "fact_ids": []},
        {"safe": True},
    ])
    answer = asyncio.run(InterviewService(text).suggest("要件が変わったらどうしますか。", automatic=True))
    assert answer == Answer("まず、要件を確認します。\n次に、優先順位を決めます。", "首先确认需求。\n接着确定优先级。")


def test_unsupported_personal_claim_is_not_shown():
    unsafe = {"before_ja": "私は東京大学を卒業しました。", "before_zh": "我毕业于东京大学。",
              "after_ja": "", "after_zh": "", "fact_ids": []}
    text = ScriptedText([unsafe, {"safe": False}, unsafe, {"safe": False}])
    with pytest.raises(ServiceError, match="核验"):
        asyncio.run(InterviewService(text).suggest("どのように進めますか。", automatic=True))
    assert [purpose for purpose, _ in text.calls] == ["draft", "verify_answer", "rewrite", "verify_answer"]


@pytest.mark.parametrize("initial_chinese,initial_safe", [("我学过工学。", False), ("", True)])
def test_self_introduction_is_rewritten_after_a_rejected_or_empty_draft(initial_chinese, initial_safe):
    question = "学歴を含めて、簡単に自己紹介をしてください。"
    initial = {"before_ja": "工学を学びました。", "before_zh": initial_chinese,
               "after_ja": "", "after_zh": "", "fact_ids": []}
    rewrite = {"before_ja": "【学校名】で【専攻】を学びました。", "before_zh": "我在【学校名】学习了【专业】。",
               "after_ja": "", "after_zh": "", "fact_ids": []}
    text = ScriptedText([initial, {"safe": initial_safe}, rewrite, {"safe": True}])

    answer = asyncio.run(InterviewService(text).suggest(question, automatic=True, level="N3"))

    assert answer == Answer(rewrite["before_ja"], rewrite["before_zh"])
    assert [purpose for purpose, _ in text.calls] == ["draft", "verify_answer", "rewrite", "verify_answer"]
    assert json.loads(text.calls[2][1]) == {"question": question, "facts": []}
    assert "占位符" in text.prompts["rewrite"] and "N3" in text.prompts["rewrite"]


@pytest.mark.parametrize("facts", [(), (Fact("fixture", "education", "工学を学びました。", "我学过工学。"),)])
def test_personal_question_without_relevant_facts_gets_a_generic_suggestion(facts):
    question = "研究の経験を教えてください。"
    draft = {"before_ja": "研究に取り組む際は、まず目的と仮説を整理します。",
             "before_zh": "开展研究时，我会先梳理目标和假设。",
             "after_ja": "", "after_zh": "", "fact_ids": []}
    classification = [{"question": True, "personal": True, "categories": ["project"]}] if facts else []
    text = ScriptedText([*classification, draft, {"safe": True}])

    answer = asyncio.run(InterviewService(text).suggest(question, automatic=True, facts=facts))

    assert answer == Answer("研究に取り組む際は、まず目的と仮説を整理します。", "开展研究时，我会先梳理目标和假设。")
    assert text.calls[-2][0] == "draft"
    assert json.loads(text.calls[-2][1]) == {"question": question, "facts": []}
    assert text.calls[-1][0] == "verify_answer"


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
    ([], ["無線信号を測定しました。"], ["我测量了无线电信号。"]),
])
def test_missing_or_invalid_excerpt_attribution_stops_before_verification(ids, ja, zh):
    draft = dict(EXCERPT_DRAFT, excerpt_ids=ids, excerpt_ja=ja, excerpt_zh=zh)
    text = ScriptedText([EXCERPT_CLASSIFICATION, draft])

    with pytest.raises(ServiceError, match="核验"):
        asyncio.run(InterviewService(text).suggest(EXCERPT_QUESTION, automatic=True, personal_info=excerpt_info()))
    assert [purpose for purpose, _ in text.calls] == ["question", "draft"]


def test_rewrite_does_not_resend_a_rejected_excerpt_or_interview_context():
    draft = dict(EXCERPT_DRAFT, excerpt_zh=["我带领团队测量了无线电信号。"])
    rewrite = {"before_ja": "測定する場合、まず条件を確認します。", "before_zh": "进行测量时，我会先确认条件。",
               "after_ja": "", "after_zh": "", "fact_ids": []}
    info = PersonalInfo(resume=excerpt_info().resume, company="示例株式会社")
    text = ScriptedText([EXCERPT_CLASSIFICATION, draft, {"safe": False}, rewrite, {"safe": True}])

    answer = asyncio.run(InterviewService(text).suggest(EXCERPT_QUESTION, automatic=True, personal_info=info))

    assert answer == Answer(rewrite["before_ja"], rewrite["before_zh"])
    assert json.loads(text.calls[2][1])["excerpts"] == [{
        "source": "I measured radio signals.", "ja": "無線信号を測定しました。", "zh": "我带领团队测量了无线电信号。",
    }]
    assert json.loads(text.calls[3][1]) == {"question": EXCERPT_QUESTION, "facts": []}
    assert "excerpts" not in json.loads(text.calls[4][1])


def test_draft_can_use_a_generic_suggestion_when_no_excerpt_answers_the_question():
    draft = {
        "before_ja": "測定する場合、まず測定条件を確認します。", "before_zh": "进行测量时，我会先确认测量条件。",
        "after_ja": "", "after_zh": "", "fact_ids": [], "excerpt_ids": [], "excerpt_ja": [], "excerpt_zh": [],
    }
    text = ScriptedText([EXCERPT_CLASSIFICATION, draft, {"safe": True}])

    answer = asyncio.run(InterviewService(text).suggest(EXCERPT_QUESTION, automatic=True, personal_info=excerpt_info()))

    assert answer == Answer("測定する場合、まず測定条件を確認します。", "进行测量时，我会先确认测量条件。")
    assert json.loads(text.calls[-1][1]) == {
        "ja": ["測定する場合、まず測定条件を確認します。", ""], "zh": ["进行测量时，我会先确认测量条件。", ""],
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
    ({}, "N2", "常见商务用语"),
    ({"level": "N1"}, "N1", "细致的语气"),
])
def test_answer_draft_uses_requested_japanese_level(options, level, guidance):
    text = ScriptedText([
        {"before_ja": "要件を確認します。", "before_zh": "我会确认需求。",
         "after_ja": "", "after_zh": "", "fact_ids": []},
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


def test_answer_annotations_use_character_offsets_and_preserve_the_bilingual_answer():
    answer = Answer("🙂要件をチームで確認します。", "我会和团队一起确认需求。")
    text = ScriptedText([{
        "terms": ["チーム", "確認", "要件"],
        "labels": ["team", "かくにん", "ようけん"],
        "contexts": ["", "", ""],
        "focus_terms": ["要件", "確認"],
    }])

    annotated = asyncio.run(InterviewService(text).annotate_answer(answer))

    assert text.calls == [("annotate_answer", answer.ja)]
    assert text.schemas["annotate_answer"]["focus_terms"] == {"type": "array", "items": {"type": "string"}}
    assert (annotated.ja, annotated.zh) == (answer.ja, answer.zh)
    assert [(ruby.start, ruby.end, ruby.label) for ruby in annotated.annotations] == [
        (1, 3, "ようけん"), (4, 7, "team"), (8, 10, "かくにん"),
    ]
    assert [(focus.start, focus.end) for focus in annotated.highlights] == [(1, 3), (8, 10)]


def test_answer_annotations_resolve_repeated_words_using_their_exact_contexts():
    answer = Answer("上手な人は舞台の上手に立ちます。", "擅长表演的人站在舞台上手。")
    text = ScriptedText([{
        "terms": ["上手", "上手"],
        "labels": ["かみて", "じょうず"],
        "contexts": ["舞台の上手", "上手な人"],
    }])

    annotated = asyncio.run(InterviewService(text).annotate_answer(answer))

    assert [(ruby.start, ruby.end, ruby.label) for ruby in annotated.annotations] == [
        (0, 2, "じょうず"), (8, 10, "かみて"),
    ]


def test_answer_annotations_drop_invalid_labels_ambiguous_matches_and_overlapping_spans():
    answer = Answer("面接で設計資料と設計手順をチームに説明します。", "我会在面试中向团队介绍设计资料和流程。")
    text = ScriptedText([{
        "terms": ["設計", "面接", "架空", "資料", "設計資料", "チーム", "設計手順", "説明", "チーム", "と"],
        "labels": ["せっけい", "メンセツ", "かくう", "しりょう", "せっけいしりょう",
                   "チーム", "せっけいてじゅん", "explanation", "team", "と"],
        "contexts": ["", "", "", "", "", "", "存在しない設計手順", "", "", ""],
    }])

    annotated = asyncio.run(InterviewService(text).annotate_answer(answer))

    assert [(answer.ja[ruby.start:ruby.end], ruby.label) for ruby in annotated.annotations] == [
        ("設計資料", "せっけいしりょう"), ("チーム", "team"),
    ]


def test_answer_annotations_discard_misaligned_response_arrays():
    answer = Answer("面接で説明します。", "我会在面试中说明。")
    text = ScriptedText([{
        "terms": ["面接", "説明"],
        "labels": ["めんせつ"],
        "contexts": ["", ""],
    }])

    assert asyncio.run(InterviewService(text).annotate_answer(answer)) == answer


def test_answer_can_highlight_a_hiragana_phrase_without_ruby():
    answer = Answer("まずははなしをききます。つぎに、やりかたをきめます。", "先听对方说，再决定怎么做。")
    text = ScriptedText([{
        "terms": [], "labels": [], "contexts": [],
        "focus_terms": ["やりかた", "はなしをききます"],
    }])

    annotated = asyncio.run(InterviewService(text).annotate_answer(answer))

    assert text.calls == [("annotate_answer", answer.ja)]
    assert annotated.annotations == ()
    assert [answer.ja[focus.start:focus.end] for focus in annotated.highlights] == ["はなしをききます", "やりかた"]


def test_answer_highlights_keep_only_five_valid_nonoverlapping_exact_phrases():
    answer = Answer(
        "まず、チームで設計資料を確認します。次に、要件と制約を整理し、工程と品質を見直します。最後に、チームへ共有します。",
        "我会和团队确认设计资料，梳理需求与限制，检查流程和质量，再与团队共享。",
    )
    text = ScriptedText([{
        "terms": [], "labels": [], "contexts": [],
        "focus_terms": [
            "まず", "チーム", "架空の語", "設計資料を確認します。", "品質", "設計資料", "資料",
            "設計資料", "見直します", "要件", "工程", "共有", "確認",
        ],
    }])

    annotated = asyncio.run(InterviewService(text).annotate_answer(answer))

    assert [answer.ja[focus.start:focus.end] for focus in annotated.highlights] == [
        "設計資料", "要件", "工程", "品質", "見直します",
    ]


def test_answer_highlights_cover_at_most_half_of_the_answer():
    answer = Answer("まず使いやすさを最優先します。", "我会优先考虑易用性。")
    text = ScriptedText([{
        "terms": [], "labels": [], "contexts": [],
        "focus_terms": ["まず使いやすさを最優先します", "使いやすさ", "最優先"],
    }])

    annotated = asyncio.run(InterviewService(text).annotate_answer(answer))

    assert [answer.ja[focus.start:focus.end] for focus in annotated.highlights] == ["使いやすさ"]


@pytest.mark.parametrize("focus_terms", [None, "確認", [False, "存在しない"]])
def test_malformed_focus_metadata_preserves_ruby(focus_terms):
    answer = Answer("まず要件を確認します。", "我会先确认需求。")
    text = ScriptedText([{
        "terms": ["要件"], "labels": ["ようけん"], "contexts": [""],
        "focus_terms": focus_terms,
    }])

    annotated = asyncio.run(InterviewService(text).annotate_answer(answer))

    assert annotated.highlights == ()
    assert [(ruby.start, ruby.end, ruby.label) for ruby in annotated.annotations] == [(2, 4, "ようけん")]


def test_short_hiragana_acknowledgement_needs_no_annotation_request():
    text = ScriptedText([])
    answer = Answer("はい。", "是的。")

    assert asyncio.run(InterviewService(text).annotate_answer(answer)) == answer
    assert text.calls == []
