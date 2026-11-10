# AI Japanese Interview Assistant

Windows 11 x64 桌面应用。面向日语模拟面试和已获授权的线上面试，计划提供日语字幕、简体中文翻译和双语口述参考答案。

| 状态 | 内容 |
| --- | --- |
| 已完成 | 技术设计与项目文档 |
| 进行中 | 本地 WASAPI 音频诊断 |
| 未实现 | 实时转写、日中字幕、回答建议、本地资料与整体联调 |

目标运行环境为 Windows 11 x64、Python 3.13 x64 和 PowerShell。本地音频诊断无需 API Key。云端模式需要可访问 OpenAI API 的网络及账户权限。

WASAPI 回环采集所选**播放设备**上的共享模式混音。请让会议软件将声音输出到所选设备，并留意同一设备上的通知声。麦克风是单独的来源。设备变化后重新枚举并选择，受保护内容可能无法采集。开始采集前应明确范围并取得必要同意。 [Microsoft WASAPI 回环](https://learn.microsoft.com/windows/win32/coreaudio/loopback-recording)

项目规则见 [AGENTS.md](AGENTS.md)。各阶段和验收项见 [开发计划](docs/superpowers/plans/2026-11-10-ai-japanese-interview-assistant.md)。
