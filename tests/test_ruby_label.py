"""Offscreen checks for Japanese answer annotations."""
from types import SimpleNamespace
import os

import pytest


pytestmark = pytest.mark.skipif(os.environ.get("AIJA_TEST_GUI") != "1", reason="opt-in Qt smoke test")


@pytest.fixture
def label(monkeypatch):
    from PySide6.QtWidgets import QApplication
    from ai_japanese_interview_assistant import glass
    from ai_japanese_interview_assistant.ruby_label import RubyLabel

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    glass.apply_theme(app, "black")
    widget = RubyLabel()
    widget.show()
    try:
        yield widget
    finally:
        widget.close()
        glass.apply_theme(app, "black")


def _ink_rows(image):
    background = image.pixelColor(image.width() - 1, 0)
    rows = {}
    for y in range(image.height()):
        pixels = [(x, image.pixelColor(x, y)) for x in range(image.width())]
        ink = [(x, color) for x, color in pixels if _color_distance(color, background) > 36]
        if ink:
            rows[y] = ink
    return rows


def _ink_bands(image):
    rows = _ink_rows(image)
    first, second = max(zip(rows, tuple(rows)[1:]), key=lambda pair: pair[1] - pair[0])
    assert second > first + 1
    return [pixel for y, pixels in rows.items() if y <= first for pixel in pixels], [
        pixel for y, pixels in rows.items() if y >= second for pixel in pixels
    ]


def _color_distance(left, right):
    return abs(left.red() - right.red()) + abs(left.green() - right.green()) + abs(left.blue() - right.blue())


@pytest.mark.parametrize("theme", ["black", "glacier"])
def test_reading_is_centered_above_base_text_and_uses_theme_colors(label, theme):
    from PySide6.QtGui import QPalette
    from PySide6.QtWidgets import QApplication
    from ai_japanese_interview_assistant.glass import apply_theme

    apply_theme(QApplication.instance(), theme)
    label.set_answer("経験", (SimpleNamespace(start=0, end=2, label="けいけん"),))
    label.resize(200, label.heightForWidth(200))
    image = label.grab().toImage()
    reading, base = _ink_bands(image)
    for pixels, color in (
        (reading, QApplication.palette().color(QPalette.ColorRole.PlaceholderText)),
        (base, label.palette().color(QPalette.ColorRole.WindowText)),
    ):
        assert min(_color_distance(pixel, color) for _, pixel in pixels) < 80
    centers = [min(x for x, _ in pixels) + max(x for x, _ in pixels) for pixels in (reading, base)]
    assert abs(centers[0] - centers[1]) <= 6
    assert label.text() == "経験"


def test_answer_wraps_and_keeps_paragraphs_at_narrow_width(label):
    answer = "日本で働きたいです。\n\n私は経験があります。"
    start = answer.index("経験")
    label.set_answer(answer, (SimpleNamespace(start=start, end=start + 2, label="けいけん"),))
    wide_height = label.heightForWidth(460)
    narrow_height = label.heightForWidth(75)

    assert narrow_height > wide_height
    label.resize(75, narrow_height)
    assert label.grab().height() == narrow_height
    assert label.text() == answer

    label.set_answer(answer.replace("\n\n", "\n"))
    assert label.heightForWidth(460) < wide_height


def test_english_gloss_uses_the_available_column_width(label):
    widths = []
    for gloss in ("demonstration", "demonstration recording"):
        label.set_answer("デモ", (SimpleNamespace(start=0, end=2, label=gloss),))
        label.resize(240, label.heightForWidth(240))
        reading, _ = _ink_bands(label.grab().toImage())
        widths.append(max(x for x, _ in reading) - min(x for x, _ in reading))

    assert widths[1] > widths[0] + 25


def test_answer_without_annotations_preserves_literal_text_and_selection(label):
    from PySide6.QtCore import Qt

    label.set_answer("日本語", (SimpleNamespace(start=0, end=3, label="にほんご"),))
    label.set_answer("<日本語> & English\n次の段落")

    assert label.text() == "<日本語> & English\n次の段落"
    assert label.textFormat() == Qt.TextFormat.PlainText
    label.setSelection(1, 3)
    assert label.selectedText() == "日本語"


@pytest.mark.parametrize("with_ruby", [False, True])
def test_emphasis_tints_only_the_selected_part_of_a_word(label, with_ruby):
    from PySide6.QtGui import QPalette
    from PySide6.QtWidgets import QApplication
    from ai_japanese_interview_assistant.glass import apply_theme

    apply_theme(QApplication.instance(), "ocean")
    annotation = SimpleNamespace(start=0, end=2, label="けいけん")
    label.set_answer(
        "経験", (annotation,) if with_ruby else (), highlights=(SimpleNamespace(start=1, end=2),),
    )
    label.resize(150, label.heightForWidth(150))
    image = label.grab().toImage()
    if with_ruby:
        _, base = _ink_bands(image)
    else:
        base = [pixel for row in _ink_rows(image).values() for pixel in row]
    midpoint = (min(x for x, _ in base) + max(x for x, _ in base)) / 2
    foreground = label.palette().color(QPalette.ColorRole.WindowText)
    first_distance = min(_color_distance(pixel, foreground) for x, pixel in base if x < midpoint)
    second_distance = min(_color_distance(pixel, foreground) for x, pixel in base if x > midpoint)
    assert second_distance > first_distance + 15


def test_display_paragraph_break_preserves_original_clipboard_text(label):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    answer = "経験があります。今も学んでいます。"
    annotation = SimpleNamespace(start=0, end=2, label="けいけん")
    label.set_answer(answer, (annotation,))
    single_line_height = label.heightForWidth(480)
    label.set_answer(answer, (annotation,), paragraph_breaks=(answer.index("今"),))

    assert label.heightForWidth(480) > single_line_height + label.font().pixelSize()
    assert label.text() == answer
    QTest.keyClick(label, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    assert QApplication.clipboard().text() == answer


def test_closing_punctuation_wraps_with_an_annotated_character(label):
    from PySide6.QtGui import QFontMetricsF

    metrics = QFontMetricsF(label.font())
    width = round(metrics.horizontalAdvance("先検討") + 5)
    label.set_answer("先検討。", (SimpleNamespace(start=2, end=3, label="と"),))
    label.resize(width, label.heightForWidth(width))
    natural = label.grab().toImage()

    label.set_answer("先検\n討。", (SimpleNamespace(start=3, end=4, label="と"),))
    label.resize(width, label.heightForWidth(width))
    assert natural == label.grab().toImage()
