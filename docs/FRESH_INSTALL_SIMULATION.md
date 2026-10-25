# 新用户安装模拟 / Fresh-user installation simulation

日期：2026-10-25。起点：公开版本 `dfe1107`。本次使用全新临时用户目录和源码副本，目录包含中文与空格，不继承作者的运行配置、环境、密钥或账号。

## 结果 / Result

安装器测试共61项通过，其中新增12项完整流程与启动入口测试。以下流程均通过模拟：

- 首次安装 → 重复运行 → 停止 → 启动 → 卸载 → 重装，身份复用且用户预设不变。
- 项目依赖安装失败后，保留可恢复状态，重试成功。
- 首次非交互 SSH 缺少指纹确认时停止；模拟用户在本机确认后可继续。
- 没有 Node 但已有 Homebrew 时，按安装流程准备 Node。
- 未登录 Codex、端口已被占用时，在接触音箱前阻止安装。
- 写入模拟音箱连接地址后中断，再次运行能恢复并继续。
- 只有连接、没有 PCM 上行时不报告安装成功，并恢复模拟音箱原地址和公钥文件。
- 对话活动时拒绝停止或卸载。
- Python 生成的配置通过真正的 Node 配置校验函数。
- `doctor`、`status`、`verify`、帮助请求即使带前置参数，也不会触发 uv 下载 Python。

## 发现并修复 / Findings fixed

1. **系统版本前置条件缺失。** 固定的 PyAV 17.1.0 arm64 wheel 名称为 `av-17.1.0-cp311-abi3-macosx_14_0_arm64.whl`。旧版只检查 Apple Silicon，会让较老 macOS 进入依赖安装乃至原生编译路径。现在明确要求 macOS 14 及以上，并使用 `--only-binary=:all:`，避免静默编译。[上游发行文件元数据](https://pypi.org/pypi/av/17.1.0/json)
2. **只读命令的参数顺序处理不完整。** `--json doctor` 等写法在 Python 未缓存时会误入 uv 下载分支。现在识别真正的子命令和参数值，提前或后置帮助标志也保持只读。回归测试先复现失败，再验证修复。

另通过小体积 PyPI 元数据查询，核对了固定依赖对 CPython3.12/macOS arm64 的 wheel 标签；没有下载或安装项目依赖。仅为读取元数据工具创建了独立临时 Python 环境，不修改已有环境。

## 隔离边界 / What was simulated

实际执行：安装器的控制流、文件权限和日志记录、配置生成、备份恢复、模型小样本哈希和原子安装、设备 shell 事务在重写后的临时路径中运行，以及 Node 的配置校验。

模拟：SSH 连接/指纹确认/密码认证和服务器强制命令、设备硬件、Codex 账号与协议输出、系统签名、launchd、pip/Homebrew 和模型下载、健康接口、PCM 音频计数。模拟命令没有回退到真实 SSH、启动项或网络服务；只读包元数据查询单独进行。

This is a higher-fidelity offline workflow simulation, not a physical clean-Mac installation. It runs the real installer helpers against a blank temporary home and a simulated OS/device boundary. Device shell transactions operate only on rewritten fixture paths. Account access, actual SSH enforcement, macOS consent/signing/launchd, real dependency/model downloads and audible conversation are still not end-to-end verified.

## 现有服务保护 / Existing-service protection

检查前后，10份受保护配置/启动项文件的内容哈希一致；9个已监听服务端口对应的进程集合一致。没有重启现有服务，没有使用真实音箱 SSH，也没有切换其连接地址。公开报告不包含实际地址、用户名、文件路径、指纹、密钥或进程编号。

The existing working speaker service was not reinstalled, restarted or rerouted. Protected configuration hashes and listening-process identities stayed unchanged. Private snapshots remain local and are not part of this repository.
