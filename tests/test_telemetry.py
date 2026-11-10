from ai_japanese_interview_assistant.telemetry import Event, SessionLog


def test_logs_are_bounded_and_contain_only_metrics(tmp_path):
    log = SessionLog(tmp_path)
    log.record(Event.REALTIME_READY, 0.125)
    log.record(Event.API_ERROR)
    log.close()
    content = (tmp_path / "assistant.log").read_text(encoding="utf-8")
    assert "realtime_ready elapsed_ms=125" in content
    assert "api_error" in content
    assert "Authorization" not in content
