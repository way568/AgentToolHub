import pytest


@pytest.fixture(autouse=True)
def _isolate_tool_hub_state(tmp_path, monkeypatch):
    """隔离 Tool Hub 全局状态目录，防止测试污染真实 ~/.agent-tool-hub。

    save_config 会经 save_hub_path_pointer 写 HUB_PATH_POINTER：
    - 进程内代码读 config_store 模块级常量，需 monkeypatch 替换；
    - CLI 子进程在 import 时读 AGENT_TOOL_HUB_STATE_DIR 环境变量，需 setenv。
    """
    state_dir = tmp_path / ".agent-tool-hub"
    state_dir.mkdir()
    monkeypatch.setenv("AGENT_TOOL_HUB_STATE_DIR", str(state_dir))
    from tool_hub import config_store

    monkeypatch.setattr(config_store, "HUB_PATH_POINTER", state_dir / ".hub-path")
    yield
