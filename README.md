# Repo Auditor

一个用于分析 GitHub 仓库并生成改进建议草稿的 AI Agent 原型工具。

基于 **Claude Agent SDK** 构建，目前已具备 CLI、配置管理、Agent 调度和 GitHub Actions 骨架，但仓库画像、对标发现、能力对比等核心分析能力仍在完善中。

## 当前状态

- 已实现 CLI 入口与配置命令
- 已接入 Claude Agent SDK 审计主流程
- 已提供 GitHub Actions workflow 骨架
- 部分自定义工具仍为占位实现，当前结果更适合原型验证而非正式审计

## 安装

```bash
uv sync
```

## 使用

### CLI 命令

```bash
# 查看帮助
uv run repo-auditor --help

# 审计仓库
uv run repo-auditor audit --repo owner/repo

# 指定对标项目
uv run repo-auditor audit --repo owner/repo --benchmarks click/click,tiangolo/typer

# 审计本地项目
uv run repo-auditor audit --repo . --output ./audit-output

# 查看配置
uv run repo-auditor config list

# 发布 issues.json 到 GitHub
uv run repo-auditor publish-issues --input ./audit-output/issues.json
```

### 当前实际支持的命令

- `audit`
- `publish-issues`
- `config list`
- `config set`
- `config path`

### 配置要求

运行 `audit` 前需要配置 Anthropic 认证信息：

```bash
uv run repo-auditor config set anthropic-api-key YOUR_KEY
uv run repo-auditor config set anthropic-model glm-5.1
```

也可以使用环境变量：

- `ANTHROPIC_AUTH_TOKEN`
- `ANTHROPIC_API_KEY`
- `ANTHROPIC_BASE_URL`
- `ANTHROPIC_MODEL`
- `GITHUB_TOKEN`

## 输出说明

Agent 目标是将结果写入输出目录，例如：

```text
output/
  profile.json
  comparison.md
  issues.json
```

注意：这些产物目前主要依赖 Agent 在运行时生成，尚未由代码层做完整校验与兜底。

## 开发

```bash
uv run pytest -v
uv run ruff check src tests
uv run mypy src
```

## 项目结构

```text
src/repo_auditor/
  cli.py             # CLI 入口
  audit.py           # Agent 审计主流程
  config/            # 配置与 MCP 设置
  tools/             # 自定义工具
tests/
  test_cli.py        # CLI 测试
  test_tools.py      # 工具测试
```
