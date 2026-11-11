"""Qt worker coordinating live audio, speech recognition, and text jobs."""
import asyncio
from functools import partial
from threading import Event
from time import monotonic

from PySide6.QtCore import QThread, Signal

from .answer_format import DEFAULT_ANSWER_LEVEL
from .audio import AudioBuffer, AudioError, capture, check_topology
from .config import OPENAI
from .interview import InterviewService
from .local_asr import LocalAsrError, load_decoder, run_local_transcription
from .personal import PersonalInfo
from .services import TextService, client_for, error_message
from .telemetry import Event as LogEvent, record
from .transcription import AudioProcessor, LOCAL_PREVIEW_EVENT, RealtimeError, TranscriptBook, run_transcription


ANSWER_PENDING = "正在生成建议…"
MAX_ACTIVE_TEXT_JOBS = 8
MAX_WAITING_ANSWERS = 32


class LiveWorker(QThread):
    status = Signal(str, str)
    transcript = Signal(object)
    partial_transcript = Signal(object)
    order = Signal(object)
    translation = Signal(object, str, str)
    answer = Signal(object, object, str, bool)

    def __init__(self, generation, device, key, parent=None, *, session_id=0, auto_answer=False,
                 facts=(), personal_info=PersonalInfo(), provider=OPENAI, answer_level=DEFAULT_ANSWER_LEVEL):
        super().__init__(parent)
        self.generation = generation
        self.session_id = session_id
        self.device = device
        self.key = key
        self.provider = provider
        self.auto_answer = auto_answer
        self.answer_level = answer_level
        self.facts = facts
        self.personal_info = personal_info
        self.sharing_revoked = Event()
        self.buffer = AudioBuffer()
        self.book = TranscriptBook()
        self.jobs = {}
        self.waiting_answers = {}
        self.loop = None
        self.runner = None

    def stop(self):
        self.requestInterruption()
        self._clear_profile()
        self.buffer.close()
        self.dispatch(self._cancel)

    def revoke_profile(self):
        self._clear_profile()
        self.dispatch(self._revoke_profile)

    def _clear_profile(self):
        self.sharing_revoked.set()
        self.facts = ()
        self.personal_info = PersonalInfo()

    def _revoke_profile(self):
        self.waiting_answers.clear()
        for (kind, _), task in self.jobs.items():
            if kind == "answer":
                task.cancel()

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
        except AudioError as exc:
            record(LogEvent.AUDIO_ERROR)
            self.status.emit("audio", str(exc))
            self.status.emit("asr", "转写连接已关闭" if self.provider is OPENAI else "本地转写已停止")
        except RealtimeError as exc:
            record(LogEvent.API_ERROR)
            self.status.emit("asr", str(exc))
        except LocalAsrError as exc:
            self.status.emit("asr", str(exc))
        except Exception as exc:
            record(LogEvent.API_ERROR)
            self.status.emit("asr", error_message(exc))
        finally:
            self.buffer.close()
            self.key = ""
            self._clear_profile()
            self.loop = None

    async def _main(self):
        self.loop = asyncio.get_running_loop()
        self.runner = asyncio.current_task()
        if self.isInterruptionRequested():
            return
        async with client_for(self.key, self.provider) as client:
            self.service = TextService(client, self.provider)
            self.interview = InterviewService(self.service)
            started = monotonic()
            try:
                if self.provider is OPENAI:
                    self.status.emit("asr", "正在连接转写服务…")

                    def connected():
                        record(LogEvent.REALTIME_READY, monotonic() - started)
                        self.status.emit("asr", "转写 API 已连接")

                    await run_transcription(
                        self.key, self.audio_commands(), self.on_event, connected,
                        on_ending=self.stop_text_and_audio,
                    )
                else:
                    self.status.emit("asr", "正在加载本地日语模型…")
                    decoder = await asyncio.to_thread(load_decoder)
                    if self.isInterruptionRequested():
                        return
                    self.status.emit("asr", "本地转写已就绪，正在接收语音")
                    await run_local_transcription(
                        decoder, self.audio_commands(), self.on_event,
                        preview_decode=partial(decoder, preview=True), on_ending=self.stop_text_and_audio,
                    )
            finally:
                self.stop_text_and_audio()
                await asyncio.gather(*self.jobs.values(), return_exceptions=True)
                if self.provider is OPENAI:
                    record(LogEvent.REALTIME_END, monotonic() - started)

    def stop_text_and_audio(self):
        self.requestInterruption()
        self._clear_profile()
        self.buffer.close()
        self.waiting_answers.clear()
        for task in self.jobs.values():
            task.cancel()

    async def audio_commands(self):
        self.status.emit("audio", "正在打开音频设备…")
        processor = AudioProcessor(self.device.rate, self.device.channels)
        with capture(self.device, self.buffer) as stream:
            if self.isInterruptionRequested():
                return
            record(LogEvent.AUDIO_OPEN)
            self.status.emit("audio", "音频 · 正在监听")
            last_frame = monotonic()
            next_topology = last_frame + 1
            flushed = False
            while not self.isInterruptionRequested():
                if monotonic() >= next_topology:
                    check_topology(self.device)
                    next_topology = monotonic() + 1
                pcm = self.buffer.pop()
                if pcm is None:
                    if not stream.is_active():
                        raise AudioError("设备已断开。停止后请刷新设备列表。")
                    if not flushed and monotonic() - last_frame >= 0.6:
                        for command in processor.finish_turn():
                            yield command
                        flushed = True
                        self.status.emit("audio", "音频 · 当前没有输入帧")
                    await asyncio.sleep(0.01)
                    continue
                last_frame = monotonic()
                if flushed:
                    self.status.emit("audio", "音频 · 正在监听")
                flushed = False
                for command in processor.push(pcm):
                    if self.isInterruptionRequested():
                        return
                    yield command

    def on_event(self, event):
        if self.isInterruptionRequested():
            return
        kind = event.get("type", "")
        part = self.book.apply(event)
        if part is None:
            return
        row_id = (self.session_id, self.generation, part.item_id)
        is_preview = kind == LOCAL_PREVIEW_EVENT or (
            kind == "conversation.item.input_audio_transcription.delta" and event.get("delta")
        )
        if is_preview and part.text and part.item_id == self.book.latest_item_id:
            self.partial_transcript.emit((row_id, part))
        if kind != "input_audio_buffer.committed" and (part.final or part.failed):
            self.transcript.emit((row_id, part))
        if kind == "input_audio_buffer.committed" or part.final or part.failed:
            self.order.emit(tuple((self.session_id, self.generation, entry.item_id) for entry in self.book.parts))
        if kind.endswith("transcription.completed") and part.text:
            self.start_translation(row_id, part.text)
            if self.auto_answer:
                self.start_answer(row_id, part.text, True)

    def start_translation(self, row_id, text):
        job_id = ("translation", row_id)
        if len(self.jobs) >= MAX_ACTIVE_TEXT_JOBS:
            self.translation.emit(row_id, "", "队列繁忙，可以重试")
            return
        self.start_job(job_id, self.translate, row_id, text)

    def start_job(self, job_id, handler, *args):
        if self.isInterruptionRequested() or job_id in self.jobs:
            return
        task = asyncio.create_task(handler(*args))
        self.jobs[job_id] = task
        task.add_done_callback(lambda task: self.finish_text_job(job_id))

    def finish_text_job(self, job_id):
        self.jobs.pop(job_id, None)
        if self.waiting_answers and not self.isInterruptionRequested() and len(self.jobs) < MAX_ACTIVE_TEXT_JOBS:
            row_id = next(iter(self.waiting_answers))
            text, automatic = self.waiting_answers.pop(row_id)
            self.start_job(("answer", row_id), self.suggest, row_id, text, automatic)

    async def translate(self, row_id, text):
        result = ""
        started = monotonic()
        self.translation.emit(row_id, result, "翻译中")
        self.status.emit("text", "正在翻译…")
        try:
            if self.isInterruptionRequested():
                raise asyncio.CancelledError
            async for delta in self.service.translate(text):
                result += delta
                self.translation.emit(row_id, result, "翻译中")
        except asyncio.CancelledError:
            self.translation.emit(row_id, result, "翻译已取消")
            raise
        except Exception as exc:
            record(LogEvent.API_ERROR)
            self.translation.emit(row_id, result, "翻译失败")
            self.status.emit("text", error_message(exc))
        else:
            record(LogEvent.TRANSLATION_READY, monotonic() - started)
            self.translation.emit(row_id, result, "已翻译")
            self.status.emit("text", "文本 API 已连接")

    def start_answer(self, row_id, text, automatic=False):
        job_id = ("answer", row_id)
        if self.isInterruptionRequested() or job_id in self.jobs or row_id in self.waiting_answers:
            return
        if len(self.jobs) < MAX_ACTIVE_TEXT_JOBS and not self.waiting_answers:
            self.start_job(job_id, self.suggest, row_id, text, automatic)
        elif len(self.waiting_answers) < MAX_WAITING_ANSWERS:
            self.waiting_answers[row_id] = (text, automatic)
            self.answer.emit(row_id, None, ANSWER_PENDING, False)
        else:
            self.answer.emit(row_id, None, "回答队列繁忙，可以重试", False)

    async def suggest(self, row_id, text, automatic):
        facts, personal_info = self.facts, self.personal_info
        level = self.answer_level
        if self.sharing_revoked.is_set():
            facts, personal_info = (), PersonalInfo()
        scoped = bool(facts or personal_info)
        started = monotonic()

        def allowed():
            return not self.isInterruptionRequested() and (not scoped or not self.sharing_revoked.is_set())

        self.answer.emit(row_id, None, ANSWER_PENDING, scoped)
        try:
            answer = await self.interview.suggest(
                text, automatic=automatic, facts=facts, personal_info=personal_info, level=level, allowed=allowed,
            )
            if not allowed():
                raise asyncio.CancelledError
        except asyncio.CancelledError:
            self.answer.emit(row_id, None, "回答已取消", scoped)
            raise
        except Exception as exc:
            self.answer.emit(row_id, None, error_message(exc), scoped)
        else:
            record(LogEvent.ANSWER_READY, monotonic() - started)
            self.answer.emit(row_id, answer, "建议已生成", scoped)
            if not allowed():
                return
            try:
                annotated = await self.interview.annotate_answer(answer)
            except Exception:
                record(LogEvent.API_ERROR)
                return
            if allowed() and annotated.annotations:
                self.answer.emit(row_id, annotated, "建议已生成", scoped)
