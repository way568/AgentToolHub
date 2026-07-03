# Tool Hub — 跨 Agent 统一管理台

> Skill 和 MCP 是你的**数字资产**，不是一次性配置文件。Tool Hub 让它们成为**跟人走的能力库**。

## 为什么需要 Tool Hub？

### Skill 管理痛点

- 你有多个 agent 应用，不想每个 agent 都装一遍个人 skill？
- 你发现某个 agent 里的某个 skill 很好用，想一键挂载到其他 agent？
- 你自研了很多 skill，散落在 5 个 agent 目录里，根本记不住哪个装了哪个？
- 新装了一个 agent 应用，想把你积累的所有 skill 瞬间同步过去？
- 同事分享了一个好用的 skill，你想一次归聚、全部 agent 共享？
- 想知道本机一共有多少个 skill、哪些是重复的、哪些只有某个 agent 在用？

### MCP 管理痛点

- 你有 5 个 Agent，每个都要单独配一遍同一个 MCP Server？
- 换了个 Agent 发现之前配过的 MCP 全没了，又得重新填一遍 URL 和密钥？
- 想看看哪些 Agent 开了哪些 MCP，却要逐个翻配置文件？
- 不确定某个 MCP Server 是不是还活着，要手动 curl 测试？

## 核心理念

你的 skill 和 MCP 是**资产**，不是配置文件。

花几十小时打磨的 skill、精心配置的 MCP 连接，不应该因为换了个 agent 就从零开始。Tool Hub 让它们成为**跟人走的个人能力库**，而不是绑定在某个 agent 上的一次性配置。

## 功能亮点

- **矩阵视图** — Skill × Agent / MCP × Agent 一目了然
- **Agent 列头排序** — 点击 Agent 名称，按该 Agent 已启用的项排序到顶部
- **搜索过滤** — 实时搜索 + 清空按钮，计数精确更新
- **Skill 描述** — 2 行省略，hover 展开完整内容
- **MCP 连通测试** — stdio 检测命令存在，sse 用 GET，streamableHttp 用 POST JSON-RPC 初始化
- **文件选择器** — Agent 编辑时 MCP 配置路径支持系统文件选择器
- **日志区分类型** — Skill 操作用 ⚡ 图标，MCP 操作用 🔌 图标
- **扫描刷新** — 同时覆盖 Skill 和 MCP 数据刷新

## 一句话总结

**一个管理台，所有 Agent 的 Skill + MCP 尽在掌握。**
