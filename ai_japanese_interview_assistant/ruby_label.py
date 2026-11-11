"""Render Japanese answers with emphasis and optional readings or glosses."""
from dataclasses import dataclass
from math import ceil
import re
from typing import TYPE_CHECKING, Iterable

from PySide6.QtCore import QPointF, QSize, QTextBoundaryFinder, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QKeySequence, QPainter, QPalette
from PySide6.QtWidgets import QApplication, QLabel, QMenu

if TYPE_CHECKING:
    from .answer_format import Highlight, RubyAnnotation


_EDGE = 2
_LINE_GAP = 5
_PARAGRAPH_GAP = 7
_RUBY_GAP = 1
_RUBY_PADDING = 2
_SELECTABLE = Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard


def _boundaries(text, boundary):
    # Qt returns UTF-16 positions, while the answer uses Python string offsets.
    offsets = {0: 0}
    position = 0
    for index, character in enumerate(text, 1):
        position += 1 if ord(character) <= 0xFFFF else 2
        offsets[position] = index
    finder = QTextBoundaryFinder(boundary, text)
    while (position := finder.toNextBoundary()) >= 0:
        yield offsets[position]


@dataclass(frozen=True)
class _TextRun:
    text: str
    width: float
    emphasized: bool = False


@dataclass(frozen=True)
class _Run:
    base: tuple[_TextRun, ...]
    base_width: float
    ruby: str = ""
    ruby_width: float = 0

    @property
    def width(self):
        return max(self.base_width, self.ruby_width + _RUBY_PADDING) if self.ruby else self.base_width


def _base_runs(text, start, end, highlights, metrics):
    normal, bold = metrics
    cursor = start
    for first, last in highlights:
        if last <= cursor:
            continue
        if first >= end:
            break
        if cursor < first:
            plain = text[cursor:first]
            yield _TextRun(plain, normal.horizontalAdvance(plain))
        cursor = min(last, end)
        emphasized = text[max(first, start):cursor]
        yield _TextRun(emphasized, bold.horizontalAdvance(emphasized), True)
    if cursor < end:
        plain = text[cursor:end]
        yield _TextRun(plain, normal.horizontalAdvance(plain))


def _with_ruby(run, ruby, width, metrics):
    gloss = metrics.elidedText(ruby, Qt.TextElideMode.ElideRight, max(0, width - _RUBY_PADDING))
    if gloss in ("", "…"):
        return _Run(run.base, run.base_width)
    return _Run(run.base, run.base_width, gloss, metrics.horizontalAdvance(gloss))


def _line_groups(text, start, end, spans, highlights, width, metrics, ruby_metrics):
    # Find line breaks in the unstyled text so a style or ruby boundary cannot orphan punctuation.
    line_ends = {start + offset for offset in _boundaries(text[start:end], QTextBoundaryFinder.BoundaryType.Line)}
    readings = {(first, last): ruby for first, last, ruby in spans if start <= first < last <= end}
    edges = {start, end}
    for first, last in readings:
        line_ends.difference_update(range(first + 1, last))
        edges.update((first, last))
    edges = sorted(edges | line_ends)
    group = []
    for first, last in zip(edges, edges[1:]):
        base = tuple(_base_runs(text, first, last, highlights, metrics))
        run = _Run(base, sum(part.width for part in base))
        if reading := readings.get((first, last)):
            run = _with_ruby(run, reading, width, ruby_metrics)
        group.append(run)
        if last in line_ends or last == end:
            yield tuple(group)
            group = []


def _fit_group(group, width, metrics, ruby_metrics):
    if sum(run.width for run in group) <= width:
        yield group
        return

    base_width = sum(run.base_width for run in group)
    if base_width <= width:
        # Give the text room first so closing punctuation can stay with its word.
        allowance = (width - base_width) / sum(bool(run.ruby) for run in group)
        yield tuple(
            _with_ruby(run, run.ruby, run.base_width + allowance, ruby_metrics) if run.ruby else run
            for run in group
        )
        return

    for run in group:
        if run.width <= width:
            yield (run,)
            continue
        # A word wider than the column must break at grapheme boundaries.
        normal, bold = metrics
        for part in run.base:
            part_metrics = bold if part.emphasized else normal
            first = 0
            for last in _boundaries(part.text, QTextBoundaryFinder.BoundaryType.Grapheme):
                fragment = part.text[first:last]
                advance = part_metrics.horizontalAdvance(fragment)
                yield (_Run((_TextRun(fragment, advance, part.emphasized),), advance),)
                first = last


def _wrap(text, start, end, spans, highlights, width, metrics, ruby_metrics):
    runs = []
    used = 0.0
    for group in _line_groups(text, start, end, spans, highlights, width, metrics, ruby_metrics):
        for unit in _fit_group(group, width, metrics, ruby_metrics):
            advance = sum(run.width for run in unit)
            if runs and used + advance > width:
                yield runs
                runs = []
                used = 0.0
            runs.extend(unit)
            used += advance
    yield runs


def _paragraphs(text, display_breaks):
    breaks = [(match.start(), match.end(), 0) for match in re.finditer(r"\r\n?|\n", text)]
    breaks.extend((offset, offset, _PARAGRAPH_GAP) for offset in display_breaks)
    start = gap = 0
    for end, next_start, next_gap in sorted(breaks):
        yield start, end, gap
        start, gap = next_start, next_gap
    yield start, len(text), gap


def _highlight_ranges(text, highlights):
    ranges = []
    for first, last in sorted((mark.start, mark.end) for mark in highlights):
        if not 0 <= first < last <= len(text):
            continue
        if ranges and first <= ranges[-1][1]:
            start, end = ranges[-1]
            ranges[-1] = (start, max(end, last))
        else:
            ranges.append((first, last))
    return tuple(ranges)


class RubyLabel(QLabel):
    """A word-wrapped label whose text remains the original Japanese answer."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._spans = ()
        self._highlights = ()
        self._paragraph_breaks = ()
        self._cache_key = None
        self._lines = ()
        self._layout_height = 0
        self.setObjectName("answerText")
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.setTextInteractionFlags(_SELECTABLE)
        font = self.font()
        font.setPixelSize(17)
        self.setFont(font)

    def set_answer(
        self, text: str, annotations: Iterable["RubyAnnotation"] = (), *,
        highlights: Iterable["Highlight"] = (), paragraph_breaks: Iterable[int] = (),
    ) -> None:
        """Apply optional formatting at Python string offsets in the original answer."""
        spans = []
        end = 0
        for annotation in annotations:
            if (end <= annotation.start < annotation.end <= len(text) and annotation.label
                    and not re.search(r"[\r\n]", text[annotation.start:annotation.end])):
                spans.append((annotation.start, annotation.end, annotation.label))
                end = annotation.end
        spans = tuple(spans)
        emphasis = _highlight_ranges(text, highlights)
        breaks = tuple(sorted({
            offset for offset in paragraph_breaks if 0 < offset < len(text)
            and text[offset - 1] not in "\r\n" and text[offset] not in "\r\n"
            and not any(start < offset < end for start, end, _ in spans)
        }))
        if (text, spans, emphasis, breaks) == (self.text(), self._spans, self._highlights, self._paragraph_breaks):
            return
        self._spans = spans
        self._highlights = emphasis
        self._paragraph_breaks = breaks
        self._cache_key = None
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction if self._formatted else _SELECTABLE)
        if self._formatted:
            self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setText(text)
        self.setAccessibleDescription(text)
        self.updateGeometry()
        self.update()

    @property
    def _formatted(self):
        return bool(self._spans or self._highlights or self._paragraph_breaks)

    def _fonts(self):
        base = self.font()
        strong = QFont(base)
        strong.setBold(True)
        ruby = QFont(base)
        ruby.setPixelSize(max(8, round(base.pixelSize() * 0.65)))
        return base, strong, ruby

    def _layout(self, width, fonts):
        key = (width, fonts[0].toString(), self.logicalDpiX(), self.logicalDpiY())
        if key != self._cache_key:
            base_metrics, strong_metrics, ruby_metrics = (QFontMetricsF(font, self) for font in fonts)
            metrics = (base_metrics, strong_metrics)
            ascent = max(metric.ascent() for metric in metrics)
            descent = max(metric.descent() for metric in metrics)
            width = max(1, width - 2 * _EDGE)
            lines = []
            top = _EDGE
            text = self.text()
            for start, end, gap in _paragraphs(text, self._paragraph_breaks):
                top += gap
                for runs in _wrap(text, start, end, self._spans, self._highlights, width, metrics, ruby_metrics):
                    reading_baseline = top + ruby_metrics.ascent()
                    if any(run.ruby for run in runs):
                        top += ruby_metrics.height() + _RUBY_GAP
                    base_baseline = top + ascent
                    lines.append((runs, reading_baseline, base_baseline))
                    top = base_baseline + descent + _LINE_GAP
            self._lines = tuple(lines)
            self._layout_height = ceil(top - _LINE_GAP + _EDGE)
            self._cache_key = key
        return self._lines

    def heightForWidth(self, width):
        if not self._formatted:
            return super().heightForWidth(width)
        margins = self.contentsMargins()
        self._layout(width - margins.left() - margins.right(), self._fonts())
        return self._layout_height + margins.top() + margins.bottom()

    def sizeHint(self):
        size = super().sizeHint()
        if self._formatted:
            size.setHeight(self.heightForWidth(size.width()))
        return size

    def minimumSizeHint(self):
        size = super().minimumSizeHint()
        if self._formatted:
            return QSize(0, size.height())
        return size

    def paintEvent(self, event):
        if not self._formatted:
            super().paintEvent(event)
            return

        rect = self.contentsRect()
        fonts = self._fonts()
        base, bold, ruby = fonts
        lines = self._layout(rect.width(), fonts)
        painter = QPainter(self)
        painter.setClipRect(rect)
        palette = self.palette()
        base_color = palette.color(QPalette.ColorRole.WindowText)
        accent = palette.color(QPalette.ColorRole.Accent)
        emphasis = QColor.fromRgbF(*(0.4 * normal + 0.6 * tint for normal, tint in zip(
            base_color.getRgbF()[:3], accent.getRgbF()[:3],
        )))
        ruby_color = QApplication.palette().color(QPalette.ColorRole.PlaceholderText)
        for runs, reading_baseline, base_baseline in lines:
            x = rect.left() + _EDGE
            for run in runs:
                if run.ruby:
                    painter.setFont(ruby)
                    painter.setPen(ruby_color)
                    left = x + (run.width - run.ruby_width) / 2
                    painter.drawText(QPointF(left, rect.top() + reading_baseline), run.ruby)
                left = x + (run.width - run.base_width) / 2
                for part in run.base:
                    painter.setFont(bold if part.emphasized else base)
                    painter.setPen(emphasis if part.emphasized else base_color)
                    painter.drawText(QPointF(left, rect.top() + base_baseline), part.text)
                    left += part.width
                x += run.width
        painter.end()

    def keyPressEvent(self, event):
        if self._formatted and event.matches(QKeySequence.StandardKey.Copy):
            QApplication.clipboard().setText(self.text())
            event.accept()
            return
        super().keyPressEvent(event)

    def contextMenuEvent(self, event):
        if not self._formatted:
            super().contextMenuEvent(event)
            return
        menu = QMenu(self)
        menu.addAction("复制日语回答", lambda: QApplication.clipboard().setText(self.text()))
        menu.exec(event.globalPos())
