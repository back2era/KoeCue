# KoeCue 第三方组件

KoeCue 源码采用 MIT 许可。以下第三方组件按各自的许可分发，文本随发布包放在 `licenses/`。发布包保留了可替换的动态库及 Python 扩展。

| 组件 | 发布包中的用途 | 许可及源码 |
| --- | --- | --- |
| CPython 3.13 | Python 运行时 | [Python 许可](https://docs.python.org/3.13/license.html) · [源码发行页](https://www.python.org/downloads/source/) |
| Qt 6.10.1、PySide6 和 Shiboken6 | 窗口和界面 | LGPL-3.0，见随包的 LGPL 与 GPL 文本。[Qt 源码](https://download.qt.io/archive/qt/6.10/6.10.1/) · [PySide6 与 Shiboken6 源码](https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.10.1-src/) · [Qt for Python 许可](https://doc.qt.io/qtforpython-6/licenses.html) |
| python-soxr / libsoxr | 音频重采样 | LGPL-2.1 或更新版本。[Python 绑定源码](https://github.com/dofuuz/python-soxr/tree/v1.0.0) · [libsoxr 源码](https://sourceforge.net/projects/soxr/files/) |
| PyAudioWPatch / PortAudio | WASAPI 音频设备 | [PyAudioWPatch 源码与许可](https://github.com/s0d3s/PyAudioWPatch) · [PortAudio 源码与许可](https://github.com/PortAudio/portaudio) |
| faster-whisper / CTranslate2 | 本地 Whisper 推理 | MIT。[faster-whisper 1.2.1 源码](https://github.com/SYSTRAN/faster-whisper/tree/v1.2.1) · [CTranslate2 4.7.1 源码](https://github.com/OpenNMT/CTranslate2/tree/v4.7.1) |
| Whisper base 多语言模型 | 日语语音识别 | MIT，源模型 © 2022 OpenAI。[OpenAI Whisper](https://github.com/openai/whisper) · [SYSTRAN 转换版与固定修订](https://huggingface.co/Systran/faster-whisper-base/tree/a80717a3a48b1b28aa687bca146cb7301feae1b1) |
| PyInstaller | Windows 程序启动器 | [PyInstaller 许可及分发例外](https://pyinstaller.org/en/v6.22.3/license.html) |

Windows 发布构建将原始 PCM 直接交给 faster-whisper。构建脚本对打包副本的音频模块做了局部修改，使外部音频文件解码依赖成为可选项。发布包省略 PyAV 及其 FFmpeg 动态库。完整修改见 [构建脚本](scripts/build_windows.py)。LGPL 组件可按相应许可证的条件替换和调试。
