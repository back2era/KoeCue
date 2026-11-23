from hashlib import sha256
from pathlib import Path
import sys
from threading import Event
from types import SimpleNamespace

import httpx
import pytest

from ai_japanese_interview_assistant.local_asr import LocalAsrError
from ai_japanese_interview_assistant.local_models import (
    MANAGED_MODELS, DownloadCancelled, ModelFile, ModelVariant, download_model, load_managed_decoder, model_available,
)


def sample_model(*files):
    return ModelVariant("test", "Test", "sensevoice", "https://example.org", tuple(
        ModelFile(name, len(data), sha256(data).hexdigest()) for name, data in files
    ))


def test_verified_download_is_installed_atomically(tmp_path):
    model = sample_model(("model.onnx", b"model"), ("tokenizer/vocab.json", b"vocab"))
    files = {"/model.onnx": b"model", "/tokenizer/vocab.json": b"vocab"}
    updates = []

    def respond(request):
        assert not model_available(tmp_path, model)
        return httpx.Response(200, content=files[request.url.path])

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        download_model(tmp_path, model, client, progress=updates.append)
        download_model(tmp_path, model, client)  # Already installed, no network.
    assert updates == [5, 10]
    assert model_available(tmp_path, model)
    assert (tmp_path / "test" / "tokenizer" / "vocab.json").read_bytes() == b"vocab"


@pytest.mark.parametrize("response", [httpx.Response(404), httpx.Response(200, content=b"xxxxx"),
                                      httpx.Response(200, content=b"longer")])
def test_incomplete_or_invalid_download_never_appears_installed(tmp_path, response):
    model = sample_model(("model.onnx", b"model"))
    with httpx.Client(transport=httpx.MockTransport(lambda _: response)) as client:
        with pytest.raises(LocalAsrError):
            download_model(tmp_path, model, client)
    assert not model_available(tmp_path, model)
    assert not list(tmp_path.iterdir())


def test_cancellation_discards_partial_download(tmp_path):
    model = sample_model(("model.onnx", b"model"), ("tokens.txt", b"tokens"))
    cancelled = Event()
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"model"))) as client:
        with pytest.raises(DownloadCancelled):
            download_model(tmp_path, model, client, cancelled=cancelled, progress=lambda _: cancelled.set())
    assert not list(tmp_path.iterdir())


def test_existing_folder_is_preserved(tmp_path):
    model = sample_model(("model.onnx", b"model"))
    existing = tmp_path / model.code
    existing.mkdir()
    note = existing / "keep.txt"
    note.write_text("keep")
    with httpx.Client(transport=httpx.MockTransport(lambda _: pytest.fail("unexpected HTTP"))) as client:
        with pytest.raises(LocalAsrError, match="已存在"):
            download_model(tmp_path, model, client)
    assert note.read_text() == "keep"


@pytest.mark.parametrize("code, method", [
    ("sensevoice-int8", "from_sense_voice"), ("sensevoice-fp32", "from_sense_voice"),
    ("qwen3-asr-0.6b", "from_qwen3_asr"), ("qwen3-asr-1.7b", "from_qwen3_asr"),
])
def test_decoder_uses_selected_variant_and_16_khz_mono(tmp_path, monkeypatch, code, method):
    from ai_japanese_interview_assistant import local_models

    options = {}
    stream = SimpleNamespace(result=SimpleNamespace(text=" テスト。 "))
    received = []
    stream.accept_waveform = lambda rate, samples: received.append((rate, samples.shape, samples.dtype.name))
    recognizer = SimpleNamespace(create_stream=lambda: stream, decode_stream=lambda _: None)
    factory = SimpleNamespace(**{method: lambda **kwargs: options.update(kwargs) or recognizer})
    monkeypatch.setattr(local_models, "model_available", lambda *args: True)
    monkeypatch.setitem(sys.modules, "sherpa_onnx", SimpleNamespace(OfflineRecognizer=factory))
    decoder = load_managed_decoder(code, directory=tmp_path, language="ja")
    assert decoder(bytes(4800), preview=True) == "テスト。"
    assert received == [(16000, (1600,), "float32")]
    if method == "from_sense_voice":
        assert options["language"] == "ja"
        assert options["model"].endswith(MANAGED_MODELS[code].files[0].path)
    else:
        assert options["encoder"].endswith(str(Path(MANAGED_MODELS[code].files[2].path)))
        assert options["tokenizer"].endswith("tokenizer")
