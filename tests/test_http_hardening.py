import subprocess
import sys
import time
import unittest
from unittest.mock import patch


class HttpHardeningTests(unittest.TestCase):
    def test_readline_with_timeout_returns_none_for_silent_process(self):
        from tool_hub.mcp.runtime import _readline_with_timeout

        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            stdout=subprocess.PIPE,
        )
        try:
            started = time.monotonic()
            line = _readline_with_timeout(proc.stdout, 0.2)
            elapsed = time.monotonic() - started
        finally:
            proc.kill()
            proc.wait(timeout=5)

        self.assertIsNone(line)
        self.assertLess(elapsed, 3)

    def test_readline_with_timeout_reads_available_line(self):
        from tool_hub.mcp.runtime import _readline_with_timeout

        proc = subprocess.Popen(
            [sys.executable, "-c", "import sys; sys.stdout.write('hello\\n'); sys.stdout.flush()"],
            stdout=subprocess.PIPE,
        )
        try:
            line = _readline_with_timeout(proc.stdout, 5)
        finally:
            proc.kill()
            proc.wait(timeout=5)

        self.assertEqual(line, b"hello\n")

    def test_fetch_mcp_tools_gives_up_on_silent_stdio_server(self):
        from tool_hub.mcp import runtime

        mcp_data = {
            "type": "stdio",
            "command": sys.executable,
            "args": ["-c", "import time; time.sleep(30)"],
        }

        started = time.monotonic()
        with patch.object(runtime, "STDIO_IO_TIMEOUT", 0.3):
            tools = runtime.fetch_mcp_tools(mcp_data)
        elapsed = time.monotonic() - started

        self.assertEqual(tools, [])
        self.assertLess(elapsed, 3)

    def test_handle_error_silences_client_disconnect(self):
        from tool_hub.http_app import SkillHubHandler, SkillHubHTTPServer

        server = SkillHubHTTPServer(("127.0.0.1", 0), SkillHubHandler)
        try:
            import io
            from contextlib import redirect_stderr

            captured = io.StringIO()
            with redirect_stderr(captured):
                try:
                    raise BrokenPipeError(32, "Broken pipe")
                except BrokenPipeError:
                    server.handle_error(None, ("127.0.0.1", 50000))
                try:
                    raise ConnectionResetError(54, "Connection reset by peer")
                except ConnectionResetError:
                    server.handle_error(None, ("127.0.0.1", 50001))
        finally:
            server.server_close()

        self.assertEqual(captured.getvalue(), "")

    def test_handle_error_still_reports_other_exceptions(self):
        from tool_hub.http_app import SkillHubHandler, SkillHubHTTPServer

        server = SkillHubHTTPServer(("127.0.0.1", 0), SkillHubHandler)
        try:
            import io
            from contextlib import redirect_stderr

            captured = io.StringIO()
            with redirect_stderr(captured):
                try:
                    raise RuntimeError("boom")
                except RuntimeError:
                    server.handle_error(None, ("127.0.0.1", 50002))
        finally:
            server.server_close()

        self.assertIn("Exception occurred", captured.getvalue())


if __name__ == "__main__":
    unittest.main()
