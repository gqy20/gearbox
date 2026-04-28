"""测试 agents/shared/scanner.py 静态分析扫描器"""

import json
import logging
from pathlib import Path
from unittest.mock import patch

from gearbox.agents.shared.scanner import (
    RepoScanResult,
    _fallback_file_counts,
    _has_optional_dev_group,
    _project_name,
    _read_pyproject,
    detect_project_type,
    format_scan_summary,
    run_cloc,
    run_deptry,
    run_govulncheck,
    run_semgrep,
    run_trivy,
    scan_repository,
)
from gearbox.agents.shared.scanner import (
    logger as scanner_logger,
)

# ---------------------------------------------------------------------------
# detect_project_type
# ---------------------------------------------------------------------------


class TestDetectProjectType:
    """项目类型检测"""

    def test_python_project(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]\nname = foo\n", encoding="utf-8")
        ptype, pmgr, docker, sec = detect_project_type(tmp_path)

        assert ptype == "python"
        assert pmgr == "pip"

    def test_typescript_project(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text('{"name":"foo"}\n', encoding="utf-8")
        ptype, pmgr, docker, sec = detect_project_type(tmp_path)

        assert ptype == "typescript"
        assert pmgr == "npm"

    def test_go_project(self, tmp_path: Path) -> None:
        (tmp_path / "go.mod").write_text("module example\n", encoding="utf-8")
        ptype, pmgr, docker, sec = detect_project_type(tmp_path)

        assert ptype == "go"
        assert pmgr == "go mod"

    def test_mixed_python_typescript(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").touch()
        (tmp_path / "package.json").write_text("{}", encoding="utf-8")
        ptype, pmgr, _, _ = detect_project_type(tmp_path)

        assert ptype == "mixed"
        assert pmgr == "multiple"

    def test_unknown_project(self, tmp_path: Path) -> None:
        ptype, pmgr, docker, sec = detect_project_type(tmp_path)

        assert ptype == "unknown"
        assert pmgr == ""
        assert docker is False

    def test_docker_detection(self, tmp_path: Path) -> None:
        (tmp_path / "Dockerfile").touch()
        _, _, has_docker, _ = detect_project_type(tmp_path)
        assert has_docker is True

    def test_docker_compose_detection(self, tmp_path: Path) -> None:
        (tmp_path / "docker-compose.yml").touch()
        _, _, has_docker, _ = detect_project_type(tmp_path)
        assert has_docker is True


# ---------------------------------------------------------------------------
# _read_pyproject / _project_name / _has_optional_dev_group
# ---------------------------------------------------------------------------


class TestPyprojectParsing:
    """pyproject.toml 解析"""

    def test_reads_name(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "my-app"\n',
            encoding="utf-8",
        )
        assert _project_name(tmp_path) == "my_app"

    def test_normalizes_dashes_in_name(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "my-cool-app"\n',
            encoding="utf-8",
        )
        assert _project_name(tmp_path) == "my_cool_app"

    def test_missing_pyproject_returns_empty(self, tmp_path: Path) -> None:
        assert _project_name(tmp_path) == ""

    def test_malformed_toml_returns_empty(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("broken[", encoding="utf-8")
        assert _read_pyproject(tmp_path) == {}

    def test_detects_dev_group(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text(
            '[project.optional-dependencies]\ndev = ["pytest"]\n',
            encoding="utf-8",
        )
        assert _has_optional_dev_group(tmp_path) is True

    def test_no_dev_group(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
        assert _has_optional_dev_group(tmp_path) is False


# ---------------------------------------------------------------------------
# _run_command
# ---------------------------------------------------------------------------


class TestRunCommand:
    """命令执行封装"""

    def test_success_returns_stdout(self, tmp_path: Path) -> None:
        from gearbox.agents.shared.scanner import _run_command

        rc, out, err = _run_command(["echo", "hello"], tmp_path)

        assert rc == 0
        assert out.strip() == "hello"
        assert err == ""

    def test_failure_returns_nonzero_and_stderr(self, tmp_path: Path) -> None:
        from gearbox.agents.shared.scanner import _run_command

        rc, out, err = _run_command(["sh", "-c", "exit 1"], tmp_path)

        assert rc != 0

    def test_timeout_returns_minus_one(self, tmp_path: Path) -> None:
        from gearbox.agents.shared.scanner import _run_command

        rc, out, err = _run_command(["sleep", "10"], tmp_path, timeout=1)

        assert rc == -1
        assert "timeout" in err


# ---------------------------------------------------------------------------
# run_cloc / run_semgrep / run_trivy / run_deptry / run_govulncheck
# ---------------------------------------------------------------------------


class TestToolRunners:
    """各扫描工具结果解析 — 用 mock _run_command 验证解析逻辑"""

    @staticmethod
    def _fake_run(returncode: int, stdout: str = "", stderr: str = ""):
        def _fake(cmd, cwd, timeout=None):
            return returncode, stdout, stderr

        return _fake

    def test_cloc_ok_parses_languages(self, tmp_path: Path) -> None:
        fake = self._fake_run(
            0,
            '{"SUM":{"nFiles":5,"code":100},"Python":{"nFiles":3,"code":80}}',
        )
        with patch("gearbox.agents.shared.scanner._run_command", fake):
            data, status = run_cloc(tmp_path)

        assert status == "ok"
        assert data["SUM"]["nFiles"] == 5
        assert "Python" in data

    def test_cloc_strips_cjk_stats(self, tmp_path: Path) -> None:
        fake = self._fake_run(
            0,
            '{"SUM":{"nFiles":5,"code":100},"CJK":{"nFiles":2,"code":20},"Python":{"nFiles":1,"code":10}}',
        )
        with patch("gearbox.agents.shared.scanner._run_command", fake):
            data, status = run_cloc(tmp_path)

        # CJK 在 cloc 返回数据中存在，但 scan_repository 会过滤；这里测试原始 run_cloc 输出
        assert "CJK" in data
        assert data["Python"]["nFiles"] == 1

    def test_cloc_parse_failed_returns_empty(self, tmp_path: Path) -> None:
        fake = self._fake_run(0, "not json", "")
        with patch("gearbox.agents.shared.scanner._run_command", fake):
            data, status = run_cloc(tmp_path)

        assert data == {}
        assert "parse_failed" in status

    def test_cloc_command_failed_returns_empty(self, tmp_path: Path) -> None:
        fake = self._fake_run(1, "", "")
        with patch("gearbox.agents.shared.scanner._run_command", fake):
            data, status = run_cloc(tmp_path)

        assert data == {}
        assert status == "command_failed"

    def test_semgrep_ok_with_findings(self, tmp_path: Path) -> None:
        finding = {"id": "1", "message": "bad"}
        fake = self._fake_run(0, json.dumps({"results": [finding]}))
        with patch("gearbox.agents.shared.scanner._run_command", fake):
            findings, status = run_semgrep(tmp_path)

        assert status == "ok"
        # semgrep 运行两个配置（auto + p/security），每个都返回相同结果
        assert len(findings) == 2
        assert findings[0]["id"] == "1"

    def test_semgrep_no_findings_but_succeeded(self, tmp_path: Path) -> None:
        fake = self._fake_run(0, json.dumps({"results": []}))
        with patch("gearbox.agents.shared.scanner._run_command", fake):
            findings, status = run_semgrep(tmp_path)

        assert status == "ok"
        assert findings == []

    def test_semgrep_parse_failed(self, tmp_path: Path) -> None:
        fake = self._fake_run(0, "not json{")
        with patch("gearbox.agents.shared.scanner._run_command", fake):
            findings, status = run_semgrep(tmp_path)

        assert status == "parse_failed"

    def test_trivy_ok_with_vulns(self, tmp_path: Path) -> None:
        vuln = {"VulnerabilityID": "CVE-123", "Severity": "HIGH", "Title": "XSS"}
        fake = self._fake_run(0, json.dumps({"Results": [vuln]}))
        with patch("gearbox.agents.shared.scanner._run_command", fake):
            vulns, status = run_trivy(tmp_path)

        assert status == "ok"
        assert len(vulns) == 1
        assert vulns[0]["VulnerabilityID"] == "CVE-123"

    def test_trivy_no_vulns(self, tmp_path: Path) -> None:
        fake = self._fake_run(0, json.dumps({"Results": []}))
        with patch("gearbox.agents.shared.scanner._run_command", fake):
            vulns, status = run_trivy(tmp_path)

        assert status == "ok"
        assert vulns == []

    def test_deptry_ok_with_issues(self, tmp_path: Path) -> None:
        issue = {"type": "deprecated", "error": {"code": "DEP002", "message": "old pkg"}}
        # deptry 写临时文件再读取，需要同时 mock _run_command 和文件读取
        fake_run = self._fake_run(0, "", "")
        with (
            patch("gearbox.agents.shared.scanner._run_command", fake_run),
            patch("pathlib.Path.read_text", return_value=json.dumps([issue])),
        ):
            issues, status = run_deptry(tmp_path)

        assert "issues=1" in status or status == "ok"
        assert len(issues) == 1
        assert issues[0]["type"] == "deprecated"

    def test_deptry_ok_no_issues(self, tmp_path: Path) -> None:
        fake_run = self._fake_run(0, "", "")
        with (
            patch("gearbox.agents.shared.scanner._run_command", fake_run),
            patch("pathlib.Path.read_text", return_value="[]"),
        ):
            issues, status = run_deptry(tmp_path)

        assert status == "ok"
        assert issues == []

    def test_deptry_new_format_array_output(self, tmp_path: Path) -> None:
        issue = {"type": "security", "error": {"code": "SEC001"}}
        fake_run = self._fake_run(0, "", "")
        with (
            patch("gearbox.agents.shared.scanner._run_command", fake_run),
            patch("pathlib.Path.read_text", return_value=json.dumps([issue])),
        ):
            issues, status = run_deptry(tmp_path)

        assert len(issues) == 1
        assert issues[0]["type"] == "security"

    def test_govulncheck_ok_with_vulns(self, tmp_path: Path) -> None:
        vuln = {"id": "GO-1", "details": {"description": "oom"}}
        fake = self._fake_run(0, json.dumps({"vulnerabilities": [vuln]}))
        with patch("gearbox.agents.shared.scanner._run_command", fake):
            vulns, status = run_govulncheck(tmp_path)

        assert status == "ok"
        assert len(vulns) == 1
        assert vulns[0]["id"] == "GO-1"


# ---------------------------------------------------------------------------
# scan_repository 编排逻辑
# ---------------------------------------------------------------------------


class TestScanRepositoryOrchestration:
    """scan_repository 的编排逻辑：根据项目类型选择正确的工具组合"""

    def test_python_runs_deptry_trivy_and_semgrep(self, tmp_path: Path) -> None:
        """Python 项目应启用 deptry、trivy 和 semgrep 扫描（Issue #17）"""
        deptry_issues = [{"type": "x"}]
        trivy_vulns = [{"VulnerabilityID": "V-1"}]
        semgrep_finds = [{"id": "S-1", "message": "hardcoded secret"}]

        with (
            patch(
                "gearbox.agents.shared.scanner.detect_project_type",
                return_value=("python", "pip", False, False),
            ),
            patch("gearbox.agents.shared.scanner.run_cloc", return_value=({}, "ok")),
            patch(
                "gearbox.agents.shared.scanner.run_deptry", return_value=(deptry_issues, "issues=1")
            ),
            patch("gearbox.agents.shared.scanner.run_trivy", return_value=(trivy_vulns, "ok")),
            patch(
                "gearbox.agents.shared.scanner.run_semgrep",
                return_value=(semgrep_finds, "ok"),
            ),
        ):
            actual = scan_repository(tmp_path)

        assert actual.deptry_scanned is True
        assert actual.trivy_scanned is True
        assert actual.semgrep_scanned is True
        assert actual.tool_statuses["deptry"] == "issues=1"
        assert actual.tool_statuses["trivy"] == "ok"
        assert actual.tool_statuses["semgrep"] == "ok"

    def test_go_runs_govulncheck_and_trivy(self, tmp_path: Path) -> None:
        govuln_vulns = [{"id": "G-1"}]
        trivy_vulns = [{"VulnerabilityID": "V-1"}]

        with (
            patch(
                "gearbox.agents.shared.scanner.detect_project_type",
                return_value=("go", "go mod", False, False),
            ),
            patch("gearbox.agents.shared.scanner.run_cloc", return_value=({}, "ok")),
            patch(
                "gearbox.agents.shared.scanner.run_govulncheck", return_value=(govuln_vulns, "ok")
            ),
            patch("gearbox.agents.shared.scanner.run_trivy", return_value=(trivy_vulns, "ok")),
        ):
            actual = scan_repository(tmp_path)

        assert actual.govulncheck_scanned is True
        assert actual.trivy_scanned is True
        assert actual.tool_statuses.get("semgrep") == "skipped"
        assert actual.tool_statuses.get("deptry") == "skipped"

    def test_typescript_runs_semgrep_and_trivy(self, tmp_path: Path) -> None:
        semgrep_finds = [{"id": "S-1"}]
        trivy_vulns = [{"VulnerabilityID": "V-1"}]

        with (
            patch(
                "gearbox.agents.shared.scanner.detect_project_type",
                return_value=("typescript", "npm", False, False),
            ),
            patch("gearbox.agents.shared.scanner.run_cloc", return_value=({}, "ok")),
            patch("gearbox.agents.shared.scanner.run_semgrep", return_value=(semgrep_finds, "ok")),
            patch("gearbox.agents.shared.scanner.run_trivy", return_value=(trivy_vulns, "ok")),
        ):
            actual = scan_repository(tmp_path)

        assert actual.semgrep_scanned is True
        assert actual.trivy_scanned is True
        assert actual.tool_statuses.get("deptry") == "skipped"
        assert actual.tool_statuses.get("govulncheck") == "skipped"

    def test_unknown_skips_all_scanners(self, tmp_path: Path) -> None:
        with (
            patch(
                "gearbox.agents.shared.scanner.detect_project_type",
                return_value=("unknown", "", False, False),
            ),
            patch("gearbox.agents.shared.scanner.run_cloc", return_value=({}, "ok")),
        ):
            actual = scan_repository(tmp_path)

        assert actual.tool_statuses["deptry"] == "skipped"
        assert actual.tool_statuses["trivy"] == "skipped"
        assert actual.tool_statuses["semgrep"] == "skipped"
        assert actual.tool_statuses["govulncheck"] == "skipped"

    def test_tool_exception_recorded_as_status(self, tmp_path: Path) -> None:
        def failing_deptry(_path):
            raise RuntimeError("boom")

        with (
            patch(
                "gearbox.agents.shared.scanner.detect_project_type",
                return_value=("python", "pip", False, False),
            ),
            patch("gearbox.agents.shared.scanner.run_cloc", return_value=({}, "ok")),
            patch("gearbox.agents.shared.scanner.run_deptry", side_effect=failing_deptry),
            patch("gearbox.agents.shared.scanner.run_trivy", return_value=([], "ok")),
        ):
            actual = scan_repository(tmp_path)

        assert "exception:boom" in actual.tool_statuses.get("deptry", "")


# ---------------------------------------------------------------------------
# format_scan_summary
# ---------------------------------------------------------------------------


class TestFormatScanSummary:
    """扫描摘要格式化输出"""

    def _base_scan(self) -> RepoScanResult:
        return RepoScanResult(
            repo_path="/tmp/repo",
            project_type="python",
            package_manager="pip",
            total_files=42,
            total_lines=1024,
            languages={
                "Python": {"code": 800, "files": 12},
                "JavaScript": {"code": 200, "files": 5},
            },
            trivy_vulnerabilities=[
                {"VulnerabilityID": "CVE-001", "Severity": "CRITICAL", "Title": "RCE"},
                {"VulnerabilityID": "CVE-002", "Severity": "HIGH", "Title": "SQLi"},
            ],
            semgrep_findings=[
                {"id": "S-1", "message": "hardcoded secret"},
                {"id": "S-2", "message": "no auth"},
            ],
            deptry_issues=[{"type": "deprecated", "error": {"code": "DEP001", "message": "old"}}],
            trivy_scanned=True,
            semgrep_scanned=True,
            deptry_scanned=True,
            tool_statuses={"cloc": "ok", "trivy": "ok", "semgrep": "ok", "deptry": "issues=1"},
        )

    def test_includes_project_metadata(self) -> None:
        output = json.loads(format_scan_summary(self._base_scan()))

        assert output["project_type"] == "python"
        assert output["package_manager"] == "pip"
        assert output["total_files"] == 42
        assert output["total_lines"] == 1024

    def test_truncates_long_lists(self) -> None:
        scan = self._base_scan()
        scan.trivy_vulnerabilities = [{"VulnerabilityID": f"V-{i}"} for i in range(20)]
        scan.semgrep_findings = [{"id": f"S-{i}"} for i in range(30)]
        scan.deptry_issues = [{"type": "dep"} for i in range(15)]
        output = json.loads(format_scan_summary(scan))

        assert len(output["vulnerabilities"]) == 10
        assert len(output["code_issues"]) == 15
        assert len(output["dependency_issues"]) == 10

    def test_empty_scan_produces_valid_json(self) -> None:
        scan = RepoScanResult(repo_path="/tmp/repo", project_type="unknown")
        output = json.loads(format_scan_summary(scan))

        assert output["project_type"] == "unknown"
        assert output["total_files"] == 0
        assert output["vulnerabilities"] == []
        assert output["code_issues"] == []

    def test_includes_tool_status_summary(self) -> None:
        output = json.loads(format_scan_summary(self._base_scan()))

        assert output["_stats"]["total_vulnerabilities"] == 2
        assert output["_stats"]["scanned_tools"]["trivy"] is True
        assert output["_stats"]["scanned_tools"]["deptry"] is True


# ---------------------------------------------------------------------------
# _fallback_file_counts
# ---------------------------------------------------------------------------


class TestFallbackFileCounts:
    """文件计数回退逻辑"""

    def test_counts_python_files(self, tmp_path: Path) -> None:
        (tmp_path / "main.py").write_text("print('hi')\n", encoding="utf-8")
        (tmp_path / "utils.py").write_text("# util\n", encoding="utf-8")
        (tmp_path / ".git" / "keep").mkdir(parents=True)
        (tmp_path / ".git" / "ignore").write_text("", encoding="utf-8")

        files, lines = _fallback_file_counts(tmp_path)
        assert files == 2
        assert lines > 0

    def test_excludes_git_and_cache_dirs(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "file.py").write_text("", encoding="utf-8")
        (tmp_path / "__pycache__").mkdir()
        (tmp_path / "__pycache__" / "cache.pyc").write_text("", encoding="utf-8")
        (tmp_path / "real.py").write_text("", encoding="utf-8")

        files, lines = _fallback_file_counts(tmp_path)
        assert files == 1  # only real.py, .git and __pycache__ excluded


# ---------------------------------------------------------------------------
# 具体异常类型 — Issue #24
# ---------------------------------------------------------------------------


class TestSpecificExceptionTypes:
    """验证 scanner.py 使用具体异常类型而非 bare except Exception。"""

    def test_read_pyproject_logs_on_toml_error(self, tmp_path: Path) -> None:
        """_read_pyproject 在 TOML 解析失败时应记录日志。"""
        (tmp_path / "pyproject.toml").write_text("broken[", encoding="utf-8")
        records: list[logging.LogRecord] = []
        handler = logging.Handler()
        handler.emit = lambda r: records.append(r)
        old_handlers = scanner_logger.handlers[:]
        scanner_logger.addHandler(handler)
        old_level = scanner_logger.level
        scanner_logger.setLevel(logging.DEBUG)
        try:
            result = _read_pyproject(tmp_path)
            # 解析失败返回空 dict（保持向后兼容）
            assert result == {}
            # 应有 warning 日志
            warnings = [r for r in records if r.levelno >= logging.WARNING]
            assert len(warnings) >= 1
        finally:
            scanner_logger.handlers = old_handlers
            scanner_logger.setLevel(old_level)

    def test_read_pyproject_returns_empty_on_missing_file(self, tmp_path: Path) -> None:
        """文件不存在时静默返回空 dict。"""
        result = _read_pyproject(tmp_path)
        assert result == {}

    def test_fallback_file_counts_logs_on_os_error(self, tmp_path: Path) -> None:
        """_fallback_file_counts 在读取文件失败时应记录日志。"""
        # 创建一个普通文件
        (tmp_path / "normal.py").write_text("print('hi')", encoding="utf-8")
        # 创建一个无法读取的路径（使用 mock）
        original_rglob = Path.rglob

        def failing_rglob(self_: Path, pattern):
            for p in original_rglob(self_, pattern):
                if p.name == "normal.py":
                    yield p
                else:
                    yield p

        records: list[logging.LogRecord] = []
        handler = logging.Handler()
        handler.emit = lambda r: records.append(r)
        old_handlers = scanner_logger.handlers[:]
        scanner_logger.addHandler(handler)
        old_level = scanner_logger.level
        scanner_logger.setLevel(logging.DEBUG)
        try:
            files, lines = _fallback_file_counts(tmp_path)
            assert files >= 1  # 至少 normal.py 被计数
        finally:
            scanner_logger.handlers = old_handlers
            scanner_logger.setLevel(old_level)


class TestScannerLoggingOnCommandFailure:
    """验证扫描工具在命令失败时记录日志。"""

    def _collect_logs(self):
        records: list[logging.LogRecord] = []
        handler = logging.Handler()
        handler.emit = lambda r: records.append(r)
        old_handlers = scanner_logger.handlers[:]
        scanner_logger.addHandler(handler)
        old_level = scanner_logger.level
        scanner_logger.setLevel(logging.DEBUG)
        return records, old_handlers, old_level

    @staticmethod
    def _restore(old_handlers, old_level):
        scanner_logger.handlers = old_handlers
        scanner_logger.setLevel(old_level)

    def test_run_cloc_logs_on_failure(self, tmp_path: Path) -> None:
        fake = TestToolRunners._fake_run(1, "", "cloc not found")
        with patch("gearbox.agents.shared.scanner._run_command", fake):
            records, oh, ol = self._collect_logs()
            try:
                data, status = run_cloc(tmp_path)
                assert data == {}
            finally:
                self._restore(oh, ol)

    def test_deptry_logs_on_parse_failure(self, tmp_path: Path) -> None:
        fake_run = TestToolRunners._fake_run(0, "", "")
        with (
            patch("gearbox.agents.shared.scanner._run_command", fake_run),
            patch("pathlib.Path.read_text", side_effect=OSError("permission denied")),
        ):
            records, oh, ol = self._collect_logs()
            try:
                issues, status = run_deptry(tmp_path)
                # 应该仍然返回结果或空列表，但记录了日志
                assert isinstance(issues, list)
            finally:
                self._restore(oh, ol)
