# Security Policy

AgentToolHub is a local-first control panel for AI agent tools, Skills, and MCP servers. It is designed for a single trusted user on a local machine.

## Supported Use

- Run it on `127.0.0.1` by default.
- Use it to inspect and manage local Skill directories and MCP configuration files.
- Treat it as a local developer utility, not as a public SaaS service.

## Safety Model

AgentToolHub can read and write local agent configuration. Depending on your setup, it may:

- Read local Skill directories.
- Read and write MCP JSON / TOML configuration files.
- Create and remove symlinks for managed Skills.
- Back up config files before writing changes.
- Store MCP `env` and `headers` values in plain text.

## Not Supported

- Do not expose the web server directly to the public internet.
- Do not use it as a multi-user admin console.
- Do not store secrets in MCP `env` / `headers` unless you accept plain-text local storage.

## Reporting Issues

For now, report security issues privately to the maintainer before opening a public GitHub issue. A dedicated disclosure channel can be added before a wider public release.
