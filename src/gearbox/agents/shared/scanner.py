"""静态分析扫描器 - 在 Agent 运行前执行全量扫描"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, cast

import tomli

logger = logging.getLogger(__name__)


@dataclass
class RepoScanResult:
    """仓库扫描结果"""

    repo_path: str

    # 语言统计 (cloc)
    languages: dict[str, dict[str, int]] = field(default_factory=dict)
    total_files: int = 0
    total_lines: int = 0

    # 安全漏洞 (trivy)
    trivy_vulnerabilities: list[dict[str, Any]] = field(default_factory=list)
    trivy_scanned: bool = False

    # 代码问题 (semgrep)
    semgrep_findings: list[dict[str, Any]] = field(default_factory=list)
    semgrep_scanned: bool = False

    # Python 依赖 (deptry)
    deptry_issues: list[dict[str, Any]] = field(default_factory=list)
    deptry_scanned: bool = False

    # Go 漏洞 (govulncheck)
    govulncheck_vulns: list[dict[str, Any]] = field(default_factory=list)
    govulncheck_scanned: bool = False

    # 仓库元信息
    project_type: str = ""  # python/typescript/go/mixed
    package_manager: str = ""  # pip/npm/go mod/maven
    has_docker: bool = False
    has_security_config: bool = False
    tool_statuses: dict[str, str] = field(default_factory=dict)


def _run_command(
    cmd: list[str],
    cwd: Path,
    timeout: int = 120,
) -> tuple[int, str, str]:
    """执行命令并返回 (returncode, stdout, stderr)"""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except Exception as e:
        return -1, "", str(e)


def _read_pyproject(repo_path: Path) -> dict[str, Any]:
    pyproject = repo_path / "pyproject.toml"
    if not pyproject.exists():
        return {}
    try:
        data = tomli.loads(pyproject.read_text(encoding="utf-8"))
        return cast(dict[str, Any], data)
    except (tomli.TOMLDecodeError, OSError, ValueError) as exc:
        logger.warning("_read_pyproject failed for %s: %s", repo_path, exc)
        return {}


def _project_name(repo_path: Path) -> str:
    data = _read_pyproject(repo_path)
    name = data.get("project", {}).get("name", "")
    if isinstance(name, str):
        return name.replace("-", "_")
    return ""


def _has_optional_dev_group(repo_path: Path) -> bool:
    data = _read_pyproject(repo_path)
    groups = data.get("project", {}).get("optional-dependencies", {})
    return isinstance(groups, dict) and "dev" in groups


def detect_project_type(repo_path: Path) -> tuple[str, str, bool, bool]:
    """检测项目类型和包管理器"""
    has_py = (repo_path / "pyproject.toml").exists() or (repo_path / "requirements.txt").exists()
    has_ts = (repo_path / "package.json").exists()
    has_go = (repo_path / "go.mod").exists()
    has_docker = (repo_path / "Dockerfile").exists() or (repo_path / "docker-compose.yml").exists()

    if has_py and has_ts:
        return "mixed", "multiple", has_docker, False
    elif has_py:
        return "python", "pip", has_docker, False
    elif has_ts:
        return "typescript", "npm", has_docker, False
    elif has_go:
        return "go", "go mod", has_docker, False
    return "unknown", "", has_docker, False


def _fallback_file_counts(repo_path: Path) -> tuple[int, int]:
    excluded_dirs = {
        ".git",
        "__pycache__",
        "node_modules",
        "vendor",
        "build",
        "dist",
        ".venv",
        ".mypy_cache",
        ".ruff_cache",
    }
    total_files = 0
    total_lines = 0

    for path in repo_path.rglob("*"):
        if not path.is_file():
            continue
        if any(part in excluded_dirs for part in path.parts):
            continue
        total_files += 1
        try:
            total_lines += len(path.read_text(encoding="utf-8", errors="ignore").splitlines())
        except (OSError, PermissionError) as exc:
            logger.debug("_fallback_file_counts: skipping %s: %s", path, exc)
            continue

    return total_files, total_lines


def run_cloc(repo_path: Path) -> tuple[dict[str, Any], str]:
    """执行 cloc 统计代码行数"""
    returncode, stdout, stderr = _run_command(
        [
            "cloc",
            "--json",
            "--exclude-dir=node_modules,.git,__pycache__,vendor,build,dist,.venv,.mypy_cache,.ruff_cache",
            ".",
        ],
        repo_path,
    )
    if returncode == 0:
        try:
            data = json.loads(stdout)
            assert isinstance(data, dict)
            return data, "ok"
        except (json.JSONDecodeError, AssertionError):
            return {}, "parse_failed"
    detail = stderr.strip() or "command_failed"
    return {}, detail


def run_semgrep(repo_path: Path) -> tuple[list[dict[str, Any]], str]:
    """执行 semgrep 扫描"""
    findings: list[dict[str, Any]] = []
    had_success = False
    last_error = "command_failed"
    for config in ["auto", "p/security"]:
        returncode, stdout, stderr = _run_command(
            ["semgrep", "scan", "--config=" + config, "--json", "--quiet"],
            repo_path,
            timeout=180,
        )
        if returncode == 0:
            had_success = True
            try:
                data = json.loads(stdout)
                findings.extend(data.get("results", []))  # type: ignore[arg-type]
            except json.JSONDecodeError:
                return findings, "parse_failed"
        else:
            last_error = stderr.strip() or f"command_failed:{config}"
    if had_success:
        return findings, "ok"
    return findings, last_error


def run_trivy(repo_path: Path) -> tuple[list[dict[str, Any]], str]:
    """执行 trivy 扫描"""
    returncode, stdout, stderr = _run_command(
        [
            "trivy",
            "fs",
            "--security-checks",
            "vuln",
            "--severity",
            "HIGH,CRITICAL",
            "--format",
            "json",
            ".",
        ],
        repo_path,
    )
    if returncode == 0:
        try:
            data = json.loads(stdout)
            results = data.get("Results", [])
            assert isinstance(results, list)
            return results, "ok"
        except (json.JSONDecodeError, AssertionError):
            return [], "parse_failed"
    detail = stderr.strip() or "command_failed"
    return [], detail


def run_deptry(repo_path: Path) -> tuple[list[dict[str, Any]], str]:
    """执行 deptry 扫描 Python 依赖"""
    import tempfile

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        tmp_path = f.name
    try:
        cmd = ["deptry", ".", "-o", tmp_path, "--no-ansi"]
        known_first_party = _project_name(repo_path)
        if known_first_party:
            cmd.extend(["--known-first-party", known_first_party])
        if _has_optional_dev_group(repo_path):
            cmd.extend(["--optional-dependencies-dev-groups", "dev"])

        returncode, stdout, stderr = _run_command(
            cmd,
            repo_path,
        )

        try:
            data = json.loads(Path(tmp_path).read_text(encoding="utf-8"))
            # 新版本输出是数组，旧版本是 {"issues": [...]}
            if isinstance(data, list):
                issues = data
            else:
                issues = data.get("issues", [])
                assert isinstance(issues, list)

            if issues:
                return issues, f"issues={len(issues)}"
            if returncode == 0:
                return issues, "ok"
        except (json.JSONDecodeError, AssertionError, OSError):
            if returncode == 0:
                return [], "parse_failed"

        detail = stderr.strip() or "command_failed"
        if stdout.strip():
            detail = stdout.strip()
        detail = detail.splitlines()[-1] if detail else "command_failed"
        return [], detail
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def run_govulncheck(repo_path: Path) -> tuple[list[dict[str, Any]], str]:
    """执行 govulncheck 扫描 Go 漏洞"""
    returncode, stdout, stderr = _run_command(
        ["govulncheck", "./...", "-json"],
        repo_path,
    )
    if returncode == 0:
        try:
            data = json.loads(stdout)
            vulns = data.get("vulnerabilities", [])
            assert isinstance(vulns, list)
            return vulns, "ok"
        except (json.JSONDecodeError, AssertionError):
            return [], "parse_failed"
    detail = stderr.strip() or "command_failed"
    return [], detail


def scan_repository(repo_path: Path) -> RepoScanResult:
    """对仓库执行全量静态分析扫描（并行执行 I/O 密集型工具）"""
    import concurrent.futures

    result = RepoScanResult(repo_path=str(repo_path))

    # 检测项目类型
    (
        result.project_type,
        result.package_manager,
        result.has_docker,
        result.has_security_config,
    ) = detect_project_type(repo_path)

    # 语言统计（快速，串行无影响）
    cloc_data, cloc_status = run_cloc(repo_path)
    result.tool_statuses["cloc"] = cloc_status
    if cloc_data.get("CJK", {}).get("nFiles", 0) > 0:
        # 跳过 CJK 统计(第三方库)
        langs = {k: v for k, v in cloc_data.items() if k not in ("CJK", "SUM", "header")}
    else:
        langs = {k: v for k, v in cloc_data.items() if k not in ("SUM", "header")}

    result.languages = langs
    if "SUM" in cloc_data:
        result.total_files = cloc_data["SUM"].get("nFiles", 0)
        result.total_lines = (
            cloc_data["SUM"].get("code", 0)
            + cloc_data["SUM"].get("blank", 0)
            + cloc_data["SUM"].get("comment", 0)
        )
    else:
        result.total_files, result.total_lines = _fallback_file_counts(repo_path)
        result.tool_statuses["cloc"] = f"{cloc_status}+fallback"

    # 收集需要并行执行的扫描任务
    scan_tasks: list[tuple[str, Callable[[], tuple[Any, str]]]] = []

    if result.project_type in ("python", "mixed"):
        scan_tasks.append(("deptry", lambda: run_deptry(repo_path)))
        scan_tasks.append(("trivy", lambda: run_trivy(repo_path)))
    else:
        result.tool_statuses["deptry"] = "skipped"

    if result.project_type in ("python", "typescript", "mixed"):
        scan_tasks.append(("semgrep", lambda: run_semgrep(repo_path)))
    else:
        result.tool_statuses["semgrep"] = "skipped"

    if result.project_type == "go":
        scan_tasks.append(("govulncheck", lambda: run_govulncheck(repo_path)))
        scan_tasks.append(("trivy", lambda: run_trivy(repo_path)))
    elif result.project_type == "typescript":
        scan_tasks.append(("trivy", lambda: run_trivy(repo_path)))
        result.tool_statuses["govulncheck"] = "skipped"
    else:
        result.tool_statuses["govulncheck"] = "skipped"
        if result.project_type not in ("python", "mixed"):
            result.tool_statuses["trivy"] = "skipped"

    # 并行执行 I/O 密集型任务
    if scan_tasks:
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            future_to_tool: dict[concurrent.futures.Future, str] = {
                executor.submit(task[1]): task[0] for task in scan_tasks
            }
            for future in concurrent.futures.as_completed(future_to_tool):
                tool_name = future_to_tool[future]
                try:
                    result_data, status = future.result()
                    result.tool_statuses[tool_name] = status
                    if tool_name == "deptry":
                        result.deptry_issues = result_data
                        result.deptry_scanned = True
                    elif tool_name == "trivy":
                        result.trivy_vulnerabilities = result_data
                        result.trivy_scanned = True
                    elif tool_name == "semgrep":
                        result.semgrep_findings = result_data
                        result.semgrep_scanned = True
                    elif tool_name == "govulncheck":
                        result.govulncheck_vulns = result_data
                        result.govulncheck_scanned = True
                except Exception as exc:
                    result.tool_statuses[tool_name] = f"exception:{exc}"

    return result


def format_scan_summary(scan: RepoScanResult) -> str:
    """将扫描结果格式化为 JSON（供 Agent 直接解析）"""
    import json

    payload: dict[str, Any] = {
        "project_type": scan.project_type,
        "package_manager": scan.package_manager,
        "total_files": scan.total_files,
        "total_lines": scan.total_lines,
        "has_docker": scan.has_docker,
        "languages": {
            lang: {"code": stats.get("code", 0), "files": stats.get("nFiles", 0)}
            for lang, stats in sorted(
                scan.languages.items(),
                key=lambda x: x[1].get("code", 0),
                reverse=True,
            )[:10]
        },
        "vulnerabilities": [
            {
                "id": v.get("VulnerabilityID", ""),
                "severity": v.get("Severity", ""),
                "title": v.get("Title", v.get("Description", ""))[:80],
            }
            for v in scan.trivy_vulnerabilities[:10]
        ],
        "govulncheck_vulns": [
            {
                "id": v.get("id", ""),
                "description": v.get("details", {}).get("description", "")[:80],
            }
            for v in scan.govulncheck_vulns[:10]
        ],
        "code_issues": [
            {
                "severity": f.get("severity", "").upper(),
                "rule": f.get("check_id", ""),
                "message": f.get("message", "")[:100],
            }
            for f in scan.semgrep_findings[:15]
        ],
        "dependency_issues": [
            {
                "type": i.get("type", i.get("error", {}).get("code", "")),
                "message": i.get("message", i.get("error", {}).get("message", ""))[:100],
            }
            for i in scan.deptry_issues[:10]
        ],
        "_stats": {
            "total_vulnerabilities": len(scan.trivy_vulnerabilities),
            "total_code_issues": len(scan.semgrep_findings),
            "total_dependency_issues": len(scan.deptry_issues),
            "scanned_tools": {
                "cloc": scan.tool_statuses.get("cloc", "unknown"),
                "trivy": scan.trivy_scanned,
                "semgrep": scan.semgrep_scanned,
                "deptry": scan.deptry_scanned,
                "govulncheck": scan.govulncheck_scanned,
            },
            "tool_statuses": scan.tool_statuses,
        },
    }

    return json.dumps(payload, ensure_ascii=False, indent=2)
