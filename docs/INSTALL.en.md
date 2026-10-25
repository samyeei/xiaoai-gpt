# Mac installation

[中文](INSTALL.zh-CN.md) · [Home](../README.en.md) · [Usage](USAGE.en.md)

The installer supports an Apple Silicon Mac with **one already-unlocked LX06 running a compatible client**. For unlocking, flashing, and SSH preparation, follow [OpenXiaoAI](https://github.com/idootop/open-xiaoai) and [the video guide](https://youtu.be/JKyJdnR1uRc?si=XTlR9v1xlLO4Cw_f); this installer never flashes firmware. Intel Macs, other speakers, and other fork clients are outside this installation route. A clean Mac installation has not yet passed independent end-to-end real-device acceptance. Automated health cannot prove that a person heard a correct answer.

## Prepare and inspect

Keep the Mac logged in, awake, online, and reachable from the speaker over the LAN. Prepare speaker SSH access, your own Codex client and login, and any needed macOS permissions. Never put passwords, tokens, SSH private keys, or host fingerprints in chat. Verify the speaker's SSH host key yourself; enter a password only in a trusted local prompt. Its client should emit events and 16 kHz mono S32LE microphone capture frames (the bridge converts these to S16LE for recognition/realtime) and support the playback and control messages this project uses.

```sh
git clone https://github.com/samyeei/xiaoai-gpt.git
cd xiaoai-gpt
./install.sh doctor
```

Inspect an existing checkout before using it; do not overwrite it. An agent should read `AGENTS.md` and this guide, inventory the architecture, existing services and ports, current speaker server destination, and rollback materials before invoking the installer. `doctor` only inspects prerequisites; it does not install dependencies or change the speaker route. The installer uses an existing Python 3.12 or prepares a managed one with uv. It finds Node 22 or installs it through an **existing** Homebrew installation. You provide the Codex client and login. A working text CLI alone does not establish support for the required realtime protocol.

The speaker must already have a compatible client, a writable SSH authorized_keys location and an SSH server enforcing command= restrictions. If firmware makes that location read-only, installation stops rather than modifying firmware; resolve that prerequisite using upstream guidance first.

## Install and resume

For interactive installation:

```sh
./install.sh install
```

Omitting the command also selects installation. The installer asks for the speaker address locally and infers the Mac LAN address from its route to that speaker; if inference fails it asks for the Mac address too. You may provide `--speaker IP --mac-ip IP --node ABS --codex ABS`. Automation can use `--settings PRIVATE_JSON --non-interactive --json`; noninteractive mode requires addresses supplied as flags or a private settings file, and existing trusted SSH authentication. It never asks for a password in chat. `--json` produces redacted machine-readable output. The complete command form is:

```text
./install.sh doctor|install|status|verify|start|stop|uninstall [--speaker IP --mac-ip IP --node ABS --codex ABS --settings PRIVATE_JSON --non-interactive --json]
```

The installer configures only resources owned by this project: private runtime and speaker configuration, two separate Python environments, models checked against pinned hashes, the bridge's ws dependency, a restricted SSH playback key, three project-specific LaunchAgents, a copied and signed Node app, and a desktop start shortcut. Model archives must match tracked SHA-256 values before extraction, then required model files are checked; the trust manifests are never rewritten. Your public `config/wake-words.json`, `config/voice-commands.json`, and `config/assistant.json` customizations are preserved. The primary route needs no NAS, ESP32, BlackHole, or historical Muse pairing.

Run installation again after resolving a blocked step. Existing identities, private data, and valid models are reused instead of regenerating credentials. Report and resolve conflicts with ports, paths, services, speaker routing, or SSH keys; do not erase existing resources to bypass checks. Keep a recoverable backup before changing the speaker-client destination or adding the restricted key. The playback key permits only the fixed `aplay` command and disables forwarding and PTY. You complete Codex login and OS permission prompts yourself.

## Check, use, and uninstall

```sh
./install.sh status
./install.sh verify
./install.sh start
./install.sh stop
./install.sh uninstall
```

`status` shows redacted state. `verify` reports automated health and a `pcm_received` ingress flag; successful installation requires connected services and incoming PCM, not only an open WebSocket. Neither proves the speaker delivered a correct answer: `conversation_verified` remains `false` until a human completes the following real-device checks. There is no CLI attestation command for conversation acceptance.

1. Native “小爱同学” still works, and short test audio is audible on the intended speaker.
2. Say “小爱同学” → “打开机劈替”, ask a short question, hear its answer, and confirm return to idle. Also test direct “你好机劈替” wake.
3. Say “小爱同学” → “开启连续对话”, wait for “可以开始了”, then ask two related questions and hear both answers.
4. After playback, say “退下吧” and confirm the farewell and session exit. During playback, interrupt with “小爱同学”.
5. Check stop, start, and autostart after login. Occasional light stutter remains a known limitation.

`start` resumes installed jobs. `stop` and `uninstall` refuse to act during an active conversation; end it first. Uninstall restores only unchanged, project-owned files, speaker routing, and the restricted public key. It retains private state, dependencies, and backups for audit and recovery. If someone has since changed a pre-install resource, inspect the reported conflict instead of forcing an overwrite.

Older `tools/` scripts and manual path-rewriting instructions are for maintenance and historical experiments; **they are not the current installer entrypoint**. Redact actual IPs, usernames, device IDs, keys, fingerprints, conversations, and raw logs before reporting a problem.
