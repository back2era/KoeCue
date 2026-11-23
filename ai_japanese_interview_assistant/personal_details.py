"""Structured fields saved by the personal information page."""
from dataclasses import dataclass, fields
import unicodedata

from .answer_format import ANSWER_LEVELS


MAX_RECORDS = 12
MAX_DETAIL = 600
LONG_FIELDS = frozenset({
    "motivation", "requirements", "scenario", "background", "responsibilities",
    "challenge", "actions", "result", "learning", "notes",
})
EXPERIENCE_KINDS = {"project": "项目", "internship": "实习", "employment": "工作"}
PREFERENCE_OPTIONS = {
    "level": {"": "跟随面试设置", **{level: level for level in ANSWER_LEVELS}},
    "tone": {"": "按题目调整", "natural": "自然口语", "formal": "正式敬语"},
    "length": {"": "按题目调整", "short": "简短 · 1–2 句", "standard": "标准 · 2–4 句", "detail": "详细 · 4–6 句"},
    "terms": {"": "按题目调整", "keep": "保留专业术语", "explain": "术语附简短解释"},
    "translation": {"": "跟随面试设置", "zh": "附简体中文", "off": "关闭"},
}


@dataclass(frozen=True)
class Basics:
    name: str = ""
    reading: str = ""
    japanese_level: str = ""
    languages: str = ""


@dataclass(frozen=True)
class Education:
    school: str = ""
    major: str = ""
    degree: str = ""
    graduation: str = ""


@dataclass(frozen=True)
class Target:
    role: str = ""
    company: str = ""
    industry: str = ""
    location: str = ""
    motivation: str = ""
    requirements: str = ""
    scenario: str = ""


@dataclass(frozen=True)
class Experience:
    title: str = ""
    kind: str = "project"
    organization: str = ""
    period: str = ""
    background: str = ""
    responsibilities: str = ""
    tools: str = ""
    challenge: str = ""
    actions: str = ""
    result: str = ""
    learning: str = ""
    notes: str = ""
    priority: bool = False


@dataclass(frozen=True)
class AnswerPreferences:
    level: str = ""
    tone: str = ""
    length: str = ""
    terms: str = ""
    translation: str = ""

    def translation_for(self, default):
        if self.translation == "off":
            return ""
        return self.translation or default


def filled(record):
    return any(getattr(record, field.name) for field in fields(record) if field.name not in {"kind", "priority"})


def normalized(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())
