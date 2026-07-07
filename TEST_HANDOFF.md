# AgentToolHub 测试 Handoff

目标：

- 让 Codex 桌面版 agent 按“真实用户拿到 zip”场景，手工验收一遍当前 `HEAD`
- 重点确认：
  - 解压即用主路径可跑
  - 初始化、CLI、Skill、MCP 主线可用
  - 最近修的边界没有回归

## 1. 先做什么

先基于当前 `HEAD` 重新打一个干净 zip，不要直接复用旧包。

在仓库根目录执行：

```bash
mkdir -p dist
git archive --format=zip --prefix=agent-tool-hub/ HEAD -o dist/agent-tool-hub-manual-test.zip
unzip -t dist/agent-tool-hub-manual-test.zip
```

预期：

- zip 生成成功
- `unzip -t` 无报错

## 2. 测试环境

建议：

- 新建一个临时目录做解压测试
- 不要直接在当前开发仓库里点点点
- 如果本机已有旧 `tool-hub` / `AgentToolDock` / `AgentToolHub` 进程，先停掉

前提：

- 本机有 `Python 3`
- 能打开浏览器

## 3. 解压即用主路径

1. 解压 `dist/agent-tool-hub-manual-test.zip`
2. 进入解压后的 `agent-tool-hub/`
3. 启动：

```bash
python3 tool_hub_server.py
```

预期：

- 服务启动成功
- 没有直接抛异常
- 默认监听 `127.0.0.1:8998`

## 4. 页面初始化

浏览器打开：

```text
http://127.0.0.1:8998
```

初始化步骤：

1. 填一个新的 `hub_path`
2. 保存配置
3. 看页面是否进入正常主界面

预期：

- 初始化成功
- 没有白屏 / 404 / 明显 JS 报错
- 页面能正常显示 agents / skills / mcp 区域

## 5. CLI 基础验收

新开终端，在解压目录执行：

```bash
python3 -m tool_hub.cli doctor
python3 -m tool_hub.cli agents list
python3 -m tool_hub.cli mcp list
```

预期：

- 不报“系统未初始化”
- `doctor` 能返回当前 hub 状态
- `agents list` 能读到刚初始化的配置

## 6. Skill 主线验收

如果本机有一个真实 Agent 的 `skills_dir`，优先用真实目录。

### gather 成功路径

执行：

```bash
python3 -m tool_hub.cli skills gather --name <skill-name> --from <绝对路径> --agent-id <agent-id>
```

预期：

- gather 成功
- skill 被移入 hub
- 原目录位置补回 symlink

### toggle 成功路径

执行：

```bash
python3 -m tool_hub.cli skills toggle --skill-id <skill-name> --agent-id <agent-id>
```

再执行一次，做开/关切换。

预期：

- 第一次能成功切换
- 第二次也能成功切回
- 不出现断链

## 7. MCP 主线验收

如果当前配置里已有 MCP，执行：

```bash
python3 -m tool_hub.cli mcp test --name <mcp-name> --no-exec
```

预期：

- 命令能跑
- 只测连通性
- 不因为测试而自动补 description

## 8. 最近修复的边界，必须手测

### upload filename 边界

在 Web 上传时，确认正常 zip 可以上传。

如果方便构造请求，再额外验证：

- multipart `filename` 不能带路径
- 不能是绝对路径
- 不能带 `..`

### gather 边界

确认以下情况会被拒绝，而不是写脏数据：

- `--agent-id` 不存在
- `--from` 不属于该 agent 的 `skills_dir`
- `--from` 目录名和 `--name` 不一致
- `--from` 本身是 symlink

### sync / scan_sync 边界

如果能方便构造一个“只有 MCP、没有 `skills_dir` 的 agent”，再验证：

- `sync()` 不会崩
- `scan_sync()` 不会崩
- 这种情况下应该记 broken / 跳过，而不是 `IndexError`

## 9. 已知非阻塞项

这次不用当阻塞：

- `scan()` 仍可能产出 `agent_id="_hub"` 的候选
- 这会带来一点 UI 体验不一致，但不是安全问题，也不是这轮主线
- 安装流程也不是这轮主线，不用优先测 `pip install`

## 10. 结果怎么回

请按这个格式回：

1. 环境
   - macOS / Python 版本
2. 通过项
   - 哪些步骤通过
3. 失败项
   - 具体命令 / 页面动作
   - 实际现象
   - 预期现象
4. 阻塞级别
   - 阻塞 / 高风险 / 非阻塞
5. 如果有问题
   - 给出最小复现路径

## 11. 优先看哪些文件

如果执行中发现问题，优先看：

- `tool_hub/services/skills.py`
- `tool_hub/services/upload.py`
- `tool_hub/http_app.py`
- `tool_hub/cli.py`
- `QUICKSTART.md`
