import struct

from ai_japanese_interview_assistant.audio import AudioBuffer, AudioError, pcm_level
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
