import json
import os
import shutil
import subprocess
import urllib.request


def _normalize_tools(tools):
    if not isinstance(tools, list):
        return []
    normalized = []
    for tool in tools:
        if not isinstance(tool, dict) or not tool.get("name"):
            continue
        item = {"name": str(tool.get("name", ""))}
        if tool.get("description"):
            item["description"] = str(tool.get("description", ""))
        normalized.append(item)
    return normalized


def _tools_from_response_payload(payload):
    if not isinstance(payload, dict):
        return []
    return _normalize_tools(payload.get("result", {}).get("tools", []))


def _tools_from_http_body(body):
    stripped = body.strip()
    if stripped.startswith("{"):
        return _tools_from_response_payload(json.loads(stripped))
    data_parts = []
    for line in body.split("\n"):
        if line.startswith("data:"):
            data_parts.append(line[5:].strip())
    if not data_parts:
        return []
    try:
        return _tools_from_response_payload(json.loads("".join(data_parts)))
    except json.JSONDecodeError:
        return []


def fetch_mcp_tools(mcp_data):
    mcp_type = mcp_data.get("type", "stdio")
    try:
        if mcp_type == "stdio":
            cmd = mcp_data.get("command", "")
            args = mcp_data.get("args", []) or []
            env = dict(os.environ)
            env.update(mcp_data.get("env", {}) or {})
            proc = subprocess.Popen(
                [cmd] + args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
            )
            try:
                init_req = json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2025-03-26",
                            "capabilities": {},
                            "clientInfo": {"name": "agent-tool-hub", "version": "1.0"},
                        },
                    }
                ) + "\n"
                proc.stdin.write(init_req.encode())
                proc.stdin.flush()
                init_resp_line = proc.stdout.readline()
                if not init_resp_line:
                    return []
                notif = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"
                proc.stdin.write(notif.encode())
                proc.stdin.flush()
                tools_req = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}) + "\n"
                proc.stdin.write(tools_req.encode())
                proc.stdin.flush()
                tools_resp_line = proc.stdout.readline()
                if not tools_resp_line:
                    return []
                return _tools_from_response_payload(json.loads(tools_resp_line))
            finally:
                proc.kill()
        url = mcp_data.get("url", "")
        if not url:
            return []
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        headers.update(mcp_data.get("headers", {}) or {})

        class RedirectHandler(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, hdrs, newurl):
                return urllib.request.Request(
                    newurl,
                    data=req.data,
                    method=req.get_method(),
                    headers=dict(req.header_items()),
                )

        opener = urllib.request.build_opener(RedirectHandler)
        init_payload = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "agent-tool-hub", "version": "1.0"},
                },
            }
        ).encode()
        req = urllib.request.Request(url, data=init_payload, method="POST", headers=headers)
        with opener.open(req, timeout=10) as resp:
            resp.read()
        tools_payload = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}).encode()
        req2 = urllib.request.Request(url, data=tools_payload, method="POST", headers=headers)
        with opener.open(req2, timeout=10) as resp2:
            return _tools_from_http_body(resp2.read().decode())
    except Exception:
        return []


def fetch_mcp_tools_description(mcp_data):
    tools = fetch_mcp_tools(mcp_data)
    if not tools:
        return None
    tool_names = [tool["name"] for tool in tools if tool.get("name")]
    total = len(tool_names)
    preview = ", ".join(tool_names[:5])
    if total > 5:
        return f"提供 {total} 个工具：{preview} 等"
    return f"提供 {total} 个工具：{preview}" if total else None


def test_mcp_connectivity(mcp_data):
    mcp_type = mcp_data.get("type", "stdio")
    if mcp_type == "stdio":
        command = mcp_data.get("command", "")
        found = shutil.which(command) is not None
        return {"status": "ok" if found else "error", "detail": f"command '{command}' {'found' if found else 'not found'}"}
    url = mcp_data.get("url", "")
    if not url:
        return {"status": "error", "detail": "no url"}
    try:
        class RedirectHandler(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return urllib.request.Request(
                    newurl,
                    data=req.data,
                    method=req.get_method(),
                    headers=dict(req.header_items()),
                )

        opener = urllib.request.build_opener(RedirectHandler)
        if mcp_type == "streamableHttp":
            payload = json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-03-26",
                        "capabilities": {},
                        "clientInfo": {"name": "agent-tool-hub-test", "version": "1.0"},
                    },
                }
            ).encode("utf-8")
            req = urllib.request.Request(url, data=payload, method="POST")
            req.add_header("Content-Type", "application/json")
            req.add_header("Accept", "application/json, text/event-stream")
        else:
            req = urllib.request.Request(url, method="GET")
            req.add_header("Accept", "text/event-stream")
        for header_name, header_value in mcp_data.get("headers", {}).items():
            req.add_header(header_name, header_value)
        with opener.open(req, timeout=10) as resp:
            return {"status": "ok", "detail": f"HTTP {resp.status}"}
    except Exception as error:
        error_str = str(error)
        if "HTTP Error" in error_str:
            code = error_str.split("HTTP Error ")[1].split(":")[0] if "HTTP Error " in error_str else ""
            if code in ("401", "403"):
                return {"status": "ok", "detail": f"可达但需认证 (HTTP {code})"}
        return {"status": "error", "detail": error_str}
