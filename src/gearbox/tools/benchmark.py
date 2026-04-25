"""对标发现工具 - 基于目标画像发现相似项目"""

import json
import subprocess
from typing import Any

from claude_agent_sdk import tool


BENCHMARK_CATALOG = [
    {
        "repo": "pallets/click",
        "language": "Python",
        "project_type": "cli",
        "stars": 17000,
        "signals": {"has_ci": True, "has_tests": True, "has_type_check": False},
        "description": "Composable command line interface toolkit",
    },
    {
        "repo": "fastapi/typer",
        "language": "Python",
        "project_type": "cli",
        "stars": 14000,
        "signals": {"has_ci": True, "has_tests": True, "has_type_check": True},
        "description": "Build great CLIs with Python type hints",
    },
    {
        "repo": "python-poetry/poetry",
        "language": "Python",
        "project_type": "cli",
        "stars": 33000,
        "signals": {"has_ci": True, "has_tests": True, "has_type_check": True},
        "description": "Python packaging and dependency management",
    },
    {
        "repo": "psf/requests",
        "language": "Python",
        "project_type": "library",
        "stars": 53000,
        "signals": {"has_ci": True, "has_tests": True, "has_type_check": False},
        "description": "A simple, yet elegant, HTTP library",
    },
    {
        "repo": "tiangolo/fastapi",
        "language": "Python",
        "project_type": "framework",
        "stars": 85000,
        "signals": {"has_ci": True, "has_tests": True, "has_type_check": True},
        "description": "Modern, fast web framework for building APIs",
    },
]


def _normalize_language(profile: dict[str, Any]) -> str:
    return str(profile.get("project", {}).get("language", "unknown")).lower()


def _normalize_project_type(profile: dict[str, Any]) -> str:
    return str(profile.get("project", {}).get("type", "unknown")).lower()


def _build_search_query(target_profile: dict[str, Any], min_stars: int) -> str:
    language = _normalize_language(target_profile)
    project_type = _normalize_project_type(target_profile)
    keywords = []
    if project_type in {"cli", "framework", "library"}:
        keywords.append(project_type)

    query_parts = [f"language:{language}", f"stars:>={min_stars}", "archived:false", "fork:false"]
    query_parts.extend(keywords)
    return " ".join(part for part in query_parts if part)


def _search_candidates_via_gh(
    target_profile: dict[str, Any], top: int, min_stars: int
) -> list[dict[str, Any]]:
    query = _build_search_query(target_profile, min_stars)
    command = [
        "gh",
        "search",
        "repos",
        query,
        "--limit",
        str(max(top * 3, 10)),
        "--json",
        "fullName,language,description,stargazersCount,isArchived,isFork,url",
    ]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    payload = json.loads(result.stdout or "[]")

    candidates = []
    for item in payload:
        if item.get("isArchived") or item.get("isFork"):
            continue
        candidates.append(
            {
                "repo": item["fullName"],
                "language": item.get("language") or "Unknown",
                "project_type": _infer_project_type(item.get("description", "")),
                "stars": item.get("stargazersCount", 0),
                "signals": {
                    "has_ci": True,
                    "has_tests": True,
                    "has_type_check": "type" in (item.get("description") or "").lower(),
                },
                "description": item.get("description") or "",
                "url": item.get("url") or "",
            }
        )

    return candidates


def _infer_project_type(description: str) -> str:
    normalized = description.lower()
    if "cli" in normalized or "command line" in normalized:
        return "cli"
    if "framework" in normalized:
        return "framework"
    if "library" in normalized:
        return "library"
    return "application"


def _score_candidate(
    target_profile: dict[str, Any], candidate: dict[str, Any]
) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []

    target_language = _normalize_language(target_profile)
    if candidate["language"].lower() == target_language:
        score += 40
        reasons.append("same language")

    target_project_type = _normalize_project_type(target_profile)
    if candidate["project_type"].lower() == target_project_type:
        score += 35
        reasons.append("same project type")

    if target_profile.get("quality", {}).get("test_framework") and candidate["signals"].get(
        "has_tests"
    ):
        score += 10
        reasons.append("testing culture")

    if target_profile.get("quality", {}).get("linters") and candidate["signals"].get("has_ci"):
        score += 5
        reasons.append("automation maturity")

    if candidate["stars"] >= 10000:
        score += 10
        reasons.append("high adoption")

    return score, reasons


def _rank_candidates(
    target_profile: dict[str, Any], candidates: list[dict[str, Any]], top: int
) -> list[dict[str, Any]]:
    ranked = []
    for candidate in candidates:
        score, reasons = _score_candidate(target_profile, candidate)
        if score == 0:
            continue

        ranked.append(
            {
                "repo": candidate["repo"],
                "language": candidate["language"],
                "project_type": candidate["project_type"],
                "stars": candidate["stars"],
                "score": score,
                "reasons": reasons,
                "url": candidate.get("url", ""),
            }
        )

    ranked.sort(key=lambda item: (-item["score"], -item["stars"], item["repo"]))
    return ranked[:top]


def _build_candidates(
    target_profile: dict[str, Any], top: int, min_stars: int
) -> list[dict[str, Any]]:
    try:
        candidates = _search_candidates_via_gh(target_profile, top=top, min_stars=min_stars)
    except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError):
        candidates = [item for item in BENCHMARK_CATALOG if item["stars"] >= min_stars]

    return _rank_candidates(target_profile, candidates, top=top)


@tool(
    "discover_benchmarks",
    "发现对标项目",
    {"target_profile": dict, "repo_name": str, "top": int, "min_stars": int},
)
async def discover_benchmarks(args: dict[str, Any]) -> dict[str, Any]:
    """基于目标仓库画像生成对标项目候选列表。"""
    top = args.get("top", 5)
    min_stars = args.get("min_stars", 100)
    target_profile = args.get("target_profile") or {
        "project": {
            "language": "python",
            "type": "library" if args.get("repo_name") else "unknown",
        },
        "quality": {},
    }

    benchmarks = _build_candidates(target_profile, top=top, min_stars=min_stars)

    return {
        "content": [
            {
                "type": "text",
                "text": f"发现 {len(benchmarks)} 个对标项目:\n\n"
                + "\n".join(
                    f"- {item['repo']} (score={item['score']}, ⭐ {item['stars']})"
                    for item in benchmarks
                ),
            }
        ],
        "structured_output": benchmarks,
    }
