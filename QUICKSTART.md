# AgentToolHub 最小发布说明

结论：

- 这是个“解压即用”的本机工具。
- 默认只在本机 `127.0.0.1` 上跑。
- 不需要先走安装流程，进目录直接启动就行。

## 1. 怎么解压即用

前提：

- 本机有 `Python 3`
- 进入项目根目录

直接启动 Web：

```bash
python3 tool_hub_server.py
```

或用模块命令启动：

```bash
python3 -m tool_hub.cli web --host 127.0.0.1 --port 8998 --no-browser
```

启动后打开：

```text
http://127.0.0.1:8998
```

如果只想先做环境确认：

```bash
python3 -m tool_hub.cli doctor
```

## 2. 怎么初始化

第一次用时，按这个顺序：

1. 启动 Web
2. 打开页面
3. 设置 `hub_path`
4. 保存初始化配置
5. 确认 Agent 是否自动检测出来

`hub_path` 是中央仓库目录。

建议：

- 用一个单独目录，比如 `~/agent-tool-hub`
- 不要直接指到某个 Agent 自己的 `skills_dir`

如果 Agent 没自动识别：

- 先确认该 Agent 的 `skills_dir` 真实存在
- 再在页面里手动补 Agent

## 3. 常见命令

常用 CLI：

```bash
python3 -m tool_hub.cli doctor
python3 -m tool_hub.cli agents list
python3 -m tool_hub.cli mcp list
python3 -m tool_hub.cli mcp test --name playwright --no-exec
python3 -m tool_hub.cli skills gather --name demo --from /abs/path/demo --agent-id codex
python3 -m tool_hub.cli skills toggle --skill-id demo --agent-id cursor
python3 -m tool_hub.cli web
```

几个关键语义：

- `agents list`：看当前已配置 Agent
- `mcp test --no-exec`：只测连通性，不自动拉 tools 描述
- `skills gather`：把某个 Agent 目录里的 skill 收进 Hub
- `skills toggle`：给某个 Agent 开/关一个已管理 skill

`skills gather` 的硬约束：

- `--agent-id` 必填
- `--from` 必须属于该 Agent 的 `skills_dir`
- `--from` 的目录名必须和 `--name` 一致
- `--from` 不能是 symlink

## 4. 常见错误

`系统未初始化`

- 说明：还没写入 `tool-hub.json`
- 处理：先打开 Web，完成初始化

`Agent 'xxx' 不存在`

- 说明：`agent_id` 不在当前配置里
- 处理：先 `agents list`，确认真实 id

`Agent 'xxx' 未配置 skills_dir`

- 说明：这个 Agent 还没有可用的 skills 目录
- 处理：先补 Agent 配置

`源路径不属于 Agent 'xxx' 的 skills_dir`

- 说明：`skills gather --from` 指到了别的目录
- 处理：把 `--from` 改成该 Agent 自己的 skills 子目录

`源路径名称与 skill_id 不一致`

- 说明：比如 `--name beta`，但 `--from` 实际是 `.../alpha`
- 处理：让目录名和 `--name` 一致

`源路径不能是 symlink`

- 说明：你试图再次 gather 一个已经 link 过的 skill
- 处理：改用真实目录，不要用 link

`只支持 .zip 文件`

- 说明：上传 skill 时文件后缀不对
- 处理：重新打成 `.zip`

`SKILL.md 缺少 frontmatter` / `frontmatter 缺少 name 或 description`

- 说明：上传包结构不合法
- 处理：检查 skill 包里的 `SKILL.md`

`上传文件名不合法`

- 说明：上传的 multipart `filename` 带了路径、`..` 或绝对路径
- 处理：用普通文件名，比如 `demo.zip`

`端口 8998 不可用`

- 说明：端口被占了
- 处理：停掉占用进程，或换端口：

```bash
python3 -m tool_hub.cli web --port 8766 --no-browser
```

## 5. 边界说明

这个工具的边界很明确：

- 只按本机个人工具设计
- 默认监听 `127.0.0.1`
- 不做多用户认证
- MCP 的 `env` / `headers` 允许明文存在配置里

如果只是接手使用，到这里就够了。
