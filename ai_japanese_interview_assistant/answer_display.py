"""Prepare Markdown answers and annotations for the desktop reader."""
import re


_SENTENCE_END = re.compile(r"[。！？!?]+[」』）】》”’]*[ \t]*")
_HEADING = re.compile(r"(?m)^ {0,3}#{1,6}[ \t]+")
_LIST_MARKER = re.compile(r"(?m)^([ \t]*)[-+*][ \t]+")
_ORDERED_MARKER = re.compile(r"(?m)^([ \t]*[0-9]{1,9})\)[ \t]+")
_INLINE_MARKUP = re.compile(
    r"(?<!\\)(`[^`\r\n]+`|\*\*(?=\S)[^*\r\n]+?(?<=\S)\*\*"
    r"|(?<![\w_])__(?=\S)[^_\r\n]+?(?<=\S)__(?!\w)"
    r"|(?<!\*)\*(?=\S)[^*\r\n]+?(?<=\S)\*(?!\*))"
)


def display_markdown(text):
    """Render the answer's Markdown subset as text with stable ruby offsets."""
    def unmark(match):
        token = match[0]
        if token.startswith("`"):
            return token[1:-1]
        size = 2 if token.startswith(("**", "__")) else 1
        return _INLINE_MARKUP.sub(unmark, token[size:-size])

    text = _HEADING.sub("", text)
    text = _LIST_MARKER.sub(r"\1• ", text)
    text = _ORDERED_MARKER.sub(r"\1. ", text)
    return _INLINE_MARKUP.sub(unmark, text)


def compact_annotations(text, annotations, highlights):
    matching = tuple(
        annotation for annotation in annotations
        if any(annotation.start < focus.end and focus.start < annotation.end for focus in highlights)
    )
    limit = 5 if matching else 3
    seen = set()
    selected = []
    for annotation in matching or annotations:
        word = text[annotation.start:annotation.end]
        if word not in seen:
            seen.add(word)
            selected.append(annotation)
            if len(selected) == limit:
                break
    return tuple(selected)


def paragraph_breaks(text):
    offsets = []
    offset = 0
    for line in text.splitlines(keepends=True):
        paragraph_start = 0
        line_end = len(line.rstrip())
        for sentence in _SENTENCE_END.finditer(line):
            end = sentence.end()
            if end - paragraph_start >= 20 and line_end - end >= 10:
                offsets.append(offset + end)
                paragraph_start = end
                if len(offsets) == 3:
                    return tuple(offsets)
        offset += len(line)
    return tuple(offsets)
