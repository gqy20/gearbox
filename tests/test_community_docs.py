"""Tests for open-source community standard files."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class TestContributingMd:
    """CONTRIBUTING.md must exist with required sections for contributors."""

    def test_contributing_exists(self) -> None:
        contributing = PROJECT_ROOT / "CONTRIBUTING.md"
        assert contributing.exists(), "CONTRIBUTING.md must exist at project root"

    def test_contributing_has_dev_setup_section(self) -> None:
        text = (PROJECT_ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
        assert "uv sync" in text, "Must describe dev environment setup with uv sync"
        assert "python" in text.lower(), "Must mention Python version requirement"

    def test_contributing_has_code_standards(self) -> None:
        text = (PROJECT_ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
        assert "ruff" in text.lower(), "Must describe ruff linting/formatting rules"
        assert "mypy" in text.lower(), "Must describe mypy type checking"

    def test_contributing_has_pr_process(self) -> None:
        text = (PROJECT_ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
        assert "pr" in text.lower() or "pull request" in text.lower(), (
            "Must describe PR workflow"
        )
        assert "test" in text.lower(), "Must require tests"


class TestCodeOfConductMd:
    """CODE_OF_CONDUCT.md must exist based on Contributor Covenant."""

    def test_code_of_conduct_exists(self) -> None:
        coc = PROJECT_ROOT / "CODE_OF_CONDUCT.md"
        assert coc.exists(), "CODE_OF_CONDUCT.md must exist at project root"

    def test_code_of_conduct_has_covenant_reference(self) -> None:
        text = (PROJECT_ROOT / "CODE_OF_CONDUCT.md").read_text(encoding="utf-8")
        assert "Contributor Covenant" in text or "contributor-covenant" in text.lower(), (
            "Should be based on Contributor Covenant"
        )

    def test_code_of_conduct_has_contact_info(self) -> None:
        text = (PROJECT_ROOT / "CODE_OF_CONDUCT.md").read_text(encoding="utf-8")
        # Must have some way to report conduct issues
        assert "@" in text or "email" in text.lower() or "contact" in text.lower(), (
            "Must provide contact information for reporting"
        )


class TestChangelogMd:
    """CHANGELOG.md must follow Keep a Changelog format."""

    def test_changelog_exists(self) -> None:
        changelog = PROJECT_ROOT / "CHANGELOG.md"
        assert changelog.exists(), "CHANGELOG.md must exist at project root"

    def test_changelog_has_version_sections(self) -> None:
        text = (PROJECT_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        # Keep a Changelog uses ## [version] - date format
        import re
        version_pattern = r"##\s+\[v?\d+\.\d+\.\d+\]"
        assert re.search(version_pattern, text), (
            "CHANGELOG must have version sections like ## [vX.Y.Z]"
        )

    def test_changelog_has_categorized_entries(self) -> None:
        text = (PROJECT_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        # Should have categorized change types
        categories = ["新增", "变更", "修复", "Added", "Changed", "Fixed"]
        found_any = any(cat in text for cat in categories)
        assert found_any, "CHANGELOG should have categorized entries (新增/变更/修复 etc.)"
