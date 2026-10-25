# Agent-assisted one-command installation design

Status: approved by the user on 2026-10-25; implemented with isolated regression tests. Clean-Mac physical acceptance remains pending. Scope: Mac + one already-unlocked LX06, retaining the working voice behavior. No firmware flashing, NAS deployment or Windows support in this milestone.

## User outcome

A new user sends the repository link and “install this on my Mac” to a local agent. AGENTS.md directs the agent to one supported installation entry point. The installer gathers missing local values, performs repeatable setup, starts the service and reports acceptance results separately from unresolved human checks. It must not require the agent to rewrite source code or invent private JSON schemas.

The user still performs their own Codex login, SSH password/fingerprint verification and any macOS permissions. The installer never requests passwords in chat or claims to bypass OS consent.

## Alternatives

1. Recommended: a stateful local installer with structured status and an agent contract. Repeatable, inspectable, supports resume and rollback.
2. Documentation-only agent adaptation: less code, but each agent may make different edits; this is the current release and does not meet the new automation objective.
3. A full signed graphical Mac application: friendlier standalone UI, but adds packaging/signing/distribution work beyond this milestone.

## Installation entry point

Provide one documented bootstrap entry that locates or prepares the supported Python runtime, then invokes the installer. Its lifecycle interface covers doctor, install/resume, start, stop, status and uninstall. Noninteractive invocation accepts a private local settings file; interactive invocation asks only for missing values. Agent-readable output is structured and redacts secrets. Missing prerequisites that require user action produce an explicit blocked step rather than false success.

Installation stages:

1. Inspect OS/architecture, runtime availability, Codex authentication/protocol support, target device and occupied ports. First supported baseline is the existing Apple Silicon Mac route; unsupported combinations fail clearly.
2. Collect speaker address and Mac LAN interface locally. Do not choose a device by blind network takeover. Create a local install identity and record owned resources.
3. Prepare isolated Node/Python dependencies and models, with pinned source hashes verified before extraction/use. Do not silently upgrade aiortc/av or rewrite the trusted checksum manifest.
4. Generate private service settings, random credentials and feature flags from versioned templates. Resolve executable/home/check-out paths dynamically. Preserve public wake/model configuration customization. Keep controls on loopback.
5. Establish user-verified SSH management access, back up target settings and provision only a fixed-command playback identity. Preserve existing keys and host checking. Check the installed speaker client protocol before changing its server destination; do not flash or silently install an incompatible client.
6. Install project-owned user LaunchAgents and a desktop start shortcut. Start the required idle compatibility, realtime and unified services without enabling a duplicate standalone text service. Avoid requiring historical Muse pairing or BlackHole. Retain only runtime dependencies necessary for this supported route.
7. Verify service readiness, actual speaker connection, PCM ingress and restricted playback. Ask the user to confirm audible prompts and single/continuous/exit behavior. Distinguish installed, connected and conversation-verified states.

## Idempotency and rollback

Private install state records completed stages, resource ownership and backup locations. A repeat invocation reuses existing credentials and identity, checks compatibility and continues instead of overwriting. Conflicting existing services/configuration cause an explicit diagnostic. Never stop an active conversation automatically to update.

Before speaker route or authorized_keys changes, save a recoverable private snapshot. Failure restores only changes owned by this install where safe; do not overwrite concurrent external edits. Uninstall removes owned jobs/entries and can restore the prior speaker route. Preserve user data/backups by default; no blanket process killing or SSH key deletion.

## Configuration portability

Replace production runtime assumptions about YOUR_USER, LOCAL_USER, example addresses and fixed home paths with explicit resolved installation settings. Do not modify fixture addresses or the live development setup. A new install must use the existing JSON wake/command/model controls without source edits.

## Evidence and acceptance

- Unit tests exercise clean install planning, resume, missing prerequisites, conflicting ports/resources, configuration validation/permissions, secret redaction and rollback ownership.
- Integration tests use isolated home directories and fake external commands to prove generated launchd/config artifacts and ordered failure recovery without touching real devices.
- Existing voice regressions remain passing.
- CI covers deterministic source/installer tests. It cannot prove macOS permissions, real account access, SSH authentication or audible voice.
- End-to-end acceptance needs a clean supported Mac and an unlocked LX06. Until available, report implementation/test evidence and this remaining hardware gap explicitly; do not call it universally one-click or fully unattended.

## Documentation/publication

Update Chinese and English READMEs, installation tutorials and AGENTS.md to the actual installer interface. Keep upstream OpenXiaoAI/video links and demo. Publish code only after staged/history privacy scans and relevant tests. Do not execute the installer against the current working services during development.
