"""Offscreen checks for saved interview context and session snapshots."""
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


def test_saving_personal_info_supplies_the_next_session_without_extra_controls(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    from PySide6.QtWidgets import QApplication, QCheckBox, QFileDialog
    from ai_japanese_interview_assistant import cloud_gui, diagnostic
    from ai_japanese_interview_assistant.__main__ import MainWindow, configure_application
    from ai_japanese_interview_assistant.audio import Device
    from ai_japanese_interview_assistant.personal import PersonalInfo

    monkeypatch.setattr(cloud_gui, "credential", lambda *args: "")
    device = Device(10, "示例播放设备", True, 48000, 2)
    monkeypatch.setattr(diagnostic, "list_devices", lambda: (device,))
    sessions = []
    monkeypatch.setattr(cloud_gui.LiveWorker, "start", lambda worker: sessions.append(worker.personal_info))
    monkeypatch.setattr(cloud_gui.LiveWorker, "stop", lambda worker: worker.finished.emit())
    fixture = tmp_path / "fixture.txt"
    fixture.write_text("Sample project\n测试内容\n確認用テキスト", encoding="utf-8")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (str(fixture), ""))

    app = QApplication.instance() or QApplication([])
    configure_application(app)
    window = MainWindow()
    window.show()
    try:
        pane = window.personal
        cloud = window.cloud
        window.navigation.button(2).click()
        assert window.tabs.currentWidget() is pane
        wait(app, lambda: pane.import_button.isEnabled() and window.cloud.key.isEnabled())
        assert not pane.findChildren(QCheckBox)
        assert cloud.auto_answer.isChecked()
        cloud.source.setCurrentIndex(1)
        cloud.key.setText("offline-test")
        wait(app, cloud.start.isEnabled)
        pane.import_button.click()
        wait(app, lambda: pane.worker is None)
        assert "確認用テキスト" in pane.resume.toPlainText()
        pane.background.setPlainText("测试简介")
        pane.company.setText("示例会社")
        pane.role.setText("电源研发工程师")
        pane.scenario.setPlainText("技术一面")
        assert pane.save.isVisible() and pane.save.isEnabled()
        assert pane.save.objectName() == "primaryAction"
        assert "未保存" in pane.status.text()
        pane.save.click()
        assert not cloud.start.isEnabled()
        wait(app, lambda: pane.worker is None)
        saved = PersonalInfo(
            background="测试简介", resume=pane.resume.toPlainText(),
            company="示例会社", role="电源研发工程师", scenario="技术一面",
        )
        assert window.cloud.saved_personal == saved
        assert window.cloud.approved_personal == PersonalInfo()
        assert sessions == []

        pane.role.setText("未保存的岗位")
        window.tabs.setCurrentWidget(cloud)
        wait(app, cloud.start.isEnabled)
        assert "相关面试资料" in cloud.start.toolTip()
        cloud.start.click()
        assert sessions == [saved]
        assert cloud.approved_personal == saved
        window.tabs.setCurrentWidget(pane)
        assert cloud.state == "active"
        assert not pane.save.isEnabled()
        cloud.pause_session()
        wait(app, cloud.start.isEnabled)
        cloud.start.click()
        assert sessions == [saved, saved]
        cloud.stop_session()
        assert cloud.approved_personal == PersonalInfo()
        assert cloud.saved_personal == saved
        cloud.provider.setCurrentIndex(cloud.provider.findData("deepseek"))
        wait(app, cloud.key.isEnabled)
        assert cloud.saved_personal == saved
    finally:
        window.close()
        wait(app, lambda: not window.isVisible())

    reopened = MainWindow()
    reopened.show()
    try:
        wait(app, lambda: reopened.personal.loaded)
        assert reopened.personal.company.text() == "示例会社"
        assert "Sample project" in reopened.personal.resume.toPlainText()
        assert reopened.cloud.saved_personal == saved
        assert reopened.cloud.approved_personal == PersonalInfo()
        for editor in (reopened.personal.company, reopened.personal.role, reopened.personal.scenario,
                       reopened.personal.resume, reopened.personal.background):
            editor.clear()
        reopened.personal.save.click()
        wait(app, lambda: reopened.personal.worker is None)
        assert reopened.cloud.saved_personal == PersonalInfo()
    finally:
        reopened.close()
        wait(app, lambda: not reopened.isVisible())
