"""Offscreen desktop tests with no live network requests."""
import os
from time import monotonic, sleep

import pytest


@pytest.fixture(autouse=True)
def local_desktop_storage(tmp_path, monkeypatch):
    if os.environ.get("AIJA_TEST_GUI") != "1":
        return
    from ai_japanese_interview_assistant import cloud_gui

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    keys = {}

    def vault(operation, value="", provider=None):
        if operation == "read":
            return keys.get(provider.label, "")
        if operation == "save":
            keys[provider.label] = value
        elif operation == "delete":
            keys.pop(provider.label, None)

    monkeypatch.setattr(cloud_gui, "credential", vault)


def wait_until(app, condition):
    deadline = monotonic() + 5
    while not condition() and monotonic() < deadline:
        app.processEvents()
        sleep(0.01)
    assert condition()


@pytest.mark.skipif(os.environ.get("AIJA_TEST_GUI") != "1", reason="opt-in Qt smoke test")
def test_diagnostics_require_consent_before_starting_capture(monkeypatch):
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication
    from ai_japanese_interview_assistant.__main__ import MainWindow

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.show()
    try:
        assert window.tabs.currentWidget() is window.cloud
        assert window.cloud.auto_answer.isChecked()
        assert window.cloud.settings.isHidden()
        assert window.cloud.history.isVisible()
        assert not window.cloud.scroll.isAncestorOf(window.cloud.history)
        assert not window.cloud.scroll.isAncestorOf(window.cloud.stop)
        pane = window.diagnostic
        wait_until(app, lambda: pane.scan is None and window.cloud.provider.isEnabled())
        assert pane.scan is None
        assert window.cloud.scan is None
        assert pane.device.count() > 1
        pane.device.setCurrentIndex(1)
        assert not pane.start.isEnabled()
        pane.consent.setChecked(True)
        assert pane.start.isEnabled()
        assert pane.worker is None

        from ai_japanese_interview_assistant.cloud_gui import Row

        cloud = window.cloud
        monkeypatch.setenv("OPENAI_API_KEY", "test-openai")
        monkeypatch.setenv("DEEPSEEK_API_KEY", "test-deepseek")
        cloud.key.setText("temporary-openai")
        cloud.consent.setChecked(True)
        cloud.provider.setCurrentIndex(cloud.provider.findData("deepseek"))
        wait_until(app, lambda: cloud.provider.isEnabled())
        assert cloud.key.text() == ""
        assert cloud.api_key() == "test-deepseek"
        assert not cloud.consent.isChecked()
        assert cloud.auto_answer.isChecked()
        assert "DeepSeek" in cloud.consent.text() and "音频在本机" in cloud.consent.text()
        assert "本地" in cloud.start.text()

        cloud.session_id = 2
        cloud.state = "active"
        cloud.rows[(1, 1, "previous")] = Row(ja="前の質問", finalized=True)
        cloud.dirty = True
        cloud.render_history()
        assert not cloud.retry.isEnabled()
        assert not cloud.suggest.isEnabled()
        cloud.stop_session()
        assert cloud.auto_answer.isChecked()
        cloud.auto_answer.setChecked(False)
        cloud.provider.setCurrentIndex(cloud.provider.findData("openai"))
        assert not cloud.auto_answer.isChecked()
    finally:
        window.close()
        wait_until(app, lambda: not window.isVisible())


@pytest.mark.skipif(os.environ.get("AIJA_TEST_GUI") != "1", reason="opt-in Qt smoke test")
def test_glass_layout_keeps_history_visible_and_settings_in_sync():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from ai_japanese_interview_assistant.__main__ import MainWindow, configure_application
    from ai_japanese_interview_assistant.cloud_gui import Row

    app = QApplication.instance() or QApplication([])
    configure_application(app)
    window = MainWindow()
    window.resize(1160, 770)
    window.show()
    cloud = window.cloud
    try:
        wait_until(app, lambda: cloud.provider.isEnabled() and window.diagnostic.scan is None)
        assert cloud.splitter.orientation() == Qt.Orientation.Horizontal
        cloud.settings_toggle.click()
        assert cloud.settings.isVisible()
        assert cloud.history.isVisible() and cloud.stop.isVisible()
        assert not cloud.settings.grab().isNull()
        cloud.settings.reject()
        assert not cloud.settings_toggle.isChecked()
        assert not cloud.settings.isVisible()
        for index in range(8):
            key = (0, index, str(index))
            cloud.rows[key] = Row(ja=f"質問 {index}", finalized=True)
            cloud.mark_changed(key)
        cloud.render_history()
        window.resize(790, 730)
        app.processEvents()
        assert cloud.splitter.orientation() == Qt.Orientation.Vertical
        assert cloud.history.isVisible() and cloud.stop.isVisible()
        scroll = cloud.history.verticalScrollBar()
        assert scroll.maximum() > 0 and scroll.value() == scroll.maximum()
        window.resize(790, 550)
        app.processEvents()
        assert cloud.splitter.orientation() == Qt.Orientation.Horizontal
        cloud.settings_toggle.click()
        window.tabs.setCurrentWidget(window.diagnostic)
        assert not cloud.settings.isVisible()
        assert window.diagnostic.isVisible()
        window.activateWindow()
        app.processEvents()
        QTest.keyClick(window, Qt.Key.Key_Tab, Qt.KeyboardModifier.ControlModifier)
        assert window.tabs.currentWidget() is window.personal
        QTest.keyClick(window, Qt.Key.Key_Tab, Qt.KeyboardModifier.ControlModifier)
        assert window.tabs.currentWidget() is cloud
    finally:
        window.close()
        wait_until(app, lambda: not window.isVisible())


@pytest.mark.skipif(os.environ.get("AIJA_TEST_GUI") != "1", reason="opt-in Qt smoke test")
def test_application_waveform_icon_reaches_main_window_and_settings():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication
    from ai_japanese_interview_assistant.__main__ import MainWindow, configure_application

    app = QApplication.instance() or QApplication([])
    configure_application(app)
    window = MainWindow()
    window.show()
    try:
        icon = app.windowIcon()
        assert not icon.isNull()
        assert window.windowIcon().cacheKey() == icon.cacheKey()
        assert window.cloud.settings.windowIcon().cacheKey() == icon.cacheKey()
        assert {size.width() for size in icon.availableSizes()} >= {16, 32, 48, 256}
        image = icon.pixmap(48, 48).toImage()
        assert image.pixelColor(0, 0).alpha() == 0
        assert image.pixelColor(24, 24).lightness() > 220
    finally:
        window.close()
        wait_until(app, lambda: not window.isVisible())


@pytest.mark.skipif(os.environ.get("AIJA_TEST_GUI") != "1", reason="opt-in Qt smoke test")
def test_selected_theme_is_restored_after_restart():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication
    from ai_japanese_interview_assistant.__main__ import MainWindow, configure_application

    app = QApplication.instance() or QApplication([])
    configure_application(app)
    window = MainWindow()
    window.show()
    try:
        wait_until(app, lambda: window.cloud.theme.isEnabled())
        theme = window.cloud.theme
        assert [theme.itemData(index) for index in range(theme.count())] == [
            "graphite", "ocean", "glacier", "sand", "black",
        ]
        theme.setCurrentIndex(theme.findData("glacier"))
        assert app.property("interviewTheme") == "glacier"
    finally:
        window.close()
        wait_until(app, lambda: not window.isVisible())

    configure_application(app)
    reopened = MainWindow()
    reopened.show()
    try:
        wait_until(app, lambda: reopened.cloud.theme.isEnabled())
        assert reopened.cloud.theme.currentData() == "glacier"
        assert app.property("interviewTheme") == "glacier"
    finally:
        reopened.close()
        wait_until(app, lambda: not reopened.isVisible())


@pytest.mark.skipif(os.environ.get("AIJA_TEST_GUI") != "1", reason="opt-in Qt smoke test")
def test_answer_level_is_restored_after_restart():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication
    from ai_japanese_interview_assistant.__main__ import MainWindow, configure_application

    app = QApplication.instance() or QApplication([])
    configure_application(app)
    window = MainWindow()
    window.show()
    try:
        wait_until(app, lambda: window.cloud.provider.isEnabled())
        level = window.cloud.answer_level
        assert level.currentData() == "N2"
        assert {level.itemData(i) for i in range(level.count())} == {"N1", "N2", "N3", "N4", "N5"}
        level.setCurrentIndex(level.findData("N1"))
    finally:
        window.close()
        wait_until(app, lambda: not window.isVisible())

    reopened = MainWindow()
    reopened.show()
    try:
        wait_until(app, lambda: reopened.cloud.provider.isEnabled())
        assert reopened.cloud.answer_level.currentData() == "N1"
    finally:
        reopened.close()
        wait_until(app, lambda: not reopened.isVisible())


@pytest.mark.skipif(os.environ.get("AIJA_TEST_GUI") != "1", reason="opt-in Qt smoke test")
def test_deepseek_worker_translates_and_automatically_suggests_a_reply_to_a_statement(monkeypatch):
    import asyncio
    import json

    import httpx
    from ai_japanese_interview_assistant import live
    from ai_japanese_interview_assistant.answer_format import RubyAnnotation
    from ai_japanese_interview_assistant.config import DEEPSEEK
    from ai_japanese_interview_assistant.interview import Answer

    async def exercise():
        finished = asyncio.Event()
        preview_ready = asyncio.Event()
        translations = []
        answers = []
        previews = []
        statement = "次に、担当業務についてご説明します。"
        answer_text = "はい、よろしくお願いします。"

        def handle(request):
            assert str(request.url) == DEEPSEEK.url
            assert request.headers["authorization"] == "Bearer test-deepseek"
            payload = json.loads(request.content)
            if payload.get("stream"):
                assert payload["input"] == statement
                return httpx.Response(200, text=(
                    'data: {"type":"response.output_text.delta","delta":"接下来我会介绍岗位职责。"}\n\n'
                    'data: {"type":"response.completed"}\n\n'
                ))
            name = payload["text"]["format"]["name"]
            if name == "draft":
                assert json.loads(payload["input"]) == {"question": statement, "facts": []}
                assert "JLPT N1" in payload["instructions"]
            elif name == "annotate_answer":
                assert payload["input"] == answer_text
            structured = {
                "draft": {"before_ja": answer_text, "before_zh": "好的，请您介绍。",
                          "after_ja": "", "after_zh": "", "fact_ids": []},
                "verify_answer": {"safe": True},
                "annotate_answer": {"terms": ["願"], "labels": ["ねが"], "contexts": [""]},
            }[name]
            return httpx.Response(200, json={"status": "completed", "output": [{
                "type": "message",
                "content": [{"type": "output_text", "text": json.dumps(structured)}],
            }]})

        def client_for(key, provider):
            assert provider is DEEPSEEK
            return httpx.AsyncClient(transport=httpx.MockTransport(handle), headers={"Authorization": f"Bearer {key}"})

        def no_openai(*args, **kwargs):
            pytest.fail("DeepSeek must not contact OpenAI Realtime")

        async def frames():
            yield b"\x01\x00" * 48000
            await asyncio.wait_for(preview_ready.wait(), 2)
            assert not translations and not answers
            yield None
            await finished.wait()

        def on_preview(data):
            previews.append(data[1].text)
            preview_ready.set()

        def on_translation(row_id, text, state):
            if state == "已翻译":
                translations.append(text)
                if answers and answers[-1][1].annotations:
                    finished.set()

        def on_answer(row_id, answer, state, scoped):
            if answer is not None:
                answers.append((row_id, answer))
                if translations and answer.annotations:
                    finished.set()

        monkeypatch.setattr(live, "client_for", client_for)
        monkeypatch.setattr(live, "load_decoder", lambda: lambda pcm, *, preview=False: "次に担当" if preview else statement)
        monkeypatch.setattr(live, "run_transcription", no_openai)
        monkeypatch.setattr(live, "record", lambda *args: None)
        worker = live.LiveWorker(1, None, "test-deepseek", provider=DEEPSEEK, auto_answer=True, answer_level="N1")
        monkeypatch.setattr(worker, "audio_commands", frames)
        worker.partial_transcript.connect(on_preview)
        worker.translation.connect(on_translation)
        worker.answer.connect(on_answer)
        await asyncio.wait_for(worker._main(), 3)
        assert previews == ["次に担当"]
        assert translations == ["接下来我会介绍岗位职责。"]
        row_id = (0, 1, "local-1")
        offset = answer_text.index("願")
        assert answers == [
            (row_id, Answer(answer_text, "好的，请您介绍。")),
            (row_id, Answer(answer_text, "好的，请您介绍。", (RubyAnnotation(offset, offset + 1, "ねが"),))),
        ]

    asyncio.run(exercise())


@pytest.mark.skipif(os.environ.get("AIJA_TEST_GUI") != "1", reason="opt-in Qt smoke test")
def test_caption_reveals_new_characters_one_at_a_time(monkeypatch):
    from PySide6.QtWidgets import QApplication
    from ai_japanese_interview_assistant.cloud_gui import CaptionLabel

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    caption = CaptionLabel("等待译文")
    caption.set_caption("我想在", animate=False)
    caption.set_caption("我想在日本工作", animate=True)
    assert caption.text() == "我想在"
    caption.reveal_next()
    assert caption.text() == "我想在日"
    caption.reveal_next()
    assert caption.text() == "我想在日本"
    caption.set_caption("历史译文", animate=False)
    assert caption.text() == "历史译文"
    assert not caption.timer.isActive()
    caption.set_caption("历史译文" + "字" * 40, animate=True)
    caption.reveal_next()
    assert caption.text() == "历史译文字"


@pytest.mark.skipif(os.environ.get("AIJA_TEST_GUI") != "1", reason="opt-in Qt smoke test")
def test_worker_shows_and_translates_only_the_final_japanese_segment(monkeypatch):
    import asyncio

    from ai_japanese_interview_assistant import live

    async def exercise():
        translated = asyncio.Event()
        transcripts = []
        output = []
        requests = []

        class Service:
            async def translate(self, text):
                requests.append(text)
                yield "在"
                yield "日本工作"

        def receive(row_id, text, state):
            output.append((row_id, text, state))
            if state == "已翻译":
                translated.set()

        monkeypatch.setattr(live, "record", lambda *args: None)
        worker = live.LiveWorker(1, None, "test")
        worker.service = Service()
        worker.translation.connect(receive)
        worker.transcript.connect(transcripts.append)
        worker.on_event({"type": "conversation.item.input_audio_transcription.delta", "item_id": "a", "delta": "日本に"})
        worker.on_event({"type": "input_audio_buffer.committed", "item_id": "a"})
        await asyncio.sleep(0)
        assert not transcripts and not requests
        worker.on_event({"type": "conversation.item.input_audio_transcription.completed", "item_id": "a", "transcript": "日本で働く"})
        await asyncio.wait_for(translated.wait(), 2)
        assert [part.text for _, part in transcripts] == ["日本で働く"]
        assert requests == ["日本で働く"]
        assert ((0, 1, "a"), "在", "翻译中") in output
        assert output[-1] == ((0, 1, "a"), "在日本工作", "已翻译")

    asyncio.run(exercise())


@pytest.mark.skipif(os.environ.get("AIJA_TEST_GUI") != "1", reason="opt-in Qt smoke test")
def test_history_keeps_old_rows_and_scroll_position_when_a_new_segment_arrives(monkeypatch):
    from PySide6.QtWidgets import QApplication
    from ai_japanese_interview_assistant.__main__ import MainWindow
    from ai_japanese_interview_assistant.cloud_gui import Row, DeviceScan
    from ai_japanese_interview_assistant.transcription import TranscriptPart

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setattr(DeviceScan, "run", lambda self: self.result.emit([]))
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.show()
    cloud = window.cloud
    try:
        wait_until(app, lambda: window.diagnostic.scan is None and cloud.provider.isEnabled())
        cloud.session_id = 1
        cloud.state = "active"
        keys = [(1, 1, str(index)) for index in range(500)]
        cloud.rows.update({key: Row(ja=f"質問 {key[-1]}", zh=f"问题 {key[-1]}", finalized=True) for key in keys})
        cloud.dirty = True
        cloud.render_history()
        app.processEvents()
        cloud.history.selectRow(5)
        scroll = cloud.history.verticalScrollBar()
        scroll.setValue(3)
        newest = (1, 1, "500")
        cloud.add_transcript((newest, TranscriptPart("500", "次の質問", final=True)))
        cloud.add_translation(newest, "下一个问题", "已翻译")
        cloud.render_history()
        assert cloud.history.rowCount() == 501
        assert cloud.history.item(0, 1).text() == "问题 0"
        assert cloud.history.item(500, 1).text() == "下一个问题"
        assert cloud.current_row()[0] == keys[5]
        assert scroll.value() == 3
        cloud.latest.click()
        assert cloud.current_row()[0] == newest
        assert scroll.value() == scroll.maximum()
        next_key = (1, 1, "501")
        cloud.add_transcript((next_key, TranscriptPart("501", "最後の質問", final=True)))
        cloud.render_history()
        assert cloud.current_row()[0] == next_key
        assert scroll.value() == scroll.maximum()
    finally:
        window.close()
        wait_until(app, lambda: not window.isVisible())


@pytest.mark.skipif(os.environ.get("AIJA_TEST_GUI") != "1", reason="opt-in Qt smoke test")
def test_settings_restore_after_closing_with_a_renumbered_audio_device(monkeypatch, tmp_path):
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from ai_japanese_interview_assistant.__main__ import MainWindow
    from ai_japanese_interview_assistant.audio import Device
    from ai_japanese_interview_assistant.diagnostic import DeviceScan

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    devices = [Device(10, "会议扬声器", True, 48000, 2)]
    monkeypatch.setattr(DeviceScan, "run", lambda self: self.result.emit(devices[:]))
    app = QApplication.instance() or QApplication([])

    def ready(window):
        return window.cloud.provider.isEnabled() and window.diagnostic.scan is None

    window = MainWindow()
    window.show()
    try:
        wait_until(app, lambda: ready(window))
        pane = window.cloud
        pane.provider.setCurrentIndex(pane.provider.findData("deepseek"))
        wait_until(app, lambda: pane.key.isEnabled())
        pane.source.setCurrentIndex(1)
        QTest.keyClicks(pane.key, "synthetic-key")
        pane.auto_answer.setChecked(False)
        pane.consent.setChecked(True)
    finally:
        window.close()
        wait_until(app, lambda: not window.isVisible())

    devices[:] = [Device(10, "其他扬声器", True, 48000, 2), Device(21, "会议扬声器", True, 48000, 2)]
    restored = MainWindow()
    restored.show()
    try:
        wait_until(app, lambda: ready(restored))
        pane = restored.cloud
        assert pane.provider.currentData() == "deepseek"
        assert pane.source.currentData().index == 21
        assert pane.key.text() == "synthetic-key"
        assert not pane.auto_answer.isChecked()
        assert not pane.consent.isChecked()
        assert pane.worker is None
        settings = tmp_path / "AIJapaneseInterviewAssistant" / "settings.ini"
        assert "synthetic-key" not in settings.read_text(encoding="utf-8")
        pane.use_vault("delete")
        wait_until(app, lambda: pane.key.isEnabled())
        assert pane.key.text() == ""
        devices[:] = [Device(10, "其他扬声器", True, 48000, 2)]
        pane.refresh_devices()
        wait_until(app, lambda: pane.source.isEnabled())
        assert pane.source.currentData() is None
        assert "上次音源不可用" in pane.input_summary.text()
    finally:
        restored.close()
        wait_until(app, lambda: not restored.isVisible())

    devices.append(Device(21, "会议扬声器", True, 48000, 2))
    reopened = MainWindow()
    reopened.show()
    try:
        wait_until(app, lambda: ready(reopened))
        assert reopened.cloud.key.text() == ""
        assert reopened.cloud.source.currentData().index == 21
    finally:
        reopened.close()
        wait_until(app, lambda: not reopened.isVisible())


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


@pytest.mark.skipif(os.environ.get("AIJA_TEST_GUI") != "1", reason="opt-in Qt smoke test")
def test_twenty_capture_cycles_release_the_stream(monkeypatch):
    from contextlib import contextmanager
    from PySide6.QtWidgets import QApplication
    from ai_japanese_interview_assistant import diagnostic
    from ai_japanese_interview_assistant.audio import Device

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    device = Device(0, "Test source", True, 48000, 1)
    opened, closed = [], []

    class Stream:
        def is_active(self):
            return True

    @contextmanager
    def simulated_capture(device, buffer):
        opened.append(device)
        buffer.push(bytes(1920))
        try:
            yield Stream()
        finally:
            closed.append(device)

    monkeypatch.setattr(diagnostic, "capture", simulated_capture)
    monkeypatch.setattr(diagnostic, "list_devices", lambda: [device])
    monkeypatch.setattr(diagnostic, "record", lambda *args: None)
    pane = diagnostic.DiagnosticPane()

    def wait_until(predicate):
        deadline = monotonic() + 3
        while not predicate() and monotonic() < deadline:
            app.processEvents()
            sleep(0.002)
        assert predicate()

    wait_until(lambda: pane.scan is None)
    pane.device.setCurrentIndex(1)
    try:
        for _ in range(20):
            pane.consent.setChecked(True)
            pane.start.click()
            wait_until(lambda: pane.state == "running")
            pane.pause.click()
            wait_until(lambda: pane.worker is None)
            assert pane.state == "paused"
            pane.start.click()
            wait_until(lambda: pane.state == "running")
            pane.stop.click()
            wait_until(lambda: pane.worker is None)
        assert len(opened) == len(closed) == 40
    finally:
        pane.shutdown()
        wait_until(lambda: pane.worker is None)
