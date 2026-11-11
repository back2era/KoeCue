"""Render Japanese answers with readings or glosses above selected spans."""
from dataclasses import dataclass
from math import ceil
from typing import TYPE_CHECKING, Iterable

from PySide6.QtCore import QPointF, QSize, QTextBoundaryFinder, Qt
from PySide6.QtGui import QFont, QFontMetricsF, QKeySequence, QPainter, QPalette
from PySide6.QtWidgets import QApplication, QLabel, QMenu

if TYPE_CHECKING:
    from .answer_format import RubyAnnotation


_EDGE = 2
_LINE_GAP = 2
_RUBY_GAP = 2
_SELECTABLE = Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard


def _segments(text, boundary):
    # Qt returns UTF-16 positions, while the answer uses Python string offsets.
    offsets = {0: 0}
    position = 0
    for index, character in enumerate(text, 1):
        position += 1 if ord(character) <= 0xFFFF else 2
        offsets[position] = index
    finder = QTextBoundaryFinder(boundary, text)
    start = 0
    while (position := finder.toNextBoundary()) >= 0:
        end = offsets[position]
        yield text[start:end]
        start = end


@dataclass(frozen=True)
class _Run:
    base: str
    ruby: str
    base_width: float
    ruby_width: float = 0

    @property
    def width(self):
        return max(self.base_width, self.ruby_width + 2 * _EDGE) if self.ruby else self.base_width


def _wrap(paragraph, width, base_metrics, ruby_metrics):
    runs = []
    used = 0.0
    for base, ruby in paragraph:
        pieces = (base,) if ruby else _segments(base, QTextBoundaryFinder.BoundaryType.Line)
        for piece in pieces:
            piece_width = base_metrics.horizontalAdvance(piece)
            if piece_width > width:
                # A phrase wider than the column must break at grapheme boundaries.
                fragments = (
                    _Run(cluster, "", base_metrics.horizontalAdvance(cluster))
                    for cluster in _segments(piece, QTextBoundaryFinder.BoundaryType.Grapheme)
                )
            else:
                gloss = ruby_metrics.elidedText(ruby, Qt.TextElideMode.ElideRight, max(0, width - 2 * _EDGE))
                fragments = (_Run(piece, gloss, piece_width, ruby_metrics.horizontalAdvance(gloss)),)
            for run in fragments:
                if runs and used + run.width > width:
                    yield runs
                    runs = []
                    used = 0.0
                runs.append(run)
                used += run.width
    yield runs


def _paragraphs(text, spans):
    """Split plain runs at hard line breaks, preserving blank paragraphs."""
    cursor = 0
    parts = []
    for start, end, ruby in spans:
        parts.append((text[cursor:start], ""))
        parts.append((text[start:end], ruby))
        cursor = end
    parts.append((text[cursor:], ""))

    paragraph = []
    for base, ruby in parts:
        for index, piece in enumerate(base.split("\n")):
            if index:
                yield paragraph
                paragraph = []
            if piece:
                paragraph.append((piece, ruby))
    yield paragraph


class RubyLabel(QLabel):
    """A word-wrapped label whose text remains the original Japanese answer."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._spans = ()
        self._cache_key = None
        self._lines = ()
        self.setObjectName("answerText")
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.setTextInteractionFlags(_SELECTABLE)
        font = self.font()
        font.setPixelSize(17)
        self.setFont(font)

    def set_answer(self, text: str, annotations: Iterable["RubyAnnotation"] = ()) -> None:
        spans = []
        end = 0
        for annotation in annotations:
            if (end <= annotation.start < annotation.end <= len(text) and annotation.label
                    and "\n" not in text[annotation.start:annotation.end]):
                spans.append((annotation.start, annotation.end, annotation.label))
                end = annotation.end
        spans = tuple(spans)
        if text == self.text() and spans == self._spans:
            return
        self._spans = spans
        self._cache_key = None
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction if spans else _SELECTABLE)
        if spans:
            self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setText(text)
        self.setAccessibleDescription(text)
        self.updateGeometry()
        self.update()

    def _fonts(self):
        base = self.font()
        ruby = QFont(base)
        ruby.setPixelSize(max(8, round(base.pixelSize() * 0.65)))
        return base, ruby

    def _layout(self, width, base_font, ruby_font, base_metrics, ruby_metrics):
        key = (width, base_font.toString(), ruby_font.toString(), self.logicalDpiX(), self.logicalDpiY())
        if key != self._cache_key:
            paragraphs = _paragraphs(self.text(), self._spans)
            self._lines = tuple(
                (runs, any(run.ruby for run in runs))
                for paragraph in paragraphs
                for runs in _wrap(paragraph, max(1, width - 2 * _EDGE), base_metrics, ruby_metrics)
            )
            self._cache_key = key
        return self._lines

    def heightForWidth(self, width):
        if not self._spans:
            return super().heightForWidth(width)
        margins = self.contentsMargins()
        base, ruby = self._fonts()
        base_metrics = QFontMetricsF(base, self)
        ruby_metrics = QFontMetricsF(ruby, self)
        lines = self._layout(width - margins.left() - margins.right(), base, ruby, base_metrics, ruby_metrics)
        height = sum(
            base_metrics.height() + _LINE_GAP + (ruby_metrics.height() + _RUBY_GAP if has_ruby else 0)
            for _, has_ruby in lines
        )
        return ceil(height - _LINE_GAP + 2 * _EDGE) + margins.top() + margins.bottom()

    def sizeHint(self):
        size = super().sizeHint()
        if self._spans:
            size.setHeight(self.heightForWidth(size.width()))
        return size

    def minimumSizeHint(self):
        size = super().minimumSizeHint()
        if self._spans:
            return QSize(0, size.height())
        return size

    def paintEvent(self, event):
        if not self._spans:
            super().paintEvent(event)
            return

        rect = self.contentsRect()
        base, ruby = self._fonts()
        base_metrics = QFontMetricsF(base, self)
        ruby_metrics = QFontMetricsF(ruby, self)
        lines = self._layout(rect.width(), base, ruby, base_metrics, ruby_metrics)
        painter = QPainter(self)
        painter.setClipRect(rect)
        base_color = self.palette().color(QPalette.ColorRole.WindowText)
        ruby_color = QApplication.palette().color(QPalette.ColorRole.PlaceholderText)
        top = rect.top() + _EDGE
        for runs, has_ruby in lines:
            x = rect.left() + _EDGE
            base_top = top + ruby_metrics.height() + _RUBY_GAP if has_ruby else top
            for run in runs:
                if run.ruby:
                    painter.setFont(ruby)
                    painter.setPen(ruby_color)
                    left = x + (run.width - run.ruby_width) / 2
                    painter.drawText(QPointF(left, top + ruby_metrics.ascent()), run.ruby)
                painter.setFont(base)
                painter.setPen(base_color)
                left = x + (run.width - run.base_width) / 2
                painter.drawText(QPointF(left, base_top + base_metrics.ascent()), run.base)
                x += run.width
            top = base_top + base_metrics.height() + _LINE_GAP
        painter.end()

    def keyPressEvent(self, event):
        if self._spans and event.matches(QKeySequence.StandardKey.Copy):
            QApplication.clipboard().setText(self.text())
            event.accept()
            return
        super().keyPressEvent(event)

    def contextMenuEvent(self, event):
        if not self._spans:
            super().contextMenuEvent(event)
            return
        menu = QMenu(self)
        menu.addAction("复制日语回答", lambda: QApplication.clipboard().setText(self.text()))
        menu.exec(event.globalPos())
