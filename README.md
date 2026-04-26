# Gearbox

> AI 驱动的 GitHub 仓库自动化飞轮系统

Gearbox 是开发母仓，用于维护源码、测试、文档、内部 workflow，并导出面向 GitHub Marketplace 的 `gearbox-action` 发布仓。

```
Audit -> Issue -> Backlog -> Implement -> Review -> Merge -> Report
```

## 快速开始

```bash
uv sync

# CLI 本地调试
uv run gearbox --help
uv run gearbox agent audit-repo --repo owner/repo --output-dir ./audit-output
uv run gearbox publish-issues --input ./audit-output/issues.json

# 配置
uv run gearbox config set anthropic-api-key YOUR_KEY
uv run gearbox config list
```

## 当前架构

```text
轻量入口:
  gqy20/gearbox-action@v1
      |
      `-- 根 action.yml（由 actions/main 导出）
              |
              `-- actions/${{ inputs.action }}/action.yml

内部审计编排:
  .github/workflows/audit.yml
      |
      |-- plan
      |-- audit-run matrix（GitHub Actions 原生并行）
      |-- aggregate-audit
      `-- create-issues（可选）

内部 backlog 编排:
  .github/workflows/backlog.yml
      |
      |-- plan
      |-- backlog-run matrix（issue_number x run_id）
      `-- aggregate-backlog（按 issue 选优并写回标签/评论）

执行层:
  actions/*/action.yml
      |
      |-- actions/_runtime（CLI 运行时）
      `-- actions/_setup（audit 扫描工具）
              |
              `-- uv run gearbox agent ...
```

核心取舍：

- Marketplace 用户默认只需要调用 `gqy20/gearbox-action@v1`，不需要手写复杂脚本。
- 本仓库的 `audit.yml` 和 `backlog.yml` 使用 inline matrix 编排，这是当前验证过的内部入口。
- `reusable-*.yml` 仍保留为高级编排模板，但不再把本仓库主路径建立在本地 reusable 调用上。
- audit 执行前会先克隆目标仓库，scanner 与 Agent 都基于克隆目录运行，提示词中也会明确写入本地分析目录。

## GitHub Actions

### 本项目常用入口

```bash
# 审计当前项目
gh workflow run audit.yml

# 分类指定 Issue（单个 issue 是 backlog 的特例）
gh workflow run backlog.yml -f issues='123'

# 批量分类多个 Issue
gh workflow run backlog.yml -f issues='2,5,6'

# 审查指定 PR
gh workflow run review.yml -f pr_number=456

# 从 ready backlog 中选择最高优先级 Issue（默认 dry-run）
gh workflow run dispatch.yml
```

也可以在 Issue / PR 评论中用工作流专属 mention 触发，避免一次评论误触发多个流程：

- `@audit`：触发仓库审计。
- `@backlog`：触发当前 Issue 分类。
- `@dispatch`：从当前 Issue 或 ready backlog 触发实现计划（默认 dry-run）。
- `@review`：触发 PR 审查。

### 对外轻量接入

```yaml
- uses: gqy20/gearbox-action@v1
  with:
    action: audit
    repo: owner/repo
    anthropic_api_key: ${{ secrets.ANTHROPIC_AUTH_TOKEN }}
    anthropic_base_url: ${{ secrets.ANTHROPIC_BASE_URL }}
    model: ${{ vars.ANTHROPIC_MODEL }}
```

统一的 backlog 入口会根据 `issues` 数量自动选择行为：1 个 issue 时执行快速分类，多个 issue 时执行批量分类并逐个写回标签/评论。

Backlog 会写入类型标签、优先级标签、复杂度标签和状态标签。若仓库还没有
`P0`-`P3`、`complexity:S/M/L`、`ready-to-implement` 或
`needs-clarification`，运行时会先自动创建这些标签，再添加到对应 Issue。
日志中的“标签不存在，正在创建”是初始化提示；只有出现“创建标签失败”或
“添加标签失败”才表示写回失败。

```yaml
- uses: gqy20/gearbox-action@v1
  with:
    action: backlog
    repo: owner/repo
    issues: '2,5,6'
    anthropic_api_key: ${{ secrets.ANTHROPIC_AUTH_TOKEN }}
```

实现阶段使用 `dispatch`。它默认只输出计划，不创建 PR；确认选择逻辑可靠后，
显式设置 `dry_run: 'false'` 才会调用已有 Implement Agent。

```yaml
- uses: gqy20/gearbox-action@v1
  with:
    action: dispatch
    repo: owner/repo
    max_items: '1'
    dry_run: 'true'
    anthropic_api_key: ${{ secrets.ANTHROPIC_AUTH_TOKEN }}
```

### 高级 matrix 编排

如果调用方需要多实例并行、artifact 聚合、选优或批量创建 Issue，可以参考本仓库的 `.github/workflows/audit.yml`，或者使用保留的 reusable workflow 模板：

```yaml
jobs:
  audit:
    uses: gqy20/gearbox/.github/workflows/reusable-audit.yml@main
    with:
      repo: owner/repo
      benchmarks: github/copilot,sourcegraph/amp
      parallel_runs: '3'
      create_issues: false
    secrets: inherit
```

### 配置 Secrets / Variables

在 GitHub Repository `Settings -> Secrets and variables -> Actions` 中添加：

| Secret | 必须 | 说明 |
| --- | --- | --- |
| `ANTHROPIC_AUTH_TOKEN` | 是 | LLM Provider API Key |
| `ANTHROPIC_BASE_URL` | 否 | 自定义兼容网关地址 |
| `GH_PAT` | 否 | 需要跨仓库写入、创建 Issue 或发布 Marketplace 仓库时使用 |

| Variable | 默认值 | 说明 |
| --- | --- | --- |
| `ANTHROPIC_MODEL` | `glm-5.1` | 默认模型名 |

## 审计可观测性

audit action 现在会输出三个层级的日志：

- 运行配置：模型、base URL、最大轮次、工作目录、克隆策略。
- 静态扫描：克隆路径、文件数、代码行数、项目类型、各工具状态。
- Agent 流式事件：thinking 摘要、文本输出、工具调用名称和关键参数，例如 `Read path=...`、`Bash command=...`。

scanner 会优先使用 `cloc`、`deptry`、`semgrep`、`trivy`、`govulncheck` 等工具；如果部分工具不可用，会记录对应状态，并对基础文件数/行数做 fallback 统计。

## 发布

```bash
# 生成 gearbox-action 发布目录
uv run gearbox package-marketplace --output-dir ./dist/gearbox-action

# 预览某个版本的发布说明
uv run gearbox release-notes --version v1.1.2
```

发布约定：

- 开发仓使用 [CHANGELOG.md](CHANGELOG.md) 作为唯一版本说明来源。
- 每次打 `vX.Y.Z` tag 前，先补对应版本段落。
- `release-marketplace.yml` 会自动提取该版本条目，并写入 `gearbox-action` 的 GitHub Release notes。

## 项目结构

```text
gearbox/
├── actions/
│   ├── _runtime/                # 轻量运行时：uv、Python、gh、项目依赖
│   ├── _setup/                  # audit 扫描工具：semgrep、deptry、cloc、trivy 等
│   ├── main/                    # 内部路由层，导出时成为根 action.yml
│   ├── audit/                   # 审计 action
│   ├── backlog/                 # backlog 分类 action
│   ├── dispatch/                # 从 ready backlog 选择 Issue 并触发实现
│   ├── review/                  # 审查 action
│   ├── implement/               # 实现 action
│   └── publish/                 # 发布 action
├── .github/workflows/
│   ├── ci.yml                   # ruff / mypy / pytest
│   ├── audit.yml                # 当前验证过的内部 audit matrix 编排
│   ├── backlog.yml              # Issue/backlog 分类入口
│   ├── dispatch.yml             # ready backlog → implement PR 入口
│   ├── review.yml               # PR 审查入口
│   ├── reusable-*.yml           # 高级编排模板
│   └── release-marketplace.yml  # Marketplace 发布流程
└── src/gearbox/
    ├── cli.py                   # CLI 入口
    ├── core/                    # GitHub 操作封装
    ├── flow/                    # 确定性编排：dispatch 计划、排序、过滤
    └── agents/
        ├── *.py                 # 具体 Agent
        └── shared/              # runtime / structured / artifacts / scanner / selection
```

## 开发

```bash
uv sync

# 本地质量检查
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy src
uv run pytest -q

# 提交前检查
uvx pre-commit install
uvx pre-commit run --all-files
```

详见 [docs/index.md](docs/index.md) 了解完整架构设计与路线图。
