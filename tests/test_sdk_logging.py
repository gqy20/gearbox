"""测试 Claude Agent SDK 日志适配。"""

import os

from claude_agent_sdk import ClaudeAgentOptions

from gearbox.agents.shared.runtime import prepare_agent_options


class TestPrepareSdkOptions:
    def test_preserves_existing_env(self) -> None:
        prepared, _ = prepare_agent_options(
            ClaudeAgentOptions(env={"KEEP_ME": "1"}),
            agent_name="audit",
        )
        assert prepared.env["KEEP_ME"] == "1"

    def test_injects_auth_token_and_base_url_from_env(self) -> None:
        os.environ["ANTHROPIC_AUTH_TOKEN"] = "sk-test-auth"
        os.environ["ANTHROPIC_BASE_URL"] = "https://proxy.example.com/anthropic"
        try:
            prepared, _ = prepare_agent_options(ClaudeAgentOptions(), agent_name="audit")
            assert prepared.env["ANTHROPIC_AUTH_TOKEN"] == "sk-test-auth"
            assert prepared.env["ANTHROPIC_BASE_URL"] == "https://proxy.example.com/anthropic"
            assert prepared.stderr is not None
        finally:
            del os.environ["ANTHROPIC_AUTH_TOKEN"]
            del os.environ["ANTHROPIC_BASE_URL"]
