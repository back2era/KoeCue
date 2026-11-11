"""Japanese difficulty guidance and validated answer markup."""
from dataclasses import dataclass
import re


ANSWER_LEVELS = {
    "N5": "使用最基本的日常词汇与简单的です／ます短句，拆开复杂意思。",
    "N4": "使用熟悉的生活和工作词汇，以及简单的原因、顺序和条件表达。",
    "N3": "使用常见工作词汇与清晰的中级语法，减少长定语和罕见术语。",
    "N2": "使用常见商务用语和自然敬体，适度使用转折、因果和条件表达。",
    "N1": "在自然面试口语中使用精准词汇、细致的语气和较丰富的衔接表达，避免堆砌生僻词。",
}
DEFAULT_ANSWER_LEVEL = "N2"
MAX_ANNOTATIONS = 64
MAX_HIGHLIGHTS = 5
MAX_HIGHLIGHT_LENGTH = 24

_KANJI = re.compile(r"[々〆㐀-䶿一-鿿豈-﫿\U00020000-\U000323AF]")
_JAPANESE_WORD = re.compile(r"[々〆ぁ-ゖー㐀-䶿一-鿿豈-﫿\U00020000-\U000323AF]+")
_HIRAGANA = re.compile(r"[ぁ-ゖゝゞー]+")
_KATAKANA = re.compile(r"[ァ-ヺｦ-ﾝ][ァ-ヺ・ーヽヾｦ-ﾟ]*")
_ENGLISH = re.compile(r"[A-Za-z][A-Za-z0-9 .’'+&/–-]*")
_FOCUS_TERM = re.compile(r"[\w .・+#/／&＆’'–-]+")
_FOCUS_FILLERS = {
    "はい", "いいえ", "こんにちは", "こんばんは", "ありがとうございます", "承知しました",
    "わかりました", "分かりました", "よろしくお願いします", "よろしくお願いいたします",
    "お願いいたします", "お願いします", "まず", "次に", "つぎに", "最後に", "さいごに",
    "また", "そして", "そのため", "例えば", "たとえば", "です", "ます", "しました",
    "と思います", "と考えます",
}


@dataclass(frozen=True)
class RubyAnnotation:
    start: int
    end: int
    label: str


@dataclass(frozen=True)
class Highlight:
    start: int
    end: int


def has_annotation_candidates(text):
    return bool(_KANJI.search(text) or _KATAKANA.search(text))


def has_highlight_candidates(text):
    return any(len(part) >= 2 and part not in _FOCUS_FILLERS for part in re.findall(r"\w+", text))


def _valid_pair(term, label):
    if not 0 < len(term) <= 24 or not 0 < len(label) <= 40:
        return False
    if _KANJI.search(term) and _JAPANESE_WORD.fullmatch(term):
        return bool(_HIRAGANA.fullmatch(label))
    return bool(_KATAKANA.fullmatch(term) and _ENGLISH.fullmatch(label))


def _unique_offset(text, fragment):
    start = text.find(fragment)
    if start < 0 or text.find(fragment, start + 1) >= 0:
        return None
    return start


def resolve_annotations(text, terms, labels, contexts):
    if len(terms) != len(labels) or len(terms) != len(contexts):
        return ()
    candidates = {}
    for term, label, context in zip(terms[:MAX_ANNOTATIONS], labels, contexts):
        label = label.strip()
        if not _valid_pair(term, label) or len(context) > 100 or "\n" in context:
            continue
        start = _unique_offset(text, context or term)
        if start is None:
            continue
        if context:
            offset = _unique_offset(context, term)
            if offset is None:
                continue
            start += offset
        candidates.setdefault((start, start + len(term)), set()).add(label)

    result = []
    # Prefer a complete word over a shorter annotation inside it.
    prioritized = sorted(candidates, key=lambda span: (span[0] - span[1], span[0]))
    for start, end in prioritized:
        readings = candidates[start, end]
        if len(readings) == 1 and not any(start < item.end and item.start < end for item in result):
            result.append(RubyAnnotation(start, end, next(iter(readings))))
    return tuple(sorted(result, key=lambda item: item.start))


def resolve_highlights(text, terms):
    if not isinstance(terms, list):
        return ()
    remaining = sum(not char.isspace() for char in text) // 2
    result = []
    for term in terms:
        if (not isinstance(term, str) or not 2 <= len(term) <= min(MAX_HIGHLIGHT_LENGTH, remaining)
                or term in _FOCUS_FILLERS or term != term.strip() or not _FOCUS_TERM.fullmatch(term)
                or not any(char.isalnum() for char in term)):
            continue
        start = _unique_offset(text, term)
        if start is None:
            continue
        end = start + len(term)
        if any(start < item.end and item.start < end for item in result):
            continue
        result.append(Highlight(start, end))
        remaining -= len(term)
        if len(result) == MAX_HIGHLIGHTS or remaining < 2:
            break
    return tuple(sorted(result, key=lambda item: item.start))
