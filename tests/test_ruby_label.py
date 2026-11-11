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


def _ink_bands(image):
    background = image.pixelColor(image.width() - 1, 0)
    rows = {}
    for y in range(image.height()):
        pixels = [(x, image.pixelColor(x, y)) for x in range(image.width())]
        ink = [(x, color) for x, color in pixels if _color_distance(color, background) > 36]
        if ink:
            rows[y] = ink
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


def test_answer_without_annotations_preserves_literal_text_and_selection(label):
    from PySide6.QtCore import Qt

    label.set_answer("日本語", (SimpleNamespace(start=0, end=3, label="にほんご"),))
    label.set_answer("<日本語> & English\n次の段落")

    assert label.text() == "<日本語> & English\n次の段落"
    assert label.textFormat() == Qt.TextFormat.PlainText
    label.setSelection(1, 3)
    assert label.selectedText() == "日本語"
