# AI Japanese Interview Assistant

Windows 11 x64 桌面应用。面向日语模拟面试和已获授权的线上面试，计划提供日语字幕、简体中文翻译和双语口述参考答案。

| 状态 | 内容 |
| --- | --- |
| 已完成 | 技术设计、项目文档、本地 WASAPI 诊断窗口 |
| 进行中 | 本地采集人工验收、日中字幕和双语回答的真实 API 联调 |
| 未实现 | 本地资料与整体联调 |

目标运行环境为 Windows 11 x64、Python 3.13 x64 和 PowerShell。本地音频诊断无需 API Key。云端模式需要可访问 OpenAI API 的网络及账户权限。

## 本地运行

在本目录使用 PowerShell。请先安装 python.org 的 Windows x64 Python 3.13 和 Python Launcher。

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m ai_japanese_interview_assistant
```

在诊断窗口选择来源，确认采集授权，点击“开始本地诊断”。播放已获授权的声音，观察电平与帧数。按“暂停”确认帧数停止，再“恢复监听”或“停止”。若会议有声音但电平一直为零，先核对会议的输出设备和 Windows 音量混音器。

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

本机已验证真实 WASAPI 设备枚举（3 个回环、2 个输入）、Qt 离屏启动和授权控件。采集会话未启动。会议声音、真实采样、USB/蓝牙切换及 20 次生命周期循环待人工验收。

## 独立转写联调

在当前进程安全设置 `OPENAI_API_KEY`。仅使用已获授权的 16 位 PCM WAV。

```powershell
.\.venv\Scripts\python.exe -m ai_japanese_interview_assistant.transcribe_wav 'C:\path\sample.wav' --send-authorized-audio
```

默认仅显示最终段数与首个增量耗时。需要在终端查看日语定稿时加 `--show-text`。默认 pytest 使用协议测试替身和本地分段样本，真实服务需用上面的命令单独验证。

桌面“实时面试辅助”页会同时展示日语增量和逐段中文译文。选择已授权的音频设备、输入会话用 Key 并勾选发送同意后，点击“开始云端监听”。选中历史行可查看完整文本，翻译异常时可重试该段。暂停和停止释放音频并取消请求。

## 无采音验证回答

自动建议默认关闭。实时会话中可以对选中的日语定稿手动生成建议，或在开始前为本次会话开启自动分类。生成后可复制日语参考答案和简体中文。

```powershell
.\.venv\Scripts\python.exe -m ai_japanese_interview_assistant.validate_text --classification tests/fixtures/questions.json --send-authorized-text
.\.venv\Scripts\python.exe -m ai_japanese_interview_assistant.validate_text --question 'チームで意見が分かれた場合、どうしますか。' --send-authorized-text --show-text
```

分类样本为 30 条人工标注文本。命令使用真实 API 计算召回和误触发次数。口述时长和 N3–N2 难度需要人工检查。

WASAPI 回环采集所选**播放设备**上的共享模式混音。请让会议软件将声音输出到所选设备，并留意同一设备上的通知声。麦克风是单独的来源。设备变化后重新枚举并选择，受保护内容可能无法采集。开始采集前应明确范围并取得必要同意。 [Microsoft WASAPI 回环](https://learn.microsoft.com/windows/win32/coreaudio/loopback-recording)

项目规则见 [AGENTS.md](AGENTS.md)。各阶段和验收项见 [开发计划](docs/superpowers/plans/2026-11-10-ai-japanese-interview-assistant.md)。
