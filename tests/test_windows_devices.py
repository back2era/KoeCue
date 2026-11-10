"""Opt-in WASAPI enumeration, with no capture or device mutation."""
import os

import pytest

from ai_japanese_interview_assistant.audio import list_devices


@pytest.mark.skipif(os.environ.get("AIJA_TEST_DEVICES") != "1", reason="opt-in WASAPI check")
def test_wasapi_enumerates_real_inputs_and_loopbacks():
    devices = list_devices()
    assert any(device.loopback for device in devices)
    assert all(device.channels > 0 and device.rate > 0 for device in devices)
