# Repo Auditor

一个用于深度分析 GitHub 仓库并生成高质量改进建议的 AI Agent 工具。

基于 **Claude Agent SDK** 构建，通过自主规划执行分析任务，产出"有证据、有路线、有业界参照"的改进建议。

## 特性

- **Agent 驱动**: Claude 自主决策分析流程
- **对标发现**: 自动搜索相似项目
- **对比矩阵**: 15 个能力维度对比
- **高质量 Issue**: 带证据、路线、收益的改进建议

## 安装

```bash
uv sync
```

## 使用

### 基本用法

```bash
# 审计仓库（自动发现对标）
repo-auditor --repo owner/repo

# 指定对标项目
repo-auditor --repo owner/repo --benchmarks click/click,typer.typer

# 审计本地项目
repo-auditor --repo . --output ./audit-output
```

### Claude Agent 会自主完成

1. ✓ 分析仓库结构、配置、依赖
2. ✓ 发现相似的对标项目
3. ✓ 生成能力对比矩阵
4. ✓ 产出带证据的改进 Issue

### 输出文件

```
output/
├── profile.json      # 仓库 Profile
├── comparison.md     # 对比矩阵
└── issues.md         # 改进建议 Issue
```

## 开发

```bash
# 运行测试
uv run pytest -v

# 代码检查
uv run ruff check src/
uv run mypy src/
```

## 项目结构

```
src/repo_auditor/
├── cli.py           # CLI 入口（单一命令）
├── audit.py         # Agent 核心逻辑
├── config/mcp.py    # MCP 服务器配置
└── tools/           # 自定义 MCP 工具
    ├── profile.py   # Profile 生成
    ├── benchmark.py  # 对标发现
    ├── compare.py   # 对比矩阵
    └── issue.py     # Issue 生成
```
