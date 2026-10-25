# Validation / 验证边界

## Agent installer, 2026-10-25

- Installer regressions: 48 passed (isolated homes, local fixtures and fake external-command/device boundaries).
- Node regressions: 178 passed.
- Python media regressions: 61 passed.
- Python voice/recognition regressions: 39 passed; the installed KWS vocabulary was temporarily supplied for the vocabulary test and removed afterward.
- Actual local read-only doctor: Apple Silicon/Python3.12/Codex experimental realtime schema supported; occupied service ports detected. No installer takeover, speaker switch, SSH provisioning, dependency download or launchd modification was performed against the existing working setup.
- Final code review covered ownership, resume, failure recovery, restricted playback, model integrity, runtime portability and bilingual instructions. No material blockers remained at handoff.

CI runs Node and standard-library installer regressions, not real audio, accounts, macOS permissions or device SSH. See the workflow run associated with the exact published commit for its current result.

## What is still unverified / 尚未验证

A clean Mac installation, real dependency downloads on another machine, system permission prompts, real SSH key provisioning and full audible end-to-end acceptance of the new installer still need a supported Mac and unlocked LX06. Tests do not prove those external outcomes. The pre-existing personal Mac/LX06 voice route was usable with occasional light stutter; it is not full duplex or guaranteed zero-lag.

自动化安装成功要求服务就绪、音箱连接和PCM上行；`conversation_verified`仍为false，不能替代真人听到正确答案、追问及退出的验收。真实地址、登录、密钥、私密备份、原始截图和对话历史不属于公开仓库。
