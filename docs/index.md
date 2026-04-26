# Gearbox 架构文档

> 齿轮箱：AI 驱动的 GitHub 仓库自动化飞轮系统

## 整体架构

```text
Marketplace 轻量入口:
  gqy20/gearbox-action@v1
      |
      `-- action.yml
              |
              `-- actions/${{ inputs.action }}/action.yml

开发仓内部入口:
  .github/workflows/audit.yml
      |
      |-- plan
      |-- audit-run matrix
      |-- aggregate-audit
      `-- create-issues

  .github/workflows/backlog.yml
      |
      |-- plan
      |-- backlog-run matrix
      `-- aggregate-backlog

执行层:
  actions/*/action.yml
      |
      |-- actions/_runtime
      `-- actions/_setup
              |
              `-- uv run gearbox agent ...

Agent 共享层:
  src/gearbox/agents/shared/
      |
      |-- runtime.py      # Claude Agent SDK 调用、流式日志、token usage
      |-- structured.py   # 结构化输出提取与校验
      |-- scanner.py      # 克隆后静态扫描
      |-- artifacts.py    # 输出文件管理
      `-- selection.py    # 多实例结果选优
```

## 层级说明

| 层级 | 文件 | 职责 |
| --- | --- | --- |
| Marketplace 根入口 | `actions/main/action.yml` | 导出后成为 `gearbox-action` 的根 `action.yml`，按 `inputs.action` 路由 |
| 内部 audit 编排 | `.github/workflows/audit.yml` | GitHub Actions 原生 matrix，并可选发布审计 Issue |
| 内部 backlog 编排 | `.github/workflows/backlog.yml` | GitHub Actions 原生 matrix，按 Issue 聚合选优并写回标签/评论 |
| 高级编排模板 | `.github/workflows/reusable-*.yml` | 面向高级调用方保留的 reusable workflow 模板 |
| Action 执行层 | `actions/*/action.yml` | 单次执行 action，负责拼装环境变量并调用 CLI |
| 轻量运行时 | `actions/_runtime/action.yml` | 安装 uv、同步项目依赖、验证 Python 与 gh |
| 扫描工具 | `actions/_setup/action.yml` | 基于 `_runtime`，额外安装 audit 需要的静态扫描工具 |
| CLI | `src/gearbox/cli.py` | 命令行入口，解析参数 |
| Agent | `src/gearbox/agents/*.py` | audit、backlog、review、implement 等业务逻辑；backlog 实现在 `agents/backlog.py` |
| Flow 编排 | `src/gearbox/flow/*.py` | 不调用 LLM 的确定性流程，例如 dispatch 选择和排序 |
| Agent 共享层 | `src/gearbox/agents/shared/*.py` | SDK runtime、structured output、scanner、artifacts、selection |
| GitHub 操作 | `src/gearbox/core/gh.py` | Issue、PR、comment、label 等 GitHub API 封装 |

## Action 清单

| Action | 用途 | 主要参数 |
| --- | --- | --- |
| `audit` | 审计仓库，发现改进建议 | `repo`, `benchmarks` |
| `backlog` | 单个或多个 Issue 分类打标 | `repo`, `issues` |
| `dispatch` | 从 ready backlog 中选择 Issue 并触发实现 PR | `repo`, `max_items`, `dry_run` |
| `review` | PR Code Review | `repo`, `pr_number` |
| `implement` | 实现 Issue 并创建 PR | `repo`, `issue_number` |
| `publish` | 发布 `issues.json` 为 GitHub Issues | `input_path` |

## 调用方式

### Marketplace 轻量调用

适合大多数外部用户。调用方只需要一个 step，不需要维护 matrix、artifact、聚合脚本。

```yaml
- uses: gqy20/gearbox-action@v1
  with:
    action: audit
    repo: owner/repo
    benchmarks: github/copilot
    anthropic_api_key: ${{ secrets.ANTHROPIC_AUTH_TOKEN }}
    anthropic_base_url: ${{ secrets.ANTHROPIC_BASE_URL }}
    model: ${{ vars.ANTHROPIC_MODEL }}
```

### 开发仓内部 audit / backlog

本项目当前使用 `.github/workflows/audit.yml` 和 `.github/workflows/backlog.yml` 作为验证过的内部入口。它们不是再调用本地 reusable workflow，而是直接在 workflow 内完成 matrix 并行、artifact 上传、聚合与副作用写回。

```text
workflow_dispatch
  -> plan
  -> audit-run[run_id=0..N]
  -> actions/audit
  -> clone target repository
  -> scanner
  -> Claude Agent SDK
  -> upload artifact
  -> aggregate-audit
  -> optional create-issues

workflow_dispatch / @backlog
  -> plan
  -> backlog-run[issue_number x run_id]
  -> actions/backlog
  -> upload backlog-results-issue-{issue_number}-run-{run_id}
  -> aggregate-backlog
  -> select best result per issue
  -> apply labels/comments once per issue
```

Backlog 的单 Issue 和多 Issue 都走同一入口：`issues` 只有一个编号时就是单 Issue
分类，多个编号时就是批量分类。聚合阶段按 Issue 分组，每个 Issue 只会选出一个
胜出结果并写回一次 GitHub 副作用。

### Dispatch 执行流程

`dispatch` 是确定性编排层，不重新实现一个全能 Agent。它只负责从 backlog 标签中
选择下一个适合开发的 Issue，再复用已有 Implement Agent。

```text
workflow_dispatch / @dispatch
  -> fetch open issues with ready-to-implement
  -> exclude needs-clarification / in-progress / has-pr
  -> sort by priority, complexity, issue number
  -> dry-run plan by default
  -> --no-dry-run calls implement agent
  -> create PR
  -> label issue with in-progress / has-pr
```

默认排序规则是 `P0 > P1 > P2 > P3`，同优先级下 `S > M > L`。为了避免误创建
PR，`dispatch` 默认 `dry_run=true`；只有显式关闭 dry-run 才会进入实现阶段。

### 高级 reusable workflow

`reusable-*.yml` 仍保留为高级模板，适合外部仓库希望复用 Gearbox 的并行编排时使用。若只是单次审计，优先使用 Marketplace action。

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

## 审计执行流程

audit agent 的当前流程是：

1. 读取 action/CLI 输入与仓库配置。
2. 将目标仓库克隆到临时目录。
3. 在克隆目录运行静态扫描。
4. 将克隆路径、扫描摘要、benchmark 要求写入提示词。
5. 在克隆目录作为 `cwd` 调用 Claude Agent SDK。
6. 提取结构化输出；没有结构化结果时直接报错。
7. 写入 `issues.json`、`summary.md`、`result.json` 等 artifact。

这样做的好处是 scanner 和大模型看到的是同一份代码，不会出现“扫描了一个目录，Agent 又基于另一个上下文分析”的错位。

## 日志与可观测性

长耗时任务需要持续反馈，目前日志分为：

- `runtime config`：模型、base URL、最大轮次、工作目录、克隆策略。
- `clone`：目标仓库与本地克隆路径。
- `scanner`：文件数、代码行数、项目类型、工具状态、问题计数。
- `stream`：SDK 消息生命周期、thinking 摘要、assistant 文本、tool-use 事件。
- `usage`：SDK 返回的 token usage、cache 命中与 service tier。

工具调用日志会尽量展示关键参数，例如：

```text
[audit] [tool-use] tool=Read path=pyproject.toml offset=0 limit=2000
[audit] [tool-use] tool=Glob pattern=.github/workflows/*.yml path=.
[audit] [tool-use] tool=Bash command=rg "ClaudeAgentOptions" src
```

## 扫描工具

| 工具 | 用途 | 状态策略 |
| --- | --- | --- |
| `cloc` | 统计文件数与代码行数 | 失败时使用 Python fallback 统计 |
| `deptry` | Python 依赖问题扫描 | 不可用时记录 skipped/error |
| `semgrep` | 通用代码规则扫描 | 不可用时记录 skipped/error |
| `trivy` | 漏洞扫描 | 不可用时记录 skipped/error |
| `govulncheck` | Go 漏洞扫描 | 非 Go 项目默认 skipped |

所有工具状态都会进入扫描摘要和日志，避免“扫描完成但不知道扫描了什么”的黑箱感。

## Backlog 标签写回

Backlog 结构化结果会映射为 GitHub 标签：

| 结果字段 | 标签 |
| --- | --- |
| `labels` | `bug`、`enhancement`、`documentation` 等类型标签 |
| `priority` | `P0`、`P1`、`P2`、`P3` |
| `complexity` | `complexity:S`、`complexity:M`、`complexity:L` |
| `ready_to_implement` | `ready-to-implement` |
| `needs_clarification` | `needs-clarification` |

如果目标仓库缺少这些标签，Gearbox 会先创建再添加。日志中的“标签不存在，正在创建”表示首次初始化标签，不代表写回失败；只有“创建标签失败”或“添加标签失败”才需要排查权限或 GitHub API 返回。

## 配置与密钥

| 名称 | 类型 | 说明 |
| --- | --- | --- |
| `ANTHROPIC_AUTH_TOKEN` | Secret | LLM Provider API Key |
| `ANTHROPIC_BASE_URL` | Secret | 兼容 Anthropic API 的自定义网关 |
| `ANTHROPIC_MODEL` | Variable | 默认模型名 |
| `GH_PAT` | Secret | 跨仓库写入、创建 Issue、同步 Marketplace 仓库时使用 |
| `GITHUB_TOKEN` | GitHub 默认 | 当前 workflow 自动提供，适合同仓库读写 |

## CI 与提交检查

`.github/workflows/ci.yml` 在 push 和 pull request 时执行：

```bash
uv sync
uv run ruff check src tests
uv run mypy src
uv run pytest -q
```

`.pre-commit-config.yaml` 会在本地提交前执行 ruff、ruff format、mypy 和 YAML 基础检查：

```bash
uvx pre-commit install
uvx pre-commit run --all-files
```

## 发布

Marketplace 发布由 `.github/workflows/release-marketplace.yml` 负责：

1. 读取 tag，例如 `v1.1.2`。
2. 从 [../CHANGELOG.md](../CHANGELOG.md) 提取对应版本说明。
3. 运行 `uv run gearbox package-marketplace` 导出发布仓内容。
4. 推送到 `gqy20/gearbox-action`。
5. 使用版本说明创建 GitHub Release。

## 开发路线图

- [x] Phase 1: Action 架构与根路由层
- [x] Phase 2: audit / publish action
- [x] Phase 3: backlog / review / implement action
- [x] Phase 4: workflow-native matrix、artifact 聚合、选优
- [x] Phase 5: CHANGELOG 驱动的 Marketplace 发布说明
- [x] Phase 6: backlog 内部入口与 audit 编排体验对齐
- [x] Phase 7: dispatch dry-run 与 ready backlog 选择
- [ ] Phase 8: review / implement 内部入口与 audit 编排体验完全对齐

## 调研文档

| 文档 | 内容 |
| --- | --- |
| [架构设计](research/architecture.md) | 整体架构、目录结构、六大 Action 设计 |
| [Claude Code Actions 调研](research/claude-code-actions.md) | 自定义命令、Skills、Agents、Settings |
| [Composite Action 设计](research/composite-actions.md) | Action 类型对比、Monorepo 布局、嵌套编排 |
| [飞轮 Workflow 设计](research/flywheel-workflow.md) | 六大 Workflow 详细流程、消费者接入方式 |
| [安全与治理](research/security-governance.md) | 防无限循环、成本控制、最小权限 |
