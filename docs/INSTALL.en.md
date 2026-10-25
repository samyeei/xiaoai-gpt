# Mac installation (agent-assisted adaptation)

[中文](INSTALL.zh-CN.md) · [Home](../README.en.md) · [Usage and wake words](USAGE.en.md)

This release provides sanitized, testable source and an installation path, not a universal installer. Some tools still contain `/Users/YOUR_USER`, `192.168.100.*`, and `com.LOCAL_USER.*` templates. **Do not run every script in tools.** An agent must inspect and adapt them. Passing unit tests does not prove a clean Mac/device installation works.

## 1. Prerequisites

- An LX06 already prepared using [OpenXiaoAI](https://github.com/idootop/open-xiaoai) and [the video guide](https://youtu.be/JKyJdnR1uRc?si=XTlR9v1xlLO4Cw_f): SSH access, a client emitting native events and 16kHz mono S16LE microphone PCM, and compatible playback/control messages. Flashing is outside this guide.
- A Mac kept awake, logged in and online. No NAS, ESP32 or BlackHole is needed for the main route. Intel Macs, other speaker models and newer fork clients have not been independently validated.
- Node.js 22, Python 3.12, Git, SSH, and an authenticated Codex client supporting `app-server`. Realtime is an experimental, version-dependent protocol: validate the installed client's support first. A working text CLI alone is insufficient.
- LAN connectivity between speaker and Mac; a DHCP reservation is helpful. Keep actual addresses private.

Give your agent the one-sentence prompt on the README. The following also guides manual installation.

## 2. Clone separately and inspect

```sh
git clone https://github.com/samyeei/xiaoai-gpt.git
cd xiaoai-gpt
```

Inspect an existing directory rather than overwriting it. Read `AGENTS.md`, this guide and the relevant source. Inventory OS/architecture, runtime/Codex versions, target device, occupied ports and existing jobs. Privately back up the speaker startup script, server destination, authorized_keys, configuration and installed jobs. Do not flash, take over a NAS connection or modify another speaker automatically.

## 3. Dependencies and models

From the repository root, prepare dependencies; these commands do not start the full stack:

```sh
python3.12 -m venv .codex-runs/mac-voice-env
python3.12 -m venv .codex-runs/realtime-voice-env
.codex-runs/mac-voice-env/bin/python -m pip install -r deploy/voice/requirements.txt
.codex-runs/mac-voice-env/bin/python -m pip install -r mac/muse-service/requirements.txt
.codex-runs/realtime-voice-env/bin/python -m pip install -r mac/realtime-voice/requirements.txt
npm install --prefix deploy/bridge --ignore-scripts
```

Muse is not the main feature, but unified currently starts its idle backend and reads its configuration, so its dependencies are still required. Do not pair a Muse phone/device. Keep the two Python environments separate, especially their NumPy versions. If a pinned wheel is unavailable on your platform, report it instead of silently upgrading aiortc/av: media code relies on version-specific internal APIs.

Model URLs and SHA-256 values are in tracked `deploy/models/sources.json`; weights are not included. **Save the original manifest to private staging before running the download script**, which rewrites the manifest with computed download hashes. Compare every downloaded archive with the saved original hash before using extracted weights. A newly computed hash alone is not trusted verification. Follow upstream model licenses.

```sh
.codex-runs/mac-voice-env/bin/python tools/prepare_voice_models.py
```

## 4. Generate your own configuration and identity

| Location | Required setup |
| --- | --- |
| `config/speakers.json` | Keep `mode: "single"`; set your own `lx06-primary` address. The unused secondary is an example, not another target to connect |
| `config/assistant.json` | Check account model/voice support; retain the 600ms output baseline |
| `config/wake-words.json`, `config/voice-commands.json` | Keep defaults for initial acceptance; customize later |
| `mac/codex-service/private/config.json` | Generate through `initializeConfig`: verified absolute Codex executable, this checkout's cwd, loopback host, ports4411/4412, separate random key/admin_key; mode0600 |
| `mac/muse-service/private/config.json` | Generate the idle backend identity with `init`; no token/pairing needed |
| `deploy/config/bridge.json` | Build the current direct-Mac configuration by reading index/controller/direct-voice source. The legacy ESP32 example is not a completed Mac configuration |
| `mac/unified-service/private/realtime-voice.json` | `{"enabled":true,"idle_seconds":60,"max_session_seconds":900}` |
| `mac/unified-service/private/asr-wake.json` | `{"enabled":true}` if local ASR-assisted wake is enabled |

Use the existing initialization functions after inspecting them:

```sh
# Set CODEX_BIN to your verified absolute executable; otherwise initializeConfig uses which codex.
node --input-type=module -e "import {initializeConfig} from './mac/codex-service/config.mjs'; console.log(initializeConfig());"
.codex-runs/mac-voice-env/bin/python mac/muse-service/index.py init
```

Preserve and inspect existing configuration. Never delete it to bypass an initialization error. Private directories should be0700 and private files0600. Generate identities locally; never copy the author's or another person's credentials.

## 5. Adapt Mac paths and connect the speaker

Search templates and inspect each occurrence rather than applying a blind global replacement:

```sh
rg -n 'YOUR_USER|LOCAL_USER|192\.168\.100\.' mac tools config deploy
```

Check the unified Node path and `BRIDGE_HOST`, LaunchAgent labels/paths, connection-script target and desktop launcher. Bind `BRIDGE_HOST` to your Mac LAN address. Keep control endpoints on loopback; do not expose them publicly. Test fixtures should keep example addresses.

In a trusted terminal, personally verify the speaker SSH fingerprint and log in. Establish the management multiplex socket `.codex-runs/lx06-diagnostic/control` with project-specific `.codex-runs/lx06-known-hosts`. `tools/connect_speaker_for_restore.command` is a reference only: adapt its example IP first. Passwords belong in terminal prompts, not chat.

Verify microphone/events against `deploy/bridge/speaker-transport.mjs` before pointing that speaker client's server destination to the Mac on port4399. Record the old destination and restore procedure. Do not mix incompatible fork protocols or start two bridges on the same port.

## 6. Continuous audio and background jobs

Diagnose in the foreground before installing these background jobs:

1. `mac/native-voice/supervisor.mjs`: idle legacy compatibility/occupancy check on4417. Do not start its desktop-audio session for the main route. BlackHole is not required.
2. `mac/realtime-voice/service.mjs`: continuous voice on4418, using the dedicated media Python environment.
3. `mac/unified-service/index.mjs`: bridge, ASR, text tasks and idle Muse backend. Do not also enable the legacy standalone xiaoai-codex job, which duplicates the text service.

Inspect and adapt `tools/install_unified_launchagent.py` and `mac/realtime-voice/install.mjs` before use. The realtime installer expects a user-owned `Xiaoai Native Voice.app/Contents/MacOS/node`. `mac/native-voice/runtime_bundle.py` shows how to copy/sign a dedicated Node identity; never re-sign shared Node. Its historical microphone/BlackHole description does not make a virtual microphone necessary for the main route. Let the user approve any required macOS local-network or other permissions; scripts cannot grant OS consent.

Continuous playback needs a restricted SSH identity. Read `mac/realtime-voice/provision.py` and `tools/provision_realtime_player.py`. While idle and using the established management connection, add a dedicated public key permitting only `aplay -q -D notify -t raw -f S16_LE -c 2 -r 48000`, with no port/agent/X11 forwarding or PTY. Preserve existing keys and back up authorized_keys. Verify forced-command enforcement before managed mode. Stop if the target is read-only or verification fails; do not modify firmware to bypass it.

Have your agent create a local desktop start shortcut and record the actual job labels, log locations, stop/reload commands and rollback. Never copy another machine's LaunchAgents, login or private keys.

## 7. Acceptance

Run source regressions:

```sh
node --test deploy/bridge/*.test.mjs mac/codex-service/*.test.mjs mac/unified-service/*.test.mjs mac/realtime-voice/*.test.mjs
.codex-runs/realtime-voice-env/bin/python -m unittest discover -s mac/realtime-voice -p 'test_*.py'
.codex-runs/mac-voice-env/bin/python -m unittest discover -s deploy/voice -p 'test_*.py'
```

The ASR suite needs the KWS vocabulary downloaded first. Unit tests do not replace these human checks:

- Speaker connected; native XiaoAI works; two short playback tones are audible.
- Native wake → single command → “what is one plus one?” answers on the intended speaker, then returns idle.
- Native wake → continuous command connects on the first attempt; “one plus one?” then “plus one more?” answers two then three.
- After output finishes, the exit command produces one farewell in the same voice and really closes the session. Native XiaoAI wake stops playback.
- A long answer, two follow-ups and idle timeout work. Check actual speech for clipped words; occasional light stutter is known.
- Verify stop/restore, then autostart after user login. One successful call does not prove full-machine recovery or unattended reliability.

Mark failed items as failed rather than declaring installation complete. Keep any diagnostic audio/logs private and redact issue reports.
