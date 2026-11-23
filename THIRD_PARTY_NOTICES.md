# KoeCue 第三方组件

KoeCue 源码采用 MIT 许可。以下第三方组件按各自的许可分发，文本随发布包放在 `licenses/`。发布包保留了可替换的动态库及 Python 扩展。

| 组件 | 发布包中的用途 | 许可及源码 |
| --- | --- | --- |
| CPython 3.13 | Python 运行时 | [Python 许可](https://docs.python.org/3.13/license.html) · [源码发行页](https://www.python.org/downloads/source/) |
| Qt 6.10.1、PySide6 和 Shiboken6 | 窗口和界面 | LGPL-3.0，见随包的 LGPL 与 GPL 文本。[Qt 源码](https://download.qt.io/archive/qt/6.10/6.10.1/) · [PySide6 与 Shiboken6 源码](https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.10.1-src/) · [Qt for Python 许可](https://doc.qt.io/qtforpython-6/licenses.html) |
| python-soxr / libsoxr | 音频重采样 | LGPL-2.1 或更新版本。[Python 绑定源码](https://github.com/dofuuz/python-soxr/tree/v1.0.0) · [libsoxr 源码](https://sourceforge.net/projects/soxr/files/) |
| PyAudioWPatch / PortAudio | WASAPI 音频设备 | [PyAudioWPatch 源码与许可](https://github.com/s0d3s/PyAudioWPatch) · [PortAudio 源码与许可](https://github.com/PortAudio/portaudio) |
| sherpa-onnx / ONNX Runtime | 本机 SenseVoice 与 Qwen3-ASR 推理 | [sherpa-onnx（Apache-2.0）](https://github.com/k2-fsa/sherpa-onnx/blob/master/LICENSE) · [ONNX Runtime（MIT）](licenses/ONNX-Runtime-MIT.txt) · [ONNX Runtime 源码](https://github.com/microsoft/onnxruntime) |
| PyInstaller | Windows 程序启动器 | [PyInstaller 许可及分发例外](https://pyinstaller.org/en/v6.22.3/license.html) |

LGPL 组件可按相应许可证的条件替换和调试。源码用户可以单独安装 [faster-whisper](https://github.com/SYSTRAN/faster-whisper) 并下载 [Whisper Base 转换版](https://huggingface.co/Systran/faster-whisper-base/tree/a80717a3a48b1b28aa687bca146cb7301feae1b1)。可选组件的许可说明见各自仓库。

SenseVoice 和 Qwen3-ASR 的模型权重由用户按需下载，来源分别为 [SenseVoice ONNX 模型](https://huggingface.co/csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17) 和 [Qwen3-ASR ONNX 模型](https://modelscope.cn/models/zengshuishui/Qwen3-ASR-onnx)。
