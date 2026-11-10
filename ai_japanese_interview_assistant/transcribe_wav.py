"""Explicit opt-in Realtime check with an authorized PCM WAV."""
import argparse
import asyncio
import os
from time import monotonic
import wave

from .transcription import AudioProcessor, TranscriptBook, run_transcription


async def stream_wav(path, key, on_event, on_start):
    with wave.open(path, "rb") as wav:
        if wav.getsampwidth() != 2 or wav.getcomptype() != "NONE":
            raise ValueError("Expected 16-bit PCM WAV")
        processor = AudioProcessor(wav.getframerate(), wav.getnchannels())
        async def frames():
            started = monotonic()
            on_start(started)
            elapsed = 0
            while chunk := wav.readframes(round(wav.getframerate() * 0.02)):
                elapsed += len(chunk) / (2 * wav.getnchannels() * wav.getframerate())
                await asyncio.sleep(max(0, started + elapsed - monotonic()))
                for command in processor.push(chunk):
                    yield command
            for command in processor.push(b"", last=True) + processor.finish_turn():
                yield command

        await run_transcription(key, frames(), on_event)


async def replay(path, key, show_text):
    book = TranscriptBook()
    started = 0.0
    first_delta = None

    def on_start(timestamp):
        nonlocal started
        started = timestamp

    def on_event(event):
        nonlocal first_delta
        part = book.apply(event)
        if first_delta is None and event.get("type", "").endswith("transcription.delta"):
            first_delta = monotonic() - started
        if show_text and part and part.final and event.get("type", "").endswith("transcription.completed"):
            print(part.text)

    await stream_wav(path, key, on_event, on_start)
    finals = sum(bool(part.final and part.text) for part in book.parts)
    print(f"final_segments={finals} first_delta_seconds={first_delta}")
    return 0 if finals else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path")
    parser.add_argument("--send-authorized-audio", action="store_true", required=True)
    parser.add_argument("--show-text", action="store_true")
    args = parser.parse_args()
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        parser.error("Set OPENAI_API_KEY in this process before running the live check.")
    try:
        return asyncio.run(replay(args.path, key, args.show_text))
    except Exception as exc:
        parser.exit(1, f"Live check failed ({type(exc).__name__}).\n")


if __name__ == "__main__":
    raise SystemExit(main())
