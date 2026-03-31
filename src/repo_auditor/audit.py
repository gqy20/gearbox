"""核心审计逻辑 - 使用 Claude Agent SDK"""

import asyncio
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    create_sdk_mcp_server,
    query,
)

from repo_auditor.config import get_anthropic_model
from repo_auditor.config.mcp import ALLOWED_TOOLS, MCP_SERVERS
from repo_auditor.tools.benchmark import discover_benchmarks
from repo_auditor.tools.compare import create_comparison
from repo_auditor.tools.issue import generate_issue_content
from repo_auditor.tools.profile import generate_profile

# 创建自定义 MCP 服务器
AUDITOR_SERVER = create_sdk_mcp_server(
    name="repo-auditor",
    version="1.0.0",
    tools=[
        generate_profile,
        discover_benchmarks,
        create_comparison,
        generate_issue_content,
    ],
)


# System prompt - 让 Claude 自主决策分析流程
SYSTEM_PROMPT = """你是 Repo Auditor，一个专业的代码库审计专家。

## 目标

分析目标仓库，发现与业界标杆的差距，生成可执行的改进建议。

## 你的工具

**内置工具**（直接可用）:
- **Read/Glob/Grep**: 分析代码结构
- **Bash**: 执行命令（包括 `gh` CLI 工具）
- **Write**: 保存分析结果到文件

**自定义工具**:
- **generate_profile**: 生成仓库 Profile（项目类型、构建配置、质量工具等）
- **discover_benchmarks**: 发现对标项目（基于 Topics、语言搜索）
- **create_comparison**: 生成 15 个能力维度的对比矩阵
- **generate_issue_content**: 生成 Issue 内容模板（标题、问题、证据、解决方案、标签）

**GitHub 仓库操作**:
使用 `gh` 命令（GitHub CLI）而不是 MCP 工具：
- `gh repo view owner/repo` - 查看仓库信息
- `gh search repos --language python --stars >1000 topic:cli` - 搜索仓库
- `gh api /repos/owner/repo/topics` - 获取 topics
- `gh api /repos/owner/repo/languages` - 获取语言统计

## 分析流程（灵活调整）

请根据实际情况自主决定分析步骤：
1. 分析目标仓库（使用 Read/Glob 查看关键文件）
2. 发现或使用指定的对标项目（使用 `gh search` 或 discover_benchmarks）
3. 生成对比矩阵
4. 产出改进建议

## 输出格式

**必须生成以下文件**（保存到指定目录）:
- `profile.json` - 仓库 Profile
- `comparison.md` - 对比矩阵（Markdown 表格）
- `issues.json` - 改进建议列表（**重要！必须创建**）

**issues.json 格式限制**（严格遵守）:
- 最多 3 个 Issues（选择最重要的）
- 每个 Issue body 不超过 1000 字符
- 每个 Issue 最多 3 个要点（问题描述、解决方案、预期收益）
- 简洁明了，去除冗余内容

**issues.json 示例**:
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

**注意事项**:
- 使用 Write 工具创建 issues.json
- 精选最重要的改进项（≤3个）
- 每个 Issue ≤1000 字符，≤3 个要点
- 标签包含优先级（critical/high/medium/low）
- 不要尝试直接创建 GitHub Issue，只生成 JSON 文件

## 改进建议质量要求

每个 Issue 必须包含：
- ✓ **证据**: 对标项目的实际做法（附链接）
- ✓ **路线**: 具体的实施步骤
- ✓ **收益**: 预期改进效果
"""


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
    # 创建输出目录
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # 配置 Agent 选项
    options = ClaudeAgentOptions(
        model=get_anthropic_model(),
        mcp_servers=MCP_SERVERS,
        allowed_tools=[
            *ALLOWED_TOOLS,
            "mcp__auditor__*",
        ],
        system_prompt=SYSTEM_PROMPT,
    )

    # 构建提示词
    if benchmarks:
        benchmark_str = ", ".join(benchmarks)
        prompt = f"""请审计仓库: {repo}

对标项目: {benchmark_str}

输出目录: {output_dir}

请自主分析并生成报告文件。"""
    else:
        prompt = f"""请审计仓库: {repo}

请自主发现对标项目（约 5 个），然后进行对比分析。

提示：可以使用 `gh search repos` 命令搜索相似项目。

输出目录: {output_dir}"""

    # 执行查询
    results = {
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
