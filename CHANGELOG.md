# 变更日志

本文件记录 `gearbox` 开发仓中所有值得关注的版本变更。

版本号使用与发布流程一致的 `vX.Y.Z` tag。每次发布到
`gearbox-action` 时，会自动提取对应版本段落作为 Release Notes。

## [未发布]

### 新增

- 新增 `dispatch` action、CLI 与 workflow，用于从 `ready-to-implement`
  backlog 中按优先级和复杂度选择 Issue，并复用现有 Implement Agent 创建 PR。
- 新增 `src/gearbox/flow/` 确定性编排层，将候选筛选、排序和 dispatch 计划与
  LLM Agent 层分离。
- 新增 GitHub Issue 摘要查询原子能力，支持按标签拉取开放 Issue 和读取单个
  Issue 的标签、标题、URL、创建时间。

### 变更

- 将过长的 `src/gearbox/cli.py` 拆分为 `src/gearbox/commands/` 命令模块，
  保留 `gearbox.cli:cli` 作为稳定入口，降低 CLI 后续维护成本。

## [v1.1.4] - 2026-04-26

### 变更

- 将 Marketplace 根 action 展示名从 `Gearbox` 改为 `Gearbox AI Flywheel`，
  避免 GitHub Marketplace 全站唯一名称校验冲突。

### 修复

- 修复 audit 评论结果步骤中的 shell 引号转义问题，避免 comment event 成功审计后
  在 `uv run --directory` 阶段找不到路径。

## [v1.1.3] - 2026-04-26

### 新增

- 新增 `ci.yml` 与本地 pre-commit 基线，覆盖 actionlint、ruff、ruff format、
  mypy、pytest、YAML/JSON/TOML 基础检查。
- 新增 `audit` 预扫描能力：每次审计先克隆目标仓库，再运行 `cloc`、`deptry`、
  `semgrep`、`trivy`、`govulncheck` 等扫描工具，并把扫描摘要传入 Agent。
- 新增 scanner fallback 与工具状态日志；扫描工具不可用时仍会统计基础文件数、
  代码行数和项目类型，避免审计过程变成黑箱。
- 新增 Claude Agent SDK 工具调用可观测性，日志会输出 `Read`、`Glob`、`Bash`
  等工具名称和关键参数，并记录 token usage、cache 命中、耗时与成本信息。
- 新增统一的 `backlog` workflow/action 入口，支持单个 Issue 和多个 Issue
  使用同一套参数、artifact 与聚合逻辑。
- Backlog 会自动创建缺失的 Gearbox 管理标签，例如 `P0`-`P3`、
  `complexity:S/M/L`、`ready-to-implement` 与 `needs-clarification`。
- 新增 CHANGELOG 驱动的 release notes 读取能力，发布流程可从指定版本段落生成
  GitHub Release 内容。

### 变更

- 将 `audit`、`backlog` 等内部入口统一为 GitHub Actions 原生 matrix 编排，
  在 workflow 层完成多实例并行、artifact 上传、聚合选优和副作用写回。
- 将 action 运行时拆分为 `_runtime` 与 `_setup`：通用依赖安装由 `_runtime`
  负责，审计扫描工具由 `_setup` 扩展安装，所有 Python 依赖通过 `uv` 管理。
- 审计执行改为“始终克隆目标仓库”，scanner 与 Agent 使用同一份克隆目录，
  并在提示词中明确写入本地分析路径。
- 结构化输出统一通过 Claude Agent SDK 的结构化结果提取；没有结构化输出时直接
  报错，不再保留非结构化 fallback。
- Evaluator 在获取结构化结果后立即停止读取，减少重复轮次和无意义 token 消耗。
- 删除旧 `triage` action、workflow 与 CLI 兼容入口，外部和内部调用统一使用
  `backlog`。
- 将内部 Agent 文件与导出命名从 triage 收口为 backlog：
  `src/gearbox/agents/backlog.py`、`BacklogItemResult`、`run_backlog_item`。
- 将工作流评论触发词拆分为 `@audit`、`@backlog`、`@review`，避免一个
  `@gearbox` 同时触发多个 workflow。
- Backlog matrix artifact 命名统一为
  `backlog-results-issue-{issue_number}-run-{run_id}`，聚合目录统一为
  `backlog-runs`。
- 更新 README 与架构文档，说明当前 Marketplace 轻量入口、内部 matrix 编排、
  backlog 标签写回、触发词和项目结构。

### 修复

- 修复 workflow 调用本仓库 action 时的相对路径、复用 workflow action 引用路径、
  caller workflow 权限和 GitHub Token 透传问题。
- 修复聚合阶段 GitHub API 调用鉴权，确保选优后可以正常写回 Issue 标签和评论。
- 修复 artifact 下载后的扁平布局与按 artifact 目录布局兼容问题。
- 修复 Issue 标签读取的 `gh api --jq` 输出，确保 labels 作为单个 JSON 数组解析。
- 修复 `deptry` 输出解析和 audit scanner 模块跟踪问题。

## [v1.1.2] - 2026-04-26

### 变更

- 打磨 Marketplace 发布流程，让 tag 推送时能稳定同步
  `gearbox-action` 的 tags 和 Releases。
- 修正导出后的 `gearbox-action` README 示例，确保 `${{ ... }}` 片段渲染正确。
- 将发布 workflow 中的 artifact actions 升级到当前仓库使用的最新主版本。

## [v1.1.1] - 2026-04-26

### 修复

- 将 `astral-sh/setup-uv` 固定到真实存在的 `v8.1.0`，修复 Marketplace
  发布链路无法启动的问题。

## [v1.1.0] - 2026-04-26

### 新增

- 为 `audit`、`triage`、`review` 增加 reusable matrix workflows，
  让高级用户可以使用真正的 GitHub Actions 原生并行编排。

### 变更

- 拆分薄触发 workflow 和 reusable orchestrator，并重写主文档，明确轻量
  Action 用法与高级 workflow 用法的区别。
- 改进 Claude Agent SDK 的可观测性，补齐实时 flush、partial stream 和
  长任务 heartbeat 日志。
- 将 Agent 共享运行时代码收敛到 `src/gearbox/agents/shared`，删除旧的
  应用内伪并行执行路径。

## [v1.0.0] - 2026-04-26

### 新增

- 发布首个可用于 Marketplace 的 `gearbox-action` 版本，并提供统一的
  `action` 路由入口。
