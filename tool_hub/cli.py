import argparse
import json
import sys

from tool_hub.config_store import get_default_hub_path, get_saved_hub_path, load_config
from tool_hub.errors import ToolHubError
from tool_hub.services.agents import AgentService
from tool_hub.services.mcp import McpService
from tool_hub.services.skills import SkillService
from tool_hub.server import start_web_server


def _resolve_hub_path(hub_path=None):
    return hub_path or get_saved_hub_path() or get_default_hub_path()


def _load_config_or_empty(hub_path=None):
    resolved_hub_path = _resolve_hub_path(hub_path)
    return load_config(hub_path) or {"hub_path": resolved_hub_path, "agents": []}


def build_parser():
    parser = argparse.ArgumentParser(prog="agent-tool-hub")
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor")
    doctor.add_argument("--hub-path", default=None)

    web = subparsers.add_parser("web")
    web.add_argument("--host", default="127.0.0.1")
    web.add_argument("--port", type=int, default=8998)
    web.add_argument("--no-browser", action="store_true")

    agents = subparsers.add_parser("agents")
    agents_sub = agents.add_subparsers(dest="agents_command", required=True)
    agents_list = agents_sub.add_parser("list")
    agents_list.add_argument("--hub-path", default=None)

    mcp = subparsers.add_parser("mcp")
    mcp_sub = mcp.add_subparsers(dest="mcp_command", required=True)
    mcp_list = mcp_sub.add_parser("list")
    mcp_list.add_argument("--hub-path", default=None)
    mcp_test = mcp_sub.add_parser("test")
    mcp_test.add_argument("--hub-path", default=None)
    mcp_test.add_argument("--name", required=True)
    mcp_test.add_argument("--no-exec", action="store_true")

    skills = subparsers.add_parser("skills")
    skills_sub = skills.add_subparsers(dest="skills_command", required=True)
    skills_gather = skills_sub.add_parser("gather")
    skills_gather.add_argument("--hub-path", default=None)
    skills_gather.add_argument("--name", required=True)
    skills_gather.add_argument("--from", dest="from_path", required=True)
    skills_gather.add_argument("--agent-id", required=True)
    skills_toggle = skills_sub.add_parser("toggle")
    skills_toggle.add_argument("--hub-path", default=None)
    skills_toggle.add_argument("--skill-id", required=True)
    skills_toggle.add_argument("--agent-id", required=True)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)

    try:
        if args.command == "web":
            start_web_server(host=args.host, port=args.port, open_browser=not args.no_browser)
            return 0

        if args.command == "doctor":
            config = _load_config_or_empty(args.hub_path)
            mcp_result = McpService().list_mcp(config)
            print(json.dumps({
                "initialized": bool(load_config(args.hub_path)),
                "hub_path": config.get("hub_path"),
                "agents": len(config.get("agents", [])),
                "mcps": len(mcp_result.get("mcps", [])),
            }, ensure_ascii=False, indent=2))
            return 0

        if args.command == "agents" and args.agents_command == "list":
            config = _load_config_or_empty(args.hub_path)
            for agent in config.get("agents", []):
                print(f"{agent.get('id')}\t{agent.get('name')}")
            return 0

        if args.command == "mcp" and args.mcp_command == "list":
            config = _load_config_or_empty(args.hub_path)
            result = McpService().list_mcp(config)
            for item in result.get("mcps", []):
                print(f"{item.get('name')}\t{item.get('type')}\t{item.get('source', '')}")
            return 0

        if args.command == "mcp" and args.mcp_command == "test":
            config = _load_config_or_empty(args.hub_path)
            result = McpService().test_mcp(config, args.name, fetch_tools=not args.no_exec)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0

        if args.command == "skills" and args.skills_command == "gather":
            config = load_config(args.hub_path)
            result = SkillService().gather(
                config,
                {
                    "skills": [
                        {
                            "name": args.name,
                            "from": args.from_path,
                            "agent_id": args.agent_id,
                        }
                    ]
                },
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0

        if args.command == "skills" and args.skills_command == "toggle":
            config = load_config(args.hub_path)
            result = SkillService().toggle_skill(
                config,
                args.skill_id,
                {"agent_id": args.agent_id},
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0

        return 1
    except ToolHubError as error:
        print(json.dumps({"error": error.message}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
