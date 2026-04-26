"""静态分析扫描器 - 在 Agent 运行前执行全量扫描"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


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


def run_cloc(repo_path: Path) -> dict[str, Any]:
    """执行 cloc 统计代码行数"""
    returncode, stdout, _ = _run_command(
        [
            "cloc",
            "--json",
            "--exclude-dir=node_modules,.git,__pycache__,vendor,build,dist,.venv,.mypy_cache,.ruff_cache",
        ],
        repo_path,
    )
    if returncode == 0:
        try:
            data = json.loads(stdout)
            assert isinstance(data, dict)
            return data
        except (json.JSONDecodeError, AssertionError):
            return {}
    return {}


def run_semgrep(repo_path: Path) -> list[dict[str, Any]]:
    """执行 semgrep 扫描"""
    findings: list[dict[str, Any]] = []
    for config in ["auto", "p/security"]:
        returncode, stdout, _ = _run_command(
            ["semgrep", "scan", "--config=" + config, "--json", "--quiet"],
            repo_path,
            timeout=180,
        )
        if returncode == 0:
            try:
                data = json.loads(stdout)
                findings.extend(data.get("results", []))  # type: ignore[arg-type]
            except json.JSONDecodeError:
                pass
    return findings


def run_trivy(repo_path: Path) -> list[dict[str, Any]]:
    """执行 trivy 扫描"""
    returncode, stdout, _ = _run_command(
        [
            "trivy",
            "fs",
            "--security-checks",
            "vuln",
            "--severity",
            "HIGH,CRITICAL",
            "--json",
            ".",
        ],
        repo_path,
    )
    if returncode == 0:
        try:
            data = json.loads(stdout)
            results = data.get("Results", [])
            assert isinstance(results, list)
            return results
        except (json.JSONDecodeError, AssertionError):
            return []
    return []


def run_deptry(repo_path: Path) -> list[dict[str, Any]]:
    """执行 deptry 扫描 Python 依赖"""
    returncode, stdout, _ = _run_command(
        ["deptry", ".", "--output-format", "json"],
        repo_path,
    )
    if returncode == 0:
        try:
            data = json.loads(stdout)
            issues = data.get("issues", [])
            assert isinstance(issues, list)
            return issues
        except (json.JSONDecodeError, AssertionError):
            return []
    return []


def run_govulncheck(repo_path: Path) -> list[dict[str, Any]]:
    """执行 govulncheck 扫描 Go 漏洞"""
    returncode, stdout, _ = _run_command(
        ["govulncheck", "./...", "-json"],
        repo_path,
    )
    if returncode == 0:
        try:
            data = json.loads(stdout)
            vulns = data.get("vulnerabilities", [])
            assert isinstance(vulns, list)
            return vulns
        except (json.JSONDecodeError, AssertionError):
            return []
    return []


def scan_repository(repo_path: Path) -> RepoScanResult:
    """对仓库执行全量静态分析扫描"""
    result = RepoScanResult(repo_path=str(repo_path))

    # 检测项目类型
    (
        result.project_type,
        result.package_manager,
        result.has_docker,
        result.has_security_config,
    ) = detect_project_type(repo_path)

    # 语言统计
    cloc_data = run_cloc(repo_path)
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

    # 根据项目类型选择性扫描
    if result.project_type in ("python", "mixed"):
        result.deptry_issues = run_deptry(repo_path)
        result.deptry_scanned = True

        result.trivy_vulnerabilities = run_trivy(repo_path)
        result.trivy_scanned = True

    if result.project_type in ("typescript", "mixed"):
        result.semgrep_findings = run_semgrep(repo_path)
        result.semgrep_scanned = True

    if result.project_type == "go":
        result.govulncheck_vulns = run_govulncheck(repo_path)
        result.govulncheck_scanned = True

        result.trivy_vulnerabilities = run_trivy(repo_path)
        result.trivy_scanned = True
    elif result.project_type == "typescript":
        result.trivy_vulnerabilities = run_trivy(repo_path)
        result.trivy_scanned = True

    return result


def format_scan_summary(scan: RepoScanResult) -> str:
    """将扫描结果格式化为 Agent 可读的摘要文本"""
    lines = ["## 仓库扫描结果摘要\n"]

    # 基本信息
    lines.append(f"- **项目类型**: {scan.project_type}")
    lines.append(f"- **包管理器**: {scan.package_manager}")
    lines.append(f"- **总文件数**: {scan.total_files}")
    lines.append(f"- **总代码行数**: {scan.total_lines}")
    lines.append(f"- **Docker**: {'是' if scan.has_docker else '否'}")
    lines.append("")

    # 语言分布
    if scan.languages:
        lines.append("### 语言分布")
        sorted_langs = sorted(
            scan.languages.items(),
            key=lambda x: x[1].get("code", 0),
            reverse=True,
        )
        for lang, stats in sorted_langs[:10]:
            code = stats.get("code", 0)
            files = stats.get("nFiles", 0)
            lines.append(f"- **{lang}**: {code} 行代码, {files} 文件")
        lines.append("")

    # 安全问题摘要
    if scan.trivy_scanned and scan.trivy_vulnerabilities:
        crit_high = [
            v
            for v in scan.trivy_vulnerabilities
            if v.get("Severity", "").upper() in ("CRITICAL", "HIGH")
        ]
        lines.append("### 安全漏洞 (trivy)")
        lines.append(f"- 发现 **{len(scan.trivy_vulnerabilities)}** 个漏洞")
        lines.append(f"- 其中 CRITICAL/HIGH: **{len(crit_high)}** 个")
        if crit_high[:3]:
            lines.append("  主要问题:")
            for v in crit_high[:3]:
                lines.append(
                    f"  - {v.get('VulnerabilityID', '?')}: {v.get('Title', v.get('Description', '?')[:60])}"
                )
        lines.append("")

    if scan.govulncheck_scanned and scan.govulncheck_vulns:
        lines.append("### Go 漏洞 (govulncheck)")
        lines.append(f"- 发现 **{len(scan.govulncheck_vulns)}** 个已知漏洞")
        for v in scan.govulncheck_vulns[:3]:
            lines.append(
                f"  - {v.get('id', '?')}: {v.get('details', {}).get('description', '?')[:60]}"
            )
        lines.append("")

    if scan.semgrep_scanned and scan.semgrep_findings:
        lines.append("### 代码问题 (semgrep)")
        lines.append(f"- 发现 **{len(scan.semgrep_findings)}** 个问题")
        # 按 severity 分类
        errors = [f for f in scan.semgrep_findings if f.get("severity", "").upper() == "ERROR"]
        if errors:
            lines.append(f"- 其中 ERROR 级别: **{len(errors)}** 个")
        if errors[:3]:
            lines.append("  主要问题:")
            for e in errors[:3]:
                lines.append(f"  - {e.get('check_id', '?')}: {e.get('message', '?')[:60]}")
        lines.append("")

    if scan.deptry_scanned and scan.deptry_issues:
        lines.append("### Python 依赖问题 (deptry)")
        lines.append(f"- 发现 **{len(scan.deptry_issues)}** 个依赖问题")
        for issue in scan.deptry_issues[:3]:
            lines.append(f"  - [{issue.get('type', '?')}] {issue.get('message', '?')[:60]}")
        lines.append("")

    return "\n".join(lines)
