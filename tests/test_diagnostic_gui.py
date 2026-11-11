"""Offscreen smoke test with real device enumeration and no capture."""
import os
from time import monotonic, sleep

import pytest


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

        from ai_japanese_interview_assistant.cloud_gui import Row

        cloud = window.cloud
        monkeypatch.setenv("OPENAI_API_KEY", "test-openai")
        monkeypatch.setenv("DEEPSEEK_API_KEY", "test-deepseek")
        cloud.key.setText("temporary-openai")
        cloud.consent.setChecked(True)
        cloud.provider.setCurrentIndex(cloud.provider.findData("deepseek"))
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
        app.processEvents()


@pytest.mark.skipif(os.environ.get("AIJA_TEST_GUI") != "1", reason="opt-in Qt smoke test")
def test_deepseek_worker_translates_and_automatically_answers_a_local_question(monkeypatch):
    import asyncio
    import json

    import httpx
    from ai_japanese_interview_assistant import live
    from ai_japanese_interview_assistant.config import DEEPSEEK

    async def exercise():
        finished = asyncio.Event()
        translations = []
        answers = []
        question = "要件が変わったらどうしますか。"

        def handle(request):
            assert str(request.url) == DEEPSEEK.url
            assert request.headers["authorization"] == "Bearer test-deepseek"
            payload = json.loads(request.content)
            if payload.get("stream"):
                assert payload["input"] == question
                return httpx.Response(200, text=(
                    'data: {"type":"response.output_text.delta","delta":"需求变更时你会怎么办？"}\n\n'
                    'data: {"type":"response.completed"}\n\n'
                ))
            name = payload["text"]["format"]["name"]
            if name == "question":
                assert payload["input"] == question
            structured = {
                "question": {"question": True, "personal": False, "categories": []},
                "draft": {"before_ja": "影響範囲を確認します。", "before_zh": "我会确认影响范围。",
                          "after_ja": "", "after_zh": "", "fact_ids": []},
                "verify_answer": {"safe": True},
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
            yield b"fixture-pcm"
            yield None
            await finished.wait()

        def on_translation(row_id, text, state):
            if state == "已翻译":
                translations.append(text)
                if answers:
                    finished.set()

        def on_answer(row_id, answer, state, scoped):
            if answer is not None:
                answers.append((row_id, answer.ja, answer.zh))
                if translations:
                    finished.set()

        monkeypatch.setattr(live, "client_for", client_for)
        monkeypatch.setattr(live, "load_decoder", lambda: lambda pcm: question)
        monkeypatch.setattr(live, "run_transcription", no_openai)
        monkeypatch.setattr(live, "record", lambda *args: None)
        worker = live.LiveWorker(1, None, "test-deepseek", provider=DEEPSEEK, auto_answer=True)
        monkeypatch.setattr(worker, "audio_commands", frames)
        worker.translation.connect(on_translation)
        worker.answer.connect(on_answer)
        await asyncio.wait_for(worker._main(), 3)
        assert translations == ["需求变更时你会怎么办？"]
        assert answers == [((0, 1, "local-1"), "影響範囲を確認します。", "我会确认影响范围。")]

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
        deadline = monotonic() + 3
        while (window.diagnostic.scan is not None or cloud.scan is not None) and monotonic() < deadline:
            app.processEvents()
            sleep(0.01)
        assert window.diagnostic.scan is None and cloud.scan is None
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
