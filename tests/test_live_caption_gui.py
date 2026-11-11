"""Exercise provisional captions independently of settled history."""
import os
from time import monotonic, sleep

import pytest


@pytest.mark.skipif(os.environ.get("AIJA_TEST_GUI") != "1", reason="opt-in Qt smoke test")
def test_provisional_captions_are_immediate_append_only_and_separate_from_history(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    from PySide6.QtWidgets import QApplication
    from ai_japanese_interview_assistant import cloud_gui, diagnostic
    from ai_japanese_interview_assistant.__main__ import MainWindow
    from ai_japanese_interview_assistant.transcription import TranscriptPart

    monkeypatch.setattr(cloud_gui, "credential", lambda *args: "")
    monkeypatch.setattr(diagnostic, "list_devices", lambda: ())
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.show()
    cloud = window.cloud
    try:
        cloud.state = "active"
        cloud.session_id = 3
        cloud.generation = 2
        cloud.rows[(3, 1, "earlier")] = cloud_gui.Row(ja="前の発言", finalized=True)
        cloud.dirty = True
        cloud.render_history()

        key = (3, 2, "current")
        cloud.add_partial_transcript((key, TranscriptPart("current", "日本で")))
        assert cloud.live_caption.isVisible()
        assert cloud.live_caption.text() == "日本で"
        assert cloud.history.rowCount() == 1
        assert cloud.original.target == "前の発言"
        cloud.add_partial_transcript((key, TranscriptPart("current", "日本ではたらく")))
        cloud.add_partial_transcript((key, TranscriptPart("current", "日本では働く")))
        cloud.add_partial_transcript(((3, 1, "stale"), TranscriptPart("stale", "古い文字")))
        assert cloud.live_caption.text() == "日本ではたらく"

        cloud.add_transcript((key, TranscriptPart("current", "日本で働く理由", final=True)))
        cloud.render_history()
        assert not cloud.live_caption.isVisible()
        assert cloud.history.rowCount() == 2
        assert cloud.original.text() == "日本で働く理由"
        cloud.add_partial_transcript(((3, 2, "next"), TranscriptPart("next", "次の発言")))
        cloud.stop_session()
        assert not cloud.live_caption.isVisible()
        assert cloud.history.rowCount() == 2
    finally:
        window.close()
        deadline = monotonic() + 5
        while window.isVisible() and monotonic() < deadline:
            app.processEvents()
            sleep(.01)
        assert not window.isVisible()
