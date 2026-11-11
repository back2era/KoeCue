"""Optional local Japanese speech recognition using the multilingual Whisper base model."""
import argparse
import asyncio
from collections import deque
from contextlib import aclosing
import os

from .audio import AudioError
from .profiles import app_directory
from .transcription import LOCAL_PREVIEW_EVENT

MODEL_REPO = "Systran/faster-whisper-base"
MODEL_REVISION = "a80717a3a48b1b28aa687bca146cb7301feae1b1"
MODEL_FILES = ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt")
PREVIEW_STRIDE = 57600  # 1.2 seconds of 24 kHz PCM16 mono
MAX_QUEUED_TURNS = 2
INTERVIEW_HOTWORDS = "自己紹介、志望動機、長所、短所、強み、弱み、職務経験、担当業務、入社後、チーム開発"


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

    def decode(pcm, *, preview=False):
        samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
        samples = soxr.resample(samples, 24000, 16000)
        segments, _ = model.transcribe(
            samples, language="ja", beam_size=1 if preview else 3, temperature=0.0,
            condition_on_previous_text=False, without_timestamps=True,
            hotwords=None if preview else INTERVIEW_HOTWORDS,
        )
        return "".join(segment.text for segment in segments).strip()

    return decode


async def run_local_transcription(decode, frames, on_event, *, preview_decode=None, on_ending=lambda: None):
    """Collect audio independently and prioritize committed turns on one decoder lane."""
    preview_decode = decode if preview_decode is None else preview_decode
    turns = deque()
    available = asyncio.Event()
    pending = bytearray()
    sequence = 1
    preview_at = PREVIEW_STRIDE
    accepted_preview = ""
    input_finished = False
    ending = False

    def end_session():
        nonlocal ending
        if not ending:
            ending = True
            on_ending()

    async def collect():
        nonlocal sequence, preview_at, accepted_preview, input_finished
        try:
            async with aclosing(frames):
                async for command in frames:
                    if command is not None:
                        pending.extend(command)
                        if len(pending) >= preview_at:
                            available.set()
                    elif pending:
                        if len(turns) >= MAX_QUEUED_TURNS:
                            raise AudioError("本机语音识别跟不上采集速度，已停止监听。")
                        turns.append((sequence, bytes(pending), bool(accepted_preview)))
                        pending.clear()
                        sequence += 1
                        preview_at = PREVIEW_STRIDE
                        accepted_preview = ""
                        available.set()
        except BaseException:
            end_session()
            raise
        input_finished = True
        available.set()

    async def recognize():
        nonlocal preview_at, accepted_preview
        previous = None
        while not ending:
            if turns:
                turn, pcm, had_preview = turns.popleft()
                text = await asyncio.to_thread(decode, pcm)
                if ending:
                    return
                if text or had_preview:
                    item = f"local-{turn}"
                    on_event({"type": "input_audio_buffer.committed", "item_id": item,
                              "previous_item_id": previous})
                    on_event({"type": "conversation.item.input_audio_transcription.completed", "item_id": item,
                              "transcript": text})
                    previous = item
            elif input_finished:
                return
            elif len(pending) >= preview_at:
                # Snapshot the current utterance only when the decoder is free. Later audio
                # replaces any unstarted preview, while a commit supersedes an in-flight one.
                turn = sequence
                pcm = bytes(pending)
                preview_at = len(pcm) + PREVIEW_STRIDE
                text = await asyncio.to_thread(preview_decode, pcm)
                if ending or input_finished or turn != sequence:
                    continue
                # Whisper often inserts terminal punctuation while the speaker is still talking.
                text = text.rstrip("。！？、…,.!? \t")
                if text and text != accepted_preview:
                    accepted_preview = text
                    on_event({"type": LOCAL_PREVIEW_EVENT, "item_id": f"local-{turn}", "transcript": text})
            else:
                available.clear()
                await available.wait()

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
