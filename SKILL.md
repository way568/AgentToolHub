---
name: tool-hub
description: "跨 Agent 统一管理台 — 管理 Skill + MCP Server。支持 skill 归聚/启用/禁用/扫描/回滚，以及 MCP Server 的添加/编辑/删除/连通性测试/一键分发到各 Agent。触发词：tool hub、skill hub、管理skill、管理mcp、打开管理台、启用skill、禁用skill、添加mcp、mcp管理。"
---

# Tool Hub — 跨 Agent 统一管理台

统一管理本机所有 AI Agent 应用的 **Skill** 和 **MCP Server**，提供 Web 矩阵视图一站式管控。

## 何时触发

- 用户说"打开管理台"、"tool hub"、"skill hub"
- 用户说“管理skill”、"启用/禁用某个 skill"、"扫描 skill"、"归聚 skill"
- 用户说"添加 MCP"、"管理 MCP"、"MCP 列表"
- 用户使用 agent 安装新的 skill 或 MCP 时

## 使用方式

### 方式一：让 Agent 帮你启动

告诉 agent：「打开 tool hub」「打开管理台」，agent 负责启动服务并打开浏览器。

### 方式二：Web 管理台

MAC 上直接双击：`启动控制台.command`，服务启动后自动打开浏览器 `http://localhost:8765`。

首次使用会引导设置中央仓库路径和检测已有 agent 应用。

## 核心功能

### Skill 管理
1. **矩阵管理** — skill × agent 的启用/禁用勾选，一键创建/删除 symlink
2. **扫描归聚** — 扫描各 agent 目录发现新 skill，移入中央仓库，原位建 symlink
3. **操作日志** — 记录所有操作，支持单条撤销和批量回滚
4. **排除名单** — 全局排除、agent 级排除、skill 级独占

### MCP 管理
5. **MCP 矩阵** — MCP × Agent 的启用/禁用切换，一键分发/移除
6. **添加/编辑 MCP** — 支持 stdio、sse、streamableHttp 三种类型
7. **连通性测试** — 检测 MCP Server 是否可达（stdio 检查命令存在，sse 用 GET，streamableHttp 用 POST JSON-RPC）
8. **智能适配** — 根据各 Agent 的适配器规则自动转换 MCP 配置格式
9. **归聚存档** — MCP 配置统一存储在 `{hub_path}/mcp/`，作为唯一源真相
10. **Agent 列头排序** — 点击 Agent 名称按该 Agent 已启用的 MCP 优先排序

### 通用
11. **Agent 管理** — 添加/编辑/删除 agent 应用，配置 skill 目录和 MCP 配置路径（文件选择器选择配置文件）
12. **Segmented Tab** — Skill / MCP 双视图快速切换
13. **搜索** — Skill/MCP 均支持实时搜索 + 清空按钮，搜索后计数精确更新
14. **Skill 描述** — 2 行省略，hover 自动展开完整内容

## 技术要求

- Python 3.8+
- 零外部依赖（纯标准库）
- 端口 8765
- **必须后台启动**：`tool_hub_server.py` 是长驻 HTTP 服务，Agent 启动时必须使用后台模式（如 `is_background=true` 或 `nohup ... &`），否则会阻塞 AI 对话。
- **仅支持 macOS**（依赖 symlink 和 AppleScript 目录选择器，Windows 暂不兼容）

## 文件结构

```
tool-hub/
├── SKILL.md              ← 本文件
├── tool_hub_server.py    ← 后端服务
├── index.html            ← 前端界面
└── mcp-adapters/         ← Agent MCP 适配器规则
    ├── claude-code.json
    └── aone-copilot.json
```
