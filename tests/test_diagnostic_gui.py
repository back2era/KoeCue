"""Offscreen smoke test with real device enumeration and no capture."""
import os
from time import monotonic, sleep

import pytest


@pytest.mark.skipif(os.environ.get("AIJA_TEST_GUI") != "1", reason="opt-in Qt smoke test")
def test_diagnostics_require_consent_before_starting_capture():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication
    from ai_japanese_interview_assistant.__main__ import MainWindow

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.show()
    try:
        pane = window.diagnostic
        deadline = monotonic() + 5
        while (pane.scan is not None or window.cloud.scan is not None) and monotonic() < deadline:
            app.processEvents()
            sleep(0.01)
        assert pane.scan is None
        assert window.cloud.scan is None
        assert pane.device.count() > 1
        pane.device.setCurrentIndex(1)
        assert not pane.start.isEnabled()
        pane.consent.setChecked(True)
        assert pane.start.isEnabled()
        assert pane.worker is None
    finally:
        window.close()
        app.processEvents()


@pytest.mark.skipif(os.environ.get("AIJA_TEST_GUI") != "1", reason="opt-in Qt smoke test")
def test_profile_editor_saves_then_shares_selected_entry(tmp_path, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    from ai_japanese_interview_assistant.profile_gui import ProfileDialog

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    app = QApplication.instance() or QApplication([])
    dialog = ProfileDialog(())
    approved = []
    dialog.authorized.connect(approved.append)

    def wait_for_io():
        deadline = monotonic() + 5
        while dialog.worker is not None and monotonic() < deadline:
            app.processEvents()
            sleep(0.01)
        assert dialog.worker is None

    wait_for_io()
    dialog.add_blank()
    dialog.table.item(0, 2).setText("工学を学びました。")
    dialog.table.item(0, 3).setText("我学习了工学。")
    dialog.table.item(0, 0).setCheckState(Qt.CheckState.Checked)
    dialog.share_profile()
    assert approved == []
    dialog.save_profile()
    wait_for_io()
    dialog.share_profile()
    assert len(approved[0]) == 1
    assert approved[0][0].ja == "工学を学びました。"
