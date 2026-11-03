import argparse
import webbrowser

from tool_hub.http_app import PORT, SkillHubHandler, SkillHubHTTPServer, _startup_network_check, load_config, migrate_config_with_presets, save_config


def start_web_server(host="127.0.0.1", port=PORT, open_browser=True):
    net_check = _startup_network_check(port)
    if not net_check["port_available"]:
        raise RuntimeError(f"端口 {port} 不可用: {net_check['port_error']}")

    try:
        config = load_config()
        if config and migrate_config_with_presets(config):
            save_config(config)
    except Exception:
        pass

    server = SkillHubHTTPServer((host, port), SkillHubHandler)
    if open_browser:
        webbrowser.open(f"http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


def build_parser():
    parser = argparse.ArgumentParser(prog="agent-tool-hub-web")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--no-browser", action="store_true")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    start_web_server(host=args.host, port=args.port, open_browser=not args.no_browser)


if __name__ == "__main__":
    main()
