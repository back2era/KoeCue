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
        assert pane.input_summary.text() == "系统音频 · 中文"
        assert not pane.status_detail.isVisible()
        assert "豆包语音" in pane.start.toolTip()
        assert "DeepSeek" in pane.start.toolTip()
        assert sessions == []
        pane.start.click()
        assert len(sessions) == 1
        assert sessions[0].key == "fixture-text-key"
        assert sessions[0].speech_key == "fixture-speech-key"
        assert sessions[0].speech.model == "volc.seedasr.sauc.duration"
        assert keys == {"DEEPSEEK_API_KEY": "fixture-text-key", "DOUBAO_ASR_API_KEY": "fixture-speech-key"}
        ini = tmp_path / "AIJapaneseInterviewAssistant" / "settings.ini"
        assert "fixture-" not in ini.read_text(encoding="utf-8")
        sessions[0].failure.emit("asr", "连接超时，请检查网络。")
        assert pane.status_detail.isVisible()
        assert pane.status_detail.text() == "转写异常"
        assert pane.status_detail.toolTip() == "连接超时，请检查网络。"
        pane.stop_session()
        assert not pane.status_detail.isVisible()
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

@pytest.mark.parametrize("language,translation", [("ja", "zh"), ("zh", "")])
def test_saved_interview_language_from_an_older_version_resolves_to_the_same_preset(
    language, translation, tmp_path, monkeypatch,
):
    from ai_japanese_interview_assistant.settings import load_preferences

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    app_data = tmp_path / "AIJapaneseInterviewAssistant"
    app_data.mkdir()
    (app_data / "settings.ini").write_text(f"[interview]\nlanguage={language}\n", encoding="utf-8")

    preferences = load_preferences()
    assert preferences.interview_language == language
    assert preferences.translation_language == translation
    assert preferences.answer_language == language


def test_language_preset_and_custom_languages_are_saved_and_history_keeps_its_languages(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("OPENAI_API_KEY", "fixture")
    from PySide6.QtWidgets import QApplication
    from ai_japanese_interview_assistant import cloud_gui
    from ai_japanese_interview_assistant.audio import Device
    from ai_japanese_interview_assistant.diagnostic import DeviceScan
    from ai_japanese_interview_assistant.interview import Answer
    from ai_japanese_interview_assistant.settings import load_preferences
    from ai_japanese_interview_assistant.transcription import TranscriptPart

    monkeypatch.setattr(cloud_gui, "credential", lambda *args: "")
    monkeypatch.setattr(DeviceScan, "run", lambda scan: scan.result.emit([Device(0, "测试设备", True, 48000, 2)]))
    sessions = []
    monkeypatch.setattr(cloud_gui.LiveWorker, "start", lambda worker: sessions.append(worker))
    monkeypatch.setattr(cloud_gui.LiveWorker, "stop", lambda worker: worker.finished.emit())
    app = QApplication.instance() or QApplication([])
    pane = cloud_gui.CloudPane()
    pane.show()
    try:
        wait(app, pane.language_preset.isEnabled)
        pane.language_preset.setCurrentIndex(pane.language_preset.findData("en"))
        assert (pane.interview_language.currentData(), pane.translation_language.currentData(),
                pane.answer_language.currentData()) == ("en", "zh", "en")
        pane.translation_language.setCurrentIndex(pane.translation_language.findData("ja"))
        pane.answer_language.setCurrentIndex(pane.answer_language.findData("zh"))
        assert pane.language_preset.currentText() == "自定义"
        pane.source.setCurrentIndex(1)
        pane.settings.accept()
        wait(app, pane.start.isEnabled)
        config = load_preferences()
        assert (config.interview_language, config.translation_language, config.answer_language) == ("en", "ja", "zh")

        pane.start.click()
        worker, = sessions
        assert (worker.language, worker.subtitle_language, worker.answer_language) == ("en", "ja", "zh")
        assert not pane.language_preset.isEnabled()
        key = (worker.session_id, worker.generation, "segment")
        pane.add_transcript((key, TranscriptPart("segment", "Tell me about yourself.", final=True)))
        pane.add_translation(key, "自己紹介をお願いします。", "已翻译")
        pane.add_answer(key, Answer(ja="回路を作りました。", zh="我制作了电路。"), "建议已生成", False)
        pane.render_history()
        pane.stop_session()
        pane.language_preset.setCurrentIndex(pane.language_preset.findData("zh"))
        pane.history.selectRow(0)

        assert pane.original_title.text() == "英语原文"
        assert pane.translation_title.text() == "日语译文"
        assert not pane.history.isColumnHidden(1)
        assert pane.answer_body.text() == "我制作了电路。"
        pane.copy_answer()
        assert app.clipboard().text() == "我制作了电路。\n\n回路を作りました。"
    finally:
        wait(app, pane.shutdown)
        pane.close()
