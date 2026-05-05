"""测试 select_best_result 候选选优逻辑。"""

import logging

import pytest

from gearbox.agents.schemas import EvaluationResult
from gearbox.agents.shared.selection import SelectionResult, select_best_result


def _make_results(n: int) -> list[dict]:
    """生成 N 个简单的候选结果。"""
    return [{"id": i} for i in range(n)]


class TestSelectBestResultNormalCase:
    """正常路径：Evaluator 返回合法的 winner 索引。"""

    @pytest.mark.asyncio
    async def test_valid_winner_returns_correct_index(self, monkeypatch):
        """winner 在范围内时返回对应结果，不触发回退。"""
        results = _make_results(3)

        async def fake_evaluator(*args, **kwargs):
            del args, kwargs
            return EvaluationResult(winner=1, reasoning="pick 1")

        monkeypatch.setattr(
            "gearbox.agents.evaluator.run_evaluator",
            fake_evaluator,
        )

        selected = await select_best_result(results, result_type="test")
        assert isinstance(selected, SelectionResult)
        assert selected.index == 1
        assert selected.result == {"id": 1}
        assert selected.is_fallback is False

    @pytest.mark.asyncio
    async def test_winner_zero_is_not_fallback(self, monkeypatch):
        """winner=0 是合法选择，不应标记为 fallback。"""
        results = _make_results(3)

        async def fake_evaluator(*args, **kwargs):
            del args, kwargs
            return EvaluationResult(winner=0, reasoning="pick 0")

        monkeypatch.setattr(
            "gearbox.agents.evaluator.run_evaluator",
            fake_evaluator,
        )

        selected = await select_best_result(results, result_type="test")
        assert selected.index == 0
        assert selected.is_fallback is False


class TestSelectBestResultFallback:
    """回退路径：Evaluator 返回越界 winner 时应记录 warning 并标记 fallback。"""

    @pytest.mark.asyncio
    async def test_negative_winner_falls_back_with_warning(self, monkeypatch, caplog):
        """winner 为负数时回退到 index 0，发出 warning 日志。

        注：Pydantic 的 ge=0 约束通常会在模型构造阶段拒绝负数值，
        但此处使用 model_construct 绕过验证以测试 select_best_result 自身的防御逻辑。
        """
        results = _make_results(3)

        async def fake_evaluator(*args, **kwargs):
            del args, kwargs
            return EvaluationResult.model_construct(winner=-1, reasoning="bad")

        monkeypatch.setattr(
            "gearbox.agents.evaluator.run_evaluator",
            fake_evaluator,
        )

        with caplog.at_level(logging.WARNING, logger="gearbox.agents.shared.selection"):
            selected = await select_best_result(results, result_type="test")

        assert isinstance(selected, SelectionResult)
        assert selected.index == 0
        assert selected.result == {"id": 0}
        assert selected.is_fallback is True

        # 验证 warning 日志包含关键信息
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) >= 1
        msg = warnings[0].message
        assert "-1" in msg  # 原始 winner 值
        assert "3" in msg  # candidates 数量

    @pytest.mark.asyncio
    async def test_out_of_range_winner_falls_back_with_warning(self, monkeypatch, caplog):
        """winner >= len(results) 时回退到 index 0，发出 warning 日志。"""
        results = _make_results(3)

        async def fake_evaluator(*args, **kwargs):
            del args, kwargs
            return EvaluationResult(winner=99, reasoning="way out of range")

        monkeypatch.setattr(
            "gearbox.agents.evaluator.run_evaluator",
            fake_evaluator,
        )

        with caplog.at_level(logging.WARNING, logger="gearbox.agents.shared.selection"):
            selected = await select_best_result(results, result_type="test")

        assert selected.index == 0
        assert selected.is_fallback is True

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) >= 1
        msg = warnings[0].message
        assert "99" in msg
        assert "3" in msg


class TestSelectBestResultEdgeCases:
    """边界情况。"""

    @pytest.mark.asyncio
    async def test_empty_results_raises_value_error(self):
        """空列表应抛出 ValueError。"""
        with pytest.raises(ValueError, match="must not be empty"):
            await select_best_result([], result_type="test")

    @pytest.mark.asyncio
    async def test_single_result_returns_immediately(self, monkeypatch):
        """只有一个候选时直接返回，不调用 evaluator。"""
        results = _make_results(1)
        called = False

        async def fake_evaluator(*args, **kwargs):
            nonlocal called
            called = True
            return EvaluationResult(winner=0, reasoning="unused")

        monkeypatch.setattr(
            "gearbox.agents.evaluator.run_evaluator",
            fake_evaluator,
        )

        selected = await select_best_result(results, result_type="test")
        assert selected.index == 0
        assert selected.is_fallback is False
        assert called is False  # evaluator 不应被调用
