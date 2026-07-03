# Tool Hub

结论：

- 现在主路径是“解压即用”的本机工具，不依赖安装流程。
- CLI / Web 入口已经拆清楚，安装入口只是可选能力。
- 核心业务在 `service` 层，`tool_hub/http_app.py` 主要负责 HTTP 壳。
- 默认按“个人可信工具”设计，不做多用户认证。

## 当前结构

```text
tool-hub/
  pyproject.toml
  tool_hub/
    cli.py
    server.py
    http_app.py
    index.html
    config_store.py
    presets.py
    safety.py
    audit.py
    backends/
      json_cfg.py
      toml_cfg.py
      registry.py
    mcp/
      adapters.py
      agent_config.py
      runtime.py
      store.py
    services/
      agents.py
      audit.py
      config.py
      mcp.py
      skills.py
      upload.py
    skills/
      backends.py
  agent-presets/
  mcp-adapters/
  tests/
  tool_hub_server.py
```

关键职责：

- `tool_hub/cli.py`：CLI 入口。
- `tool_hub/server.py`：Web 启动入口。
- `tool_hub/http_app.py`：路由、HTTP 编解码、少量基础接口。
- `tool_hub/services/config.py`：配置初始化、读取、Agent 列表。
- `tool_hub/services/upload.py`：`multipart/form-data` 解析、zip 校验、skill 落盘。
- `tool_hub/services/skills.py`：scan/gather/toggle/sync/delete。
- `tool_hub/services/mcp.py`：MCP 列表、增删改、gather、toggle、test。

## 启动方式

推荐直接用：

```bash
python3 tool_hub_server.py
python3 -m tool_hub.cli web --host 127.0.0.1 --port 8765 --no-browser
python3 -m tool_hub.cli doctor
```

如果只想跑 Web，这就是主路径。

可选安装入口还保留：

```bash
pip install .
tool-hub --help
tool-hub-web --host 127.0.0.1 --port 8765 --no-browser
```

不走安装时，也可以直接用模块命令：

```bash
python3 -m tool_hub.cli agents list
python3 -m tool_hub.cli mcp list
```

## 常用命令

```bash
python3 -m tool_hub.cli doctor
python3 -m tool_hub.cli agents list
python3 -m tool_hub.cli mcp list
python3 -m tool_hub.cli mcp test --name playwright --no-exec
python3 -m tool_hub.cli skills gather --name demo --from /abs/path/demo --agent-id codex
python3 -m tool_hub.cli skills toggle --skill-id demo --agent-id cursor
python3 -m tool_hub.cli web
```

`skills` 命令语义：

- `skills gather`：把某个 Agent 目录里的 skill 移入 Hub，并在原目录补回 symlink。
  - 必须提供真实 `agent_id`，且 `from` 路径必须属于该 Agent 的 `skills_dir`。
- `skills toggle`：给目标 Agent 开/关某个已管理 skill。

`mcp test` 语义：

- `python3 -m tool_hub.cli mcp test --name xxx --no-exec`：只测连通性，不拉 tools 描述。
- 不带 `--no-exec`：等价 `fetch_tools=true`，允许补 MCP 描述。

## HTTP 面

主接口：

- `GET /api/config`
- `PUT /api/config`
- `GET /api/agents`
- `GET /api/skills`
- `POST /api/skills/upload`
- `POST /api/gather`
- `POST /api/skills/<id>/toggle`
- `POST /api/mcp/<name>/test`

当前 `tool_hub/http_app.py` 已经不再承载 `config` 和 `upload skill` 业务细节；这两块已经下沉到 `service`。

## 边界

当前边界很明确：

- Web 默认只监听 `127.0.0.1`。
- CORS 只允许同源 localhost / `127.0.0.1`。
- `agent_id` / `skill_id` / `MCP 名称` 统一做 slug 校验。
- 删除 skill 走路径归一化，避免越界删除。
- JSON / TOML 配置写入前自动备份。
- `fetch_tools=false` 是默认安全值；stdio MCP 默认不自动扫 tools。
- 上传 skill 只接受 `.zip`，且必须带 `SKILL.md` frontmatter，并且要求 `name` / `description`。
  - multipart 里的 `filename` 也必须是普通文件名，不能带路径或 `..`。

不做的事也很明确：

- 不做多用户认证。
- 不隐藏 MCP 的 `env` / `headers` 明文存储能力。
- 不把它当公网 SaaS。

## 验证

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall tool_hub
python3 -m py_compile tool_hub_server.py
```

当前测试已经覆盖：

- service：`ConfigService` / `UploadSkillService` / Skill / MCP / Audit
- CLI 端到端：`agents list`、`mcp test --no-exec`、`skills gather/toggle`
- HTTP 端到端：`config`、`agents`、`skills upload`
- 文档和打包断言：`README.md`、`HANDOFF.md`、`pyproject.toml`

## Review 重点

如果交给别的 agent review，重点看这几件事：

- `ConfigService` / `UploadSkillService` 下沉后，HTTP 行为有没有变。
- `skills gather/toggle` 的 symlink 和配置写回是否一致。
- `mcp test --no-exec` 是否仍然严格对应 `fetch_tools=false`。
- 本机边界有没有被放松：`127.0.0.1`、CORS、slug/path 校验、写前备份。

这轮 review 不需要把“安装流程是否优雅”当主问题。当前产品定位下，`解压即用` 才是主路径。
