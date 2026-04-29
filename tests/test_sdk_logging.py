"""测试 Claude Agent SDK 日志适配和预算控制。"""

import os

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ResultMessage,
    StreamEvent,
)

from gearbox.agents.shared.runtime import (
    CostBudgetExceededError,
    SdkEventLogger,
    prepare_agent_options,
    query_with_budget,
)


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
            assert prepared.include_partial_messages is True
        finally:
            del os.environ["ANTHROPIC_AUTH_TOKEN"]
            del os.environ["ANTHROPIC_BASE_URL"]


class TestSdkEventLogger:
    def test_stream_event_partial_text_is_humanized(
        self,
        monkeypatch,
    ) -> None:
        entries: list[tuple[str, str, str]] = []

        monkeypatch.setattr(
            "gearbox.agents.shared.runtime._log",
            lambda agent, stage, message: entries.append((agent, stage, message)),
        )

        logger = SdkEventLogger("audit")
        logger.handle_message(
            StreamEvent(
                uuid="u0",
                session_id="s1",
                event={
                    "type": "content_block_start",
                    "content_block": {"type": "text"},
                },
            )
        )
        logger.handle_message(
            StreamEvent(
                uuid="u1",
                session_id="s1",
                event={
                    "type": "content_block_delta",
                    "delta": {"text": "Inspecting repository..."},
                },
            )
        )
        logger.handle_message(
            StreamEvent(
                uuid="u2",
                session_id="s1",
                event={"type": "content_block_stop"},
            )
        )

        assert any(stage == "assistant-partial" for _, stage, _ in entries)
        assert any("Inspecting repository" in message for _, _, message in entries)

    def test_tool_use_logs_read_path_and_range(
        self,
        monkeypatch,
    ) -> None:
        entries: list[tuple[str, str, str]] = []

        monkeypatch.setattr(
            "gearbox.agents.shared.runtime._log",
            lambda agent, stage, message: entries.append((agent, stage, message)),
        )

        logger = SdkEventLogger("audit")
        logger.handle_message(
            StreamEvent(
                uuid="u0",
                session_id="s1",
                event={
                    "type": "content_block_start",
                    "content_block": {
                        "type": "tool_use",
                        "name": "Read",
                        "input": {
                            "file_path": "tests/test_cli.py",
                            "offset": 10,
                            "limit": 50,
                        },
                    },
                },
            )
        )

        assert (
            "audit",
            "tool-use",
            "tool=Read, path=tests/test_cli.py, offset=10, limit=50",
        ) in entries

    def test_tool_use_logs_bash_command_summary(
        self,
        monkeypatch,
    ) -> None:
        entries: list[tuple[str, str, str]] = []

        monkeypatch.setattr(
            "gearbox.agents.shared.runtime._log",
            lambda agent, stage, message: entries.append((agent, stage, message)),
        )

        logger = SdkEventLogger("audit")
        logger.handle_message(
            StreamEvent(
                uuid="u0",
                session_id="s1",
                event={
                    "type": "content_block_start",
                    "content_block": {
                        "type": "tool_use",
                        "name": "Bash",
                        "input": {
                            "command": 'rg -n "workflow_call" .github/workflows',
                        },
                    },
                },
            )
        )

        assert any(
            stage == "tool-use" and "tool=Bash, command=rg -n" in message
            for _, stage, message in entries
        )


class TestCostBudgetExceededError:
    """CostBudgetExceededError 异常行为测试。"""

    def test_is_exception_subclass(self) -> None:
        assert issubclass(CostBudgetExceededError, RuntimeError)

    def test_preserves_message_and_cost(self) -> None:
        err = CostBudgetExceededError("budget hit", cost_usd=3.50, limit_usd=2.00)
        assert "budget hit" in str(err)
        assert err.cost_usd == 3.50
        assert err.limit_usd == 2.00

    def test_default_values(self) -> None:
        err = CostBudgetExceededError("test")
        assert err.cost_usd is None
        assert err.limit_usd is None


class TestQueryWithBudget:
    """query_with_budget 预算控制包装器测试。"""

    @staticmethod
    def _make_result_msg(cost: float, turns: int) -> ResultMessage:
        return ResultMessage(
            subtype="result",
            duration_ms=1000,
            duration_api_ms=800,
            is_error=False,
            num_turns=turns,
            session_id="s1",
            total_cost_usd=cost,
        )

    def test_passes_all_messages_when_under_budget(self, monkeypatch) -> None:
        """预算未超限时，所有消息正常透传。"""
        messages = [
            self._make_result_msg(0.30, 1),
            self._make_result_msg(0.50, 2),
        ]

        async def fake_query(*args, **kwargs):
            del args, kwargs
            for msg in messages:
                yield msg

        monkeypatch.setattr("gearbox.agents.shared.runtime.query", fake_query)

        collected = []

        async def _collect():
            async for msg in query_with_budget(
                prompt="test",
                options=ClaudeAgentOptions(model="test", max_turns=10),
                max_cost_usd=2.0,
            ):
                collected.append(msg)

        import asyncio

        asyncio.run(_collect())

        assert len(collected) == 2

    def test_stops_when_cost_exceeds_limit(self, monkeypatch) -> None:
        """成本超过 max_cost_usd 时提前终止迭代并抛出异常。"""
        messages = [
            self._make_result_msg(0.50, 1),
            self._make_result_msg(1.00, 2),
            self._make_result_msg(3.0, 3),  # 超过 $2.00 预算
            self._make_result_msg(4.0, 4),  # 不应被消费
        ]

        async def fake_query(*args, **kwargs):
            del args, kwargs
            for msg in messages:
                yield msg

        monkeypatch.setattr("gearbox.agents.shared.runtime.query", fake_query)

        collected: list[object] = []
        raised = False

        async def _run():
            nonlocal raised
            try:
                async for msg in query_with_budget(
                    prompt="test",
                    options=ClaudeAgentOptions(model="test", max_turns=10),
                    max_cost_usd=2.0,
                ):
                    collected.append(msg)
            except CostBudgetExceededError:
                raised = True

        import asyncio

        asyncio.run(_run())

        # 应该收到前两条消息 + 触发超限的 result 消息（用于检测）
        assert len(collected) == 3
        assert raised

    def test_no_budget_constraint_when_max_cost_is_none(self, monkeypatch) -> None:
        """max_cost_usd=None 时不做任何预算检查。"""
        messages = [self._make_result_msg(999.99, 1)]

        async def fake_query(*args, **kwargs):
            del args, kwargs
            for msg in messages:
                yield msg

        monkeypatch.setattr("gearbox.agents.shared.runtime.query", fake_query)

        collected: list[object] = []

        async def _collect():
            async for msg in query_with_budget(
                prompt="test",
                options=ClaudeAgentOptions(model="test", max_turns=10),
                max_cost_usd=None,
            ):
                collected.append(msg)

        import asyncio

        asyncio.run(_collect())

        assert len(collected) == 1

    def test_raises_with_correct_cost_details(self, monkeypatch) -> None:
        """异常携带正确的 cost/limit 信息。"""
        messages = [self._make_result_msg(5.0, 10)]

        async def fake_query(*args, **kwargs):
            del args, kwargs
            for msg in messages:
                yield msg

        monkeypatch.setattr("gearbox.agents.shared.runtime.query", fake_query)

        caught: CostBudgetExceededError | None = None

        async def _run():
            nonlocal caught
            try:
                async for _msg in query_with_budget(
                    prompt="test",
                    options=ClaudeAgentOptions(model="test", max_turns=10),
                    max_cost_usd=2.0,
                ):
                    pass
            except CostBudgetExceededError as e:
                caught = e

        import asyncio

        asyncio.run(_run())

        assert caught is not None
        assert caught.cost_usd == 5.0
        assert caught.limit_usd == 2.0


class TestSdkEventLoggerCostAlert:
    """SdkEventLogger 成本阈值告警测试。"""

    def test_emits_warning_when_cost_exceeds_threshold(self, monkeypatch) -> None:
        """cost 超过阈值时输出 ::warning:: 日志。"""
        printed: list[str] = []

        monkeypatch.setattr(
            "builtins.print",
            lambda *a, **kw: printed.append(" ".join(str(x) for x in a)),
        )

        logger = SdkEventLogger("audit", cost_warning_threshold_usd=2.0)
        logger.handle_message(
            ResultMessage(
                subtype="result",
                duration_ms=5000,
                duration_api_ms=4000,
                is_error=False,
                num_turns=15,
                session_id="s1",
                total_cost_usd=3.50,
            )
        )

        warnings = [p for p in printed if "::warning::" in p]
        assert len(warnings) >= 1
        assert "3.50" in warnings[0]

    def test_no_warning_when_cost_below_threshold(self, monkeypatch) -> None:
        """cost 未超过阈值时不输出 warning。"""
        printed: list[str] = []

        monkeypatch.setattr(
            "builtins.print",
            lambda *a, **kw: printed.append(" ".join(str(x) for x in a)),
        )

        logger = SdkEventLogger("audit", cost_warning_threshold_usd=2.0)
        logger.handle_message(
            ResultMessage(
                subtype="result",
                duration_ms=1000,
                duration_api_ms=800,
                is_error=False,
                num_turns=3,
                session_id="s1",
                total_cost_usd=0.80,
            )
        )

        warnings = [p for p in printed if "::warning::" in p]
        assert len(warnings) == 0

    def test_default_threshold_is_2_dollars(self) -> None:
        """默认阈值为 $2.00。"""
        logger = SdkEventLogger("audit")
        assert logger.cost_warning_threshold_usd == 2.0

    def test_custom_threshold_via_init(self) -> None:
        """可通过构造参数自定义阈值。"""
        logger = SdkEventLogger("audit", cost_warning_threshold_usd=5.0)
        assert logger.cost_warning_threshold_usd == 5.0
