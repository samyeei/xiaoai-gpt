# Mac 安装教程

[English](INSTALL.en.md) · [首页](../README.md) · [使用教程](USAGE.zh-CN.md)

本安装器面向运行 macOS 14 及以上版本的 Apple Silicon Mac、**一台已解锁并运行兼容客户端的 LX06**。音箱解锁、刷机和 SSH 准备请参考 [OpenXiaoAI](https://github.com/idootop/open-xiaoai) 与[视频教程](https://youtu.be/JKyJdnR1uRc?si=XTlR9v1xlLO4Cw_f)；安装器不会刷机。Intel Mac、其他音箱及不同 fork 客户端未纳入这条安装路线。新 Mac 从零安装尚未独立完成端到端实机验收，自动检查不能代替听到真实回答。

## 准备与检查

Mac 需要保持登录、联网且不睡眠，并与音箱在同一可互通的局域网。准备音箱 SSH 访问、自己的 Codex 客户端和登录，以及可能需要的 macOS 授权。不要把密码、token、SSH 私钥或音箱指纹发到聊天里。先核对音箱 SSH 指纹；需要输入密码时只在可信的本机交互提示中输入。音箱客户端应能发送事件与 16 kHz 单声道 S32LE（桥接转换为供识别/实时上传使用的 S16LE） 麦克风 PCM，并支持项目使用的播放和控制消息。

```sh
git clone https://github.com/samyeei/xiaoai-gpt.git
cd xiaoai-gpt
./install.sh doctor
```

已有同名目录时先检查，勿覆盖。Agent 应先读 `AGENTS.md` 和本教程，清点系统架构、已有服务、端口、音箱当前服务器地址及回滚资料，再运行安装器。`doctor` 只检查条件，不安装依赖、不改音箱路由。安装器使用已有 Python 3.12，或通过 uv 准备受管版本；Node 22 优先使用现有版本，必要时通过**已有** Homebrew 安装。Codex 客户端和登录由用户提供；仅有文字 CLI 不保证当前客户端支持所需的实时协议。

安装器需要音箱已具备兼容客户端、可写的 SSH authorized_keys 位置及支持 command= 强制命令的 SSH 服务。若固件把这些位置设为只读，安装器会停止，不会改固件绕过；先按上游教程解决该前置条件。

安装器只安装预编译的 Python 包，不会自动回退为本机编译。固定的 PyAV 17.1.0 arm64 安装包从 macOS 14 起，因此较旧系统会先收到明确提示。

## 安装与恢复

交互安装：

```sh
./install.sh install
```

省略命令时也执行安装。安装器会询问缺少的音箱 IP，并根据到该音箱的路由自动获取 Mac 局域网 IP；无法确定时才询问 Mac 地址。也可指定 `--speaker IP --mac-ip IP --node ABS --codex ABS`。自动化调用使用 `--settings PRIVATE_JSON --non-interactive --json`；非交互模式要求通过参数或私密设置文件提供地址，并已有可信 SSH 认证，不会要求把密码写进聊天。`--json` 提供脱敏的机器可读结果。完整命令形式：

```text
./install.sh doctor|install|status|verify|start|stop|uninstall [--speaker IP --mac-ip IP --node ABS --codex ABS --settings PRIVATE_JSON --non-interactive --json]
```

安装器只配置当前项目拥有的资源：私密运行与音箱配置、独立的两套 Python 虚拟环境、已固定哈希的模型、桥接所需的 ws、受限 SSH 播放公钥、三个项目专属 LaunchAgent、已复制并签名的 Node app，以及桌面启动快捷方式。模型压缩包必须先匹配仓库跟踪的 SHA-256，解包后还要核对所需文件；安装不会改写信任清单。公开的 `config/wake-words.json`、`config/voice-commands.json` 和 `config/assistant.json` 保留用户自定义内容。主链路不需要 NAS、ESP32、BlackHole 或历史 Muse 配对。

安装可在修复阻塞后再次执行：已有身份、私密数据和有效模型会复用，不会为“重试”重生成密钥。端口、路径、现有服务、音箱路由或 SSH key 冲突应先报告并处理；勿删除旧资源来绕过检查。切换音箱客户端目的地址和添加受限公钥前应保留可恢复备份。播放公钥只允许固定 `aplay` 命令，禁用转发与 PTY。用户完成 Codex 登录和系统授权；安装器不会代做这些步骤。

## 检查、使用与卸载

```sh
./install.sh status
./install.sh verify
./install.sh start
./install.sh stop
./install.sh uninstall
```

`status` 显示脱敏状态；`verify` 会报告自动化健康状态和 `pcm_received` 音频上行标记；安装成功要求服务、连接和 PCM 上行均存在，不只看 WebSocket 是否连上。它们不能证明音箱已播出正确回答：在用户亲耳完成下列验收前，`conversation_verified` 应保持 `false`。安装器没有声称完成对话验收的命令。

1. 音箱原生“小爱同学”仍可用，目标音箱能听到短播放音。
2. 说“小爱同学”→“打开机劈替”，提一个简短问题，听到回答后回到待机；也测试“你好机劈替”直接唤醒。
3. 说“小爱同学”→“开启连续对话”，等“可以开始了”，连续问两个有关联的问题并听到各自回答。
4. 等播报结束说“退下吧”，确认告别和会话结束；播报中用“小爱同学”中断。
5. 核对停止、再次启动和登录后的自启动；偶有轻微卡顿仍是已知限制。

`start` 恢复已安装的作业。`stop` 和 `uninstall` 遇到活动中的通话会拒绝执行；请先结束通话。卸载只恢复仍保持原样的项目拥有文件、音箱路由和受限公钥，不动其他服务或 SSH key；私密状态、依赖与备份会保留，便于审计和恢复。若安装前状态已被其他人修改，按冲突提示检查，勿强行覆盖。

老的 `tools/` 脚本与手工路径替换说明用于维护和历史实验，**不是当前安装入口**；不要批量执行。问题报告先删去真实 IP、用户名、设备标识、密钥、指纹、对话和原始日志。
