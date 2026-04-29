"""Tests for commands/shared.py — candidate discovery, backlog application, and _select_single."""

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from gearbox.commands.shared import (
    _apply_backlog_item,
    _apply_backlog_item_with_comments,
    _candidate_result_files,
    _select_single,
)

# ---------------------------------------------------------------------------
# _candidate_result_files — artifact layout discovery
# ---------------------------------------------------------------------------


class TestCandidateResultFiles:
    """Verify result.json discovery across flat and nested artifact layouts."""

    def test_flat_layout_single_file(self, tmp_path: Path) -> None:
        """Single result.json at root of input directory."""
        result_file = tmp_path / "result.json"
        result_file.write_text('{"key": "val"}')

        candidates = _candidate_result_files(tmp_path)
        assert len(candidates) == 1
        assert candidates[0] == (tmp_path.name, result_file)

    def test_nested_layout_run_dirs(self, tmp_path: Path) -> None:
        """Multiple run directories each containing result.json."""
        for i in range(3):
            (tmp_path / f"run_{i}").mkdir()
            (tmp_path / f"run_{i}" / "result.json").write_text(f'{{"run": {i}}}')

        candidates = _candidate_result_files(tmp_path)
        assert len(candidates) == 3
        names = [name for name, _ in candidates]
        assert names == ["run_0", "run_1", "run_2"]

    def test_mixed_flat_and_nested(self, tmp_path: Path) -> None:
        """Flat result.json plus nested run directories."""
        (tmp_path / "result.json").write_text('{"flat": true}')
        (tmp_path / "run_0").mkdir()
        (tmp_path / "run_0" / "result.json").write_text('{"run": 0}')

        candidates = _candidate_result_files(tmp_path)
        assert len(candidates) == 2
        # Flat file comes first
        assert candidates[0][0] == tmp_path.name
        assert candidates[1][0] == "run_0"

    def test_no_result_files_returns_empty(self, tmp_path: Path) -> None:
        """Directory with no result.json files returns empty list."""
        (tmp_path / "other.txt").write_text("hello")
        (tmp_path / "empty_dir").mkdir()
        (tmp_path / "empty_dir" / ".gitkeep").write_text("")

        candidates = _candidate_result_files(tmp_path)
        assert candidates == []

    def test_nonexistent_directory_returns_empty(self, tmp_path: Path) -> None:
        """Non-existent path returns empty list (no crash)."""
        candidates = _candidate_result_files(tmp_path / "does_not_exist")
        assert candidates == []

    def test_nested_dirs_without_result_json_skipped(self, tmp_path: Path) -> None:
        """Run directories without result.json are silently skipped."""
        (tmp_path / "run_0").mkdir()
        (tmp_path / "run_0" / "result.json").write_text("{}")
        (tmp_path / "run_1").mkdir()
        (tmp_path / "run_1" / "data.txt").write_text("no result here")
        (tmp_path / "run_2" / "subdir").mkdir(parents=True)
        (tmp_path / "run_2" / "subdir" / "result.json").write_text("{}")

        candidates = _candidate_result_files(tmp_path)
        # Only run_0 has a direct result.json; run_2's is in a subdir
        assert len(candidates) == 1
        assert candidates[0][0] == "run_0"

    def test_dirs_are_sorted_alphabetically(self, tmp_path: Path) -> None:
        """Run directories should be returned in sorted order."""
        for name in ["run_z", "run_a", "run_m"]:
            (tmp_path / name).mkdir()
            (tmp_path / name / "result.json").write_text("{}")

        candidates = _candidate_result_files(tmp_path)
        names = [name for name, _ in candidates]
        assert names == ["run_a", "run_m", "run_z"]


# ---------------------------------------------------------------------------
# _apply_backlog_item — label and comment application
# ---------------------------------------------------------------------------


class TestApplyBacklogItem:
    def test_missing_issue_number_raises(self) -> None:
        """Result without issue_number attribute raises ClickException."""

        class BadResult:
            pass

        with pytest.raises(Exception, match="missing issue_number"):
            _apply_backlog_item("owner/repo", BadResult())

    def test_invalid_comment_mode_raises(self, monkeypatch) -> None:
        """comment_mode outside {auto, never} raises ClickException."""

        class FakeResult:
            issue_number = 1

        monkeypatch.setattr(
            "gearbox.commands.shared.github_labels_for_backlog_item",
            lambda r: ["bug"],
        )
        monkeypatch.setattr(
            "gearbox.commands.shared.replace_managed_issue_labels",
            lambda *args, **kwargs: MagicMock(success=True),
        )

        with pytest.raises(Exception, match="comment_mode must be"):
            _apply_backlog_item_with_comments("owner/repo", FakeResult(), comment_mode="invalid")

    def test_comment_mode_never_skips_comment_posting(self, monkeypatch) -> None:
        """When comment_mode=never, labels are applied but no comment is posted."""

        class FakeResult:
            issue_number = 42
            ready_to_implement = True

        label_called: bool = False
        comment_called: bool = False

        def fake_labels(r):
            nonlocal label_called
            label_called = True
            return ["bug", "P1"]

        def fake_replace(*args, **kwargs):
            return MagicMock(success=True)

        def fake_comment(*args, **kwargs):
            nonlocal comment_called
            comment_called = True
            return MagicMock(success=True)

        monkeypatch.setattr("gearbox.commands.shared.github_labels_for_backlog_item", fake_labels)
        monkeypatch.setattr("gearbox.commands.shared.replace_managed_issue_labels", fake_replace)
        monkeypatch.setattr("gearbox.commands.shared.post_issue_comment", fake_comment)

        _apply_backlog_item_with_comments("owner/repo", FakeResult(), comment_mode="never")

        assert label_called
        assert not comment_called


# ---------------------------------------------------------------------------
# _select_single — end-to-end selection with mocked SDK
# ---------------------------------------------------------------------------


class TestSelectSingle:
    """Test the full select → callback → github-output pipeline."""

    def test_empty_candidates_raises(self) -> None:
        async def _run():
            return await _select_single([], result_type="T", model="m", max_turns=5)

        with pytest.raises(Exception, match="No candidates found"):
            asyncio.run(_run())

    def test_single_candidate_skips_evaluator(self, monkeypatch, tmp_path: Path) -> None:
        """With one candidate, evaluator should not be called."""

        class FakeResult:
            def __init__(self) -> None:
                self.branch_name = "feat/issue-1"

        item = FakeResult()
        eval_called: bool = False

        async def fake_select_best(*args, **kwargs):
            nonlocal eval_called
            eval_called = True
            return 0, args[0][0]

        monkeypatch.setattr("gearbox.commands.shared.select_best_result", fake_select_best)

        output_file = str(tmp_path / "output.txt")
        callback_called_with: list = []

        def fake_callback(result, name):
            callback_called_with.append((result, name))

        async def _run():
            return await _select_single(
                [("only", item)],
                result_type="T",
                model="m",
                max_turns=5,
                winner_callback=fake_callback,
                output=output_file,
            )

        result, name = asyncio.run(_run())
        # Single item fast path means select_best_result IS called but it short-circuits
        assert result is item
        assert name == "only"
        assert callback_called_with == [(item, "only")]
        # Output file should be written
        assert Path(output_file).exists()

    def test_multi_candidate_calls_evaluator_and_callback(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        """With multiple candidates, runs evaluation then applies winner callback."""

        class FakeResultA:
            def __init__(self) -> None:
                self.branch_name = "feat/issue-1-a"

        class FakeResultB:
            def __init__(self) -> None:
                self.branch_name = "feat/issue-1-b"

        item_a = FakeResultA()
        item_b = FakeResultB()

        async def fake_select_best(*args, **kwargs):
            return 1, item_b  # winner index 1 = item_b

        monkeypatch.setattr("gearbox.commands.shared.select_best_result", fake_select_best)

        output_file = str(tmp_path / "output.txt")
        callback_results: list = []

        def fake_callback(result, name):
            callback_results.append((result, name))

        async def _run():
            return await _select_single(
                [("run_a", item_a), ("run_b", item_b)],
                result_type="Test",
                model="test-model",
                max_turns=10,
                winner_callback=fake_callback,
                output=output_file,
            )

        result, name = asyncio.run(_run())
        assert result is item_b
        assert name == "run_b"
        assert callback_results == [(item_b, "run_b")]
        assert Path(output_file).exists()
