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
    from PySide6.QtWidgets import QApplication, QFileDialog
    from ai_japanese_interview_assistant import cloud_gui, diagnostic
    from ai_japanese_interview_assistant.__main__ import MainWindow, configure_application
    from ai_japanese_interview_assistant.audio import Device
    from ai_japanese_interview_assistant.personal import PersonalInfo
    from ai_japanese_interview_assistant.transcription import TranscriptPart

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
        window.navigation.button(3).click()
        assert window.tabs.currentWidget() is pane
        wait(app, lambda: pane.import_button.isEnabled() and window.cloud.key.isEnabled())
        assert pane.pages.count() == 6
        assert cloud.auto_answer.isChecked()
        cloud.source.setCurrentIndex(1)
        cloud.key.setText("offline-test")
        wait(app, cloud.start.isEnabled)
        pane.import_button.click()
        wait(app, lambda: pane.worker is None)
        assert "確認用テキスト" in pane.resume.toPlainText()
        pane.background.setPlainText("测试简介")
        pane.navigation.button(1).click()
        pane.targets.add_button.click()
        pane.targets.cards[0].fields.editors["role"].setText("其他测试岗位")
        pane.targets.add_button.click()
        pane.targets.cards[1].active.click()
        editors = pane.targets.cards[1].fields.editors
        editors["company"].setText("示例会社")
        editors["role"].setText("电源研发工程师")
        editors["scenario"].setPlainText("技术一面")
        translation = pane.preferences.editors["translation"]
        translation.setCurrentIndex(translation.findData("off"))
        saved = pane.current()
        assert pane.save.isVisible() and pane.save.isEnabled()
        assert pane.save.objectName() == "primaryAction"
        assert "未保存" in pane.status.text()
        pane.save.click()
        assert not cloud.start.isEnabled()
        wait(app, lambda: pane.worker is None)
        assert window.cloud.saved_personal == saved
        assert saved.target_context["role"] == "电源研发工程师"
        assert window.cloud.approved_personal == PersonalInfo()
        assert sessions == []

        editors["role"].setText("未保存的岗位")
        window.tabs.setCurrentWidget(cloud)
        wait(app, cloud.start.isEnabled)
        assert "相关面试资料" in cloud.start.toolTip()
        cloud.start.click()
        assert sessions == [saved]
        assert cloud.approved_personal == saved
        assert cloud.worker.subtitle_language == "zh" and cloud.worker.answer_translation_language == ""
        part = TranscriptPart("question", "模擬の質問", final=True)
        key = (cloud.session_id, cloud.generation, part.item_id)
        cloud.add_transcript((key, part))
        assert cloud.rows[key].translation_language == "zh" and cloud.rows[key].answer_translation_language == ""
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
        assert reopened.personal.targets.cards[1].active.isChecked()
        assert reopened.personal.targets.cards[1].fields.editors["company"].text() == "示例会社"
        assert "Sample project" in reopened.personal.resume.toPlainText()
        assert reopened.cloud.saved_personal == saved
        assert reopened.cloud.approved_personal == PersonalInfo()
        for card in list(reopened.personal.targets.cards):
            reopened.personal.targets.remove(card)
        reopened.personal.resume.clear()
        reopened.personal.background.clear()
        translation = reopened.personal.preferences.editors["translation"]
        translation.setCurrentIndex(translation.findData(""))
        reopened.personal.save.click()
        wait(app, lambda: reopened.personal.worker is None)
        assert reopened.cloud.saved_personal == PersonalInfo()
    finally:
        reopened.close()
        wait(app, lambda: not reopened.isVisible())


@pytest.mark.parametrize("lines,school,title,task,tool", [
    (("Name: Example Candidate", "Education", "School: Example University", "Major: Electronics",
      "Projects", "Project name: Converter test", "Responsibilities: Measured ripple", "Tools: Oscilloscope"),
     "Example University", "Converter test", "Measured ripple", "Oscilloscope"),
    (("姓名：示例同学", "教育经历", "学校：示例大学", "专业：电子信息工程",
      "项目经历", "项目名称：电源测试", "个人职责：测量输出纹波", "使用工具：示波器"),
     "示例大学", "电源测试", "测量输出纹波", "示波器"),
    (("氏名：山田テスト", "学歴", "学校名：サンプル大学", "専攻：電子工学", "プロジェクト経験",
      "プロジェクト名：電源評価", "担当：リップルを測定", "使用技術：オシロスコープ"),
     "サンプル大学", "電源評価", "リップルを測定", "オシロスコープ"),
], ids=("English", "Chinese", "Japanese"))
def test_pdf_import_fills_editable_education_and_project_fields(tmp_path, monkeypatch, lines, school, title, task, tool):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    from PySide6.QtGui import QFont, QPainter, QPdfWriter
    from PySide6.QtWidgets import QApplication, QFileDialog
    from ai_japanese_interview_assistant.__main__ import configure_application
    from ai_japanese_interview_assistant.personal import PersonalStore
    from ai_japanese_interview_assistant.personal_gui import PersonalPane

    app = QApplication.instance() or QApplication([])
    configure_application(app)
    path = tmp_path / "synthetic.pdf"
    pdf = QPdfWriter(str(path))
    pdf.setResolution(72)
    painter = QPainter(pdf)
    painter.setFont(QFont("Microsoft YaHei UI", 12))
    for line, text in enumerate(lines):
        painter.drawText(25, 45 + 20 * line, text)
    painter.end()
    del pdf
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (str(path), ""))

    pane = PersonalPane()
    pane.show()
    try:
        wait(app, pane.import_button.isEnabled)
        pane.basics.editors["name"].setText("Manually entered")
        pane.import_button.click()
        wait(app, lambda: pane.worker is None)
        assert pane.basics.editors["name"].text() == "Manually entered"
        assert pane.education.cards[0].fields.editors["school"].text() == school
        project = pane.experiences.cards[0].fields.editors
        assert project["responsibilities"].toPlainText() == task
        assert project["tools"].text() == tool
        assert not PersonalStore().load()

        project["tools"].setText("Scope and electronic load")
        pane.import_button.click()
        wait(app, lambda: pane.worker is None)
        assert len(pane.experiences.cards) == 1
        assert pane.current().experiences[0].tools == "Scope and electronic load"
        pane.save.click()
        wait(app, lambda: pane.worker is None)
        assert PersonalStore().load().experiences[0].title == title
    finally:
        pane.close()
