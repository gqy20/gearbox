# GitHub Actions 集成

## 内部入口

本项目提供以下内部 workflow 入口，用于在开发仓内直接触发各流程：

```bash
# 触发仓库审计
gh workflow run audit.yml

# 分类指定 Issue
gh workflow run backlog.yml -f issues='123'

# 批量分类多个 Issue
gh workflow run backlog.yml -f issues='2,5,6'

# 审查指定 PR
gh workflow run review.yml -f pr_number=456

# 从 ready backlog 选择 Issue（默认 dry-run）
gh workflow run dispatch.yml
```

也可以在 Issue / PR 评论中使用专属 mention 触发：

| Mention | 触发动作 |
| --- | --- |
| `@audit` | 仓库审计 |
| `@backlog` | 当前 Issue 分类 |
| `@dispatch` | 从 ready backlog 触发实现计划（默认 dry-run） |
| `@review` | PR 审查 |

## Marketplace 轻量接入

外部用户通过 Marketplace action 调用，只需要一个 step：

```yaml
- uses: gqy20/gearbox-action@v1
  with:
    action: audit
    repo: owner/repo
    anthropic_api_key: ${{ secrets.ANTHROPIC_AUTH_TOKEN }}
    anthropic_base_url: ${{ secrets.ANTHROPIC_BASE_URL }}
    model: ${{ vars.ANTHROPIC_MODEL }}
```

### 各 Action 用法

#### Audit

```yaml
- uses: gqy20/gearbox-action@v1
  with:
    action: audit
    repo: owner/repo
    benchmarks: github/copilot
    anthropic_api_key: ${{ secrets.ANTHROPIC_AUTH_TOKEN }}
```

#### Backlog

统一的 backlog 入口会根据 `issues` 数量自动选择行为：1 个 issue 时快速分类，多个 issue 时批量分类并逐个写回标签/评论。

```yaml
- uses: gqy20/gearbox-action@v1
  with:
    action: backlog
    repo: owner/repo
    issues: '2,5,6'
    anthropic_api_key: ${{ secrets.ANTHROPIC_AUTH_TOKEN }}
```

#### Dispatch

默认只输出计划，不创建 PR；确认选择逻辑可靠后，显式设置 `dry_run: 'false'` 才会调用 Implement Agent。

```yaml
- uses: gqy20/gearbox-action@v1
  with:
    action: dispatch
    repo: owner/repo
    max_items: '1'
    dry_run: 'true'
    anthropic_api_key: ${{ secrets.ANTHROPIC_AUTH_TOKEN }}
```

#### Review

```yaml
- uses: gqy20/gearbox-action@v1
  with:
    action: review
    repo: owner/repo
    pr_number: 456
    anthropic_api_key: ${{ secrets.ANTHROPIC_AUTH_TOKEN }}
```

## 高级 Matrix 编排

如果需要多实例并行、artifact 聚合、选优或批量创建 Issue，可以使用 reusable workflow 模板：

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

## 配置 Secrets / Variables

在 GitHub Repository **Settings → Secrets and variables → Actions** 中配置：

### Secrets

| Secret | 必须 | 说明 |
| --- | --- | --- |
| `ANTHROPIC_AUTH_TOKEN` | 是 | LLM Provider API Key |
| `ANTHROPIC_BASE_URL` | 否 | 自定义兼容网关地址 |
| `GH_PAT` | 否 | 跨仓库写入、创建 Issue 或发布 Marketplace 仓库时使用 |

### Variables

| Variable | 默认值 | 说明 |
| --- | --- | --- |
| `ANTHROPIC_MODEL` | `glm-5.1` | 默认模型名 |
