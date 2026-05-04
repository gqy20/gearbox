"""Tests for schema version identification and forward/backward compatibility."""

import json
from pathlib import Path

import pytest

from gearbox.agents.schemas import (
    AuditResult,
    BacklogItemResult,
    EvaluationResult,
    FixResult,
    ImplementResult,
    ReviewResult,
    parse_with_model,
)
from gearbox.agents.schemas.audit import Issue as AuditIssue

# ---------------------------------------------------------------------------
# 1. All result schemas carry schema_version with correct default
# ---------------------------------------------------------------------------


class TestSchemaVersionFieldPresent:
    """Every result model must expose a schema_version field defaulting to '1.0'."""

    @pytest.mark.parametrize(
        "model_cls, kwargs",
        [
            (AuditResult, {"repo": "o/r"}),
            (ReviewResult, {"verdict": "LGTM", "score": 8, "summary": "ok"}),
            (ImplementResult, {"branch_name": "f/x", "summary": "s"}),
            (BacklogItemResult, {}),
            (EvaluationResult, {"winner": 0}),
            (FixResult, {"verdict": "skipped", "commits_pushed": 0}),
        ],
    )
    def test_default_schema_version_is_1_0(self, model_cls, kwargs) -> None:
        instance = model_cls(**kwargs)
        assert instance.schema_version == "1.0"

    @pytest.mark.parametrize(
        "model_cls",
        [
            AuditResult,
            ReviewResult,
            ImplementResult,
            BacklogItemResult,
            EvaluationResult,
            FixResult,
        ],
    )
    def test_schema_version_field_in_json_schema(self, model_cls) -> None:
        schema = model_cls.model_json_schema()
        assert "schema_version" in schema["properties"]
        assert "1.0" in schema["properties"]["schema_version"].get(
            "const", schema["properties"]["schema_version"].get("enum", [])
        )

    def test_schema_version_serialises_to_json(self) -> None:
        result = ImplementResult(branch_name="f/x", summary="s")
        dumped = result.model_dump()
        assert dumped["schema_version"] == "1.0"


# ---------------------------------------------------------------------------
# 2. parse_with_model tolerates missing schema_version (SDK output)
# ---------------------------------------------------------------------------


class TestParseWithModelVersionTolerance:
    """Structured output from the SDK may omit schema_version; we must still parse it."""

    def test_audit_parse_without_schema_version_succeeds(self) -> None:
        from claude_agent_sdk import ResultMessage

        msg = ResultMessage(
            subtype="result",
            duration_ms=100,
            duration_api_ms=80,
            is_error=False,
            num_turns=1,
            session_id="s",
            structured_output={
                "repo": "owner/repo",
                "profile": {},
                "comparison_markdown": "",
                "benchmarks": [],
                "issues": [],
            },
        )
        result = parse_with_model(msg, AuditResult)
        assert result is not None
        assert result.schema_version == "1.0"

    def test_review_parse_without_schema_version_succeeds(self) -> None:
        from claude_agent_sdk import ResultMessage

        msg = ResultMessage(
            subtype="result",
            duration_ms=100,
            duration_api_ms=80,
            is_error=False,
            num_turns=1,
            session_id="s",
            structured_output={
                "verdict": "LGTM",
                "score": 7,
                "summary": "ok",
                "comments": [],
            },
        )
        result = parse_with_model(msg, ReviewResult)
        assert result is not None
        assert result.schema_version == "1.0"


# ---------------------------------------------------------------------------
# 3. load_* functions validate version on persisted artifacts
# ---------------------------------------------------------------------------


class TestLoadAuditResultVersionCheck:
    """load_audit_result must reject artifacts whose version does not match."""

    def test_loads_current_version(self, tmp_path: Path) -> None:
        from gearbox.agents.audit import _write_audit_outputs, load_audit_result

        result = AuditResult(repo="o/r", issues=[AuditIssue(title="T", body="B", labels="bug")])
        _write_audit_outputs(result, tmp_path)

        loaded = load_audit_result(tmp_path)
        assert loaded.repo == "o/r"
        assert loaded.schema_version == "1.0"

    def test_rejects_missing_version_in_issues_json(self, tmp_path: Path) -> None:
        from gearbox.agents.audit import load_audit_result

        # Write a legacy (pre-version) issues.json
        (tmp_path / "issues.json").write_text(
            json.dumps(
                {
                    "repo": "o/r",
                    "profile": {},
                    "benchmarks": [],
                    "issues": [],
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "comparison.md").write_text("# old\n", encoding="utf-8")

        with pytest.raises(ValueError, match="schema_version"):
            load_audit_result(tmp_path)

    def test_rejects_wrong_version(self, tmp_path: Path) -> None:
        from gearbox.agents.audit import load_audit_result

        (tmp_path / "issues.json").write_text(
            json.dumps(
                {
                    "schema_version": "2.0",
                    "repo": "o/r",
                    "profile": {},
                    "benchmarks": [],
                    "issues": [],
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "comparison.md").write_text("# v2\n", encoding="utf-8")

        with pytest.raises(ValueError, match="schema_version.*2.0.*1.0"):
            load_audit_result(tmp_path)


class TestLoadReviewResultVersionCheck:
    def test_loads_current_version(self, tmp_path: Path) -> None:
        from gearbox.agents.review import load_review_result, write_review_result

        result = ReviewResult(verdict="LGTM", score=8, summary="ok")
        write_review_result(result, tmp_path / "result.json")
        loaded = load_review_result(tmp_path / "result.json")
        assert loaded.schema_version == "1.0"

    def test_rejects_missing_version(self, tmp_path: Path) -> None:
        from gearbox.agents.review import load_review_result

        (tmp_path / "result.json").write_text(
            json.dumps({"verdict": "LGTM", "score": 8, "summary": "ok", "comments": []}),
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="schema_version"):
            load_review_result(tmp_path / "result.json")


class TestLoadImplementResultVersionCheck:
    def test_loads_current_version(self, tmp_path: Path) -> None:
        from gearbox.agents.implement import load_implement_result, write_implement_result

        result = ImplementResult(branch_name="f/x", summary="s")
        write_implement_result(result, tmp_path / "result.json")
        loaded = load_implement_result(tmp_path / "result.json")
        assert loaded.schema_version == "1.0"

    def test_rejects_missing_version(self, tmp_path: Path) -> None:
        from gearbox.agents.implement import load_implement_result

        (tmp_path / "result.json").write_text(
            json.dumps({"branch_name": "f/x", "summary": "s"}),
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="schema_version"):
            load_implement_result(tmp_path / "result.json")


class TestLoadBacklogResultVersionCheck:
    def test_loads_current_version(self, tmp_path: Path) -> None:
        from gearbox.agents.backlog import BacklogResult, load_backlog_result, write_backlog_result

        item = BacklogItemResult(labels=["bug"], priority="P1", complexity="S")
        write_backlog_result(BacklogResult(items=[item]), tmp_path / "result.json")
        loaded = load_backlog_result(tmp_path / "result.json")
        assert loaded.items[0].schema_version == "1.0"

    def test_rejects_missing_version_on_items(self, tmp_path: Path) -> None:
        from gearbox.agents.backlog import load_backlog_result

        (tmp_path / "result.json").write_text(
            json.dumps({"items": [{"labels": ["bug"], "priority": "P1", "complexity": "S"}]}),
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="schema_version"):
            load_backlog_result(tmp_path / "result.json")


# ---------------------------------------------------------------------------
# 4. Artifact writers embed version metadata
# ---------------------------------------------------------------------------


class TestArtifactVersionMetadata:
    def test_write_audit_outputs_includes_schema_version(self, tmp_path: Path) -> None:
        from gearbox.agents.audit import _write_audit_outputs

        result = AuditResult(repo="o/r", issues=[AuditIssue(title="T", body="B", labels="bug")])
        _write_audit_outputs(result, tmp_path)

        data = json.loads((tmp_path / "issues.json").read_text(encoding="utf-8"))
        assert data.get("schema_version") == "1.0"

    def test_benchmark_cache_includes_version_metadata(self, tmp_path, monkeypatch) -> None:
        from gearbox.agents.audit import _cache_benchmarks, _get_cached_benchmarks

        cache_dir = tmp_path / "cache"
        monkeypatch.setattr("gearbox.agents.audit._BENCHMARK_CACHE_DIR", cache_dir)

        _cache_benchmarks("owner/repo", ["bench/a", "bench/b"])
        cached = _get_cached_benchmarks("owner/repo")
        assert cached == ["bench/a", "bench/b"]

        cache_file = cache_dir / "owner_repo.json"
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        assert data.get("schema_version") == "1.0"
