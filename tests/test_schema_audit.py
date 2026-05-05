"""Tests for audit schema — Issue.labels type correctness."""

from gearbox.agents.schemas.audit import AuditResult, Issue


class TestIssueLabelsType:
    """Verify Issue.labels is list[str] to match downstream gh.create_issue() contract."""

    def test_labels_accepts_list_of_strings(self) -> None:
        """LLM returning labels as array should parse without ValidationError."""
        issue = Issue(
            title="Test issue",
            body="Test body",
            labels=["bug", "enhancement"],
        )
        assert issue.labels == ["bug", "enhancement"]

    def test_labels_list_iterates_as_elements_not_characters(self) -> None:
        """Iterating labels must yield label strings, not individual characters."""
        issue = Issue(
            title="Test issue",
            body="Test body",
            labels=["bug", "security"],
        )
        # Downstream code does: [label for label in labels if label in VALID_ISSUE_LABELS]
        filtered = [label for label in issue.labels if label in {"bug", "security", "enhancement"}]
        assert filtered == ["bug", "security"]
        assert len(filtered) == 2  # not 11 (character count)

    def test_labels_default_is_empty_list(self) -> None:
        """Missing labels should default to empty list, not empty string."""
        issue = Issue(title="Test", body="Body")
        assert isinstance(issue.labels, list)
        assert issue.labels == []

    def test_audit_result_with_list_labels_roundtrips(self) -> None:
        """Full AuditResult with list labels should serialise and deserialise correctly."""
        result = AuditResult(
            repo="owner/repo",
            issues=[
                Issue(title="A", body="B", labels=["P0", "security"]),
                Issue(title="C", body="D", labels=["enhancement"]),
            ],
        )
        data = result.model_dump()
        restored = AuditResult.model_validate(data)
        assert restored.issues[0].labels == ["P0", "security"]
        assert restored.issues[1].labels == ["enhancement"]

    def test_labels_rejects_plain_string(self) -> None:
        """Passing a comma-separated string like 'bug,enhancement' must NOT silently coerce."""
        import pytest as pt

        with pt.raises(Exception):  # ValidationError or similar
            Issue.model_validate(
                {"title": "T", "body": "B", "labels": "bug,enhancement"}
            )
