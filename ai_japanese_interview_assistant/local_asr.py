"""Optional local Japanese speech recognition using the multilingual Whisper base model."""
import argparse
import asyncio
from collections import deque
from contextlib import aclosing
import os

from .audio import AudioError
from .profiles import app_directory

MODEL_REPO = "Systran/faster-whisper-base"
MODEL_REVISION = "a80717a3a48b1b28aa687bca146cb7301feae1b1"
MODEL_FILES = ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt")
FIRST_PREVIEW_BYTES = 48000  # One second of 24 kHz mono PCM16.
PREVIEW_STEP_BYTES = 57600


class LocalAsrError(Exception):
    """Safe, actionable local-model error."""


def model_directory():
    return app_directory() / "models" / "faster-whisper-base"


def load_decoder():
    try:
        from faster_whisper import WhisperModel
    except (ImportError, OSError) as exc:
        raise LocalAsrError("本地语音组件不可用。请按 README 安装 requirements-local.txt。") from exc

    directory = model_directory()
    if not all((directory / name).is_file() for name in MODEL_FILES):
        raise LocalAsrError("尚未安装本地日语模型。请按 README 下载模型。")

    import numpy as np
    import soxr

    try:
        model = WhisperModel(str(directory), device="cpu", compute_type="int8",
                             cpu_threads=min(4, os.cpu_count() or 1), local_files_only=True)
    except (RuntimeError, ValueError, OSError) as exc:
        raise LocalAsrError("无法加载本地日语模型。请按 README 检查安装。") from exc

    def decode(pcm):
        samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
        samples = soxr.resample(samples, 24000, 16000)
        segments, _ = model.transcribe(samples, language="ja", beam_size=1, temperature=0.0,
                                       condition_on_previous_text=False, without_timestamps=True)
        return "".join(segment.text for segment in segments).strip()

    return decode


async def run_local_transcription(decode, frames, on_event, *, on_ending=lambda: None):
    """Decode growing speech snapshots and prioritize final turns over previews."""
    turns = deque()
    ready = asyncio.Event()
    preview = None
    active_item = None
    input_ended = False
    ending = False

    def end_session():
        nonlocal ending
        if not ending:
            ending = True
            on_ending()

    async def collect():
        nonlocal active_item, preview, input_ended
        pending = bytearray()
        sequence = 0
        next_preview = FIRST_PREVIEW_BYTES
        async with aclosing(frames):
            try:
                async for command in frames:
                    if command is not None:
                        if active_item is None:
                            sequence += 1
                            active_item = f"local-{sequence}"
                        pending.extend(command)
                        if len(pending) >= next_preview:
                            preview = (active_item, bytes(pending))
                            next_preview = len(pending) + PREVIEW_STEP_BYTES
                            ready.set()
                    elif pending:
                        if len(turns) >= 2:
                            raise AudioError("本机语音识别跟不上采集速度，已停止监听。")
                        turns.append((active_item, bytes(pending)))
                        active_item = preview = None
                        pending.clear()
                        next_preview = FIRST_PREVIEW_BYTES
                        ready.set()
            except BaseException:
                end_session()
                raise
        active_item = preview = None
        input_ended = True
        ready.set()

    async def recognize():
        nonlocal preview
        previous = None
        shown_item = None
        shown_text = ""
        while not ending:
            await ready.wait()
            final = bool(turns)
            if final:
                item, pcm = turns.popleft()
            elif preview is not None:
                item, pcm = preview
                preview = None
            elif input_ended:
                return
            else:
                ready.clear()
                continue
            text = await asyncio.to_thread(decode, pcm)
            if ending:
                return
            if not final:
                if item == active_item and text and (item, text) != (shown_item, shown_text):
                    shown_item, shown_text = item, text
                    on_event({"type": "conversation.item.input_audio_transcription.revised", "item_id": item, "transcript": text})
                continue
            if text or shown_item == item:
                on_event({"type": "input_audio_buffer.committed", "item_id": item, "previous_item_id": previous})
                on_event({"type": "conversation.item.input_audio_transcription.completed", "item_id": item, "transcript": text})
                previous = item

    tasks = (asyncio.create_task(collect()), asyncio.create_task(recognize()))
    try:
        await asyncio.gather(*tasks)
    finally:
        end_session()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download-model", action="store_true", required=True)
    parser.parse_args()
    try:
        from huggingface_hub import snapshot_download

        snapshot_download(MODEL_REPO, revision=MODEL_REVISION, allow_patterns=list(MODEL_FILES),
                          local_dir=model_directory(), token=False)
        load_decoder()
    except Exception as exc:
        parser.exit(1, f"本地模型安装失败（{type(exc).__name__}）。请检查依赖和下载网络。\n")
    print("本地日语语音模型安装并加载成功。")


if __name__ == "__main__":
    main()
