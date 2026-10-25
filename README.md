# xiaoai-gpt

> **使用许可：仅限非商业用途。任何商业使用必须事先取得项目作者 的书面授权。** 详见 [LICENSE](LICENSE)。本项目为源码可见项目，不属于 OSI 定义的开源软件；第三方组件仍遵循各自许可。

[English](README.en.md) · **中文**

让小爱音箱 Pro（LX06）通过 Mac 使用 Codex：支持单次问答、连续语音、可配置唤醒词和退出口令。

这是从实际使用的 Mac 方案整理的公开源码和受控安装器，默认单音箱。安装器目前面向运行 macOS 14 及以上版本的 Apple Silicon Mac 和已解锁的 LX06；**新 Mac 从零安装尚未独立完成端到端实机验收。**

## 实际效果

[作者实机演示：小红书](https://www.xiaohongshu.com/explore/6add72ed000000002b00da22)（可能需要登录或客户端）。演示由作者提供；不是所有设备、网络和版本的效果保证。

## 先把音箱准备好

音箱解锁、刷机、开启 SSH 和安装音箱客户端，请参考：

- [OpenXiaoAI 原项目及文档](https://github.com/idootop/open-xiaoai)（原仓库已归档）。
- [小爱音箱改造视频教程](https://youtu.be/JKyJdnR1uRc?si=XTlR9v1xlLO4Cw_f)。

这里不重复造刷机轮子，不提供自动刷机。先确认自己的型号和固件符合上游要求；本项目实际验证范围是 LX06。不要假设其他 fork 的最新版客户端与本桥接协议兼容。

## 让你的 Agent 帮你装

把下面一句发给你的 Codex 或其他具备本机操作能力的 Agent：

> 请把 https://github.com/samyeei/xiaoai-gpt 安装到我的 Mac：先阅读 AGENTS.md 和安装教程，检查这台 Mac 与已解锁 LX06 的条件，再使用 `./install.sh doctor` 和安装器；保留现有配置与回滚，让我完成 Codex 登录和系统授权，最后逐项做实机语音验收，如实报告未完成项。

安装器会在本机询问缺少的音箱与 Mac 地址；你仍需准备已解锁音箱、完成自己的 Codex 登录、核对设备 SSH 指纹，并按提示授权。不要把密码发给 Agent 聊天记录。也可以自行在仓库根目录先运行 `./install.sh doctor`；检查不会安装任何东西。

- [中文安装教程](docs/INSTALL.zh-CN.md) / [English installation](docs/INSTALL.en.md)
- [中文使用与改唤醒词](docs/USAGE.zh-CN.md) / [English usage and wake words](docs/USAGE.en.md)
- [架构与开发交接 / Architecture](docs/ARCHITECTURE.md)
- [隐私与提交检查 / Privacy](SECURITY.md)

## 平时怎么用

| 场景 | 说法 |
| --- | --- |
| 单次问答 | “你好机劈替”，等提示再问 |
| 通过小爱进入单问 | “小爱同学” → 等回应 → “打开机劈替” |
| 连续对话 | “小爱同学” → 等回应 → “开启连续对话” → 等“可以开始了” |
| 退出 | 等它说完后说“退下吧” |
| 播报中停止 | 叫“小爱同学” |

三处配置统一放在 `config/`：

- `wake-words.json`：直接唤醒词、发音 token、开关。
- `voice-commands.json`：小爱回应后的单问、连续、退出口令。
- `assistant.json`：模型、推理强度、人声和音量。当前预设 `gpt-5.6-luna`，单问 `medium`，连续 `high`，人声 `maple`；可用性取决于你的 Codex 账号和客户端版本。

更换直接唤醒词需要同步词表支持的发音 token 并实测，不能只换显示文字。保存后须在空闲时重启相应服务，详见使用教程。

## 支持范围和限制

- 主链路：LX06 ↔ 局域网 Mac ↔ 已登录的 Codex App Server；连续语音用 WebRTC，播放通过受限 SSH `aplay` 返回音箱。无需 NAS、ESP32 或 BlackHole。
- 使用 Codex 账号额度；不是独立 OpenAI Realtime API 接入，不承诺免费或无限。
- 已使用的环境接受偶有轻微卡顿；不是全双工，播报时暂停云端收音。
- 源码保留双音箱互斥逻辑，但公开版本默认单台；不承诺所有多机场景验收完毕。
- 历史 Muse、NAS、桌面音频实验文件不是当前主安装路线，不表示这些集成已经可用。
- 不含登录、密钥、模型权重、私密备份、原始截图或对话记录。

## 致谢与许可

感谢 [OpenXiaoAI](https://github.com/idootop/open-xiaoai)、[sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx)、[Codex](https://github.com/openai/codex)、[aiortc](https://github.com/aiortc/aiortc) 和 ws。本项目原创内容采用[非商业用途许可](LICENSE)，商用须经作者事先书面授权；第三方组件保留原许可，见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。这是社区项目，与小米、OpenAI 无官方隶属关系。

许可变更之前发布的 MIT 版本保留其原许可；本次变更不追溯撤销已授予的权利。商业授权请通过 [GitHub Issues](https://github.com/samyeei/xiaoai-gpt/issues) 联系作者，申请本身不代表获准。
