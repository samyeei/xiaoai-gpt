# Agent installer implementation plan

> Implement task by task using subagent-driven-development with focused reviews. User approved the design and GitHub publication. Work only in the isolated publication checkout, never the live service root.

Goal: repository-link-to-agent installation for one unlocked LX06 on Apple Silicon macOS.
Architecture: standard-library Python stateful installer + shell bootstrap + a private runtime config read by existing Node services. Tests isolate homes/devices/external commands.
Tech: Python3.12, Node22, user launchd, SSH, pinned sherpa/aiortc/PyAV.

## Global constraints

No firmware flashing; keep private identities local; no live install during development. Reuse credentials on resume, refuse foreign/conflicting resources, fixed-command playback, checksum-before-extraction, distinguish health from human listening evidence. Preserve existing wake/model JSON customizations.

## Task 1: Portable runtime configuration

Files: mac/runtime-config.mjs and tests; mac/unified-service/index.mjs; deploy/bridge/index.mjs; deploy/bridge/multi-index.mjs; mac/realtime-voice/service.mjs; tools/start_voice_services.mjs.
- [ ] Add failing tests for private runtime config validation, paths, and Codex-only route.
- [ ] Implement loadRuntime(root): read mac/installer/private/runtime.json if present, otherwise compatible defaults. New config schema: version1, node absolute path, bridge_host private IPv4, labels {native,realtime,unified}, muse_enabled false. Do not expose keys.
- [ ] In unified use process.execPath/runtime.node, configured bridge_host; skip Muse backend/config when disabled. Use an unavailable Muse client without activating ESP32 when disabled. Keep existing legacy behavior with absent config.
- [ ] Native occupancy check remains idle, no desktop audio capture. Runtime launcher uses installed labels.
- [ ] Run Node regression tests; report changes for root review.

## Task 2: Installer core, trusted resources and device transaction

Files: install.sh, tools/install.py, tools/installer/{core,resources,device,cli}.py; tools/installer/test_*.py.
- [ ] Write failing isolated tests: IP/path validation, permissions, owned writes/refusal, resume identity reuse, interrupted writes/rollback, tar traversal/hash failure, exact SSH restriction and restoration conflicts.
- [ ] Implement bootstrap: require macOS arm64, locate Python3.12 or uv-managed Python, no curl-pipe install. Resolve Node22/Codex existing paths; install missing Node via existing brew or report actionable blocked prerequisite. Let user handle missing OS tooling/login.
- [ ] CLI lifecycle ./install.sh doctor|install|status|start|stop|uninstall|verify. Inputs --speaker, --mac-ip, --non-interactive; JSON results never include keys/passwords. No mutation in doctor/status.
- [ ] Persist private install identity, phase journal, resource backups and content hashes. Exclusive lock prevents concurrent mutations. Write generated config/templates using atomic0600 files; snapshots preserved; safe uninstall restores only owned unchanged outputs, refuses divergent external changes.
- [ ] Probe Codex login and exported experimental schema for realtime v3/WebRTC support without opening a conversation. Prepare separated environments, vendored ws, trusted model downloads and resource manifest; no global package installs.
- [ ] SSH uses verified host keys, trusted interactive terminal/mux. Back up server.txt and authorized_keys; validate LX06/client prerequisites, append fixed playback key, confirm restriction. Change only known client server.txt format, recover on failure; do not alter firmware/startup scripts.
- [ ] Generate project-owned launchd jobs, signed copied Node app identity, desktop shortcut; verify idle before stop/reload. Readiness checks do not claim human hearing. Rollback jobs/remote resources on failed activation, retain dependencies/private recovery material for resume.

## Task 3: Docs and publication

Files: README.md, README.en.md, docs/INSTALL.*, docs/USAGE.*, AGENTS.md, workflow.
- [ ] Document actual lifecycle commands, prerequisite handoffs, one-sentence agent prompt, rollback and evidence limits in both languages.
- [ ] Add installer tests to CI; run existing Node/media/ASR plus isolated installer tests. Privacy scan Git staging/history and check links.
- [ ] Focused code review of installer/state/device rollback and portability integration. Fix material issues and rerun affected checks.
- [ ] Commit and push approved work; verify remote SHA/public docs and GitHub CI. Report clean-Mac physical acceptance gap honestly.
