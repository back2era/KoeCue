# AI Japanese Interview Assistant

Windows 11 x64 桌面应用。面向日语模拟面试和已获授权的线上面试，提供本地音频诊断、日语字幕、简体中文翻译和双语口述参考答案。

| 状态 | 内容 |
| --- | --- |
| 已完成 | 逐字显示的日中字幕、常驻对话历史、OpenAI / DeepSeek / Anthropic 选择、本地日语转写、离线测试及真实 WASAPI 设备枚举 |
| 进行中 | 实际会议采样、服务商真实 API、30 分钟联调和延迟验收 |
| 未实现 | 按应用独立采集留待后续版本 |

目标运行环境为 Windows 11 x64、Python 3.13 x64 和 PowerShell。本地音频诊断无需 API Key。翻译和回答建议需要所选服务商的 Key 与可用网络。

## 本地运行

在本目录使用 PowerShell。请先安装 python.org 的 Windows x64 Python 3.13 和 Python Launcher。

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m ai_japanese_interview_assistant
```

## 选择服务商

| 服务商 | 日语语音转写 | 中文翻译与回答 |
| --- | --- | --- |
| OpenAI | OpenAI Realtime，按确认的语段显示 | OpenAI `gpt-6-luna` |
| DeepSeek | 本机 Whisper，断句后识别 | DeepSeek `deepseek-flash` |
| Anthropic | 本机 Whisper，断句后识别 | Claude `claude-haiku-5-5` |

**只有 DeepSeek Key 时**，在项目目录执行一次下列命令。Anthropic 使用相同的本地语音组件。多语言 Whisper base 模型约 148 MB，下载完成后在 CPU 上运行。 [Whisper 模型](https://huggingface.co/Systran/faster-whisper-base/tree/a80717a3a48b1b28aa687bca146cb7301feae1b1)

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-local.txt
.\.venv\Scripts\python.exe -m ai_japanese_interview_assistant.local_asr --download-model
.\.venv\Scripts\python.exe -m ai_japanese_interview_assistant
```

在「实时面试辅助」页点「设置」，选 **DeepSeek**，输入或读取自己的 DeepSeek Key，选择音源，确认同意后点击「开始本地转写」。音频留在本机，日语转写和单独授权的相关资料发给所选服务商。本地识别速度取决于电脑性能。 [DeepSeek Responses API](https://api-docs.deepseek.com/guides/responses_api/) · [Claude Messages API](https://platform.claude.com/docs/en/api/messages/create)

## 本地音频诊断

在诊断窗口选择来源，确认采集授权，点击“开始本地诊断”。播放已获授权的声音，观察电平与帧数。按“暂停”确认帧数停止，再“恢复监听”或“停止”。若会议有声音但电平一直为零，先核对会议的输出设备和 Windows 音量混音器。

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

本机以 CPython 3.13.12 验证安装、真实 WASAPI 设备枚举（3 个回环、2 个输入）、Qt 离屏启动和日中字符渲染。默认测试用实际重采样与协议替身。额外运行了 20 次模拟开始、暂停、恢复、停止循环。

## 独立转写联调

在当前进程安全设置 `OPENAI_API_KEY`。仅使用已获授权的 16 位 PCM WAV。

```powershell
.\.venv\Scripts\python.exe -m ai_japanese_interview_assistant.transcribe_wav 'C:\path\sample.wav' --send-authorized-audio
```

默认仅显示最终段数与首个增量耗时。需要在终端查看日语定稿时加 `--show-text`。默认 pytest 使用协议测试替身和本地分段样本，真实服务需用上面的命令单独验证。

桌面默认打开「实时面试辅助」。确认一段日语后新增一行，中文随翻译响应逐字显示。下方「历史对话」可滚动并选中任意一段。查看旧对话时会保留所选行和滚动位置，点「回到最新」可继续跟随。历史保留到关闭软件。本次会话的翻译异常可以重试。暂停和停止释放音频并取消请求。暂停后可继续同一次授权会话。上述 WAV 云端转写命令使用 OpenAI Realtime。

## 无采音验证回答

自动建议默认开启。开始监听后，识别到面试问题就会为对应的字幕生成日语参考答案和简体中文，可在历史对话里选中该行查看和复制。可在设置中关闭自动回答，也可对选中的日语定稿手动生成建议。

```powershell
.\.venv\Scripts\python.exe -m ai_japanese_interview_assistant.validate_text --classification tests/fixtures/questions.json --send-authorized-text
.\.venv\Scripts\python.exe -m ai_japanese_interview_assistant.validate_text --question 'チームで意見が分かれた場合、どうしますか。' --send-authorized-text --show-text
```

分类样本为 30 条人工标注文本。命令使用真实 API 计算召回和误触发次数。口述时长和 N3–N2 难度需要人工检查。

文本验收可以加 `--provider deepseek` 或 `--provider anthropic`，并设置对应的环境变量。此命令直接接收日语文字，无需安装本地语音模型。

## 本地资料与凭据

在“编辑资料 / 本次授权”中填写并核对教育、技能、经历、项目或目标岗位的日语和中文事实句。保存后可另外勾选本次允许发送的条目。每次回答只会选择最多两条相关资料。关键词用于匹配日语问题，留空表示可供同类问题选用。可随时撤销分享，停止会话后授权重置。资料文件位于 `%LOCALAPPDATA%\AIJapaneseInterviewAssistant\profile.json`。该文件是当前 Windows 用户目录下的普通 JSON。

开始监听或正常关闭软件时，会保存当前的服务商、音源、自动回答开关和本次输入的 API Key。下次打开自动恢复这些设置。API Key 按服务商分别存入 Windows 凭据管理器，也可从「Windows 凭据」菜单删除。若上次的音源不可用或有同名设备，请在设置中重新选择。开发时也可以按所选服务商使用 `OPENAI_API_KEY`、`DEEPSEEK_API_KEY` 或 `ANTHROPIC_API_KEY`。采集同意与资料分享授权每次会话重新确认。

音频和会话历史在应用中只保留于内存。`%LOCALAPPDATA%\AIJapaneseInterviewAssistant\assistant.log` 滚动保留固定事件名和耗时。OpenAI 文本请求使用 `store=false`，服务端保留规则取决于 API 账户与端点。 [OpenAI 数据控制](https://developers.openai.com/api/docs/guides/your-data)

## 验收记录

| 项目 | 结果 |
| --- | --- |
| 干净运行时与锁定依赖 | Windows 11 x64、CPython 3.13.12，`pip check` 通过 |
| 完整自动化套件 | 52 项通过，包括离屏 Qt、真实设备枚举、设置恢复、字幕逐字追加、历史保留和阅读位置、模拟采集生命周期及三家服务商协议替身 |
| 本地 Whisper | 在 Windows 11 上用真实模型离线识别公开日语发音片段。测试片段由 Spesco 发布，CC BY-SA 4.0。 [Ja-konnichiwa.ogg](https://commons.wikimedia.org/wiki/File:Ja-konnichiwa.ogg) |
| 实际采集 | 待验证浏览器、Teams、Zoom、麦克风、USB/蓝牙切换及真机生命周期 |
| 真实 API 与 30 分钟联调 | 待在有可用 Key 和已授权素材的环境验证，包括错误 Key、限流、断网、分类质量和回答时长 |
| p50/p95 | 待实测，未生成延迟数据 |

本地复跑完整自动化测试时，在 PowerShell 设置 `$env:AIJA_TEST_DEVICES='1'` 和 `$env:AIJA_TEST_GUI='1'` 后执行 `python -m pytest -q`。硬件测试只枚举设备。

延迟验收用本地私有 JSON 清单，包含至少 30 段已授权的 16 位 PCM WAV，每段只含一个语段。其中至少 10 段应为无需个人资料的面试问题。每条提供 `wav`（相对清单的路径）、`start_s`（开口时间）、`end_s`（说完时间）和 `answer`（是否测回答耗时）。将清单和音频放在仓库忽略的 `private/` 中。

```powershell
.\.venv\Scripts\python.exe -m ai_japanese_interview_assistant.benchmark_wav private/manifest.json --device 'Win11 x64' --network 'Wi-Fi' --send-authorized-audio
```

工具按实时节奏回放 WAV，输出模型、测量数及 p50/p95。测量包含音频处理和网络请求。真机采集与界面刷新需要用桌面端单独验收。

WASAPI 回环采集所选**播放设备**上的共享模式混音。请让会议软件将声音输出到所选设备，并留意同一设备上的通知声。麦克风是单独的来源。设备变化后重新枚举并选择，受保护内容可能无法采集。开始采集前应明确范围并取得必要同意。 [Microsoft WASAPI 回环](https://learn.microsoft.com/windows/win32/coreaudio/loopback-recording)

项目规则见 [AGENTS.md](AGENTS.md)。各阶段和验收项见 [开发计划](docs/superpowers/plans/2026-11-10-ai-japanese-interview-assistant.md)。
