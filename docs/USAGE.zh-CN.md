# 使用教程：口令、模型和维护

[English](USAGE.en.md) · [回首页](../README.md)

先完成[安装和实机验收](INSTALL.zh-CN.md)。Mac 要保持登录、联网且不睡眠，音箱需连接到 Mac 桥接服务。桌面启动快捷方式只恢复停止的作业，不等于重新加载配置。

## 对话

1. 单问：说“你好机劈替”，等提示后再提问。或“小爱同学”回应后说“打开机劈替”。回答完自动回待机。
2. 连续：先“小爱同学”，回应后说“开启连续对话”。等“可以开始了”再说话，听完再追问。不必手点桌面语音按钮，也不要连接时反复重复口令。
3. 退出：等播报结束，说“退下吧”。会用原声音告别再退出。若正在播放，先叫“小爱同学”停止。

## 改直接唤醒词

编辑 `config/wake-words.json` 中现有 Codex 路由，保留其 `label` 和 `backend`，修改 `phrases`、`kws_tokens`、`enabled`。例如当前 `HEY_GPT` 的名字是“你好机劈替”，不是固定英语 hey GPT。

```json
{
  "label": "HEY_GPT",
  "backend": "codex",
  "enabled": true,
  "phrases": ["你好机劈替", "你好GPT"],
  "kws_tokens": ["n", "í", "h", "ǎo", "j", "ī", "p", "ī", "t", "ì"]
}
```

这是单个路由示例，不能覆盖整个文件。`phrases` 是识别文本别名；`kws_tokens` 是所选 KWS 模型的发音 token，需要与 `deploy/models/kws/tokens.txt` 一致。不是任意汉字、拼音字符串或正则。让 Agent 检查词表和现有关键词生成代码，不确定发音时先做影子识别，切勿编造 token。

原生“小爱同学”不能通过本文件更名。新名字、远距离和方言效果都要实测。历史 `HEY_LUKA`、`HEY_CODEX` 默认关闭；Muse 路由不是当前 Codex 功能。

## 改单问、连续和退出口令

编辑 `config/voice-commands.json`，例如：

```json
{
  "version": 1,
  "single": ["打开机劈替", "打开GPT"],
  "continuous": ["开启连续对话", "打开连续对话"],
  "exit": ["退下吧", "结束对话"]
}
```

每个别名单独一项；按规范化后的完整句匹配，统一大小写、空白和常见标点，不是任意子串命中。口令是字面文本，不是正则。三组不得重名或形成跨组连续口令拼接冲突；连续口令兼容最多三个配置词的连续拼接。每组最多32项，每项1–80字符；exit至少一项，其他两组可为空。

先校验：

```sh
node --input-type=module -e "import {loadVoiceCommands} from './deploy/bridge/voice-commands.mjs'; loadVoiceCommands(); console.log('OK');"
```

## 改模型、人声、音量

编辑 `config/assistant.json`：

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

`single_reasoning_effort` 只改单问，省略时继承 `reasoning_effort`；后者用于连续。更换模型或音色前核实当前客户端及账号支持，不能仅凭配置保存成功判断可用。`voice`、增益和缓冲主要针对连续语音；单问由音箱原生 TTS 播报，人声可能不同。不要盲目增大增益或缓冲：曾出现更慢、更卡的情况。

## 重启与维护

先退出所有通话。改控制口令要重启 unified 和 realtime；改唤醒词要重启 unified（含识别子进程）；改模型/人声重启 unified 和 realtime。安装时让 Agent 记录真实 LaunchAgent 标签；源码的 `com.LOCAL_USER.*` 只是模板。使用自己的 `id -u`，不要复制别人的用户编号。

停止、重载和卸载只能操作本项目实际安装的作业，不要批量杀 node/python 或删除所有 SSH key。先停止连接，再恢复安装前备份的音箱客户端服务地址；只删除本项目新增的受限播放公钥条目，保留原有 key 和 known_hosts。

## 排查

- 没唤醒：先测“小爱同学→打开机劈替”；检查音箱客户端在线、麦克风 PCM 和词表，再调阈值，别同时改多个参数。
- 能听不能播：检查受限 SSH 播放、host key 和 `aplay`，不要先改模型。
- 进入口令被当普通问题：检查 voice-commands、ASR 完整文本、unified/realtime 是否均已重载。
- 卡顿：检查 Wi-Fi、SSH 下行和 WebRTC 丢包，保持600ms基线；偶有轻微卡顿属于已知限制。
- 退不出：等播报结束再说；播放中用“小爱同学”停止，必要时本机受认证控制界面停止。

报告问题前删除真实 IP、用户名、设备标识、key/token、对话内容和 SSH 指纹。不要上传 private 目录或完整日志。
