# Repo Auditor

一个用于深度分析GitHub仓库并生成高质量改进建议的**AI Agent工具**。通过对标分析，产出"有证据、有路线、有业界参照"的高质量Issue。

基于 **Claude Agent SDK** 构建，支持 CLI 和 GitHub Actions 两种使用方式。

## 核心特性

- **Agent驱动**：使用 Claude Agent SDK 实现智能分析，可自主规划和执行分析任务
- **仓库分析**：自动分析仓库结构、CI配置、依赖、测试覆盖等
- **对标发现**：基于依赖、Topics、代码形态发现相似项目
- **对比矩阵**：生成目标仓库与对标仓库的能力对比
- **Issue生成**：使用LLM生成带证据的高质量改进建议
- **CI集成**：支持 GitHub Actions 集成，可通过 `@claude` 触发

## 技术选型

### Claude Agent SDK

本项目基于 [Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk-python) 构建，利用其内置工具集实现代码库分析能力：

| 内置工具 | 功能 |
|----------|------|
| `Read` / `Write` / `Edit` | 文件读写操作 |
| `Glob` / `Grep` | 文件搜索与内容查找 |
| `Bash` | 执行Shell命令和Git操作 |
| `WebSearch` / `WebFetch` | 网络搜索与内容抓取 |

#### 自定义工具示例

```python
from claude_agent_sdk import tool, create_sdk_mcp_server, ClaudeAgentOptions, ClaudeSDKClient

@tool("analyze_ci", "分析CI配置文件", {"config_path": str})
async def analyze_ci(args) -> dict:
    """分析仓库的CI配置并返回改进建议"""
    return {
        "content": [{"type": "text", "text": "CI分析结果..."}]
    }

# 创建MCP服务器
server = create_sdk_mcp_server(
    name="repo-auditor-tools",
    version="1.0.0",
    tools=[analyze_ci]
)
```

#### Agent 定义

使用单个通用 Agent，让 Claude 自主决定使用什么工具和步骤：

```python
from claude_agent_sdk import query, ClaudeAgentOptions

options = ClaudeAgentOptions(
    system_prompt="""你是 Repo Auditor，一个专业的代码库审计专家。

## 分析流程
1. 分析目标仓库结构、配置、依赖
2. 发现相似的对标项目
3. 生成能力对比矩阵
4. 产出带证据的改进建议

## 输出要求
- Profile JSON：项目结构、构建配置、质量指标
- 对比矩阵：15个能力维度的对标分析
- Issue 草稿：有证据、有路线、有业界参照的改进建议
""",
    allowed_tools=["Read", "Write", "Glob", "Grep", "Bash"],
    mcp_servers=MCP_SERVERS,  # 包含自定义 MCP 工具
)

async for message in query(prompt="分析 owner/repo 仓库", options=options):
    print(message)
```

### Claude Code Action 集成

支持通过 GitHub Actions 在 PR/Issue 中使用：

```yaml
# .github/workflows/repo-audit.yml
name: Repo Audit
on:
  issue_comment:
    types: [created]
  pull_request_review_comment:
    types: [created]

jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: anthropics/claude-code-action@v1
        with:
          system-prompt: |
            你是Repo Auditor专家。
            当收到 @repo-auditor audit 命令时，使用工具分析代码库并生成改进建议。
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```

**触发方式**：在 Issue 或 PR 评论中输入 `@repo-auditor audit` 即可触发分析。

### MCP 服务器配置

本项目使用 MCP (Model Context Protocol) 服务器扩展能力，支持以下两种配置方式：

#### SDK 方式 (推荐)

使用 `ClaudeAgentOptions.mcp_servers` 在代码中配置：

```python
from claude_agent_sdk import query, ClaudeAgentOptions

# MCP 服务器配置
MCP_SERVERS = {
    "github": {
        "type": "stdio",
        "command": "uvx",
        "args": ["mcp-server-github"],
        "env": {"GITHUB_TOKEN": "${GITHUB_TOKEN}"}
    },
    "web-search-prime": {
        "type": "http",
        "url": "https://open.bigmodel.cn/api/mcp/web_search_prime/mcp",
        "headers": {"Authorization": "Bearer ${ANTHROPIC_AUTH_TOKEN}"}
    },
    "context7": {
        "type": "http",
        "url": "https://open.bigmodel.cn/api/mcp/context7/mcp",
        "headers": {"Authorization": "Bearer ${ANTHROPIC_AUTH_TOKEN}"}
    },
}

async def audit_repo():
    async for message in query(
        prompt="搜索 GitHub 仓库并分析",
        options=ClaudeAgentOptions(
            mcp_servers=MCP_SERVERS,
            allowed_tools=["mcp__github__*", "mcp__web_search_prime__*"],
        )
    ):
        print(message)
```

#### 与 .mcp.json 的区别

| 特性 | `.mcp.json` | SDK `mcp_servers` |
|------|-------------|-------------------|
| **读取方** | Claude Code CLI 自动读取 | SDK 需在代码中显式配置 |
| **适用场景** | Claude Code 交互式使用 | 程序化调用 (CLI/API) |
| **配置位置** | 项目根目录 JSON 文件 | Python 代码或独立配置文件 |

**说明**：`.mcp.json` 是 Claude Code 的配置文件格式，SDK 程序无法直接读取，需要维护一份独立的 Python 配置（见 `src/repo_auditor/config/mcp.py`）。

### 配置的 MCP 服务器

| 服务器 | 类型 | 用途 |
|--------|------|------|
| `github` | stdio | GitHub API 操作 (搜索仓库、获取信息) |
| `web-search-prime` | HTTP | 网络搜索 |
| `context7` | HTTP | 文档查询 (库文档、API文档) |
| `crawl-mcp` | stdio | 网页爬取 |

## 安装

```bash
# 使用 uv 安装（推荐）
uv pip install -e .

# 或使用传统方式
pip install -e .
```

## 使用方法

### 方式一：命令行

```bash
# 分析单个仓库并生成profile
repo-auditor profile --repo owner/repo

# 发现对标项目
repo-auditor discover owner/repo --top 5

# 完整分析流程
repo-auditor audit owner/repo --benchmarks "project1,project2,project3"

# 生成对比矩阵
repo-auditor compare owner/repo --benchmarks "project1,project2"
```

### 方式二：GitHub Actions

```bash
# 在 Issue 或 PR 中评论
@repo-auditor audit --repo owner/repo --benchmarks "project1,project2"
```

### 方式三：Python API

```python
import asyncio
from claude_agent_sdk import query, ClaudeAgentOptions

async def audit_repo():
    async for message in query(
        prompt="分析 owner/repo 仓库，生成Profile并发现5个对标项目，产出改进建议",
        options=ClaudeAgentOptions(
            allowed_tools=["Read", "Write", "Glob", "Grep", "Bash"],
            system_prompt="你是 Repo Auditor，执行完整的仓库审计流程..."
        )
    ):
        if hasattr(message, "result"):
            print(message.result)

asyncio.run(audit_repo())
```

## 命令详解

### `repo-auditor profile`

分析目标仓库，生成统一的Profile JSON。

```bash
repo-auditor profile --repo owner/repo [OPTIONS]
```

**选项**：

| 选项 | 说明 |
|------|------|
| `--repo` | 目标仓库 (格式: owner/repo) |
| `--output` | 输出目录 (默认: ./output) |
| `--depth` | Git克隆深度 (默认: 1) |

**输出示例** (`profile.json`):

```json
{
  "project": {
    "type": "library",
    "language": "python",
    "entry_points": ["src/package/__init__.py"],
    "modules": ["core", "cli", "api"]
  },
  "build": {
    "install_command": "pip install -e .",
    "test_command": "pytest",
    "ci_file": ".github/workflows/test.yml"
  },
  "quality": {
    "linters": ["ruff", "mypy"],
    "test_framework": "pytest",
    "coverage": 85.2
  },
  "extensibility": {
    "plugins": true,
    "hooks": false,
    "config_schema": null
  },
  "security": {
    "dependabot": true,
    "secrets_scan": false
  }
}
```

### `repo-auditor discover`

发现与目标仓库相似的对标项目。

```bash
repo-auditor discover owner/repo [OPTIONS]
```

**选项**：

| 选项 | 说明 |
|------|------|
| `--top` | 返回数量 (默认: 5) |
| `--min-stars` | 最低stars数 (默认: 100) |
| `--output` | 输出文件路径 |

**返回字段**：

| 字段 | 说明 |
|------|------|
| `similarity_score` | 相似度评分 (0-100) |
| `match_reasons` | 匹配原因列表 |
| `topics_overlap` | Topics重叠率 |

### `repo-auditor compare`

生成目标仓库与对标仓库的对比矩阵。

```bash
repo-auditor compare owner/repo --benchmarks "proj1,proj2" [OPTIONS]
```

**能力项矩阵** (15个维度):

| 能力项 | 说明 |
|--------|------|
| `has_ci` | 是否有CI/CD |
| `has_lint` | 是否有代码检查 |
| `has_type_check` | 是否有类型检查 |
| `has_coverage` | 是否有测试覆盖 |
| `has_dependabot` | 是否有依赖更新 |
| `has_plugin_system` | 是否有插件系统 |
| `has_config_schema` | 是否有配置Schema |
| `has_error_handling` | 是否有统一错误处理 |
| `has_logging` | 是否有日志系统 |
| `has_tests` | 是否有测试套件 |
| `has_docker` | 是否有Docker支持 |
| `has_documentation` | 是否有文档 |
| `has_changelog` | 是否有变更日志 |
| `has_contributing_guide` | 是否有贡献指南 |
| `has_code_of_conduct` | 是否有行为准则 |

### `repo-auditor audit`

完整分析流程：profile → discover → compare → generate issues。

```bash
repo-auditor audit owner/repo --benchmarks "proj1,proj2" [OPTIONS]
```

**选项**：

| 选项 | 说明 |
|------|------|
| `--repo` | 目标仓库 |
| `--benchmarks` | 逗号分隔的对标仓库列表 |
| `--output` | 输出目录 |
| `--generate-issues` | 是否生成Issue草稿 (默认: true) |

## 配置文件

### `pyproject.toml`

```toml
[tool.repo-auditor]
output_dir = "output"
cache_dir = ".cache/repo-auditor"
log_level = "INFO"

# 默认对标仓库列表
[tool.repo-auditor.benchmarks]
default = ["click-dev/click"]

# Agent配置
[tool.repo-auditor.agents]
profile_model = "sonnet"
audit_model = "sonnet"
```

### `.env`

```bash
# GitHub Token (可选，增加API限制)
GITHUB_TOKEN = "ghp_xxxxxxxxxxxx"

# Claude API Key (用于Agent驱动)
ANTHROPIC_API_KEY = "sk-ant-api03-xxxxxxxxxxxx"

# 代理设置 (可选)
HTTPS_PROXY = "http://127.0.0.1:7890"
```

## 项目结构

```
repo-auditor/
├── src/
│   └── repo_auditor/
│       ├── __main__.py              # CLI入口 (python -m repo_auditor)
│       ├── cli.py                   # Click命令定义
│       ├── audit.py                 # 核心审计逻辑 (Agent SDK)
│       ├── tools/                   # 自定义MCP工具
│       │   ├── __init__.py
│       │   ├── profile.py           # Profile生成工具
│       │   ├── benchmark.py         # 对标发现工具
│       │   ├── compare.py           # 对比矩阵工具
│       │   └── issue.py             # Issue生成工具
│       ├── config/
│       │   ├── __init__.py
│       │   └── mcp.py               # MCP服务器配置
│       └── utils/
│           ├── __init__.py
│           ├── git.py               # Git操作封装
│           └── github.py            # GitHub API封装
├── .github/
│   └── workflows/
│       └── repo-audit.yml           # GitHub Actions工作流
├── docs/
│   └── index.md                     # 本文档
├── tests/
├── pyproject.toml
└── README.md
```

## 架构设计

```
┌─────────────────────────────────────────────────────────┐
│                   Repo Auditor Agent                     │
├─────────────────────────────────────────────────────────┤
│  Core: Claude Agent SDK + 自定义 MCP 工具                 │
├─────────────────────────────────────────────────────────┤
│  MCP Tools:                                             │
│  ├── github - GitHub API (搜索仓库、获取信息)            │
│  ├── web-search-prime - 网络搜索                        │
│  ├── context7 - 文档查询                                │
│  ├── crawl-mcp - 网页爬取                               │
│  └── 自定义工具 - Profile分析、对比矩阵等                │
├─────────────────────────────────────────────────────────┤
│  单一 Agent: 自主规划执行流程                            │
│  └─ 系统提示词定义分析目标和输出格式                     │
├─────────────────────────────────────────────────────────┤
│  Output: Profile JSON / Comparison Matrix / Issue Draft │
├─────────────────────────────────────────────────────────┤
│  Integration:                                           │
│  ├── CLI - repo-auditor 命令 (Agent SDK)                │
│  └── GitHub Actions - claude-code-action + system-prompt│
└─────────────────────────────────────────────────────────┘
```

## 实现路线图

| 优先级 | 功能 | 依赖 | 说明 |
|--------|------|------|------|
| P0 | 核心模块 | Claude Agent SDK | audit.py 基础框架 |
| P0 | MCP 工具 | SDK | Profile/Compare/Issue 工具 |
| P1 | MCP 服务器 | GitHub API | 对标项目发现 |
| P2 | CLI 命令 | Click | repo-auditor 命令 |
| P3 | GitHub Actions | claude-code-action | @mention 触发 |

## 开发

### 环境准备

```bash
# 克隆仓库
git clone https://github.com/your-org/repo-auditor.git
cd repo-auditor

# 使用 uv 初始化环境（推荐）
uv sync

# 或使用传统方式
# python -m venv .venv
# source .venv/bin/activate
# pip install -e ".[dev]"
```

### 安装依赖

```toml
# pyproject.toml
[project]
requires-python = ">=3.10"
dependencies = [
    "claude-agent-sdk>=1.0.0",
    "click>=8.0.0",
    "pygithub>=2.0.0",
    "pydantic>=2.0.0",
    "jinja2>=3.0.0",
    "httpx>=0.27.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "ruff>=0.4.0",
    "mypy>=1.0.0",
    "pytest-asyncio>=0.23.0",
]
```

### 开发命令

```bash
# 运行测试
pytest

# 代码检查
ruff check src/
mypy src/

# 格式化代码
ruff format src/
```

### 添加自定义工具

```python
# src/repo_auditor/tools/example.py
from claude_agent_sdk import tool, create_sdk_mcp_server

@tool("example_tool", "工具描述", {"param": str})
async def example_tool(args) -> dict:
    """工具实现"""
    result = do_something(args["param"])
    return {
        "content": [{"type": "text", "text": result}],
        "structured_output": {"key": "value"}  # 可选结构化输出
    }

# 注册到MCP服务器
example_server = create_sdk_mcp_server(
    name="example",
    version="1.0.0",
    tools=[example_tool]
)
```

### 调试Agent

```python
# 调试脚本
from claude_agent_sdk import query, ClaudeAgentOptions

async def debug_agent():
    async for message in query(
        prompt="分析当前仓库的 pyproject.toml 文件",
        options=ClaudeAgentOptions(
            allowed_tools=["Read", "Grep"],
            permission_mode="acceptEdits",
            # 添加自定义工具
            mcp_servers={"repo-tools": example_server},
        )
    ):
        print(message)

asyncio.run(debug_agent())
```

## 双模式实现方案

### 方案架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    Repo Auditor 双模式架构                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  模式1: 本地 CLI (repo-auditor 命令)                             │
│  ├─ pip install -e . 安装                                       │
│  ├─ repo-auditor audit --repo owner/repo                       │
│  └─ 输出: Profile JSON + 对比矩阵 + Issue 草稿                   │
│                                                                 │
│  模式2: GitHub Actions (@repo-auditor mention)                   │
│  ├─ claude-code-action + system-prompt                          │
│  ├─ 复用相同的分析逻辑                                           │
│  └─ 输出: 直接发布到 Issue/PR                                    │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 模式 1: 本地 CLI

```bash
# 安装
pip install -e .

# 使用
repo-auditor audit --repo owner/repo --benchmarks "click/click,typer.typer"
```

核心代码在 `src/repo_auditor/cli.py` 和 `src/repo_auditor/audit.py`:

```python
# cli.py - Click 命令入口
import click
from .audit import run_audit

@click.command()
@click.option("--repo", required=True, help="目标仓库")
@click.option("--benchmarks", help="对标仓库列表")
@click.option("--output", default="./output", help="输出目录")
def audit(repo: str, benchmarks: str, output: str):
    """执行仓库审计"""
    benchmark_list = benchmarks.split(",") if benchmarks else None
    run_audit(repo, benchmark_list, output)


# audit.py - 使用 Claude Agent SDK
from claude_agent_sdk import query, ClaudeAgentOptions
from .config.mcp import MCP_SERVERS

def run_audit(repo: str, benchmarks: list[str] | None, output: str):
    options = ClaudeAgentOptions(
        mcp_servers=MCP_SERVERS,
        system_prompt="你是 Repo Auditor...",
    )
    # ... 执行分析
```

### 模式 2: GitHub Actions

```yaml
# .github/workflows/audit.yml
name: Repo Audit

on:
  issue_comment:
    types: [created]
  pull_request_review_comment:
    types: [created]

permissions:
  contents: read
  pull-requests: write
  issues: write

jobs:
  audit:
    if: contains(github.event.comment.body, '@repo-auditor')
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5

      - uses: anthropics/claude-code-action@v1
        with:
          anthropic_api_key: ${{ secrets.ANTHROPIC_API_KEY }}
          system-prompt: |
            你是 Repo Auditor，一个专业的代码库审计专家。

            ## 分析流程
            1. 分析仓库结构 (Read, Glob, Grep)
            2. 检查 CI/CD 配置
            3. 使用 GitHub MCP 搜索对标项目
            4. 生成对比矩阵
            5. 产出改进建议并创建 Issue

          settings: |
            {
              "mcpServers": {
                "github": {
                  "type": "stdio",
                  "command": "uvx",
                  "args": ["mcp-server-github"],
                  "env": {"GITHUB_TOKEN": "${{ github.token }}"}
                }
              }
            }
```

### 两种模式对比

| 特性 | 本地 CLI | GitHub Actions |
|------|----------|----------------|
| **使用场景** | 本地开发、调试 | Issue/PR 中触发 |
| **触发方式** | `repo-auditor audit` | `@repo-auditor` mention |
| **输出** | 本地文件 | 直接发布到 Issue/PR |
| **MCP 工具** | 代码中配置 | settings.json 配置 |
| **成本** | 按使用计费 | 按使用计费 |

## 贡献

欢迎提交Issue和PR！

## 许可证

MIT License
