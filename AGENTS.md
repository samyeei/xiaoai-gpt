# Agent installation contract

Read README.md (Chinese) or README.en.md, then docs/INSTALL.zh-CN.md or docs/INSTALL.en.md before executing tools.

- This is a sanitized source release, not a universal installer. Inspect templates and adapt them to the user's Mac. Do not claim a script completed installation unless real-device acceptance succeeds.
- Default to one LX06 (`mode: single`). Preserve existing services, device configuration, server destinations, SSH identities and rollback. Do not switch a NAS/device route without the user's installation authorization and a recoverable backup.
- Firmware unlocking/flashing is delegated to upstream OpenXiaoAI and the linked video; do not flash automatically.
- Obtain credentials through trusted local interactive prompts. Let the user perform Codex login and OS permissions. Never request passwords in chat or copy another user's authentication.
- Generate private configuration locally (0700 directories,0600 files). Keep control endpoints on loopback. Never expose admin_key, tokens, SSH keys/fingerprints, actual addresses, usernames, conversations or raw screenshots in commits/log excerpts/issues.
- Inspect each YOUR_USER/LOCAL_USER/example-IP occurrence; do not replace test fixtures indiscriminately. Do not run every historical tools script.
- Keep Python voice/media environments separate. Preserve pinned aiortc/av versions unless a deliberate tested migration is requested. Save the model hash manifest before downloading and compare the archives with the original hashes.
- Use only a fixed-command, forwarding-disabled playback SSH key. Preserve other authorized_keys entries and verify forced-command behavior.
- End calls before reloading. Do not enable the old standalone text service beside unified. Do not kill unrelated Node/Python processes.
- Report source tests, network connection, audible playback and real conversational acceptance separately. A health endpoint is not proof that the user heard an answer.
- At handoff record actual installed job labels, start/stop/reload/rollback commands, supported models/client versions, and unresolved limitations without secrets.
