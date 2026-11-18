"""Opt-in check of the live text services without capturing audio."""
import argparse
import asyncio
import json
import os
from pathlib import Path
from time import monotonic

from .config import PROVIDERS
from .interview import InterviewService
from .services import TextService, client_for, error_message


async def validate(args, key, provider):
    async with client_for(key, provider) as client:
        text_service = TextService(client, provider, model=args.model, workspace=args.workspace)
        interview = InterviewService(text_service)
        if args.classification:
            examples = json.loads(Path(args.classification).read_text(encoding="utf-8"))
            questions = sum(expected for _, expected in examples)
            correct, false_positives = 0, 0
            for japanese, expected in examples:
                result = await interview.classify(japanese)
                detected = result["question"] is True
                correct += expected and detected
                false_positives += detected and not expected
            print(f"examples={len(examples)} recall={correct / questions:.3f} false_positives={false_positives}")
            return int(len(examples) < 30 or correct / questions < 0.9 or false_positives > 1)

        started = monotonic()
        translation = ""
        first_delta = None
        async for delta in text_service.translate(args.question):
            if first_delta is None:
                first_delta = monotonic() - started
            translation += delta
        started = monotonic()
        answer = await interview.suggest(args.question, automatic=False)
        print(f"first_translation_delta_s={first_delta:.2f} answer_ready_s={monotonic() - started:.2f}")
        if args.show_text:
            print(translation, answer.ja, answer.zh, sep="\n\n")
        return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--question")
    inputs.add_argument("--classification", metavar="JSON")
    parser.add_argument("--provider", choices=PROVIDERS, default="openai")
    parser.add_argument("--model", default="", help="Use this text model ID instead of the provider default.")
    parser.add_argument("--workspace", default="", help="Optional Qwen Beijing workspace ID.")
    parser.add_argument("--send-authorized-text", action="store_true", required=True)
    parser.add_argument("--show-text", action="store_true")
    args = parser.parse_args()
    provider = PROVIDERS[args.provider]
    try:
        provider.endpoint(args.workspace)
    except ValueError as exc:
        parser.error(str(exc))
    key = os.environ.get(provider.key_env, "").strip()
    if not key:
        parser.error(f"Set {provider.key_env} in this process before running the live check.")
    try:
        return asyncio.run(validate(args, key, provider))
    except Exception as exc:
        parser.exit(1, error_message(exc) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
