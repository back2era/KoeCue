"""Pinned local speech model catalog, downloads, and CPU decoding."""
from dataclasses import dataclass
from hashlib import sha256
import os
from pathlib import Path
from shutil import disk_usage
from tempfile import TemporaryDirectory

import httpx

from .local_asr import LocalAsrError, load_decoder, local_model_available
from .profiles import app_directory


@dataclass(frozen=True)
class ModelFile:
    path: str
    size: int
    sha256: str


@dataclass(frozen=True)
class ModelVariant:
    code: str
    label: str
    engine: str
    source: str
    files: tuple[ModelFile, ...]

    @property
    def size(self):
        return sum(file.size for file in self.files)


SENSEVOICE_SOURCE = (
    "https://huggingface.co/csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17"
    "/resolve/2365baeacb507f821a0c8120fcee3d484dba7a07"
)
QWEN3_SOURCE = "https://modelscope.cn/models/zengshuishui/Qwen3-ASR-onnx/resolve/cb045ad80b8970c9d411d463e5b78991a566596c"
WHISPER_SOURCE = "https://huggingface.co/csukuangfj/sherpa-onnx-whisper-base/resolve/bb53ee204431c90d314c1cc08d28d23e5b7927cc"

SENSEVOICE_TOKENS = ModelFile("tokens.txt", 315894, "f449eb28dc567533d7fa59be34e2abca8784f771850c78a47fb731a31429a1dc")
QWEN3_TOKENIZER = (
    ModelFile("tokenizer/chat_template.json", 1161, "75a8cfca24f00de72d796fbfed6858fc9614ef3dabd8696684cc3bc03a9c58ff"),
    ModelFile("tokenizer/config.json", 6193, "76d3ae4601ce939830b2517f4a6cadb86cc51316c3900af6b020b051c21a478c"),
    ModelFile("tokenizer/merges.txt", 1671853, "8831e4f1a044471340f7c0a83d7bd71306a5b867e95fd870f74d0c5308a904d5"),
    ModelFile("tokenizer/preprocessor_config.json", 330, "45e120a4eda2c20c5d7f2ea9354e63536bf35e27aa573fb7cdf78017b378770d"),
    ModelFile("tokenizer/tokenizer_config.json", 12487, "4942d005604266809309cabc9f4e9cb89ce855d59b14681fdc0e1cc62ea26c4c"),
    ModelFile("tokenizer/vocab.json", 2776833, "ca10d7e9fb3ed18575dd1e277a2579c16d108e32f27439684afa0e10b1440910"),
)
MANAGED_MODELS = {
    variant.code: variant for variant in (
        ModelVariant("sensevoice-int8", "SenseVoice · Small INT8", "sensevoice", SENSEVOICE_SOURCE, (
            ModelFile("model.int8.onnx", 239233841, "c71f0ce00bec95b07744e116345e33d8cbbe08cef896382cf907bf4b51a2cd51"),
            SENSEVOICE_TOKENS,
        )),
        ModelVariant("sensevoice-fp32", "SenseVoice · Small FP32", "sensevoice", SENSEVOICE_SOURCE, (
            ModelFile("model.onnx", 937617178, "977016bd9c79f9eb343430b5cc305e07ab64d5212dff41b0dcfa1694bee9a8cb"),
            SENSEVOICE_TOKENS,
        )),
        ModelVariant("qwen3-asr-0.6b", "Qwen3-ASR · 0.6B INT8", "qwen3", QWEN3_SOURCE, (
            ModelFile("model_0.6B/conv_frontend.onnx", 44148281, "d22dc4423e0940e49884e903d2ea2f7e5567c14fc1aed97e4e26d6b8f208ef9e"),
            ModelFile("model_0.6B/decoder.int8.onnx", 755914231, "4f6885be5959ae26af3089d38ee7972c5fafbeeb1cf8d5e76eab6d8b61ca5771"),
            ModelFile("model_0.6B/encoder.int8.onnx", 182491662, "60748d3e6744a57c9c91e1b17424a6c2990567e8adceb0783940c03ed98fa9d9"),
            *QWEN3_TOKENIZER,
        )),
        ModelVariant("qwen3-asr-1.7b", "Qwen3-ASR · 1.7B INT8", "qwen3", QWEN3_SOURCE, (
            ModelFile("model_1.7B/conv_frontend.onnx", 48080441, "fa894a4ba53da6a4238f2a6ca0b09362e505d39cecbd646051b033e2e8d7e2fb"),
            ModelFile("model_1.7B/decoder.int8.onnx", 2037458645, "c43c853fa6e97d08365cb8a5502b360b595cd43c00dc60e4d8ca7cc18cad460b"),
            ModelFile("model_1.7B/encoder.int8.onnx", 314222162, "436fbd910a0c8914851e5ac1354e807be9f283d08a5da728adaa609731c41469"),
            *QWEN3_TOKENIZER,
        )),
        # Keep the saved speech model ID used by earlier versions.
        ModelVariant("local", "Whisper · Base INT8", "whisper", WHISPER_SOURCE, (
            ModelFile("base-encoder.int8.onnx", 29120534, "0b8fb1304b6109976038efff5ace81720e00386f3ff6b54ee8c75291ca0a1e11"),
            ModelFile("base-decoder.int8.onnx", 130672026, "9759d217388a01b3a4c7c15533201067b48ae819c4daafc8624e64b9409dc02d"),
            ModelFile("base-tokens.txt", 816730, "b34b360dbb493e781e479794586d661700670d65564001f23024971d1f2fa126"),
        )),
    )
}


def models_directory(configured=""):
    return Path(configured) if configured else app_directory() / "models"


def model_available(directory, model):
    target = directory / model.code
    try:
        return all((target / file.path).is_file() and (target / file.path).stat().st_size == file.size
                   for file in model.files)
    except OSError:
        return False


def model_installation(directory, model):
    """Prefer the managed weights and recognize usable legacy Whisper installs."""
    if model_available(directory, model):
        return "downloaded"
    if model.engine == "whisper" and local_model_available():
        return "legacy"
    return ""


class DownloadCancelled(Exception):
    """The user cancelled the current download."""


def download_model(directory, model, client, *, cancelled=None, progress=lambda _: None):
    """Only make a model visible after its complete set of files passes integrity checks."""
    def check_cancelled():
        if cancelled is not None and cancelled.is_set():
            raise DownloadCancelled

    target = directory / model.code
    total = 0
    try:
        check_cancelled()
        if model_available(directory, model):
            return
        if target.exists():
            raise LocalAsrError("模型目录已存在但文件不完整。请选择其他下载目录或移走旧目录。")
        directory.mkdir(parents=True, exist_ok=True)
        if disk_usage(directory).free < model.size:
            raise LocalAsrError("磁盘空间不足，请更换模型目录。")
        with TemporaryDirectory(prefix=".koecue-download-", dir=directory) as staging:
            staged = Path(staging) / "model"
            for file in model.files:
                check_cancelled()
                digest = sha256()
                size = 0
                path = staged / file.path
                path.parent.mkdir(parents=True, exist_ok=True)
                with client.stream("GET", f"{model.source}/{file.path}") as response:
                    response.raise_for_status()
                    with path.open("wb") as output:
                        for chunk in response.iter_bytes(chunk_size=256 * 1024):
                            check_cancelled()
                            size += len(chunk)
                            if size > file.size:
                                raise LocalAsrError("模型文件大小不符，请重新下载。")
                            digest.update(chunk)
                            output.write(chunk)
                            total += len(chunk)
                            progress(total)
                if size != file.size or digest.hexdigest() != file.sha256:
                    raise LocalAsrError("模型文件校验失败，请重新下载。")
            check_cancelled()
            try:
                staged.rename(target)
            except OSError:
                if not model_available(directory, model):
                    raise
    except httpx.HTTPError as exc:
        raise LocalAsrError("模型下载失败，请检查网络后重试。") from exc
    except OSError as exc:
        raise LocalAsrError("无法写入模型，请检查目录权限和磁盘空间。") from exc


def load_managed_decoder(code, *, directory, language):
    model = MANAGED_MODELS[code]
    installation = model_installation(directory, model)
    if installation == "legacy":
        try:
            return load_decoder(language=language)
        except LocalAsrError as exc:
            raise LocalAsrError("旧版 Whisper 无法启动，请在「语音识别」页下载新版。") from exc
    if not installation:
        raise LocalAsrError("模型文件缺失，请在「语音识别」页下载模型。")
    try:
        from sherpa_onnx import OfflineRecognizer
    except (ImportError, OSError) as exc:
        raise LocalAsrError("本地语音组件不可用，请更新 requirements.txt 的依赖。") from exc

    import numpy as np
    import soxr

    target = directory / model.code
    threads = min(4, os.cpu_count() or 1)
    try:
        if model.engine == "sensevoice":
            recognizer = OfflineRecognizer.from_sense_voice(
                model=str(target / model.files[0].path), tokens=str(target / "tokens.txt"),
                language=language, use_itn=True, num_threads=threads,
            )
        elif model.engine == "whisper":
            recognizer = OfflineRecognizer.from_whisper(
                encoder=str(target / model.files[0].path), decoder=str(target / model.files[1].path),
                tokens=str(target / model.files[2].path), language=language, task="transcribe",
                num_threads=threads,
            )
        else:
            folder = (target / model.files[0].path).parent
            recognizer = OfflineRecognizer.from_qwen3_asr(
                conv_frontend=str(folder / "conv_frontend.onnx"),
                encoder=str(folder / "encoder.int8.onnx"), decoder=str(folder / "decoder.int8.onnx"),
                tokenizer=str(target / "tokenizer"), num_threads=threads,
            )
    except (RuntimeError, ValueError, OSError, MemoryError) as exc:
        raise LocalAsrError("无法加载本地模型，请检查内存和模型文件。") from exc

    def decode(pcm, *, preview=False):
        samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
        samples = soxr.resample(samples, 24000, 16000)
        try:
            stream = recognizer.create_stream()
            stream.accept_waveform(16000, samples)
            recognizer.decode_stream(stream)
            return stream.result.text.strip()
        except (RuntimeError, ValueError, MemoryError) as exc:
            raise LocalAsrError("本地识别失败，请尝试较小的模型。") from exc

    return decode
