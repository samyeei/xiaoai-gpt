# Privacy and security / 隐私与安全

This repository contains example configuration only. Generate your own local identities. Do not commit `private/`, `.codex-runs/`, `.env`, SSH keys, known_hosts, login/session history, raw screenshots or backups. Keep private directories0700 and files0600. Control services belong on loopback, not the public Internet. The speaker connection is intended for a trusted LAN; it is not a hardened public multi-tenant service.

公开提交和 issue 中不得包含真实 IP、用户名、本机路径、设备指纹、账号、token、密钥、对话或未脱敏截图。Git ignore 不能删除已提交的历史；提交前检查暂存区和历史。如已泄漏，先撤销/轮换身份，再处理历史。

Playback keys must be restricted to the fixed aplay command with forwarding/PTY disabled. Preserve existing authorized_keys and verify host identity. Never disable strict host-key checking to hide a connection error.

Do not post exploitable security details or secrets in a public issue. For a leaked credential, revoke/rotate it locally before discussing a redacted report. This project does not operate a credential collection service.
