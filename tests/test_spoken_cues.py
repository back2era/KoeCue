import asyncio
import json

import pytest
import httpx

from ai_japanese_interview_assistant.profiles import Fact
from ai_japanese_interview_assistant.services import ServiceError


QUESTION = "SPIとI2Cの違いを教えてください。"
INTENT = {"question": True, "complete": True, "personal": False,
          "categories": [], "question_type": "technical", "confidence": "high"}


def draft(**changes):
    return {
        "question_zh": "请说明 SPI 和 I2C 的区别。", "keywords": ["SPI", "I2C", "配線"],
        "opening_ja": "SPIは信号線が多いです。", "opening_zh": "SPI 的信号线较多。",
        "sentences_ja": ["I2Cは二本の線を使います。"], "sentences_zh": ["I2C 使用两根线。"],
        "sentence_sources": ["", ""], "needs_more_context": False, **changes,
    }


class Text:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.calls = []

    async def structured(self, name, prompt, value, schema, max_tokens):
        self.calls.append((name, prompt, json.loads(value)))
        result = next(self.responses)
        if isinstance(result, Exception):
            raise result
        return result


def suggest(text, question=QUESTION, **options):
    from ai_japanese_interview_assistant.spoken_cues import SpokenCueService

    return asyncio.run(SpokenCueService(text).suggest(question, automatic=True, **options))


def test_spoken_cue_keeps_technical_terms_and_defaults_to_n3():
    text = Text(INTENT, draft(), {"safe": True})
    result = suggest(text)
    assert result.question == QUESTION
    assert result.question_type == "technical"
    assert result.keywords == ("SPI", "I2C", "配線")
    assert result.opening.ja == "SPIは信号線が多いです。"
    assert result.ja.splitlines() == ["SPIは信号線が多いです。", "I2Cは二本の線を使います。"]
    assert "N3" in text.calls[1][1]
    assert "前提" in text.calls[1][1]


@pytest.mark.parametrize("changes", [{"question": False}, {"complete": False}])
def test_automatic_skips_nonquestions_and_incomplete_turns(changes):
    text = Text(dict(INTENT, **changes))
    assert suggest(text) is None
    assert [call[0] for call in text.calls] == ["spoken_intent"]


def test_followup_uses_only_preceding_context_and_authorized_related_facts():
    text = Text(dict(INTENT, personal=True, question_type="follow_up", categories=["project"]),
                draft(question_zh="为什么呢？"), {"safe": True})
    facts = (Fact("spi", "project", "SPIを使いました。", "我用过 SPI。", ("SPI",)),
             Fact("other", "project", "UARTを使いました。", "我用过 UART。", ("UART",)))
    answer = suggest(text, "なぜですか？", previous=("SPIを選んだそうですね。",), facts=facts)
    assert answer.question_type == "follow_up"
    assert text.calls[1][2]["preceding"] == ["SPIを選んだそうですね。"]
    assert [item["id"] for item in text.calls[1][2]["facts"]] == ["spi"]


@pytest.mark.parametrize("bad", [
    draft(opening_ja="長" * 60),
    draft(opening_ja="第一文です。第二文です。"),
    draft(keywords=["一", "二", "三", "四"]),
    draft(sentences_zh=[]),
])
def test_invalid_draft_is_rewritten_once(bad):
    assert suggest(Text(INTENT, bad, draft(), {"safe": True})).keywords == ("SPI", "I2C", "配線")


def test_invalid_json_gets_one_retry_and_then_an_actionable_error():
    from ai_japanese_interview_assistant.services import StructuredOutputError

    text = Text(INTENT, StructuredOutputError(), StructuredOutputError())
    with pytest.raises(ServiceError, match="格式"):
        suggest(text)
    assert [call[0] for call in text.calls] == ["spoken_intent", "spoken_cue", "spoken_cue"]


@pytest.mark.parametrize("envelope", [False, True])
def test_malformed_provider_json_is_retried_using_native_schema(envelope):
    from ai_japanese_interview_assistant.services import TextService
    from ai_japanese_interview_assistant.spoken_cues import SpokenCueService

    names = []

    def response(request):
        request_format = json.loads(request.content)["text"]["format"]
        assert request_format["type"] == "json_schema" and request_format["strict"]
        name = request_format["name"]
        names.append(name)
        if len(names) == 2:
            if envelope:
                return httpx.Response(200, content=b"{")
            return httpx.Response(200, json={
                "status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": "{"}]}],
            })
        value = {"spoken_intent": INTENT, "spoken_cue": draft(), "verify_spoken_cue": {"safe": True}}[name]
        return httpx.Response(200, json={"status": "completed", "output": [{
            "type": "message", "content": [{"type": "output_text", "text": json.dumps(value)}],
        }]})

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
            return await SpokenCueService(TextService(client)).suggest(QUESTION, automatic=True)

    assert asyncio.run(exercise()).keywords == ("SPI", "I2C", "配線")
    assert names == ["spoken_intent", "spoken_cue", "spoken_cue", "verify_spoken_cue"]


def test_network_failure_is_not_retried():
    text = Text(INTENT, TimeoutError())
    with pytest.raises(TimeoutError):
        suggest(text)
    assert len(text.calls) == 2


def test_rejected_personal_content_is_rewritten_without_profile_and_verified_again():
    text = Text(dict(INTENT, personal=True, categories=["education"]), draft(), {"safe": False},
                draft(needs_more_context=True), {"safe": True})
    fact = Fact("education", "education", "工学を学びました。", "我学过工学。")
    answer = suggest(text, "学歴を教えてください。", facts=(fact,))
    assert answer.needs_more_context
    assert len(text.calls[1][2]["facts"]) == 1
    assert text.calls[3][2]["facts"] == []


def test_keywords_only_accepts_three_keywords_and_no_script():
    from ai_japanese_interview_assistant.spoken_cues import CueOptions

    text = Text(INTENT, draft(opening_ja="", opening_zh="", sentences_ja=[], sentences_zh=[],
                             sentence_sources=[]), {"safe": True})
    answer = suggest(text, options=CueOptions(mode="keywords_only"))
    assert answer.opening is None and answer.sentences == ()
    assert answer.keywords == ("SPI", "I2C", "配線")
