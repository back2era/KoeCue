import struct
import sys
from types import SimpleNamespace

from ai_japanese_interview_assistant import audio
from ai_japanese_interview_assistant.audio import AudioBuffer, AudioError, Device, capture, pcm_level
import pytest


def test_pause_drops_frames_and_refuses_late_callbacks():
    buffer = AudioBuffer(max_frames=2)
    assert buffer.push(b'first')
    buffer.close()
    assert not buffer.push(b'late')
    assert buffer.pop() is None


def test_overflow_ends_capture_instead_of_sending_backlog():
    buffer = AudioBuffer(max_frames=1)
    assert buffer.push(b'first')
    assert not buffer.push(b'overflow')
    with pytest.raises(AudioError, match='队列'):
        buffer.pop()


def test_meter_separates_silence_and_loud_input():
    assert pcm_level(struct.pack('<4h', 0, 0, 0, 0)) == 0
    assert pcm_level(struct.pack('<4h', -32768, 32767, -32768, 32767)) >= 99


def test_stop_before_open_does_not_initialize_the_driver(monkeypatch):
    def driver():
        pytest.fail("PortAudio opened after stop")

    monkeypatch.setitem(sys.modules, "pyaudiowpatch", SimpleNamespace(PyAudio=driver))
    buffer = AudioBuffer()
    buffer.close()
    with pytest.raises(AudioError, match="停止"):
        with capture(Device(0, "Output", True, 48000, 2), buffer):
            pytest.fail("Stream became active after stop")


def test_different_endpoint_topology_requires_explicit_reselection(monkeypatch):
    device = Device(0, "Output", True, 48000, 2, (("Render", "original"),))
    monkeypatch.setattr(audio, "endpoint_topology", lambda: (("Render", "replacement"),))
    with pytest.raises(AudioError, match="设备已变化"):
        audio.check_topology(device)
