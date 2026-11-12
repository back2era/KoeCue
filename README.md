# KoeCue

Windows 11 x64 桌面应用。面向日语模拟面试和已获授权的线上面试，提供本地音频诊断、日语字幕、简体中文翻译和双语口述参考答案。

| 状态 | 内容 |
| --- | --- |
| 已完成 | 五套可切换的玻璃主题、简历导入与面试场景、逐字显示的日中字幕、常驻对话历史、八家文本 API 的设置和协议适配、本地日语转写、离线测试及真实 WASAPI 设备枚举 |
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

Windows 任务栏会使用应用自己的波形图标。升级后请关闭旧窗口再启动。若之前把 Python 启动项固定到了任务栏，可取消固定旧项，再从新波形图标固定应用。

## 选择服务商

| 服务商 | 默认文本模型 | 可用的环境变量 | API 文档 |
| --- | --- | --- | --- |
| OpenAI | `gpt-6-luna` | `OPENAI_API_KEY` | [模型目录](https://developers.openai.com/api/docs/models) |
| DeepSeek | `deepseek-flash` | `DEEPSEEK_API_KEY` | [Responses API](https://api-docs.deepseek.com/guides/responses_api/) |
| Anthropic | `claude-haiku-5-5` | `ANTHROPIC_API_KEY` | [Messages API](https://platform.claude.com/docs/en/api/messages/create) |
| 千问 · 阿里云百炼 | `qwen3.8-flash` | `DASHSCOPE_API_KEY` | [百炼 Chat Completions](https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope) |
| Kimi · 月之暗面 | `kimi-k3.1-pro` | `MOONSHOT_API_KEY` | [Kimi API](https://platform.kimi.com/docs/api/chat) |
| GLM · 智谱 | `glm-5.3` | `ZHIPUAI_API_KEY` | [智谱开放平台](https://docs.bigmodel.cn/cn/guide/start/quick-start) |
| MiniMax | `MiniMax-M3.1-Flash` | `MINIMAX_API_KEY` | [MiniMax 开放平台](https://platform.minimax.cn/docs/api-reference/text-openai-api) |
| Google Gemini | `gemini-3.8-flash` | `GEMINI_API_KEY` | [Gemini API](https://aistudio.google.com/docs/openai) · [支持地区](https://ai.google.dev/gemini-api/docs/available-regions) |

在「实时面试 → 设置 → API 服务」选择服务商，填写自己的 API Key，然后从「文本模型」下拉框选择或直接输入模型 ID。例如 OpenAI 可选 `gpt-6.1-terra` 或 `gpt-6.1-sol`。翻译、建议生成和核验共用所选文本模型。「刷新模型」可从 OpenAI、DeepSeek、Anthropic、Kimi 和 Gemini 拉取列表。「测试连接」只发送固定日语短句并检查流式译文，无需音源或本地语音模型。模型可用性取决于账户权限。千问使用中国内地百炼 Key，可选填北京业务空间 ID。

**使用 OpenAI 时**，语音走 OpenAI Realtime。**选择其他服务商时**，语音由同一份本机 Whisper 模型转写，只需要当前服务商的 Key。首次使用本地转写时执行下列命令一次。多语言 Whisper base 模型约 148 MB，下载完成后在 CPU 上运行。 [Whisper 模型](https://huggingface.co/Systran/faster-whisper-base/tree/a80717a3a48b1b28aa687bca146cb7301feae1b1)

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-local.txt
.\.venv\Scripts\python.exe -m ai_japanese_interview_assistant.local_asr --download-model
.\.venv\Scripts\python.exe -m ai_japanese_interview_assistant
```

在「设置」选择音源并确认采集同意，点击「开始本地转写」。本地转写时音频留在本机，日语转写和单独授权的相关资料发给所选文本服务商。本地识别速度取决于电脑性能。

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

桌面默认打开「实时面试」。说话时，顶部「日语 · 识别中」随识别结果更新，后续音频可以纠正这段临时字幕中的词。本地 Whisper 收到约 1.2 秒音频后尝试第一次预览，实际显示时间还取决于推理速度和语音清晰度。断句后，本地模型结合整段音频和常见面试词汇重新识别。只有定稿写入历史，再流式翻译成中文并生成建议。

「历史对话」可滚动并选中任意一段。查看旧对话时会保留所选行和滚动位置，点「回到最新」可继续跟随。历史保留到关闭软件。本次会话的翻译异常可以重试。暂停和停止释放音频并取消请求。暂停后可继续同一次授权会话。上述 WAV 云端转写命令使用 OpenAI Realtime。

## 无采音验证回答

自动建议默认开启。每段非空日语定稿都会触发双语建议，提问可获得参考回答，陈述可获得简短回应。没有相关个人资料时，建议会采用通用做法、明确假设或礼貌澄清。服务繁忙时建议会自动排队。可在历史中查看和复制建议，也可在「个人信息 → 回答与资料授权」关闭自动生成。

在「设置 → AI 回答难度」选择 N5 至 N1，默认 N2。新生成的回答会按照所选等级调整日语词汇、语法和表达，已核对的双语事实仍按原句引用。开始监听或正常关闭软件后会保存所选等级。

日语建议先显示正文。随后同一文本服务商从正文里选出少数关键词，以加粗和主题强调色标记。长回答按句分段，日文和中文用细线分隔。默认优先显示重点词的平假名和英文原词，点击「全部标注」可以展开剩余标注。复制回答会复制日语原文和简体中文。

宽窗口并排显示实时字幕和历史对话，窄窗口会改为上下排列。可拖动分隔线调整空间。「设置」在独立窗口打开，主界面上的历史和监听控制仍可使用。玻璃卡片透出应用内部的模糊背景。

在「设置 → 界面主题」可即时切换石墨银、深海青、冰川白、暖雾米和纯黑。首次使用默认纯黑，开始监听或正常关闭软件后会记住所选主题。

```powershell
.\.venv\Scripts\python.exe -m ai_japanese_interview_assistant.validate_text --classification tests/fixtures/questions.json --send-authorized-text
.\.venv\Scripts\python.exe -m ai_japanese_interview_assistant.validate_text --question 'チームで意見が分かれた場合、どうしますか。' --send-authorized-text --show-text
```

分类样本为 30 条人工标注文本。命令使用真实 API 计算召回和误触发次数。回答的口述时长和目标难度需要人工检查。

文本验收用 `--provider` 选择 `openai`、`deepseek`、`anthropic`、`qwen`、`kimi`、`glm`、`minimax` 或 `gemini`，并在当前进程设置对应的环境变量。可加 `--model` 指定模型 ID，千问可加 `--workspace` 指定北京业务空间。此命令直接接收日语文字，无需安装本地语音模型。

## 本地资料与凭据

1. 打开「个人信息」，输入自我介绍，或导入中文、英文、日文简历。支持带文字层的 PDF、DOCX 和 UTF-8 或带 BOM 的 UTF-16 TXT。扫描版 PDF 可以先提取文字，再粘贴到「简历文本」。导入上限为 8 MB、12,000 字，PDF 最多 24 页。
2. 可填写对方公司、应聘岗位和场景说明。确认简历提取结果后，点击表单下方的「保存个人信息」。勾选当次愿意分享的资料类别，再点击「授权所选」并开始面试。
3. 回答生成时才会向当前选定的服务商发送已授权的面试场景，以及最多两条相关的已核对事实或简历、简介片段。原始文件和路径留在本机。软件会核验来自摘录的双语陈述，资料不足时给出通用建议。可随时撤销分享，停止或更换服务商会重置授权。

原有的双语事实仍可在「管理已核对事实」中编辑并按条授权。回答中采用的已核对事实保留原句。简历提取文字、简介和场景保存在 `%LOCALAPPDATA%\AIJapaneseInterviewAssistant\personal.json`，双语事实保存在同目录的 `profile.json`。两者均为本机普通 JSON。KoeCue 沿用该本地目录及现有 Windows 凭据条目，升级后可继续读取原有资料、设置和 API Key。

已有安装升级后，如遇到 PDF 组件不可用，在项目目录运行 `.\.venv\Scripts\python.exe -m pip install -r requirements.txt`，然后重新启动。

在设置中点击「完成」、开始监听或正常关闭软件时，会保存服务商、各家模型、音源、自动回答开关和当前输入的 API Key。下次打开自动恢复这些设置。API Key 按服务商分别存入 Windows 凭据管理器，也可从「Windows 凭据」菜单删除。若上次的音源不可用或有同名设备，请在设置中重新选择。采集同意与资料分享授权每次会话重新确认。

音频和会话历史在应用中只保留于内存。`%LOCALAPPDATA%\AIJapaneseInterviewAssistant\assistant.log` 滚动保留固定事件名和耗时。OpenAI 文本请求使用 `store=false`，服务端保留规则取决于 API 账户与端点。 [OpenAI 数据控制](https://developers.openai.com/api/docs/guides/your-data)

## 验收记录

| 项目 | 结果 |
| --- | --- |
| 干净运行时与锁定依赖 | Windows 11 x64、CPython 3.13.12，`pip check` 通过 |
| 完整自动化套件 | 157 项通过，包括离屏 Qt、Windows Shell 任务栏、真实设备枚举、字幕与历史、回答标注、模型设置恢复和八家服务商协议替身 |
| 本地 Whisper | 用真实模型比较了两种合成日语音色。常见面试词汇提示让两段清晰的「自分の長所と短所は何ですか」正确识别出关键字「長所」「短所」。实际会议音质下的准确率待测。 |
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

项目规则见 [AGENTS.md](AGENTS.md)。各阶段和验收项见 [开发计划](docs/superpowers/plans/2026-11-10-koecue.md)。
