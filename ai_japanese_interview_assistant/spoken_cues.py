"""Typed and verified oral-interview suggestions for the desktop."""
import asyncio
from dataclasses import dataclass
import json
import re

from .answer_format import ANSWER_LEVELS, Highlight, RubyAnnotation
from .cue_prompts import INTENT_PROMPT, SPOKEN_PROMPT, STRATEGIES, VERIFY_CUE_PROMPT
from .interview import InterviewService
from .personal import PersonalInfo, select_excerpts
from .profiles import CATEGORIES, select_facts
from .services import StructuredOutputError


MODES = {"keywords_only": "只看关键词", "short": "关键词 + 短句", "structured": "短句 + 展开说明"}
DEFAULT_LEVEL = "N3"
DEFAULT_MAX_ITEMS = 3
_FORMAT_ERROR = "口语提示格式不正确。可重试该段，或使用下方救场句。"
_END = re.compile(r"[。！？!?]+")
RESCUE_PHRASES = (
    ("そうですね、少し考えさせてください。", "请让我想一下。"),
    ("すみません、もう一度お願いします。", "不好意思，请再说一遍。"),
    ("つまり、〇〇ということでしょうか？", "您的意思是……对吗？"),
    ("うまく説明できないのですが……", "我可能解释得不太好……"),
    ("もう一つあります。", "还有一点。"),
)

_STRING = {"type": "string"}
_BOOLEAN = {"type": "boolean"}
_STRINGS = {"type": "array", "items": _STRING}
_INTENT = {
    "question": _BOOLEAN, "complete": _BOOLEAN, "personal": _BOOLEAN,
    "categories": {"type": "array", "items": {"type": "string", "enum": list(CATEGORIES)}},
    "question_type": {"type": "string", "enum": list(STRATEGIES)},
    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
}
_CUE = {
    "question_zh": _STRING, "keywords": _STRINGS, "opening_ja": _STRING, "opening_zh": _STRING,
    "sentences_ja": _STRINGS, "sentences_zh": _STRINGS, "sentence_sources": _STRINGS,
    "needs_more_context": _BOOLEAN,
}


@dataclass(frozen=True)
class CueOptions:
    mode: str = "short"
    max_keywords: int = DEFAULT_MAX_ITEMS
    max_sentences: int = DEFAULT_MAX_ITEMS


@dataclass(frozen=True)
class SpokenLine:
    ja: str
    zh: str


@dataclass(frozen=True)
class InterviewAnswer:
    question: str
    question_zh: str
    question_type: str
    keywords: tuple[str, ...]
    opening: SpokenLine | None
    sentences: tuple[SpokenLine, ...]
    confidence: str
    needs_more_context: bool
    annotations: tuple[RubyAnnotation, ...] = ()
    highlights: tuple[Highlight, ...] = ()

    @property
    def lines(self):
        return ((self.opening,) if self.opening else ()) + self.sentences

    @property
    def ja(self):
        return "\n".join(line.ja for line in self.lines)

    @property
    def zh(self):
        return "\n".join(line.zh for line in self.lines)


def _text(value, limit):
    value = value.strip()
    if not value or len(value) > limit or len(value.splitlines()) != 1:
        raise StructuredOutputError(_FORMAT_ERROR)
    return value


def _pair(ja, zh):
    ja, zh = _text(ja, 48), _text(zh, 72)
    if _END.search(ja.rstrip('。！？!?」』）】')) or _END.search(zh.rstrip('。！？!?」』）】')):
        raise StructuredOutputError(_FORMAT_ERROR)
    return SpokenLine(ja, zh)


def _read_cue(draft, question, intent, options):
    question_zh = _text(draft["question_zh"], 240)
    keywords = tuple(_text(word, 18) for word in draft["keywords"])
    if not 1 <= len(keywords) <= options.max_keywords or len(set(word.casefold() for word in keywords)) != len(keywords):
        raise StructuredOutputError(_FORMAT_ERROR)
    if any(_END.search(word) for word in keywords):
        raise StructuredOutputError(_FORMAT_ERROR)

    start_ja, start_zh = draft["opening_ja"].strip(), draft["opening_zh"].strip()
    opening = _pair(start_ja, start_zh) if start_ja or start_zh else None
    ja, zh = draft["sentences_ja"], draft["sentences_zh"]
    if len(ja) != len(zh) or len(ja) + int(opening is not None) > options.max_sentences:
        raise StructuredOutputError(_FORMAT_ERROR)
    sentences = tuple(_pair(a, b) for a, b in zip(ja, zh))
    answer = InterviewAnswer(
        question, question_zh, intent["question_type"], keywords, opening, sentences,
        intent["confidence"], draft["needs_more_context"] or intent["confidence"] == "low",
    )
    if ((not answer.lines) != (options.mode == "keywords_only")
            or len(draft["sentence_sources"]) != len(answer.lines)):
        raise StructuredOutputError(_FORMAT_ERROR)
    return answer


def _require_active(allowed):
    if not allowed():
        raise asyncio.CancelledError


class SpokenCueService(InterviewService):
    async def classify(self, japanese, previous=()):
        return await self.text_service.structured(
            "spoken_intent", INTENT_PROMPT, json.dumps({"question": japanese, "preceding": previous}, ensure_ascii=False),
            _INTENT, 240,
        )

    async def suggest(self, japanese, *, automatic, facts=(), personal_info=PersonalInfo(), level=DEFAULT_LEVEL,
                      options=CueOptions(), previous=(), allowed=lambda: True):
        japanese = japanese.strip()
        if not japanese:
            return None
        _require_active(allowed)
        previous = tuple(text[-160:] for text in previous[-2:])
        try:
            intent = await self.classify(japanese, previous)
        except StructuredOutputError:
            raise StructuredOutputError("未能确认问题格式。可重试该段，或使用常用救场句。") from None
        _require_active(allowed)
        if not intent["complete"] or (automatic and not intent["question"]):
            return None
        kind = intent["question_type"]
        if kind not in ("follow_up", "clarification"):
            previous = ()
        query = " ".join((*previous, japanese))
        categories = intent["categories"] if intent["personal"] or kind == "motivation" else ()
        facts = select_facts(facts, query, categories)
        excerpts = select_excerpts(personal_info, categories, query)[:2 - len(facts)]
        sources = {f"excerpt_{index}": text for index, text in enumerate(excerpts, 1)}
        context = {}
        if kind in {"self_introduction", "motivation", "behavioral"} or (kind == "follow_up" and intent["personal"]):
            context = {key: value for key in ("company", "role", "scenario") if (value := getattr(personal_info, key))}
        prompt = (
            SPOKEN_PROMPT + STRATEGIES[kind] + f"日语难度 {level}。{ANSWER_LEVELS[level]}"
            + f"输出 1 至 {options.max_keywords} 个关键词。"
        )
        if options.mode == "keywords_only":
            prompt += "起句和短句字段留空，只提供关键词。"
        else:
            prompt += f"日语总共 1 至 {options.max_sentences} 句，起句也算一句。"
        if intent["confidence"] == "low":
            prompt += "仅给用于确认问题的措辞和关键词。"

        for attempt in range(2):
            _require_active(allowed)
            payload = {"question": japanese, "preceding": previous, "facts": [
                {"id": fact.id, "ja": fact.ja, "zh": fact.zh} for fact in facts
            ]}
            if sources:
                payload["excerpts"] = [{"id": key, "text": value} for key, value in sources.items()]
            if context:
                payload["context"] = context
            try:
                draft = await self.text_service.structured(
                    "spoken_cue", prompt, json.dumps(payload, ensure_ascii=False), _CUE, 560,
                )
                _require_active(allowed)
                answer = _read_cue(draft, japanese, intent, options)
                await self._verify_cue(answer, draft["sentence_sources"], facts, sources, allowed)
                return answer
            except StructuredOutputError:
                if attempt:
                    raise StructuredOutputError(_FORMAT_ERROR) from None
                facts, sources, context = (), {}, {}
                prompt += "上一稿未通过核验。请重写为更简短的提示。人物经历使用待填字段或提问确认。"
        raise AssertionError("Both cue attempts must either return or raise")

    async def _verify_cue(self, answer, citations, facts, sources, allowed):
        by_id = {fact.id: fact for fact in facts}
        claims = []
        for line, citation in zip(answer.lines, citations):
            if citation in by_id:
                fact = by_id[citation]
                if line != SpokenLine(fact.ja, fact.zh):
                    raise StructuredOutputError(_FORMAT_ERROR)
                continue
            claim = {"ja": line.ja, "zh": line.zh}
            if citation:
                if citation not in sources:
                    raise StructuredOutputError(_FORMAT_ERROR)
                claim["source"] = sources[citation]
            claims.append(claim)
        _require_active(allowed)
        result = await self.text_service.structured(
            "verify_spoken_cue", VERIFY_CUE_PROMPT,
            json.dumps({"keywords": answer.keywords, "lines": claims}, ensure_ascii=False), {"safe": _BOOLEAN}, 100,
        )
        _require_active(allowed)
        if result["safe"] is not True:
            raise StructuredOutputError(_FORMAT_ERROR)
