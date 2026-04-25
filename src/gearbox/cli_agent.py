"""Agent CLI 入口 — 供 GitHub Actions 调用"""

import asyncio
import json

import click

from gearbox.agents.ci_fix import run_ci_fix
from gearbox.agents.implement import run_implement
from gearbox.agents.review import run_review
from gearbox.agents.triage import run_triage
from gearbox.gh import write_outputs


def _result_to_github_output(result, output_file: str = "/tmp/github_output") -> None:
    """通用结果转 GitHub Output 文件"""
    data = {}
    for key, value in vars(result).items():
        if isinstance(value, list):
            data[key] = json.dumps(value)
        elif isinstance(value, bool):
            data[key] = str(value).lower()
        elif value is None:
            data[key] = ""
        else:
            data[key] = str(value)
    data["status"] = "success"
    write_outputs(data, output_file)


@click.group()
def agent() -> None:
    """Gearbox Agent CLI — 供 GitHub Actions 调用"""
    pass


@agent.command()
@click.option("--repo", required=True, help="仓库标识 (owner/name)")
@click.option("--issue", required=True, type=int, help="Issue 编号")
@click.option("--model", default="claude-sonnet-4-6", help="使用的模型")
@click.option("--max-turns", default=5, type=int, help="最大对话轮次")
@click.option("--output", default="/tmp/github_output", help="输出文件路径")
def triage(repo: str, issue: int, model: str, max_turns: int, output: str) -> None:
    """运行 Triage Agent"""
    result = asyncio.run(
        run_triage(
            repo,
            issue,
            model=model,
            max_turns=max_turns,
        )
    )
    _result_to_github_output(result, output)
    print(f"✅ Triage: labels={result.labels}, priority={result.priority}")


@agent.command()
@click.option("--repo", required=True, help="仓库标识 (owner/name)")
@click.option("--pr", required=True, type=int, help="PR 编号")
@click.option("--model", default="claude-sonnet-4-6", help="使用的模型")
@click.option("--max-turns", default=10, type=int, help="最大对话轮次")
@click.option("--output", default="/tmp/github_output", help="输出文件路径")
def review(repo: str, pr: int, model: str, max_turns: int, output: str) -> None:
    """运行 Review Agent"""
    result = asyncio.run(
        run_review(
            repo,
            pr,
            model=model,
            max_turns=max_turns,
        )
    )
    _result_to_github_output(result, output)
    print(f"✅ Review: verdict={result.verdict}, score={result.score}")


@agent.command()
@click.option("--repo", required=True, help="仓库标识 (owner/name)")
@click.option("--issue", required=True, type=int, help="Issue 编号")
@click.option("--model", default="claude-sonnet-4-6", help="使用的模型")
@click.option("--base-branch", default="main", help="PR 目标分支")
@click.option("--max-turns", default=20, type=int, help="最大对话轮次")
@click.option("--output", default="/tmp/github_output", help="输出文件路径")
def implement(repo: str, issue: int, model: str, base_branch: str, max_turns: int, output: str) -> None:
    """运行 Implement Agent"""
    result = asyncio.run(
        run_implement(
            repo,
            issue,
            model=model,
            base_branch=base_branch,
            max_turns=max_turns,
        )
    )
    _result_to_github_output(result, output)
    print(f"✅ Implement: branch={result.branch_name}, ready={result.ready_for_review}")


@agent.command()
@click.option("--repo", required=True, help="仓库标识 (owner/name)")
@click.option("--run-id", "run_id", required=True, type=int, help="Workflow Run ID")
@click.option("--model", default="claude-opus-4-7", help="使用的模型")
@click.option("--base-branch", default="main", help="PR 目标分支")
@click.option("--max-turns", default=15, type=int, help="最大对话轮次")
@click.option("--output", default="/tmp/github_output", help="输出文件路径")
def ci_fix(repo: str, run_id: int, model: str, base_branch: str, max_turns: int, output: str) -> None:
    """运行 CI Fix Agent"""
    result = asyncio.run(
        run_ci_fix(
            repo,
            run_id,
            model=model,
            base_branch=base_branch,
            max_turns=max_turns,
        )
    )
    _result_to_github_output(result, output)
    print(f"✅ CI Fix: branch={result.branch_name}, fixed={result.fixed}")


if __name__ == "__main__":
    agent()
