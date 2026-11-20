import os
from time import monotonic, sleep

import pytest


pytestmark = pytest.mark.skipif(os.environ.get("AIJA_TEST_GUI") != "1", reason="opt-in Qt smoke test")


def wait(app, condition):
    until = monotonic() + 5
    while not condition() and monotonic() < until:
        app.processEvents()
        sleep(0.01)
    assert condition()


def test_opens_with_two_saved_services_and_reuses_key_when_they_match(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from ai_japanese_interview_assistant import cloud_gui
    from ai_japanese_interview_assistant.audio import Device
    from ai_japanese_interview_assistant.diagnostic import DeviceScan
    from ai_japanese_interview_assistant.settings import Preferences, save_preferences

    keys = {}

    def vault(operation, value, provider):
        if operation == "read":
            return keys.get(provider.key_env, "")
        if operation == "save":
            keys[provider.key_env] = value

    for name in ("OPENAI_API_KEY", "DEEPSEEK_API_KEY", "DOUBAO_ASR_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(cloud_gui, "credential", vault)
    monkeypatch.setattr(DeviceScan, "run", lambda scan: scan.result.emit([Device(0, "测试设备", True, 48000, 2)]))
    sessions = []
    monkeypatch.setattr(cloud_gui.LiveWorker, "start", lambda worker: sessions.append(worker))
    monkeypatch.setattr(cloud_gui.LiveWorker, "stop", lambda worker: worker.finished.emit())

    app = QApplication.instance() or QApplication([])
    save_preferences(Preferences(provider="deepseek", interview_language="zh", speech_model="doubao"))
    pane = cloud_gui.CloudPane()
    pane.show()
    try:
        wait(app, pane.key.isEnabled)
        pane.settings_toggle.setChecked(True)
        pane.source.setCurrentIndex(1)
        QTest.keyClicks(pane.key, "fixture-text-key")
        assert not pane.start.isEnabled()
        assert pane.speech_key.isVisible()
        QTest.keyClicks(pane.speech_key, "fixture-speech-key")
        pane.settings.accept()
        wait(app, pane.start.isEnabled)
        assert "豆包语音" in pane.capture_notice.text()
        assert "DeepSeek" in pane.capture_notice.text()
        assert sessions == []
        pane.start.click()
        assert len(sessions) == 1
        assert sessions[0].key == "fixture-text-key"
        assert sessions[0].speech_key == "fixture-speech-key"
        assert sessions[0].speech.model == "volc.seedasr.sauc.duration"
        assert keys == {"DEEPSEEK_API_KEY": "fixture-text-key", "DOUBAO_ASR_API_KEY": "fixture-speech-key"}
        ini = tmp_path / "AIJapaneseInterviewAssistant" / "settings.ini"
        assert "fixture-" not in ini.read_text(encoding="utf-8")
        pane.stop_session()
        wait(app, lambda: pane.shutdown())
    finally:
        pane.close()

    pane = cloud_gui.CloudPane()
    pane.show()
    try:
        wait(app, pane.start.isEnabled)
        assert pane.speech_model.currentData() == "doubao"
        assert pane.speech_key.text() == "fixture-speech-key"
        pane.interview_language.setCurrentIndex(pane.interview_language.findData("ja"))
        assert not pane.start.isEnabled()
        pane.speech_model.setCurrentIndex(pane.speech_model.findData("deepseek"))
        wait(app, pane.start.isEnabled)
        pane.settings_toggle.setChecked(True)
        assert not pane.speech_key.isVisible()
        assert pane.asr_key() == "fixture-text-key"
        assert "共用" in pane.speech_help.text()
    finally:
        wait(app, pane.shutdown)
        pane.close()
