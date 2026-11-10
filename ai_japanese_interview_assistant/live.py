"""Qt worker coordinating live audio, the Realtime socket, and text jobs."""
import asyncio
from time import monotonic

from PySide6.QtCore import QThread, Signal

from .audio import AudioBuffer, AudioError, capture
from .services import TextService, client_for, error_message
from .transcription import AudioProcessor, RealtimeError, TranscriptBook, run_transcription


class LiveWorker(QThread):
    status = Signal(str, str)
    transcript = Signal(object)
    order = Signal(object)
    translation = Signal(object, str, str)

    def __init__(self, generation, device, key, parent=None):
        super().__init__(parent)
        self.generation = generation
        self.device = device
        self.key = key
        self.buffer = AudioBuffer()
        self.book = TranscriptBook()
        self.jobs = {}
        self.loop = None
        self.runner = None

    def stop(self):
        self.requestInterruption()
        self.buffer.close()
        self.dispatch(self._cancel)

    def _cancel(self):
        if self.runner is not None:
            self.runner.cancel()

    def dispatch(self, callback, *args):
        loop = self.loop
        if loop is not None:
            try:
                loop.call_soon_threadsafe(callback, *args)
            except RuntimeError:
                pass

    def run(self):
        try:
            asyncio.run(self._main())
        except asyncio.CancelledError:
            pass
        except (AudioError, RealtimeError) as exc:
            self.status.emit("asr", str(exc))
        except Exception as exc:
            self.status.emit("asr", error_message(exc))
        finally:
            self.buffer.close()
            self.key = ""
            self.loop = None

    async def _main(self):
        self.loop = asyncio.get_running_loop()
        self.runner = asyncio.current_task()
        if self.isInterruptionRequested():
            return
        async with client_for(self.key) as client:
            self.service = TextService(client)
            try:
                self.status.emit("asr", "正在连接转写服务…")
                await run_transcription(
                    self.key, self.audio_commands(), self.on_event,
                    lambda: self.status.emit("asr", "API 已连接，正在打开音频…"),
                )
            finally:
                for task in self.jobs.values():
                    task.cancel()
                await asyncio.gather(*self.jobs.values(), return_exceptions=True)

    async def audio_commands(self):
        processor = AudioProcessor(self.device.rate, self.device.channels)
        with capture(self.device, self.buffer) as stream:
            if self.isInterruptionRequested():
                return
            self.status.emit("asr", "转写已连接 · 正在监听")
            last_frame = monotonic()
            flushed = False
            while not self.isInterruptionRequested():
                pcm = self.buffer.pop()
                if pcm is None:
                    if not stream.is_active():
                        raise AudioError("设备已断开。停止后请刷新设备列表。")
                    if not flushed and monotonic() - last_frame >= 0.6:
                        for command in processor.finish_turn():
                            yield command
                        flushed = True
                    await asyncio.sleep(0.01)
                    continue
                last_frame = monotonic()
                flushed = False
                for command in processor.push(pcm):
                    if self.isInterruptionRequested():
                        return
                    yield command

    def on_event(self, event):
        kind = event.get("type", "")
        part = self.book.apply(event)
        if part is None:
            return
        row_id = (self.generation, part.item_id)
        self.transcript.emit((row_id, part))
        if kind == "input_audio_buffer.committed":
            self.order.emit(tuple((self.generation, part.item_id) for part in self.book.parts))
        elif kind.endswith("transcription.completed") and part.text:
            self.start_translation(row_id, part.text)

    def start_translation(self, row_id, text):
        job_id = ("translation", row_id)
        if self.isInterruptionRequested() or job_id in self.jobs:
            return
        if len(self.jobs) >= 8:
            self.translation.emit(row_id, "", "队列繁忙，可以重试")
            return
        task = asyncio.create_task(self.translate(row_id, text))
        self.jobs[job_id] = task
        task.add_done_callback(lambda task: self.jobs.pop(job_id, None))

    async def translate(self, row_id, text):
        result = ""
        self.translation.emit(row_id, result, "翻译中")
        self.status.emit("text", "正在翻译…")
        try:
            async for delta in self.service.translate(text):
                result += delta
                self.translation.emit(row_id, result, "翻译中")
        except asyncio.CancelledError:
            self.translation.emit(row_id, result, "翻译已取消")
            raise
        except Exception as exc:
            self.translation.emit(row_id, result, "翻译失败")
            self.status.emit("text", error_message(exc))
        else:
            self.translation.emit(row_id, result, "已翻译")
            self.status.emit("text", "文本 API 已连接")
