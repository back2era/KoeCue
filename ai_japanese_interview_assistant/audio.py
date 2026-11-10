"""WASAPI input, capture buffering, and local metering."""
from array import array
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass
from math import sqrt
from threading import Lock


class AudioError(Exception):
    """Safe message about an audio failure."""


@dataclass(frozen=True)
class Device:
    index: int
    name: str
    loopback: bool
    rate: int
    channels: int


class AudioBuffer:
    def __init__(self, max_frames=100):
        self._frames = deque()
        self._max_frames = max_frames
        self._lock = Lock()
        self._closed = False
        self._error = ""

    def push(self, data, driver_status=0):
        with self._lock:
            if self._closed:
                return False
            if driver_status or len(self._frames) >= self._max_frames:
                self._error = "音频驱动报告采集异常。" if driver_status else "音频队列已满。"
                self._frames.clear()
                self._closed = True
                return False
            if data:
                self._frames.append(data)
            return True

    def pop(self):
        with self._lock:
            if self._error:
                raise AudioError(self._error)
            return self._frames.popleft() if self._frames else None

    def close(self):
        with self._lock:
            self._closed = True
            self._frames.clear()


def pcm_level(pcm):
    samples = array("h", pcm)
    if not samples:
        return 0
    rms = sqrt(sum(sample * sample for sample in samples) / len(samples))
    return min(100, round(rms * 100 / 32768))


def _wasapi_inputs(api, pa):
    for info in api.get_device_info_generator_by_host_api(host_api_type=pa.paWASAPI):
        if info["maxInputChannels"] > 0:
            yield Device(
                info["index"], info["name"], bool(info.get("isLoopbackDevice")),
                round(info["defaultSampleRate"]), int(info["maxInputChannels"]),
            )


def list_devices():
    import pyaudiowpatch as pa

    with pa.PyAudio() as api:
        return sorted(_wasapi_inputs(api, pa), key=lambda device: (not device.loopback, device.name))


@contextmanager
def capture(device, buffer):
    import pyaudiowpatch as pa

    def on_audio(data, frame_count, time_info, status):
        active = buffer.push(data, status)
        return (None, pa.paContinue if active else pa.paAbort)

    with pa.PyAudio() as api:
        if device not in list(_wasapi_inputs(api, pa)):
            raise AudioError("所选设备已变更。请刷新列表并重新选择。")
        stream = api.open(
            format=pa.paInt16, channels=device.channels, rate=device.rate, input=True,
            input_device_index=device.index, frames_per_buffer=round(device.rate * 0.02),
            stream_callback=on_audio, start=False,
        )
        try:
            stream.start_stream()
            yield stream
        finally:
            buffer.close()
            stream.close()
