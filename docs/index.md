# Gearbox 架构文档

> 齿轮箱 — AI 驱动的 GitHub 仓库自动化飞轮系统

## 整体架构

```
开发仓内部: uses: ./actions/main
    │
    ▼
actions/main/action.yml (路由层)
    │
    └── uses: ./actions/${{ inputs.action }}
              │
              ├── audit/action.yml       ← 仓库审计
              ├── triage/action.yml      ← Issue 分类
              ├── review/action.yml      ← PR 审查
              ├── implement/action.yml  ← Issue 实现
              └── publish/action.yml     ← 发布 Issues
                      │
                      └── uses: ./actions/_setup (环境准备)
                              │
                              └── python3 -m gearbox.cli agent $action
                                      │
                                      └── src/gearbox/core/gh.py (GitHub 操作)
```

## 层级说明

| 层级 | 文件 | 职责 |
|------|------|------|
| 内部入口 | `actions/main/action.yml` | 当前仓库内部调用入口，也是导出的 Marketplace 根 `action.yml` 来源 |
| 内部编排 | `.github/workflows/*.yml` | 本项目内部 workflow orchestration |
| Action | `actions/*/action.yml` | 具体业务逻辑，调用 CLI + gh.py |
| 环境准备 | `actions/_setup/action.yml` | 安装必要工具 (Python, gh, 工具链) |
| CLI | `src/gearbox/cli.py` | 命令行入口，解析参数 |
| Agent | `src/gearbox/agents/*.py` | 业务逻辑实现 |
| GitHub 操作 | `src/gearbox/core/gh.py` | GitHub API 封装 (issue, PR, comment 等) |

## Action 清单

| Action | 用途 | 主要参数 |
|--------|------|----------|
| `audit` | 审计仓库，发现改进建议 | `repo`, `benchmarks`, `parallel_count` |
| `triage` | Issue 分类打标 | `repo`, `issue_number` |
| `review` | PR Code Review | `repo`, `pr_number` |
| `implement` | 实现 Issue 并创建 PR | `repo`, `issue_number` |
| `publish` | 发布 issues.json 为 GitHub Issues | `input_path` |

## 内部调用 vs 外部调用

### 外部调用（其他仓库）

```yaml
# 导出 Marketplace bundle
- run: uv run gearbox package-marketplace --output-dir ./dist/gearbox-action
```

### Marketplace 发布仓调用（导出后）

```yaml
- uses: gqy20/gearbox-action@v1
  with:
    action: audit
    repo: owner/repo
    benchmarks: github/copilot
    anthropic_api_key: ${{ secrets.ANTHROPIC_AUTH_TOKEN }}
```

### 内部调用（本项目）

```yaml
# 本项目 .github/workflows/audit.yml
- uses: ./actions/main
  with:
    action: audit
    repo: ${{ steps.target.outputs.repo }}
    parallel_count: 3
```

## 并行执行

`parallel_count` 参数控制并行任务数：

```
workflow → actions/audit → cli.py → run_parallel() → 多个 Agent 实例
```

## GitHub 操作封装

`src/gearbox/core/gh.py` 集中管理所有 GitHub 操作：

- `create_issue()` — 创建 Issue
- `post_issue_comment()` — Issue 评论
- `post_review_comment()` — PR Review 评论
- `add_issue_labels()` — 添加标签
- `create_pr()` — 创建 PR

## 环境要求

| 工具 | 用途 |
|------|------|
| Python 3.10+ | 运行时 |
| gh CLI | GitHub 操作 |
| uv | 包管理 |

### 可选工具（audit 需要）

| 工具 | 用途 |
|------|------|
| node + npm | ctx7, semgrep, ts-prune |
| go | govulncheck |
| pip | deptry |

## 开发路线图

- [x] Phase 1: Action 架构 (main 路由层)
- [x] Phase 2: audit / publish action 实现
- [x] Phase 3: triage / review / implement action 实现
- [ ] Phase 4: Marketplace 发布仓同步与发版

## 调研文档

| 文档 | 内容 |
|------|------|
| [架构设计](research/architecture.md) | 整体架构、目录结构、六大 Action 设计 |
| [Claude Code Actions 调研](research/claude-code-actions.md) | 自定义命令、Skills、Agents、Settings |
| [Composite Action 设计](research/composite-actions.md) | Action 类型对比、Monorepo 布局、嵌套编排 |
| [飞轮 Workflow 设计](research/flywheel-workflow.md) | 六大 Workflow 详细流程、消费者接入方式 |
| [安全与治理](research/security-governance.md) | 防无限循环、成本控制、最小权限 |
