"""Offscreen checks for application-wide theme changes."""
import os

import pytest


pytestmark = pytest.mark.skipif(os.environ.get("AIJA_TEST_GUI") != "1", reason="opt-in Qt smoke test")


@pytest.fixture
def app(monkeypatch):
    from PySide6.QtWidgets import QApplication

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    application = QApplication.instance() or QApplication([])
    yield application
    from ai_japanese_interview_assistant import glass

    if hasattr(glass, "apply_theme"):
        glass.apply_theme(application, "black")


def test_switching_theme_updates_open_windows_and_new_dialogs(app):
    from PySide6.QtGui import QPalette
    from ai_japanese_interview_assistant import glass

    glass.apply_theme(app, "black")
    opened = glass.GlassDialog("Already open")
    opened.show()
    try:
        canvas = opened.findChild(glass.GlassCanvas)
        label = opened.findChild(glass.QLabel, "pageTitle")
        assert canvas.grab().toImage().pixelColor(0, 0).name() == "#000000"
        dark_ink = label.palette().color(QPalette.ColorRole.WindowText)

        glass.apply_theme(app, "glacier")
        app.processEvents()
        late = glass.GlassDialog("Opened after switching")
        late.resize(opened.size())
        late.show()
        try:
            light_pixel = canvas.grab().toImage().pixelColor(0, 0)
            assert light_pixel.lightness() > 200
            assert late.findChild(glass.GlassCanvas).grab().toImage().pixelColor(0, 0) == light_pixel
            assert label.palette().color(QPalette.ColorRole.WindowText).lightness() < 80
            assert dark_ink.lightness() > 200
        finally:
            late.close()
    finally:
        opened.close()


def test_five_themes_have_distinct_rendered_backdrops(app):
    from ai_japanese_interview_assistant import glass

    canvas = glass.GlassCanvas()
    canvas.resize(320, 200)
    canvas.show()
    try:
        corner_colors = []
        for theme_id in ("graphite", "ocean", "glacier", "sand", "black"):
            glass.apply_theme(app, theme_id)
            app.processEvents()
            corner_colors.append(canvas.grab().toImage().pixelColor(0, 0).name())
        assert len(set(corner_colors)) == 5
        glass.apply_theme(app, "unknown")
        assert canvas.grab().toImage().pixelColor(0, 0).name() == "#000000"
    finally:
        canvas.close()
