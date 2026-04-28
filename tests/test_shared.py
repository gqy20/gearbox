"""Tests for agents/shared modules — structured output, artifacts, selection, prompt helpers."""

import json
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel

from gearbox.agents.shared.artifacts import read_json_artifact, to_jsonable, write_json_artifact
from gearbox.agents.shared.github_output import format_currency, result_to_github_output
from gearbox.agents.shared.prompt_helpers import format_issues_summary
from gearbox.agents.shared.structured import (
    json_schema_output,
    parse_structured_output,
    parse_with_model,
)
from gearbox.core.gh import IssueSummary

# ---------------------------------------------------------------------------
# prompt_helpers
# ---------------------------------------------------------------------------


class TestFormatIssuesSummary:
    """测试 format_issues_summary"""

    def test_formats_multiple_issues(self) -> None:
        issues = [
            IssueSummary(
                number=1,
                title="Bug fix",
                labels=["bug"],
                url="https://example.com/1",
                created_at="",
            ),
            IssueSummary(
                number=2,
                title="Feature",
                labels=["enhancement"],
                url="https://example.com/2",
                created_at="",
            ),
        ]
        result = format_issues_summary(issues)

        assert "#1 [Bug fix](https://example.com/1)" in result
        assert "#2 [Feature](https://example.com/2)" in result
        assert "其他 Open Issues 概览" in result

    def test_excludes_current_issue(self) -> None:
        issues = [
            IssueSummary(number=1, title="A", labels=[], url="http://x.com/1", created_at=""),
            IssueSummary(number=2, title="B", labels=[], url="http://x.com/2", created_at=""),
        ]
        result = format_issues_summary(issues, current_issue_number=1)

        assert "#1" not in result
        assert "#2" in result

    def test_empty_issues_returns_placeholder(self) -> None:
        result = format_issues_summary([])

        assert "(无其他 open issues)" in result

    def test_custom_header(self) -> None:
        issues = [
            IssueSummary(number=1, title="X", labels=["P1"], url="http://x.com/1", created_at="")
        ]
        result = format_issues_summary(issues, header="Custom Header")

        assert "Custom Header" in result

    def test_labels_displayed_as_comma_separated(self) -> None:
        issues = [
            IssueSummary(
                number=1,
                title="X",
                labels=["P1", "complexity:S"],
                url="http://x.com/1",
                created_at="",
            )
        ]
        result = format_issues_summary(issues)

        assert "P1, complexity:S" in result

    def test_no_labels_shows_placeholder(self) -> None:
        issues = [IssueSummary(number=1, title="X", labels=[], url="http://x.com/1", created_at="")]
        result = format_issues_summary(issues)

        assert "无标签" in result

    def test_single_issue_excluded_leaves_empty_list(self) -> None:
        issues = [
            IssueSummary(number=7, title="Only", labels=[], url="http://x.com/7", created_at="")
        ]
        result = format_issues_summary(issues, current_issue_number=7)

        assert "(无其他 open issues)" in result


# ---------------------------------------------------------------------------
# structured output
# ---------------------------------------------------------------------------


class TestJsonSchemaOutput:
    """测试 json_schema_output"""

    def test_wraps_schema_correctly(self) -> None:
        schema = {"type": "object", "properties": {"name": {"type": "string"}}}
        result = json_schema_output(schema)

        assert result["type"] == "json_schema"
        assert result["schema"] == schema


class TestParseStructuredOutput:
    """测试 parse_structured_output"""

    def test_returns_none_for_non_message(self) -> None:
        assert parse_structured_output("not a message", lambda x: x) is None

    def test_returns_none_when_raw_is_none(self) -> None:
        fake_msg = MagicMock(spec=object)
        # Mock _extract_raw_dict to return None
        with patch("gearbox.agents.shared.structured._extract_raw_dict", return_value=None):
            assert parse_structured_output(fake_msg, lambda x: x) is None

    def test_calls_parser_with_extracted_dict(self) -> None:
        extracted = {"key": "value"}
        fake_msg = MagicMock()

        with patch("gearbox.agents.shared.structured._extract_raw_dict", return_value=extracted):
            result = parse_structured_output(fake_msg, lambda d: d["key"])

        assert result == "value"


class TestParseWithModel:
    """测试 parse_with_model"""

    def test_validates_with_pydantic_model(self) -> None:
        class MyModel(BaseModel):
            name: str
            count: int

        raw = {"name": "test", "count": 42}
        fake_msg = MagicMock()

        with patch("gearbox.agents.shared.structured._extract_raw_dict", return_value=raw):
            result = parse_with_model(fake_msg, MyModel)

        assert result is not None
        assert result.name == "test"
        assert result.count == 42

    def test_returns_none_when_extraction_fails(self) -> None:
        class MyModel(BaseModel):
            name: str

        fake_msg = MagicMock()

        with patch("gearbox.agents.shared.structured._extract_raw_dict", return_value=None):
            assert parse_with_model(fake_msg, MyModel) is None

    def test_raises_validation_error_for_invalid_data(self) -> None:
        class MyModel(BaseModel):
            name: str  # required

        raw = {"count": 42}  # missing name
        fake_msg = MagicMock()

        with patch("gearbox.agents.shared.structured._extract_raw_dict", return_value=raw):
            with pytest.raises(Exception):  # ValidationError
                parse_with_model(fake_msg, MyModel)


# ---------------------------------------------------------------------------
# artifacts
# ---------------------------------------------------------------------------


class TestToJsonable:
    """测试 to_jsonable"""

    def test_handles_pydantic_basemodel(self) -> None:
        class M(BaseModel):
            x: int

        assert to_jsonable(M(x=42)) == {"x": 42}

    def test_handles_dataclass(self) -> None:
        @dataclass
        class D:
            a: str
            b: int

        assert to_jsonable(D(a="hello", b=10)) == {"a": "hello", "b": 10}

    def test_handles_plain_dict(self) -> None:
        assert to_jsonable({"key": "value"}) == {"key": "value"}

    def test_handles_list_recursively(self) -> None:
        @dataclass
        class D:
            v: int

        assert to_jsonable([D(v=1), D(v=2)]) == [{"v": 1}, {"v": 2}]

    def test_handles_nested_dict(self) -> None:
        @dataclass
        class D:
            x: int

        assert to_jsonable({"item": D(x=99)}) == {"item": {"x": 99}}

    def test_skips_private_attributes_on_objects(self) -> None:
        class Obj:
            def __init__(self) -> None:
                self.public = "visible"
                self._private = "hidden"

        assert to_jsonable(Obj()) == {"public": "visible"}

    def test_passes_through_primitives(self) -> None:
        assert to_jsonable(42) == 42
        assert to_jsonable("str") == "str"
        assert to_jsonable(None) is None

    def test_handles_object_with_model_dump(self) -> None:
        class Custom:
            def model_dump(self) -> dict[str, object]:
                return {"custom": "dumped"}

        assert to_jsonable(Custom()) == {"custom": "dumped"}


class TestWriteJsonArtifact:
    """测试 write_json_artifact"""

    def test_writes_file(self, tmp_path: Path) -> None:
        artifact_path = tmp_path / "out" / "result.json"
        write_json_artifact(artifact_path, {"key": "value"})

        assert artifact_path.exists()
        data = json.loads(artifact_path.read_text(encoding="utf-8"))
        assert data == {"key": "value"}

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        artifact_path = tmp_path / "nested" / "deep" / "file.json"
        write_json_artifact(artifact_path, {})

        assert artifact_path.exists()


class TestReadJsonArtifact:
    """测试 read_json_artifact"""

    def test_reads_valid_json(self, tmp_path: Path) -> None:
        f = tmp_path / "data.json"
        f.write_text('{"a": 1}', encoding="utf-8")

        assert read_json_artifact(f) == {"a": 1}

    def test_raises_on_non_dict(self, tmp_path: Path) -> None:
        f = tmp_path / "list.json"
        f.write_text("[1, 2, 3]", encoding="utf-8")

        with pytest.raises(AssertionError):
            read_json_artifact(f)


# ---------------------------------------------------------------------------
# github_output
# ---------------------------------------------------------------------------


class TestFormatCurrency:
    """测试 format_currency"""

    def test_formats_amount(self) -> None:
        assert format_currency(0.1234) == "$0.1234"

    def test_formats_large_amount(self) -> None:
        assert format_currency(9999.9999) == "$9999.9999"

    def test_returns_na_for_none(self) -> None:
        assert format_currency(None) == "n/a"


class TestResultToGithubOutput:
    """测试 result_to_github_output"""

    def test_writes_flat_fields(self, tmp_path: Path) -> None:
        @dataclass
        class R:
            name: str
            count: int

        output_file = tmp_path / "output.txt"
        result_to_github_output(R(name="test", count=5), output_file=str(output_file))

        content = output_file.read_text(encoding="utf-8")
        assert "name=test\n" in content
        assert "count=5\n" in content
        assert "status=success\n" in content

    def test_converts_bool_to_lowercase_string(self, tmp_path: Path) -> None:
        @dataclass
        class R:
            flag: bool

        output_file = tmp_path / "output.txt"
        result_to_github_output(R(flag=True), output_file=str(output_file))

        content = output_file.read_text(encoding="utf-8")
        assert "flag=true\n" in content

    def test_converts_none_to_empty_string(self, tmp_path: Path) -> None:
        @dataclass
        class R:
            optional: str | None

        output_file = tmp_path / "output.txt"
        result_to_github_output(R(optional=None), output_file=str(output_file))

        content = output_file.read_text(encoding="utf-8")
        assert "optional=\n" in content

    def test_jsonifies_lists_and_dicts(self, tmp_path: Path) -> None:
        @dataclass
        class R:
            items: list[str]

        output_file = tmp_path / "output.txt"
        result_to_github_output(R(items=["a", "b"]), output_file=str(output_file))

        content = output_file.read_text(encoding="utf-8")
        assert '"items"' in content or "items" in content

    def test_calls_write_outputs(self, tmp_path: Path) -> None:
        @dataclass
        class R:
            value: int

        output_file = tmp_path / "gh_output"
        result_to_github_output(R(value=42), output_file=str(output_file))

        assert output_file.exists()
