"""Offscreen checks for the personal page and session authorization."""
import os
from time import monotonic, sleep

import pytest


pytestmark = pytest.mark.skipif(os.environ.get("AIJA_TEST_GUI") != "1", reason="opt-in Qt smoke test")


def wait(app, condition):
    end = monotonic() + 5
    while not condition() and monotonic() < end:
        app.processEvents()
        sleep(.01)
    assert condition()


def test_personal_tab_imports_saves_and_only_shares_the_selected_group(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    from PySide6.QtWidgets import QApplication, QFileDialog
    from ai_japanese_interview_assistant import cloud_gui, diagnostic
    from ai_japanese_interview_assistant.__main__ import MainWindow, configure_application
    from ai_japanese_interview_assistant.personal import PersonalInfo

    monkeypatch.setattr(cloud_gui, "credential", lambda *args: "")
    monkeypatch.setattr(diagnostic, "list_devices", lambda: ())
    fixture = tmp_path / "fixture.txt"
    fixture.write_text("Sample project\n测试内容\n確認用テキスト", encoding="utf-8")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (str(fixture), ""))

    app = QApplication.instance() or QApplication([])
    configure_application(app)
    window = MainWindow()
    window.show()
    try:
        pane = window.personal
        window.navigation.button(2).click()
        assert window.tabs.currentWidget() is pane
        wait(app, lambda: pane.import_button.isEnabled() and pane.facts.isEnabled())
        pane.import_button.click()
        wait(app, lambda: pane.worker is None)
        assert "確認用テキスト" in pane.resume.toPlainText()
        pane.background.setPlainText("测试简介")
        pane.company.setText("示例会社")
        pane.role.setText("示例岗位")
        pane.scenario.setPlainText("技术一面")
        assert not pane.share.isEnabled()
        assert pane.save.isVisible() and pane.save.isEnabled()
        assert pane.save.objectName() == "primaryAction"
        assert "未保存" in pane.status.text()
        pane.save.click()
        wait(app, lambda: pane.share_scenario.isEnabled())
        assert pane.status.text() == "已保存到本机。"
        pane.share_scenario.setChecked(True)
        pane.share.click()
        assert window.cloud.approved_personal == PersonalInfo(
            company="示例会社", role="示例岗位", scenario="技术一面",
        )
        assert "本次已授权 面试场景" in pane.sharing_status.text()
        assert pane.revoke.isEnabled()

        window.tabs.setCurrentWidget(window.cloud)
        window.cloud.state = "active"
        window.cloud.controls()
        window.tabs.setCurrentWidget(pane)
        assert window.cloud.state == "active"
        assert not pane.save.isEnabled() and pane.revoke.isEnabled()
        pane.revoke.click()
        assert window.cloud.approved_personal == PersonalInfo()
        assert "本次尚未授权" in pane.sharing_status.text()
    finally:
        window.close()
        wait(app, lambda: not window.isVisible())

    reopened = MainWindow()
    reopened.show()
    try:
        wait(app, lambda: reopened.personal.loaded)
        assert reopened.personal.company.text() == "示例会社"
        assert "Sample project" in reopened.personal.resume.toPlainText()
        assert reopened.cloud.approved_personal == PersonalInfo()
    finally:
        reopened.close()
        wait(app, lambda: not reopened.isVisible())
