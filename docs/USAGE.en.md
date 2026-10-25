# Usage: commands, model and maintenance

[中文](USAGE.zh-CN.md) · [Home](../README.en.md)

Complete [installation and real-device acceptance](INSTALL.en.md) first. Keep the Mac logged in, awake and online, and keep the speaker client connected to the Mac bridge. A desktop start shortcut recovers stopped jobs; it does not reload configuration. Use `./install.sh status` for redacted installed state.

## Conversations

1. Single question: say “你好机劈替”, wait for the prompt, then ask. Alternatively say “小爱同学”, wait for its response, then “打开机劈替”. The service returns to idle after answering.
2. Continuous: say “小爱同学”, wait, then “开启连续对话”. Wait for “可以开始了”, ask, and wait until each answer finishes before following up. No desktop voice button is needed. Do not repeat the start command during connection.
3. Exit: after playback finishes, say “退下吧”. It should say goodbye in the same voice and exit. During playback, use the native “小爱同学” wake phrase to stop it first.

## Change direct wake words

Edit an existing Codex route in `config/wake-words.json`. Keep its `label` and `backend`; change `phrases`, `kws_tokens`, and `enabled`. The `HEY_GPT` label currently means the spoken Chinese name “你好机劈替”; the label is not the spoken phrase.

```json
{
  "label": "HEY_GPT",
  "backend": "codex",
  "enabled": true,
  "phrases": ["你好机劈替", "你好GPT"],
  "kws_tokens": ["n", "í", "h", "ǎo", "j", "ī", "p", "ī", "t", "ì"]
}
```

This is one route, not the entire file. `phrases` contains ASR text aliases; `kws_tokens` contains pronunciation tokens from the selected KWS vocabulary (`deploy/models/kws/tokens.txt`). Arbitrary characters, romanization or regular expressions are not valid replacements. Have your agent check the vocabulary and keyword-generation code. Use shadow recognition to evaluate uncertain names; never invent tokens.

This file does not rename the speaker's native “小爱同学” wake word. Test any new language/name, accent and distance. Historical `HEY_LUKA` and `HEY_CODEX` routes are disabled by default; the Muse route is not part of the current Codex feature set.

## Change single/continuous/exit commands

Edit `config/voice-commands.json`:

```json
{
  "version": 1,
  "single": ["打开机劈替", "打开GPT"],
  "continuous": ["开启连续对话", "打开连续对话"],
  "exit": ["退下吧", "结束对话"]
}
```

Add each alias separately. Matching uses the normalized whole utterance (case, whitespace and common punctuation), not an arbitrary substring. These are literal strings, not regexes. Groups must not overlap, including cross-group conflicts with concatenated continuous commands. Up to three concatenated continuous aliases are accepted. Each group allows up to 32 entries of 1–80 characters. `exit` must not be empty; the other groups may be empty. English aliases are possible but require actual ASR testing.

Validate before restarting:

```sh
node --input-type=module -e "import {loadVoiceCommands} from './deploy/bridge/voice-commands.mjs'; loadVoiceCommands(); console.log('OK');"
```

## Model, voice and volume

Edit `config/assistant.json`:

```json
{
  "version": 1,
  "model": "gpt-5.6-luna",
  "reasoning_effort": "high",
  "single_reasoning_effort": "medium",
  "voice": "maple",
  "output_gain": 4,
  "output_buffer_ms": 600
}
```

`single_reasoning_effort` affects single questions; if omitted it inherits `reasoning_effort`, which also controls continuous mode. Confirm model/voice support in your installed client and account before changing them. Saving JSON does not prove runtime availability. Voice, gain and buffering primarily affect continuous output; single questions use the speaker's native TTS and may sound different. Larger gain/buffers can make performance worse.

## Restart, stop and rollback

End conversations first, then run `./install.sh stop` and `./install.sh start` from the checkout to load changed commands, wake words, model or voice settings. `stop` refuses an active conversation. Run `./install.sh verify` for automated health and repeat the affected real speech checks; `verify` cannot prove that you heard a correct answer. The installer records and uses this Mac's actual LaunchAgent labels. `com.LOCAL_USER.*` in older source is only a template.

Use `./install.sh uninstall` to remove the project-owned installation; it also refuses an active conversation. It restores only unchanged resources it owns and retains private state, dependencies and backups. Do not kill every Node/Python process or delete all SSH keys. If someone changed the speaker route or authorized_keys afterward, inspect the conflict instead of forcing an overwrite.

## Troubleshooting

- No wake: try native “小爱同学 → 打开机劈替”; check client connection, microphone PCM and vocabulary before tuning thresholds.
- Input works, output silent: test restricted SSH playback, host-key verification and `aplay` before changing models.
- Start command becomes an ordinary question: inspect command config, full ASR utterance, and whether both services were reloaded.
- Stutter: inspect Wi-Fi, SSH output and WebRTC loss; retain the 600ms baseline. Occasional light stutter is known.
- Cannot exit: wait until playback ends; interrupt playback with native XiaoAI wake. Use authenticated local controls to stop if needed.

Remove actual IPs, usernames, device IDs, tokens/keys, conversations and SSH fingerprints before filing issues. Never upload private directories or full raw logs.
