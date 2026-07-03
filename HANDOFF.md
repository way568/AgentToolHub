# Tool Hub 交接文档

生成时间：2026-07-03

## 背景

本轮工作围绕 `/Users/wayne/AI产物/skills/tool-hub`，目标是把当前 Codex Agent 接入 Tool Hub，并处理 Codex MCP 配置格式特殊的问题。

Tool Hub 服务地址：`http://localhost:8765`

Tool Hub 全局配置文件：`/Users/wayne/AI产物/skills/tool-hub.json`

项目目录：`/Users/wayne/AI产物/skills/tool-hub`

## 已完成

- 已将当前 Agent 识别为 `codex` / `Codex`。
- 已通过 Tool Hub API upsert Codex Agent。
- Codex Agent 配置如下：
  - `skills_dir`: `/Users/wayne/.codex/skills`
  - `mcp_config_path`: `/Users/wayne/.codex/config.toml`
  - `mcp_config_key`: `mcp_servers`
- 已确认 Codex 的 MCP 配置是 TOML 格式，不是常见 JSON `mcpServers` 格式。
- 已新增 Codex MCP adapter：`mcp-adapters/codex.json`
- 已修改 `tool_hub_server.py`：
  - 增加 Codex Agent preset。
  - 增加 TOML MCP 读取支持。
  - 增加 TOML MCP 写入和删除支持。
  - 支持 `[mcp_servers.name]` 与 `[mcp_servers.name.env]` 结构。
- 已验证：
  - `python3 -m py_compile tool_hub_server.py` 通过。
  - `mcp-adapters/codex.json` JSON 格式有效。
  - 使用临时 TOML 文件测试 MCP 新增、读取、删除成功，没有改真实 `~/.codex/config.toml`。
  - `GET /api/mcp` 能扫描出 Codex 的 `node_repl`，且 `agent_status.codex = true`。
- 已在项目目录初始化 Git 仓库并创建初始提交：
  - `88465bf Initial Tool Hub import`
- `.gitignore` 已忽略本地状态文件：
  - `.DS_Store`
  - `.hub-path`
  - `.gitignore 15.05.32`
  - Python 缓存和日志

## 当前状态

- Git 仓库位于：`/Users/wayne/AI产物/skills/tool-hub/.git`
- 当前分支：`main`
- 当前提交：`88465bf Initial Tool Hub import`
- `git status --short --ignored` 只显示 ignored 本地文件，没有未提交源码变更。
- Tool Hub Python 服务最后确认运行在 `localhost:8765`，监听进程为本地 `python3 tool_hub_server.py`。如果下一会话发现端口未监听，直接在项目目录运行：

```bash
python3 tool_hub_server.py
```

或后台运行：

```bash
cd /Users/wayne/AI产物/skills/tool-hub
nohup python3 tool_hub_server.py >/tmp/tool-hub.log 2>&1 < /dev/null &
```

## 重要文件

- `/Users/wayne/AI产物/skills/tool-hub/tool_hub_server.py`
- `/Users/wayne/AI产物/skills/tool-hub/mcp-adapters/codex.json`
- `/Users/wayne/AI产物/skills/tool-hub/mcp-adapters/claude-code.json`
- `/Users/wayne/AI产物/skills/tool-hub/mcp-adapters/aone-copilot.json`
- `/Users/wayne/AI产物/skills/tool-hub/index.html`
- `/Users/wayne/AI产物/skills/tool-hub.json`

## 设计判断

用户询问过当前架构是否一定需要 Python 服务，以及能否改成 CLI。

建议方向：CLI 为主，HTML 服务为可选壳。

原因：

- 核心能力是本地配置读写、Agent 检测、MCP adapter 转换、MCP 启停和测试，这些不需要长期 HTTP 服务。
- HTML 前端仍需要本地服务，因为浏览器不能直接安全读写用户目录或执行本地命令。
- 推荐后续拆分为：
  - `core/config.py`
  - `core/agents.py`
  - `core/skills.py`
  - `core/mcp.py`
  - `core/adapters.py`
  - `core/formats.py`
  - `cli.py`
  - `server.py`

推荐渐进路线：

1. 先把 `tool_hub_server.py` 的核心逻辑拆到 `core/`，不改变 Web 行为。
2. 增加 CLI 命令入口。
3. 让 HTTP 服务只作为 `tool-hub web` 可选模式。
4. 后续 Agent 自动接入优先调用 CLI，而不是 HTTP API。

## 建议命令

检查服务：

```bash
lsof -nP -iTCP:8765 -sTCP:LISTEN
curl -sS http://localhost:8765/api/agents | python3 -m json.tool
curl -sS http://localhost:8765/api/mcp | python3 -m json.tool
```

检查 Codex 配置扫描：

```bash
python3 - <<'PY'
import importlib.util, json
path='/Users/wayne/AI产物/skills/tool-hub/tool_hub_server.py'
spec=importlib.util.spec_from_file_location('tool_hub_server', path)
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
agent={
  'id':'codex',
  'name':'Codex',
  'mcp_config_path':'/Users/wayne/.codex/config.toml',
  'mcp_config_key':'mcp_servers'
}
mcps=mod.read_agent_mcp_config(agent)
print(json.dumps({'count': len(mcps), 'has_node_repl': 'node_repl' in mcps}, ensure_ascii=False, indent=2))
PY
```

## 注意事项

- 不要在交接文档或提交信息中粘贴 MCP headers、API key、token 等敏感值。
- `/api/mcp` 返回里可能包含某些 Agent MCP 的认证 headers；排查时只看结构和状态即可。
- Codex TOML 写入逻辑目前是定向追加/替换 `[mcp_servers.<name>]` 相关 section，不会重写整个 `config.toml`。
- 当前 TOML parser 是轻量实现，主要覆盖 Codex MCP 配置的常见字符串、数字、布尔、数组、子表场景；如果后续出现更复杂 TOML 语法，建议引入标准 TOML 库或进一步收紧格式支持。

## Suggested Skills

- `mattpocock-skills:handoff`：继续交接或压缩上下文时使用。
- `vps-ops`：如果后续需要检查 VPS 上同步后的 Tool Hub 或远程服务状态时使用。
- `skill-creator`：如果要把 Tool Hub 工作流整理成正式 Codex skill 时使用。
- `browser:control-in-app-browser`：如果需要验证 HTML 前端交互或截图时使用。
