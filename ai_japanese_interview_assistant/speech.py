"""Cloud ASR adapters that emit the existing transcript preview and final events."""
import asyncio
from contextlib import aclosing, asynccontextmanager
from dataclasses import dataclass
import gzip
from io import BytesIO
import json
from uuid import uuid4
import wave

import httpx
from websockets.asyncio.client import connect as websocket_connect
from websockets.exceptions import InvalidStatus, WebSocketException

from .config import DEEPSEEK, OPENAI, QWEN, Provider, REALTIME_MODEL
from .local_models import MANAGED_MODELS
from .transcription import LOCAL_PREVIEW_EVENT, RealtimeError


QWEN_ASR_URL = "wss://dashscope.aliyuncs.com/api-ws/v1/inference"
DOUBAO = Provider(
    "豆包语音 · 火山引擎", "DOUBAO_ASR_API_KEY",
    "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async", "volc.seedasr.sauc.duration",
)
DEEPSEEK_ASR_URL = "https://api.deepseek.com/v1/tools/asr"
COMPLETE_EVENT = "conversation.item.input_audio_transcription.completed"


@dataclass(frozen=True)
class SpeechModel:
    label: str
    provider: Provider | None
    model: str = ""
    continuous: bool = False
    languages: tuple[str, ...] = ("zh", "ja", "en")


SPEECH_MODELS = {
    "openai": SpeechModel("OpenAI · GPT-Live-Transcribe", OPENAI, REALTIME_MODEL),
    "doubao": SpeechModel("豆包 2.0 · 中英实时", DOUBAO, DOUBAO.model, True, ("zh", "en")),
    "qwen-3.1": SpeechModel("千问 Qwen-Audio 3.1 · 实时", QWEN, "qwen-audio-3.1-asr-flash-streaming", True),
    "qwen-3.0": SpeechModel("千问 Qwen-Audio 3.0 · 实时", QWEN, "qwen-audio-3.0-asr-flash-streaming", True),
    "deepseek": SpeechModel("DeepSeek · 停顿后转写", DEEPSEEK),
    **{code: SpeechModel(variant.label, None) for code, variant in MANAGED_MODELS.items()},
}


def transcript(on_event, item_id, text, *, final=False):
    if isinstance(text, str) and (final or text.strip()):
        on_event({"type": COMPLETE_EVENT if final else LOCAL_PREVIEW_EVENT,
                  "item_id": item_id, "transcript": text.strip()})


def rejected(provider, status):
    if status in (401, 403):
        return RealtimeError(f"{provider} 转写鉴权失败，请检查 API Key 和服务权限。")
    if status == 429:
        return RealtimeError(f"{provider} 转写已限流，请检查用量或稍后重试。")
    return RealtimeError(f"{provider} 转写请求失败，请检查服务配置和额度。")


@asynccontextmanager
async def connected_socket(connect, url, headers, provider):
    try:
        async with connect(url, additional_headers=headers, open_timeout=10, close_timeout=1,
                           ping_interval=10, ping_timeout=5, max_queue=32) as socket:
            yield socket
    except InvalidStatus as exc:
        raise rejected(provider, exc.response.status_code) from exc
    except TimeoutError as exc:
        raise RealtimeError(f"{provider} 转写连接超时。") from exc
    except (WebSocketException, OSError) as exc:
        raise RealtimeError(f"{provider} 转写连接已断开，请检查网络后重试。") from exc
    except (ValueError, AttributeError, TypeError, EOFError) as exc:
        raise RealtimeError(f"{provider} 返回了无法读取的转写消息。") from exc


async def exchange_audio(frames, packet_size, send_audio, finish, receive):
    """Close input on disconnect and wait for a bounded final response when input ends."""

    input_finished = asyncio.Event()

    async def send():
        pending = bytearray()
        async with aclosing(frames):
            async for frame in frames:
                pending.extend(frame)
                while len(pending) >= packet_size:
                    await asyncio.wait_for(send_audio(bytes(pending[:packet_size])), 4)
                    del pending[:packet_size]
        input_finished.set()
        await asyncio.wait_for(finish(bytes(pending)), 4)

    sending = asyncio.create_task(send())
    receiving = asyncio.create_task(receive())
    try:
        done, _ = await asyncio.wait((sending, receiving), return_when=asyncio.FIRST_COMPLETED)
        if sending in done:
            sending.result()
            await asyncio.wait_for(receiving, 12)
        else:
            receiving.result()
            if not input_finished.is_set():
                raise RealtimeError("转写服务已结束会话，请重新开始监听。")
    finally:
        sending.cancel()
        receiving.cancel()
        await asyncio.gather(sending, receiving, return_exceptions=True)


async def run_qwen(key, frames, on_event, on_ready, *, model, language, connect=websocket_connect):
    headers = {"Authorization": f"Bearer {key}"}
    task = uuid4().hex

    def request(action, **payload):
        return json.dumps({"header": {"action": action, "task_id": task, "streaming": "duplex"},
                           "payload": {"input": {}, **payload}})

    async with connected_socket(connect, QWEN_ASR_URL, headers, "千问") as socket:
        async def receive_message():
            message = json.loads(await socket.recv())
            header = message.get("header", {})
            kind = header.get("event")
            if kind == "task-failed":
                raise RealtimeError("千问转写失败，请检查百炼北京地域的 Key、模型权限及额度。")
            return kind, message.get("payload", {})

        await socket.send(request(
            "run-task", task_group="audio", task="asr", function="recognition", model=model.model,
            parameters={"format": "pcm", "sample_rate": 16000, "language_hints": [language],
                        "max_sentence_silence": 600, "heartbeat": True},
        ))
        async with asyncio.timeout(10):
            kind, _ = await receive_message()
            if kind != "task-started":
                raise RealtimeError("千问转写未能启动。")
        on_ready()

        async def finish(tail):
            if tail:
                await socket.send(tail)
            await socket.send(request("finish-task"))

        async def receive():
            while True:
                kind, payload = await receive_message()
                if kind == "task-finished":
                    return
                if kind != "result-generated":
                    continue
                sentence = payload.get("output", {}).get("sentence") or {}
                item = sentence.get("sentence_id")
                if isinstance(item, int) and item > 0 and not sentence.get("heartbeat"):
                    transcript(on_event, f"qwen-{item}", sentence.get("text"),
                               final=sentence.get("sentence_end") is True)

        await exchange_audio(frames, 3200, socket.send, finish, receive)


def doubao_packet(kind, payload, *, final=False):
    compression = gzip.compress(payload)
    flags = 2 if final else 0
    encoding = 0x11 if kind == 1 else 0x01
    return bytes((0x11, kind << 4 | flags, encoding, 0)) + len(compression).to_bytes(4, "big") + compression


def doubao_response(packet):
    if not isinstance(packet, bytes) or len(packet) < 8 or packet[0] >> 4 != 1:
        raise RealtimeError("豆包返回了无法读取的转写消息。")
    offset = (packet[0] & 15) * 4
    kind, flags = packet[1] >> 4, packet[1] & 15
    if kind == 15:
        raise RealtimeError("豆包转写失败，请检查火山引擎语音 Key、服务权限及额度。")
    if kind != 9 or offset < 4 or packet[2] >> 4 != 1:
        raise RealtimeError("豆包返回了不支持的转写消息。")
    if flags & 1:
        offset += 4
    size = int.from_bytes(packet[offset:offset + 4], "big")
    body = packet[offset + 4:]
    if not size or size != len(body):
        raise RealtimeError("豆包转写消息不完整。")
    if packet[2] & 15 == 1:
        # The WebSocket limit covers the compressed frame. Bound its expanded payload too.
        with gzip.GzipFile(fileobj=BytesIO(body)) as source:
            body = source.read(2_000_001)
        if len(body) > 2_000_000:
            raise RealtimeError("豆包转写消息超出大小限制。")
    return json.loads(body), bool(flags & 2)


class DoubaoResults:
    """Convert cumulative two-pass output to individual stable caption rows."""

    def __init__(self, on_event):
        self.on_event = on_event
        self.completed = set()
        self.confirmed = ""

    def accept(self, response):
        results = response.get("result") or {}
        if isinstance(results, dict):
            results = [results]
        for result in results:
            partial = None
            for utterance in result.get("utterances") or ():
                text = utterance.get("text")
                if not isinstance(text, str) or not text.strip():
                    continue
                start, end = utterance.get("start_time"), utterance.get("end_time")
                if utterance.get("definite") is True and isinstance(end, int):
                    span = (start, end)
                    if span not in self.completed:
                        self.completed.add(span)
                        self.confirmed += text
                        transcript(self.on_event, f"doubao-{len(self.completed)}", text, final=True)
                    partial = None
                else:
                    partial = text
            if partial is None:
                total = result.get("text", "")
                if isinstance(total, str) and total.startswith(self.confirmed):
                    partial = total[len(self.confirmed):]
            transcript(self.on_event, f"doubao-{len(self.completed) + 1}", partial)


async def run_doubao(key, frames, on_event, on_ready, *, connect=websocket_connect):
    session_id = str(uuid4())
    headers = {"X-Api-Key": key, "X-Api-Resource-Id": DOUBAO.model, "X-Api-Connect-Id": session_id,
               "X-Api-Request-Id": session_id, "X-Api-Sequence": "-1"}
    request = {
        "user": {"uid": "koecue"},
        "audio": {"format": "pcm", "codec": "raw", "rate": 16000, "bits": 16, "channel": 1},
        "request": {"model_name": "bigmodel", "show_utterances": True,
                    "enable_nonstream": True, "end_window_size": 600},
    }
    results = DoubaoResults(on_event)

    async with connected_socket(connect, DOUBAO.url, headers, "豆包") as socket:
        await socket.send(doubao_packet(1, json.dumps(request).encode()))
        async with asyncio.timeout(10):
            _, finished = doubao_response(await socket.recv())
            if finished:
                raise RealtimeError("豆包转写未能启动。")
        on_ready()

        async def send_audio(frame):
            await socket.send(doubao_packet(2, frame))

        async def finish(tail):
            await socket.send(doubao_packet(2, tail, final=True))

        async def receive():
            while True:
                response, finished = doubao_response(await socket.recv())
                results.accept(response)
                if finished:
                    return

        await exchange_audio(frames, 6400, send_audio, finish, receive)


async def run_deepseek(key, frames, on_event, client):
    """Upload only VAD-committed turns. Keep capturing while the last turn is in flight."""
    pending = asyncio.Queue(maxsize=2)

    async def collect():
        turn = bytearray()
        async with aclosing(frames):
            async for frame in frames:
                if frame is not None:
                    turn.extend(frame)
                elif turn:
                    if pending.full():
                        raise RealtimeError("DeepSeek 转写跟不上采集速度，已停止监听。")
                    pending.put_nowait(bytes(turn))
                    turn.clear()
        await pending.put(None)

    async def recognize():
        count = 0
        while (turn := await pending.get()) is not None:
            audio = BytesIO()
            with wave.open(audio, "wb") as wav:
                wav.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
                wav.writeframes(turn)
            try:
                response = await client.post(
                    DEEPSEEK_ASR_URL, headers={"Authorization": f"Bearer {key}"},
                    files={"file": ("utterance.wav", audio.getvalue(), "audio/wav")},
                )
            except httpx.TimeoutException as exc:
                raise RealtimeError("DeepSeek 转写超时。") from exc
            except httpx.RequestError as exc:
                raise RealtimeError("DeepSeek 转写连接失败，请检查网络。") from exc
            if not response.is_success:
                raise rejected("DeepSeek", response.status_code)
            try:
                text = response.json()["text"]
                if not isinstance(text, str):
                    raise TypeError
            except (ValueError, KeyError, TypeError) as exc:
                raise RealtimeError("DeepSeek 返回了无法读取的转写消息。") from exc
            count += 1
            transcript(on_event, f"deepseek-{count}", text, final=True)

    tasks = (asyncio.create_task(collect()), asyncio.create_task(recognize()))
    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
