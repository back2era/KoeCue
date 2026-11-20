# KoeCue-SWT · 英语口测版

基于 [KoeCue v0.0.1](https://github.com/back2era/KoeCue/tree/v0.0.1) 的 MIT 源码（e1f94fd），保留原版 Qt 界面、主题、设置、实时字幕与历史、音频诊断、简历导入和会话授权。语言改为英文输入、简中翻译和英中口语建议；英语难度为 A1–C1，默认 B1。口语建议面向 BridgeUSA Summer Work Travel（SWT）机构口测，包括基本背景、项目动机、文化交流、工作场景、住宿、通勤和返校安排。只用你提供的事实，不把岗位意向写成已确认的安排。

## 打开和设置

1. 完整解压 ZIP，双击 `KoeCue-SWT.exe`。不要分开移动 `_internal` 和 `models`，不需要系统 Python。
2. 点击「实时面试 → 设置」：选择视频或会议所使用的**系统播放设备**（不是麦克风）；到「音频诊断」可以检查播放电平。
3. 选 API 服务商、填 Key，点「测试连接」。Groq、DeepSeek、千问等使用内置多语种 Whisper **本机转写英语**；翻译与回答用文本 API。选择 OpenAI 时按原版使用云端转写。API 权限、模型可用性以你的账户为准。
4. 想给出个性化答案，在「个人信息」填实际背景或导入简历，保存并勾选「授权所选」。开始监听后，可看识别预览，断句后查看中文翻译及双语回答。右侧历史可回看，「回到最新」恢复跟随。
5. 只在允许采集和使用辅助工具的场合启动。结束时点「停止」。音频、字幕和回答历史只保留在本次会话，资料保存在电脑上，Key 可保存到 Windows 凭据管理器。此版本独立存储，不覆盖原版设置。

## 开发与打包

Windows x64 + Python 3.13：

```powershell
python -m pip install -r requirements-build.txt -r requirements-dev.txt
python -m ai_japanese_interview_assistant.local_asr --download-model
python -m scripts.build_windows
```

打包脚本按上游固定修订校验模型文件。测试：`python -m pytest -q`。真实云端端到端需要可用的 API Key，不包含在离线回归范围内。

## 豆包实时语音识别 2.0

在设置里保留已有的文本服务和 Key，勾选「使用豆包实时语音识别 2.0」，填写火山引擎新版语音控制台的 API Key。此版本使用流式语音识别 2.0 小时版（`volc.seedasr.sauc.duration`），Key 仅保留在当前进程内。重新勾选音频发送同意，再点「开始豆包转写」。设置里的「测试连接」仍只测试文本 API；豆包在开始监听时连接。取消勾选即恢复原语音引擎。
