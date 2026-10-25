# xiaoai-gpt

> **Noncommercial use only. Any commercial use requires prior written authorization from the project author.** See [LICENSE](LICENSE). This is a source-available project, not OSI-defined open source; third-party components retain their own licenses.

**English** · [中文](README.md)

Use a XiaoAI Pro (LX06) speaker with Codex through a Mac: single questions, continuous voice, configurable wake words, and configurable exit commands.

This public release includes a controlled installer for one speaker on an Apple Silicon Mac running macOS 14 or later, with an already-unlocked LX06. **A clean Mac installation has not yet passed independent, end-to-end real-device acceptance.**

## Demo and speaker preparation

[Author's real-device demo on Xiaohongshu](https://www.xiaohongshu.com/explore/6add72ed000000002b00da22) (login/app may be required). The author supplied this demo; it does not guarantee identical performance on every device or network.

For unlocking/flashing, SSH access, and the speaker client, use the [original OpenXiaoAI repository](https://github.com/idootop/open-xiaoai) (archived) and [this video tutorial](https://youtu.be/JKyJdnR1uRc?si=XTlR9v1xlLO4Cw_f). This repository does not repeat the flashing procedure or flash automatically. Verify your exact model/firmware first. LX06 is the tested model here; do not assume a newer client from another fork is protocol-compatible.

## One sentence for your agent

> Install https://github.com/samyeei/xiaoai-gpt on my Mac: first read AGENTS.md and the installation guide, inspect this Mac and my already-unlocked LX06, then use `./install.sh doctor` and the installer; preserve existing settings and rollback, let me handle Codex login and OS permissions, and report each real-device voice acceptance result honestly.

The installer prompts locally for missing speaker and Mac addresses. You still need an unlocked speaker, your own Codex login, verified SSH host keys, and any required local permissions. Enter passwords only in trusted local prompts, never in chat. You can run `./install.sh doctor` from the repository root first; it does not install anything.

- [Installation](docs/INSTALL.en.md) / [中文安装](docs/INSTALL.zh-CN.md)
- [Usage and wake words](docs/USAGE.en.md) / [中文使用教程](docs/USAGE.zh-CN.md)
- [Architecture](docs/ARCHITECTURE.md) · [Privacy](SECURITY.md)

## Daily use

| Action | Spoken sequence |
| --- | --- |
| One question | “你好机劈替” (nǐ hǎo jī pī tì), wait for the prompt, then ask |
| One question via XiaoAI | “小爱同学”, wait, then “打开机劈替” |
| Continuous conversation | “小爱同学”, wait, then “开启连续对话”; wait for “可以开始了” |
| Exit | Wait until playback ends, then say “退下吧” |
| Stop playback | Say the native wake phrase “小爱同学” |

The default commands are Chinese. English aliases can be configured, but recognition must be tested; English defaults have not been validated in a new installation.

Configuration lives in `config/wake-words.json` (direct wake aliases, pronunciation tokens and switches), `config/voice-commands.json` (single/continuous/exit commands), and `config/assistant.json` (model, reasoning, voice and output). Defaults are `gpt-5.6-luna`, `medium` for single questions, `high` for continuous voice, and `maple`. Availability depends on your account/client. A direct wake change needs valid model vocabulary tokens and a real recognition test. Restart the relevant services while idle after changes.

## Scope

LX06 ↔ LAN Mac ↔ authenticated Codex App Server. Continuous audio uses WebRTC and a restricted SSH `aplay` player. The main route needs no NAS, ESP32, or BlackHole. It consumes Codex account quota; it is not a separate OpenAI Realtime API integration and is not unlimited/free by promise.

Occasional light stutter remains. Playback pauses cloud microphone input: this is not full duplex. Optional two-speaker mutual-exclusion code is included, but one speaker is the public default and broader multi-device acceptance is incomplete. Historical Muse/NAS/desktop-audio experiments are not the primary installation route.

No credentials, model weights, private backups, raw screenshots or conversation history are included.

## Credits and license

Thanks to [OpenXiaoAI](https://github.com/idootop/open-xiaoai), [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx), [Codex](https://github.com/openai/codex), [aiortc](https://github.com/aiortc/aiortc) and ws. Original project material uses the [Noncommercial License](LICENSE); commercial use requires the author’s prior written authorization; third-party components retain their own licenses: [notices](THIRD_PARTY_NOTICES.md). This is an independent community project, unaffiliated with Xiaomi or OpenAI.

Earlier MIT releases retain their original terms; this change does not retroactively revoke previously granted rights. Request commercial permission through [GitHub Issues](https://github.com/samyeei/xiaoai-gpt/issues); a request is not authorization.
