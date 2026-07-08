# AgentToolHub

Local-first control panel for AI agent tools, Skills, and MCP servers.

AgentToolHub helps you manage local AI agent capabilities without scattering Skills and MCP server configs across multiple agent directories. It focuses on a local, auditable workflow: scan, gather, link, unlink, toggle, and test tools before exposing them to agents.

Chinese quick start: see [`QUICKSTART.md`](QUICKSTART.md). Legacy Chinese project notes can be kept in `README.zh-CN.md` when needed.

## Why

- Manage local AI agent Skills and MCP servers in one place.
- Link, unlink, gather, and audit local tools safely.
- Run locally by default on `127.0.0.1`.

## Status

AgentToolHub is currently packaged as a local developer utility. The public package and command names use `agent-tool-hub`. Internal Python imports still use `tool_hub` in v0.1.0 for compatibility.

## Quick Start

Install from the source tree:

```bash
pip install .
agent-tool-hub --help
agent-tool-hub-web --host 127.0.0.1 --port 8998 --no-browser
```

Common CLI commands:

```bash
agent-tool-hub doctor
agent-tool-hub agents list
agent-tool-hub mcp list
agent-tool-hub mcp test --name playwright --no-exec
agent-tool-hub skills gather --name demo --from /abs/path/demo --agent-id codex
agent-tool-hub skills toggle --skill-id demo --agent-id cursor
agent-tool-hub web
```

Legacy command aliases are kept for migration:

```bash
agent-tool-dock --help
agent-tool-dock-web --host 127.0.0.1 --port 8998 --no-browser
tool-hub --help
tool-hub-web --host 127.0.0.1 --port 8998 --no-browser
```

## Screenshots

### Skill Management

![Skill Management](docs/images/skill-manage.jpg)

### MCP Management

![MCP Management](docs/images/mcp-manage.jpg)

## What It Manages

- Built-in agent presets and MCP adapter rules.
- Local Skill directories.
- MCP server definitions and adapter configs.
- Link-based Skill enable / disable state: symlink on macOS / Linux, directory junction on Windows.
- JSON / TOML agent configuration writes with backups.

## Safety Model

AgentToolHub is designed for a single trusted user on a local machine.

- The web server listens on `127.0.0.1` by default.
- CORS is limited to localhost / `127.0.0.1` origins.
- It reads local Skill directories and MCP configuration files.
- It may create / remove managed directory links.
- On macOS / Linux, Skill links use symlinks.
- On Windows, Skill links use directory junctions via `mklink /J` where possible.
- It may write JSON / TOML config files.
- Config files are backed up before writes.
- MCP `env` / `headers` values are not encrypted at rest.
- `fetch_tools=false` is the default safety value; stdio MCP tools are not auto-fetched by default.

Do not expose AgentToolHub directly to the public internet. See [`SECURITY.md`](SECURITY.md).

## Boundaries

Current boundaries:

- No multi-user authentication.
- No public SaaS deployment model.
- No secret vault for MCP `env` / `headers`.
- macOS is the primary tested platform.
- Windows support is experimental and mechanism-supported, but not verified with a real Windows end-to-end test run.
- Windows junction handling has a compatibility layer, but Windows workflows should be manually validated before being advertised as fully supported.

## Windows Link Support

AgentToolHub uses managed directory links to enable / disable Skills inside agent-specific Skill directories. On macOS and Linux this is implemented with symlinks. On Windows, AgentToolHub uses directory junctions via `cmd /c mklink /J <link> <target>` where possible.

Rationale:

- AgentToolHub only needs to link directories, not individual files.
- Microsoft documents `mklink /J` as the command option for creating a Directory Junction, while `mklink /D` creates a directory symbolic link.
- Microsoft documents junctions as directory links that can point to directories on different local volumes on the same computer, but not to mapped network volumes or files.
- Windows symbolic links can work, but symlink creation may depend on Developer Mode, elevation, or local security policy. Junctions are a more compatible default for this project because the managed Skill target is a local directory.

Expected Windows behavior:

- Local NTFS folders are the intended target.
- Cross-drive local folders should be viable for junctions.
- Mapped network drives are not supported for junction targets.
- File links are not supported by AgentToolHub's Skill linking model.
- Junction removal should remove only the managed link, not the central Skill directory.

Validation status:

- The compatibility layer is covered by automated tests and POSIX-side behavior checks.
- Windows-specific behavior has been evaluated against Microsoft documentation, but has not been manually tested on a real Windows machine.
- Until a real Windows workflow is tested, Windows support should be described as experimental rather than fully supported.

References:

- Microsoft Learn: `mklink` command — https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/mklink
- Microsoft Learn: Hard links and junctions — https://learn.microsoft.com/en-us/windows/win32/fileio/hard-links-and-junctions
- Microsoft Learn: Creating symbolic links — https://learn.microsoft.com/en-us/windows/win32/fileio/creating-symbolic-links
- Windows Developer Blog: Symlinks in Windows 10 — https://blogs.windows.com/windowsdeveloper/2016/12/02/symlinks-windows-10/

## HTTP Surface

Main endpoints:

- `GET /api/config`
- `PUT /api/config`
- `GET /api/agents`
- `GET /api/skills`
- `POST /api/skills/upload`
- `POST /api/gather`
- `POST /api/skills/<id>/toggle`
- `POST /api/mcp/<name>/test`

## Validation

```bash
python3 -m unittest discover -s tests -v
```

Current tests cover:

- services: `ConfigService`, `UploadSkillService`, Skill, MCP, Audit
- CLI flows: `agents list`, `mcp test --no-exec`, `skills gather`, `skills toggle`
- HTTP flows: config, agents, skills upload
- docs and packaging assertions: `README.md`, `HANDOFF.md`, `pyproject.toml`

## Developer Compatibility Notes

The public project name is `AgentToolHub` and the package name is `agent-tool-hub`.

For v0.1.0 compatibility:

- Internal Python imports remain `tool_hub`.
- The source-tree web entry remains `python3 tool_hub_server.py`.
- Direct module commands remain available, for example `python3 -m tool_hub.cli doctor`.
- Legacy CLI commands `agent-tool-dock`, `agent-tool-dock-web`, `tool-hub`, and `tool-hub-web` remain available.
- Existing local config files such as `tool-hub.json` are not renamed automatically in this pass.
- The built-in presets and adapters are packaged under `tool_hub/data/`.
- Developer checks can still use `python3 -m compileall tool_hub` and `python3 -m py_compile tool_hub_server.py`.

Minimal source layout:

```text
agent-tool-hub/
  pyproject.toml
  tool_hub/                 # internal Python package kept for compatibility
    cli.py
    server.py
    http_app.py
    linking.py
    services/
    mcp/
    data/
      agent-presets/
      mcp-adapters/
  tests/
  tool_hub_server.py
```

## License

MIT License. See [`LICENSE`](LICENSE).
