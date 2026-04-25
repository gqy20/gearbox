"""核心审计逻辑 - 使用 Claude Agent SDK"""

import asyncio
from pathlib import Path
from typing import Any

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ResultMessage, TextBlock, query

from gearbox.config import get_anthropic_model
from gearbox.config.mcp import ALLOWED_TOOLS, MCP_SERVERS

# System prompt - AI-native 审计专家
SYSTEM_PROMPT = """你是 Gearbox，一个专业的代码库审计专家。

## 目标

分析目标仓库，发现与业界标杆的差距，生成可执行的改进建议。

## 你的工具

**内置工具**（直接可用）:
- **Read/Glob/Grep**: 分析代码结构
- **Bash**: 执行命令（包括 `gh` CLI 工具）
- **Write**: 保存分析结果到文件

**MCP 工具**（可用于外部知识查询）:
- **mcp__web_search_prime__search_text**: 网络搜索，发现对标项目
- **mcp__context7__query_docs**: 查询库/框架官方文档

**GitHub 仓库操作**:
使用 `gh` 命令:
- `gh repo view owner/repo` - 查看仓库信息
- `gh search repos --language python --stars >1000 topic:cli` - 搜索仓库
- `gh api /repos/owner/repo/contents/pyproject.toml` - 获取项目配置

## 工作方式

1. 用 Read 分析本地仓库结构，或用 gh 查看远程仓库
2. 用 web_search_prime 搜索对标项目
3. 用 context7 查询相关库的官方文档
4. 自主分析并生成报告

## 输出格式

**必须生成以下文件**（使用 Write 工具保存到指定目录）:
- `profile.json` - 仓库 Profile（类型、语言、构建配置、质量工具等）
- `comparison.md` - 对比矩阵（Markdown 表格）
- `issues.json` - 改进建议列表（**重要！必须创建**）

**issues.json 格式**:
```json
{
  "issues": [
    {
      "repo": "owner/repo",
      "title": "简短明确的标题",
      "body": "## 问题\n一句话描述\n\n## 解决方案\n1. 要点一\n2. 要点二\n3. 要点三",
      "labels": "high,enhancement"
    }
  ]
}
```

## 质量要求

- 最多 3 个 Issues
- 每个 Issue ≤1000 字符，≤3 个要点
- 标签包含优先级（critical/high/medium/low）
- 精选最重要的改进项
- 不要尝试创建 GitHub Issue，只生成 JSON 文件
- 尽量引用实际仓库证据和对标项目参考"""


async def run_audit(
    repo: str,
    benchmarks: list[str] | None = None,
    output_dir: str = "./output",
) -> dict[str, Any]:
    """
    执行完整的仓库审计流程。

    Args:
        repo: 目标仓库 (owner/repo 或本地路径)
        benchmarks: 指定的对标仓库列表
        output_dir: 输出目录

    Returns:
        审计结果字典
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    options = ClaudeAgentOptions(
        model=get_anthropic_model(),
        mcp_servers=MCP_SERVERS,
        allowed_tools=ALLOWED_TOOLS,
        system_prompt=SYSTEM_PROMPT,
    )

    if benchmarks:
        benchmark_str = ", ".join(benchmarks)
        prompt = f"""请审计仓库: {repo}

对标项目: {benchmark_str}

输出目录: {output_dir}

请生成 profile.json、comparison.md 和 issues.json。"""
    else:
        prompt = f"""请审计仓库: {repo}

请自主发现对标项目（约 5 个），然后进行对比分析。

输出目录: {output_dir}

请生成 profile.json、comparison.md 和 issues.json。"""

    results: dict[str, Any] = {
        "repo": repo,
        "benchmarks": benchmarks,
        "output_dir": output_dir,
        "messages": [],
    }

    async for message in query(prompt=prompt, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    print(block.text)
                    results["messages"].append({"type": "assistant", "text": block.text})
        elif isinstance(message, ResultMessage):
            if message.total_cost_usd:
                print(f"\n💰 成本: ${message.total_cost_usd:.4f}")
                results["cost"] = message.total_cost_usd

    return results


def run_audit_sync(
    repo: str, benchmarks: list[str] | None = None, output_dir: str = "./output"
) -> dict[str, Any]:
    """同步包装器 - 用于 CLI 调用"""
    return asyncio.run(run_audit(repo, benchmarks, output_dir))
