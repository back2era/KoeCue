"""Measure the real cloud pipeline using an explicitly authorized WAV manifest."""
import argparse
import asyncio
import json
from math import ceil
import os
from pathlib import Path
from time import monotonic

from .config import REALTIME_MODEL, TEXT_MODEL
from .interview import InterviewService
from .services import TextService, client_for
from .transcribe_wav import stream_wav


def latency_summary(samples, limit):
    values = sorted(value for value in samples if value is not None)
    p50 = values[ceil(0.5 * len(values)) - 1] if values else None
    p95 = values[ceil(0.95 * len(values)) - 1] if values else None
    return {"expected": len(samples), "measured": len(values), "p50_s": p50, "p95_s": p95,
            "target_s": limit, "passed": p95 is not None and len(values) == len(samples) and p95 <= limit}


async def measure(path, key, service, speech_start, speech_end, needs_answer):
    first_ja = first_zh = answer_ready = None
    start = final = None
    seen = set()
    tasks = []

    def on_start(timestamp):
        nonlocal start
        start = timestamp

    async def translation(text):
        nonlocal first_zh
        async for delta in service.translate(text):
            if delta and first_zh is None:
                first_zh = monotonic() - start - speech_end

    async def suggestion(text):
        nonlocal answer_ready
        result = await InterviewService(service).suggest(text, automatic=True)
        if result is not None:
            answer_ready = monotonic() - final

    def on_event(event):
        nonlocal first_ja, final
        kind = event.get("type")
        if kind == "conversation.item.input_audio_transcription.delta" and event.get("delta") and first_ja is None:
            first_ja = monotonic() - start - speech_start
        if kind == "conversation.item.input_audio_transcription.completed" and event.get("transcript"):
            item = event["item_id"]
            if item in seen:
                return
            seen.add(item)
            if len(seen) == 1:
                final = monotonic()
                tasks.append(asyncio.create_task(translation(event["transcript"])))
                if needs_answer:
                    tasks.append(asyncio.create_task(suggestion(event["transcript"])))

    try:
        await stream_wav(path, key, on_event, on_start)
    except Exception:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        return None, None, None
    outcomes = await asyncio.gather(*tasks, return_exceptions=True)
    if len(seen) != 1:
        return None, None, None
    if outcomes and isinstance(outcomes[0], BaseException):
        first_zh = None
    return tuple(value if value is not None and value >= 0 else None for value in (first_ja, first_zh, answer_ready))


async def run(manifest, key, device, network):
    samples = json.loads(manifest.read_text(encoding="utf-8"))
    if len(samples) < 30 or sum(row["answer"] is True for row in samples) < 10:
        raise ValueError("At least 30 clips including 10 general interview questions are required")
    ja, zh, answer = [], [], []
    async with client_for(key) as client:
        service = TextService(client)
        for row in samples:
            if not 0 <= row["start_s"] < row["end_s"] or not isinstance(row["answer"], bool):
                raise ValueError("Invalid sample labels")
            first_ja, first_zh, ready = await measure(manifest.parent / row["wav"], key, service,
                                                      row["start_s"], row["end_s"], row["answer"])
            ja.append(first_ja)
            zh.append(first_zh)
            if row["answer"]:
                answer.append(ready)
    results = {"japanese": latency_summary(ja, 2.5), "chinese": latency_summary(zh, 3.0),
               "answer": latency_summary(answer, 10.0)}
    print(json.dumps({"device": device, "network": network, "transcription_model": REALTIME_MODEL,
                      "text_model": TEXT_MODEL, **results}, indent=2, ensure_ascii=False))
    return int(not all(result["passed"] for result in results.values()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--device", required=True, help="Non-sensitive device label")
    parser.add_argument("--network", required=True, help="Non-sensitive network condition label")
    parser.add_argument("--send-authorized-audio", action="store_true", required=True)
    args = parser.parse_args()
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        parser.error("Set OPENAI_API_KEY in this process before running the live check.")
    try:
        return asyncio.run(run(args.manifest, key, args.device, args.network))
    except Exception as exc:
        parser.exit(1, f"Benchmark failed ({type(exc).__name__}).\n")


if __name__ == "__main__":
    raise SystemExit(main())
