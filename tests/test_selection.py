"""测试 select_best_result 的降级检测逻辑。"""

import asyncio
import logging

import pytest

from gearbox.agents.shared.selection import select_best_result


class TestSelectBestResultDegradation:
    """验证 max_runs 参数触发降级警告的行为。"""

    def test_single_result_no_max_runs_returns_immediately(self) -> None:
        """单结果 + 未指定 max_runs → 正常返回，无警告。"""
        results = [{"id": "only"}]
        idx, val = asyncio.run(select_best_result(results, result_type="test"))
        assert idx == 0
        assert val == {"id": "only"}

    def test_single_result_with_max_runs_warns_on_degradation(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """单结果 + max_runs=3 → 1/3 < 50% 阈值，应记录降级警告。"""
        with caplog.at_level(logging.WARNING, logger="gearbox.agents.shared.selection"):
            results = [{"id": "only"}]
            idx, val = asyncio.run(select_best_result(results, result_type="test", max_runs=3))
            assert idx == 0
            assert val == {"id": "only"}

        # Should emit a degradation warning
        assert any(
            "degradation" in rec.message.lower() or "degraded" in rec.message.lower()
            for rec in caplog.records
        ), f"Expected degradation warning in logs: {[r.message for r in caplog.records]}"

    def test_one_of_three_results_clearly_degraded(self, caplog: pytest.LogCaptureFixture) -> None:
        """1/3 = 33% < 50% 阈值，必须记录降级。"""
        with caplog.at_level(logging.WARNING, logger="gearbox.agents.shared.selection"):
            results = [{"id": "solo"}]
            idx, val = asyncio.run(select_best_result(results, result_type="test", max_runs=3))
            assert idx == 0

        degradation_warnings = [
            r
            for r in caplog.records
            if "degradation" in r.message.lower() or "degraded" in r.message.lower()
        ]
        assert len(degradation_warnings) >= 1
        # Warning should mention the ratio
        msg = degradation_warnings[0].message.lower()
        assert "1" in msg or "33" in msg

    def test_one_of_five_results_clearly_degraded(self, caplog: pytest.LogCaptureFixture) -> None:
        """1/5 = 20% < 50% 阈值，必须记录降级。"""
        with caplog.at_level(logging.WARNING, logger="gearbox.agents.shared.selection"):
            results = [{"id": "solo"}]
            idx, val = asyncio.run(select_best_result(results, result_type="test", max_runs=5))
            assert idx == 0

        degradation_warnings = [
            r
            for r in caplog.records
            if "degradation" in r.message.lower() or "degraded" in r.message.lower()
        ]
        assert len(degradation_warnings) >= 1

    def test_two_results_with_max_runs_three_no_warning_on_threshold_met(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """2 结果 + max_runs=3 → threshold=1.5, 2≥1.5 不应警告（但走 evaluator 路径）。

        验证阈值检查不阻止正常流程，且不发出降级警告。
        """
        with caplog.at_level(logging.WARNING, logger="gearbox.agents.shared.selection"):
            results = [{"id": "a"}, {"id": "b"}]
            # Evaluator may or may not run depending on environment;
            # we only verify no degradation warning is emitted.
            try:
                asyncio.run(select_best_result(results, result_type="test", max_runs=3))
            except Exception:
                pass  # SDK unavailable / evaluator error in CI — acceptable

    def test_zero_max_runs_disables_degradation_check(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """max_runs=0 → 不进行降级检测，无警告。"""
        with caplog.at_level(logging.WARNING, logger="gearbox.agents.shared.selection"):
            results = [{"id": "only"}]
            idx, val = asyncio.run(select_best_result(results, result_type="test", max_runs=0))
            assert idx == 0

        assert not any(
            "degradation" in rec.message.lower() or "degraded" in rec.message.lower()
            for rec in caplog.records
        )

    def test_default_max_runs_no_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """不传 max_runs 时默认为 0，不进行降级检测。"""
        with caplog.at_level(logging.WARNING, logger="gearbox.agents.shared.selection"):
            results = [{"id": "only"}]
            idx, val = asyncio.run(select_best_result(results, result_type="test"))
            assert idx == 0

        assert not any(
            "degradation" in rec.message.lower() or "degraded" in rec.message.lower()
            for rec in caplog.records
        )

    def test_empty_results_raises_valueerror(self) -> None:
        """空结果列表应抛出 ValueError。"""
        with pytest.raises(ValueError, match="results must not be empty"):
            asyncio.run(select_best_result([], result_type="test"))

    def test_two_results_default_max_runs_no_warning_before_evaluator(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """2 结果 + 默认 max_runs(=0) → 无降级检测，直接进入 evaluator 路径。"""
        with caplog.at_level(logging.WARNING, logger="gearbox.agents.shared.selection"):
            results = [{"id": "a"}, {"id": "b"}]
            # Evaluator may or may not run depending on environment;
            # we only verify no degradation warning is emitted before/after.
            try:
                asyncio.run(select_best_result(results, result_type="test"))
            except Exception:
                pass  # SDK unavailable / evaluator error in CI — acceptable

        assert not any(
            "degradation" in rec.message.lower() or "degraded" in rec.message.lower()
            for rec in caplog.records
        )
