# Publication validation / 发布验收边界

Public source preparation, 2026-10-25:

- Node regressions: 170 passed.
- Python media regressions: 59 passed.
- Python voice/recognition regressions: 39 passed; the existing local KWS vocabulary was temporarily supplied for the vocabulary test, then removed from publication.
- Private-value scan and local Markdown link check passed before publication. No raw screenshots, private backups, credentials, model weights or conversation histories are included.
- Tests used the already installed local runtimes; they do not establish that dependency installation works on every new Mac. GitHub CI covers Node source regressions only, not device audio, account authentication or Mac permissions.

此前真人可用的 Mac/LX06 方案接受偶有轻微卡顿。本次发布只整理脱敏源码、教程和许可，未改动现有音箱服务。新 Mac 全新安装、完整恢复及其他音箱型号仍需单独验收；不能把单元测试当成音箱实际出声证明。
