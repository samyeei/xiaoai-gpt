# Mac 安装教程（Agent 协助适配）

[English](INSTALL.en.md) · [首页](../README.md) · [使用和改唤醒词](USAGE.zh-CN.md)

本版发布可读、可测试的脱敏源码和安装路线，尚未提供通用安装器。部分旧工具仍有 `/Users/YOUR_USER`、`192.168.100.*` 和 `com.LOCAL_USER.*` 模板。**不要直接运行全部 tools 脚本。** Agent 应先读代码，再按下面步骤适配；不能把测试通过说成新机器实机成功。

## 1. 先准备

- 已按 [OpenXiaoAI](https://github.com/idootop/open-xiaoai) 和[视频](https://youtu.be/JKyJdnR1uRc?si=XTlR9v1xlLO4Cw_f)准备的 LX06：SSH 可登录、客户端可发送事件及16kHz单声道S16LE麦克风 PCM，并能接受播放/控制消息。刷机在本教程范围之外。
- 一台保持登录、不睡眠的 Mac；当前主路线不需要 NAS/ESP32/BlackHole。Intel Mac、其他音箱型号、新版 fork 客户端未独立验证。
- Node.js 22、Python 3.12、Git、SSH，以及可登录且能运行 `app-server` 的 Codex 客户端。Codex 的实时协议是版本相关的实验能力，需先验证本机支持；只安装普通文字 CLI 不代表实时可用。
- Mac 与音箱局域网互通，建议在路由器保留地址。设备实际地址只保存在本机，不发到公开 issue。

复制首页的一句话给 Agent 即可开始。下面也适用于手动安装者。

## 2. 下载到新目录，先读后执行

```sh
git clone https://github.com/samyeei/xiaoai-gpt.git
cd xiaoai-gpt
```

已有同名目录时先检查，不覆盖。Agent 先阅读 `AGENTS.md`、本教程和源码；记录系统/架构、Node/Python/Codex 版本、目标设备、已占用端口和既有服务。保留现有音箱启动脚本、服务器地址、authorized_keys、项目配置及启动项的私密备份。不改刷机状态，不自动接管 NAS 或另一台设备。

## 3. 安装依赖与模型

在仓库根目录执行下面的**依赖准备**，不是启动全部服务：

```sh
python3.12 -m venv .codex-runs/mac-voice-env
python3.12 -m venv .codex-runs/realtime-voice-env
.codex-runs/mac-voice-env/bin/python -m pip install -r deploy/voice/requirements.txt
.codex-runs/mac-voice-env/bin/python -m pip install -r mac/muse-service/requirements.txt
.codex-runs/realtime-voice-env/bin/python -m pip install -r mac/realtime-voice/requirements.txt
npm install --prefix deploy/bridge --ignore-scripts
```

Muse 不是主功能，但当前 unified 入口仍会启动其空闲后端并读取其配置，因此暂时保留相关依赖；无需进行 Muse 手机配对。两套 Python 环境不要混用，尤其不同 NumPy 版本。若锁定版本在你的平台无法安装，先报告具体阻塞，不静默升级 aiortc/av：媒体代码使用版本相关内部接口。

模型来源及 SHA-256 在 `deploy/models/sources.json`；文件在 Git 中跟踪，但权重不提供。`tools/prepare_voice_models.py` 可下载和解包；**运行前保留原始 sources.json 校验清单到私密暂存目录**，因为该脚本会用下载结果重写此清单。将暂存归档的 SHA-256 与原清单逐项比较，匹配后再使用权重；不把“脚本生成了新哈希”当成可信校验。许可按模型上游执行。

```sh
.codex-runs/mac-voice-env/bin/python tools/prepare_voice_models.py
```

## 4. 创建自己的配置和身份

Agent 应完成并逐项验证以下配置，任何 key 均在本机随机生成，不复制作者或他人的身份：

| 位置 | 内容和约束 |
| --- | --- |
| `config/speakers.json` | `mode: "single"`，`lx06-primary` 地址改为自己的音箱；未启用的 secondary 为示例，不能误连 |
| `config/assistant.json` | 按账号支持情况核实模型/音色；保留600ms音频缓冲基线 |
| `config/wake-words.json`、`config/voice-commands.json` | 默认先不改，成功后再按使用教程改名 |
| `mac/codex-service/private/config.json` | 用 `initializeConfig` 创建：真实绝对 Codex executable、当前 checkout 的 cwd、loopback host、4411/4412、各自独立的 key/admin_key；文件0600 |
| `mac/muse-service/private/config.json` | 用 Muse 的 `init` 生成空闲本地后端身份；不需要 token/配对 |
| `deploy/config/bridge.json` | 当前 Mac 直连桥配置；读取 `index.mjs`、`controller.mjs`、`direct-voice.mjs` 的字段，不把旧 ESP32 示例当成当前成品配置 |
| `mac/unified-service/private/realtime-voice.json` | `{"enabled":true,"idle_seconds":60,"max_session_seconds":900}` |
| `mac/unified-service/private/asr-wake.json` | 若启用本地 ASR 辅助唤醒，写 `{"enabled":true}` |

可由 Agent 调用已有初始化函数：

```sh
# 先让 CODEX_BIN 指向自己已验证的绝对可执行文件；否则初始化函数使用 which codex。
node --input-type=module -e "import {initializeConfig} from './mac/codex-service/config.mjs'; console.log(initializeConfig());"
.codex-runs/mac-voice-env/bin/python mac/muse-service/index.py init
```

这些命令遇到已有配置应保留并核对，不能删掉后重新生成以绕过问题。所有 private 目录0700，私密配置0600。

## 5. 适配 Mac 路径和音箱连接

Agent 搜索模板，而不是盲目全库替换：

```sh
rg -n 'YOUR_USER|LOCAL_USER|192\.168\.100\.' mac tools config deploy
```

至少检查 unified 入口的 Node 路径与 `BRIDGE_HOST`、LaunchAgent 标签/运行路径、连接脚本目标、桌面启动脚本。`BRIDGE_HOST` 绑定自己的 Mac LAN 地址；控制端口保持 loopback，不向公网开放。不要修改测试夹具中的示例值来“适配设备”。

先人工在终端核对音箱 SSH 指纹并登录，建立 `.codex-runs/lx06-diagnostic/control` 管理复用连接；设备专属 known_hosts 在 `.codex-runs/lx06-known-hosts`。可参考 `tools/connect_speaker_for_restore.command`，但先适配其示例 IP。密码只在终端输入。

先测试音箱 PCM/事件与 `deploy/bridge/speaker-transport.mjs` 的消息格式相符，再把**该音箱客户端**服务器地址指向 Mac 的4399端口。记录旧地址和恢复命令。不要混搭 fork 协议，不在同一端口同时启动两套桥。

## 6. 配置连续音频和常驻服务

按源码建立以下作业，但先做前台诊断，再安装自启动：

1. `mac/native-voice/supervisor.mjs`：历史兼容的空闲占用检查服务（4417）。当前主链路不应启动其桌面音频会话，也无需安装 BlackHole。
2. `mac/realtime-voice/service.mjs`：连续服务（4418），使用独立媒体虚拟环境。
3. `mac/unified-service/index.mjs`：统一管理桥接、ASR、文字任务和空闲 Muse 后端。不要同时启用旧独立 xiaoai-codex 作业，避免双启动。

`tools/install_unified_launchagent.py`、`mac/realtime-voice/install.mjs` 是模板参考，先检查路径/标签和已存在启动项。实时安装器预期用户目录内的 `Xiaoai Native Voice.app/Contents/MacOS/node`；`mac/native-voice/runtime_bundle.py` 展示如何复制并签名专用 Node 身份，**不得重签共享 Node**。其历史麦克风/BlackHole说明不等于当前主路线需要虚拟麦克风。Mac 系统若要求本地网络或其他权限，由本人确认，不声称脚本能代替系统授权。

连续播放需受限 SSH 身份。阅读 `mac/realtime-voice/provision.py` 和 `tools/provision_realtime_player.py`：在空闲、诊断管理连接已建立时，为自己的音箱添加专用公钥，只允许固定 `aplay -q -D notify -t raw -f S16_LE -c 2 -r 48000`，禁止端口/代理/X11转发和PTY。保留已有 key、备份 authorized_keys，确认强制命令生效后再使用 managed 模式；目录不可写或验证失败时停止，不修改固件绕过。

完成后让 Agent 生成自己的“启动小爱语音.command”，记录真实作业标签、日志位置、停止/重载/恢复方法。不可直接复制作者原机器的 LaunchAgents、账号或密钥。

## 7. 逐项验收

源码检查：

```sh
node --test deploy/bridge/*.test.mjs mac/codex-service/*.test.mjs mac/unified-service/*.test.mjs mac/realtime-voice/*.test.mjs
.codex-runs/realtime-voice-env/bin/python -m unittest discover -s mac/realtime-voice -p 'test_*.py'
.codex-runs/mac-voice-env/bin/python -m unittest discover -s deploy/voice -p 'test_*.py'
```

最后一组需先下载 KWS 词表。测试通过只证明代码回归，以下必须真人确认：

- 音箱在线，原生小爱仍可用；播放两声提示音可听见。
- “小爱同学→打开机劈替→一加一等于几”只回答本机，完成后回待机。
- “小爱同学→开启连续对话”，只说一次就接通；先问一加一，再追问再加一，分别回答二、三。
- 等播报结束说“退下吧”，同一人声告别且真正退出；播报中叫“小爱同学”能停止。
- 长回答、两次追问及空闲超时；检查是否有明显断字。偶有轻微卡顿是已知限制。
- 验证停止与恢复，再验用户登录后的自启动。全新 Mac 恢复、长时无人值守不能从一次通话推定成功。

任何一项失败都记录为未通过，不掩盖为“安装成功”。日志/测试录音如需保留，只能在本机私密目录；公开问题报告先脱敏。
