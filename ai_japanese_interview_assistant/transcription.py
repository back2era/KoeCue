"""Streaming English transcription and client-side speech segmentation."""
import asyncio
from base64 import b64encode
from collections import deque
from contextlib import aclosing
from dataclasses import dataclass, replace
import json

from .config import REALTIME_MODEL, REALTIME_URL


LOCAL_PREVIEW_EVENT = "local.transcription.preview"


class RealtimeError(Exception):
    """Safe error message without provider payloads."""


@dataclass(frozen=True)
class TranscriptPart:
    item_id: str
    text: str = ""
    final: bool = False
    failed: bool = False


class TranscriptBook:
    def __init__(self):
        self._parts = {}
        self._order = []

    @property
    def parts(self):
        return tuple(self._parts[item] for item in self._order)

    @property
    def latest_item_id(self):
        return self._order[-1] if self._order else None

    def apply(self, event):
        kind = event.get("type", "")
        item = event.get("item_id")
        if not item or not (
            kind in ("input_audio_buffer.committed", LOCAL_PREVIEW_EVENT)
            or kind.startswith("conversation.item.input_audio_transcription.")
        ):
            return None

        if item not in self._parts:
            self._parts[item] = TranscriptPart(item)
            self._order.append(item)
        part = self._parts[item]

        if kind == "input_audio_buffer.committed":
            previous = event.get("previous_item_id")
            if previous != item and (previous is None or previous in self._order):
                self._order.remove(item)
                position = self._order.index(previous) + 1 if previous is not None else 0
                self._order.insert(position, item)
            return part
        if part.final or part.failed:
            return None
        match kind.rsplit(".", 1)[-1]:
            case "preview" if kind == LOCAL_PREVIEW_EVENT:
                part = replace(part, text=event["transcript"])
            case "delta":
                part = replace(part, text=part.text + event.get("delta", ""))
            case "completed":
                part = replace(part, text=event.get("transcript", "").strip(), final=True)
            case "failed":
                part = replace(part, failed=True)
            case _:
                return None
        self._parts[item] = part
        return part


class TurnCutter:
    """Consumes 20 ms frames and emits PCM appends and commit markers."""

    def __init__(self):
        self._prefix = deque(maxlen=10)
        self._length = 0
        self._silence = 0

    def push(self, pcm, speech):
        if not self._length:
            if not speech:
                self._prefix.append(pcm)
                return []
            pcm = b"".join(self._prefix) + pcm
            self._prefix.clear()
        self._length += len(pcm)
        self._silence = 0 if speech else self._silence + 1
        if self._silence == 30 or self._length >= 20 * 48000:
            return [pcm, *self.finish()]
        return [pcm]

    def finish(self):
        if not self._length:
            return []
        padding = max(0, 4800 - self._length)
        self._length = self._silence = 0
        return [bytes(padding), None] if padding else [None]


class AudioProcessor:
    def __init__(self, source_rate, channels):
        import numpy as np
        from soxr import ResampleStream
        import webrtcvad

        self._np = np
        self._channels = channels
        self._asr = ResampleStream(source_rate, 24000, 1, dtype="float32")
        self._vad_rate = ResampleStream(source_rate, 16000, 1, dtype="float32")
        self._vad = webrtcvad.Vad(2)
        self._cutter = TurnCutter()
        self._asr_bytes = bytearray()
        self._vad_bytes = bytearray()

    def push(self, pcm, *, last=False):
        np = self._np
        samples = np.frombuffer(pcm, dtype="<i2").reshape(-1, self._channels)
        mono = samples.mean(axis=1, dtype=np.float32)
        for converter, buffer in ((self._asr, self._asr_bytes), (self._vad_rate, self._vad_bytes)):
            output = converter.resample_chunk(mono, last=last)
            buffer.extend(np.clip(np.rint(output), -32768, 32767).astype("<i2").tobytes())
        commands = []
        paired = min(len(self._asr_bytes) // 960, len(self._vad_bytes) // 640)
        for offset in range(paired):
            asr = bytes(self._asr_bytes[offset * 960 : (offset + 1) * 960])
            vad = bytes(self._vad_bytes[offset * 640 : (offset + 1) * 640])
            commands.extend(self._cutter.push(asr, self._vad.is_speech(vad, 16000)))
        del self._asr_bytes[: paired * 960]
        del self._vad_bytes[: paired * 640]
        if last and self._asr_bytes and self._vad_bytes:
            vad = bytes(self._vad_bytes).ljust(640, b"\0")
            asr = bytes(self._asr_bytes).ljust(960, b"\0")
            commands.extend(self._cutter.push(asr, self._vad.is_speech(vad, 16000)))
        return commands

    def finish_turn(self):
        return self._cutter.finish()


async def run_transcription(key, frames, on_event, on_ready=lambda: None, *, connect=None, on_ending=lambda: None):
    """Send frames and emit provider events until input ends or the task is cancelled."""
    if connect is None:
        from websockets.asyncio.client import connect

    config = {
        "type": "session.update",
        "session": {
            "type": "transcription",
            "audio": {"input": {
                "format": {"type": "audio/pcm", "rate": 24000},
                "transcription": {"model": REALTIME_MODEL, "languages": ["en"], "delay": "low"},
                "turn_detection": None,
            }},
        },
    }

    async with connect(
        REALTIME_URL, additional_headers={"Authorization": f"Bearer {key}"},
        open_timeout=10, close_timeout=1, ping_interval=10, ping_timeout=5, max_queue=32,
    ) as socket:
        await socket.send(json.dumps(config))
        async with asyncio.timeout(10):
            while True:
                event = json.loads(await socket.recv())
                if event.get("type") == "error":
                    raise RealtimeError("转写配置被拒绝，请检查账户和模型权限。")
                if event.get("type") == "session.updated":
                    break

        pending = 0
        completed_ids = set()
        all_final = asyncio.Event()
        all_final.set()

        async def send_frames():
            nonlocal pending
            async with aclosing(frames):
                async for frame in frames:
                    if frame is None:
                        pending += 1
                        all_final.clear()
                        event = {"type": "input_audio_buffer.commit"}
                    else:
                        event = {"type": "input_audio_buffer.append", "audio": b64encode(frame).decode("ascii")}
                    await asyncio.wait_for(socket.send(json.dumps(event)), timeout=4)
            await asyncio.wait_for(all_final.wait(), timeout=15)

        async def receive_events():
            nonlocal pending
            while True:
                event = json.loads(await socket.recv())
                kind = event.get("type", "")
                if kind == "error":
                    raise RealtimeError("转写服务报告异常，当前会话已结束。")
                on_event(event)
                item = event.get("item_id")
                if item and kind in {
                    "conversation.item.input_audio_transcription.completed",
                    "conversation.item.input_audio_transcription.failed",
                } and item not in completed_ids:
                    completed_ids.add(item)
                    pending -= 1
                    if pending <= 0:
                        all_final.set()

        send_task = asyncio.create_task(send_frames())
        receive_task = asyncio.create_task(receive_events())
        try:
            on_ready()
            done, _ = await asyncio.wait((send_task, receive_task), return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        finally:
            on_ending()
            send_task.cancel()
            receive_task.cancel()
            await asyncio.gather(send_task, receive_task, return_exceptions=True)

# Doubao streaming ASR 2.0. The existing transcript events keep the UI and text API independent.
def _doubao_packet(kind, payload, *, final=False, json_payload=False):
    import gzip
    import struct
    body = gzip.compress(payload)
    return bytes((0x11, kind << 4 | (2 if final else 0), (16 if json_payload else 0) | 1, 0)) + struct.pack(">I", len(body)) + body


def _doubao_response(packet):
    import gzip
    import struct
    if not isinstance(packet, bytes) or len(packet) < 8 or packet[0] >> 4 != 1:
        raise RealtimeError("豆包返回了无效的语音协议帧。")
    offset = (packet[0] & 15) * 4
    kind, flags = packet[1] >> 4, packet[1] & 15
    if kind == 15:
        code = int.from_bytes(packet[offset:offset + 4], "big")
        raise RealtimeError(f"豆包语音服务拒绝请求（{code}），请检查语音服务权限与额度。")
    if kind != 9:
        return {}, False
    offset += 4 if flags & 1 else 0
    try:
        size = struct.unpack_from(">I", packet, offset)[0]
        body = packet[offset + 4:]
        if len(body) != size or (packet[2] & 15) not in (0, 1):
            raise ValueError("payload")
        data = json.loads(gzip.decompress(body) if packet[2] & 15 else body)
        if not isinstance(data, dict):
            raise ValueError("payload")
        return data, bool(flags & 2)
    except (ValueError, OSError, EOFError, struct.error) as exc:
        raise RealtimeError("无法解析豆包语音识别结果。") from exc


class DoubaoTranscript:
    def __init__(self, emit):
        self.emit = emit
        self.final_end = -1
        self.index = 1

    def accept(self, data):
        result = data.get("result") or {}
        for part in result.get("utterances") or ():
            text = (part.get("text") or "").strip()
            end = part.get("end_time", -1)
            if not text or end <= self.final_end:
                continue
            final = part.get("definite") is True
            self.emit({"type": "conversation.item.input_audio_transcription.completed" if final else LOCAL_PREVIEW_EVENT,
                       "item_id": f"doubao-{self.index}", "transcript": text})
            if final:
                self.final_end = end
                self.index += 1
            else:
                break


async def run_doubao(key, frames, on_event, on_ready=lambda: None, *, connect=None):
    from uuid import uuid4
    from websockets.exceptions import ConnectionClosed, InvalidStatus
    if connect is None:
        from websockets.asyncio.client import connect

    headers = {"X-Api-Key": key, "X-Api-Resource-Id": "volc.seedasr.sauc.duration",
               "X-Api-Request-Id": str(uuid4())}
    request = {"user": {"uid": "koecue-swt"},
               "audio": {"format": "pcm", "codec": "raw", "rate": 16000, "bits": 16, "channel": 1},
               "request": {"model_name": "bigmodel", "show_utterances": True, "enable_nonstream": True,
                           "enable_punc": True, "enable_itn": True}}
    transcript = DoubaoTranscript(on_event)

    try:
        async with connect("wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async",
                           additional_headers=headers, open_timeout=8, close_timeout=2) as socket:
            await socket.send(_doubao_packet(1, json.dumps(request).encode(), json_payload=True))
            first, done = _doubao_response(await asyncio.wait_for(socket.recv(), 8))
            transcript.accept(first)
            if done:
                raise RealtimeError("豆包在开始采音前结束了连接。")
            on_ready()

            async def send():
                pending = bytearray()
                async with aclosing(frames):
                    async for pcm in frames:
                        pending.extend(pcm)
                        while len(pending) >= 6400:
                            await socket.send(_doubao_packet(2, bytes(pending[:6400])))
                            del pending[:6400]
                await socket.send(_doubao_packet(2, bytes(pending), final=True))

            sender = asyncio.create_task(send())
            try:
                while True:
                    if sender.done():
                        sender.result()
                    incoming = asyncio.create_task(socket.recv())
                    try:
                        if not sender.done():
                            await asyncio.wait((incoming, sender), return_when=asyncio.FIRST_COMPLETED)
                            if sender.done():
                                sender.result()
                        packet = await asyncio.wait_for(incoming, 8) if sender.done() else await incoming
                    finally:
                        if not incoming.done():
                            incoming.cancel()
                            await asyncio.gather(incoming, return_exceptions=True)
                    data, done = _doubao_response(packet)
                    transcript.accept(data)
                    if done:
                        return
            finally:
                sender.cancel()
                await asyncio.gather(sender, return_exceptions=True)
    except InvalidStatus as exc:
        raise RealtimeError(f"豆包连接失败（HTTP {exc.response.status_code}）；请核对语音 Key 和流式识别 2.0 开通状态。") from exc
    except (OSError, TimeoutError, ConnectionClosed) as exc:
        raise RealtimeError("豆包语音连接中断或超时，请检查网络后重试。") from exc


class DoubaoPCM:
    def __init__(self, rate, channels):
        import numpy as np
        from soxr import ResampleStream
        self.np = np
        self.channels = channels
        self.resample = ResampleStream(rate, 16000, 1, dtype="float32")

    def push(self, pcm):
        np = self.np
        mono = np.frombuffer(pcm, "<i2").reshape(-1, self.channels).mean(axis=1, dtype=np.float32)
        samples = self.resample.resample_chunk(mono)
        return np.clip(np.rint(samples), -32768, 32767).astype("<i2").tobytes()
