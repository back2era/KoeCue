"""Optional local Japanese speech recognition using the multilingual Whisper base model."""
import argparse
import asyncio
from contextlib import aclosing
import os

from .audio import AudioError
from .profiles import app_directory

MODEL_REPO = "Systran/faster-whisper-base"
MODEL_REVISION = "a80717a3a48b1b28aa687bca146cb7301feae1b1"
MODEL_FILES = ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt")


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
    """Keep audio collection independent of CPU inference and bound queued turns."""
    turns = asyncio.Queue(maxsize=2)
    ending = False

    def end_session():
        nonlocal ending
        if not ending:
            ending = True
            on_ending()

    async def collect():
        pending = bytearray()
        async with aclosing(frames):
            try:
                async for command in frames:
                    if command is not None:
                        pending.extend(command)
                    elif pending:
                        try:
                            turns.put_nowait(bytes(pending))
                        except asyncio.QueueFull as exc:
                            raise AudioError("本机语音识别跟不上采集速度，已停止监听。") from exc
                        pending.clear()
            except BaseException:
                end_session()
                raise
        await turns.put(None)

    async def recognize():
        sequence = 0
        previous = None
        while (pcm := await turns.get()) is not None:
            text = await asyncio.to_thread(decode, pcm)
            if ending:
                return
            if not text:
                continue
            sequence += 1
            item = f"local-{sequence}"
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
