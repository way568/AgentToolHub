# Contributing

Thanks for considering a contribution to AgentToolHub.

AgentToolHub is a local-first control panel for AI agent tools, Skills, and MCP servers. Contributions should preserve the local-only safety model unless a change explicitly documents and tests a different boundary.

## Development Setup

Use Python 3.9 or later.

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall tool_hub
python3 -m py_compile tool_hub_server.py
```

Run the web UI locally:

```bash
python3 tool_hub_server.py
python3 -m tool_hub.cli web --host 127.0.0.1 --port 8998 --no-browser
```

Optional install flow:

```bash
pip install .
agent-tool-hub --help
agent-tool-hub-web --host 127.0.0.1 --port 8998 --no-browser
```

## Pull Request Checklist

Before opening a pull request:

- Run all tests.
- Keep the web server default bound to `127.0.0.1`.
- Do not weaken slug or path validation.
- Do not remove config backups before writes.
- Document any change that reads or writes local files.
- Avoid adding heavyweight frontend build dependencies unless necessary.

## Compatibility Notes

The public project name is AgentToolHub. The internal Python package remains `tool_hub` in v0.1.0 to reduce migration risk. Legacy CLI aliases `agent-tool-dock`, `agent-tool-dock-web`, `tool-hub`, and `tool-hub-web` are kept for now.
