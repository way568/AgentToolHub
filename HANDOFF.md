# Tool Hub 交接文档

生成时间：2026-07-03

## 结论

`Phase 0~7` 已完成。

现在的状态是：

- `ConfigService` 和 `UploadSkillService` 已抽出。
- `tool_hub/http_app.py` 又薄了一刀，`config` / `upload skill` 已从 HTTP 层下沉。
- CLI 已补 `skills gather` / `skills toggle`。
- HTTP / CLI 端到端测试已补齐主流程。
- 发布收口已完成：`pyproject.toml`、`tool-hub`、`tool-hub-web` 已到位。
- `README.md` 和 `HANDOFF.md` 已按当前真实结构更新。
- 当前 review 口径：先按“解压即用”看，不把安装流程当阻塞项。

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

关键点：

- `tool_hub/http_app.py`：HTTP 壳，主做路由和编解码。
- `tool_hub/services/config.py`：初始化配置、返回配置、Agent 列表。
- `tool_hub/services/upload.py`：处理 zip 上传。
- `tool_hub/services/skills.py`：scan/gather/toggle/sync/delete。
- `tool_hub/services/mcp.py`：list/add/edit/delete/gather/toggle/test。
- `tool_hub/services/audit.py`：log list / rollback / undo。

## 命令

主路径：

```bash
python3 tool_hub_server.py
python3 -m tool_hub.cli web --host 127.0.0.1 --port 8765 --no-browser
```

常用模块命令：

```bash
python3 -m tool_hub.cli doctor
python3 -m tool_hub.cli agents list
python3 -m tool_hub.cli mcp test --name playwright --no-exec
python3 -m tool_hub.cli skills gather --name demo --from /abs/path/demo --agent-id codex
python3 -m tool_hub.cli skills toggle --skill-id demo --agent-id cursor
```

`skills gather` 约束：

- `agent_id` 必填，且必须命中已配置 Agent。
- `from` 路径必须属于该 Agent 的 `skills_dir`。

可选安装入口：

```bash
pip install .
tool-hub --help
tool-hub-web --host 127.0.0.1 --port 8765 --no-browser
```

## 测试与发布

当前测试命令：

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall tool_hub
python3 -m py_compile tool_hub_server.py
```

当前测试覆盖：

- `tests/test_phase0_core.py`
- `tests/test_phase2_services.py`
- `tests/test_phase3_safety.py`
- `tests/test_phase4_cli.py`
- `tests/test_phase5_registry.py`
- `tests/test_phase6_services.py`
- `tests/test_phase7_services.py`
- `tests/test_phase7_e2e.py`
- `tests/test_packaging.py`
- `tests/test_docs_closure.py`

发布相关文件：

- `pyproject.toml`
- `tool_hub/index.html`
- `tool_hub_server.py`

## 边界

边界不要搞混：

- 这是本机个人工具，不是多用户平台。
- 默认只监听 `127.0.0.1`。
- CORS 只允许同源 localhost / `127.0.0.1`。
- `agent_id` / `skill_id` / `MCP 名称` 都做 slug 校验。
- 删除 skill 会做路径归一化，避免越界删目录。
- JSON / TOML 写入前自动备份。
- `fetch_tools=false` 是默认值；`mcp test --no-exec` 就是这个边界的 CLI 映射。
- 上传 zip 必须有 `SKILL.md` frontmatter，且要求 `name` / `description`。
- multipart `filename` 也必须是普通文件名，不能带路径或 `..`。
- MCP 的 `env` / `headers` 允许明文存在配置里，这是显式设计，不是漏掉。

## 当前判断

这一轮已经完成主线收口，当前仓库可以按下面理解：

- 业务主线可用。
- 解压可直接启动，可测试。
- 主要边界清楚。
- 还可以继续做的，只剩“进一步瘦 `tool_hub/http_app.py`”这类增量优化，不是必须修的阻塞项。

## 给 Review Agent

建议 review 时重点盯：

1. `tool_hub/services/config.py`
2. `tool_hub/services/upload.py`
3. `tool_hub/http_app.py`
4. `tool_hub/cli.py`
5. `tests/test_phase7_services.py`
6. `tests/test_phase7_e2e.py`

建议重点判断：

- service 下沉后是否有行为回归
- CLI `skills gather/toggle` 是否和 HTTP 语义一致
- `mcp test --no-exec` 的安全边界是否还在
- 文档描述是否和当前代码一致

这轮可以先忽略：

- 安装流程是否足够优雅
- 更进一步的 `http_app.py` 继续拆分
- 版本号 / changelog / 正式发布流程

如果还有下一轮，优先级建议：

1. 继续下沉 `user-info` / `network-info` / `choose-file` / `choose-folder`
2. 视需要补更多 CLI 子命令
3. 再考虑更细的发布版本号和 changelog 流程
