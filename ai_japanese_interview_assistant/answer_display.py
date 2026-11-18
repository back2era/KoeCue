"""Choose a readable subset of annotations and display-only paragraph breaks."""
import re


_SENTENCE_END = re.compile(r"[。！？!?]+[」』）】》”’]*[ \t]*")


def preview_end(text, sentence_limit=3):
    for count, sentence in enumerate(_SENTENCE_END.finditer(text), 1):
        if count == sentence_limit:
            end = sentence.end()
            return end if text[end:].strip() else len(text)
    return len(text)


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
