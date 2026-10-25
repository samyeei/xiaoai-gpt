# Configuration / 配置

See [中文使用教程](../docs/USAGE.zh-CN.md) or [English usage](../docs/USAGE.en.md) for complete examples, validation and restart instructions.

| File | Purpose / 用途 |
| --- | --- |
| assistant.json | Model, separate single/continuous reasoning, continuous voice/gain/buffer / 模型、强度、人声、音量与缓冲 |
| wake-words.json | Direct wake aliases and KWS pronunciation tokens / 直接唤醒词和发音 |
| voice-commands.json | Single, continuous and exit commands / 单问、连续、退出口令 |
| speakers.json | Example device registry, single by default / 示例设备，默认单台 |

No account credentials belong here. Actual device addresses, local paths and generated keys must remain private when sharing changes. Private configs are separate and ignored. Existing example LAN addresses and `LOCAL_USER` labels are placeholders, not working settings.

Changing commands requires restarting unified and realtime while idle. Direct-wake changes require restarting recognition/unified and checking the KWS vocabulary. The start shortcut does not reload already running jobs. Keep the 600ms audio baseline until you have real listening evidence for a change.
