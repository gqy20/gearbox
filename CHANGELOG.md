# 变更日志

本文件记录 `gearbox` 开发仓中所有值得关注的版本变更。

版本号使用与发布流程一致的 `vX.Y.Z` tag。每次发布到
`gearbox-action` 时，会自动提取对应版本段落作为 Release Notes。

## [v1.1.6] - 2026-04-27

### 新增

- Audit Agent 在分析前通过 `gh issue list` 拉取仓库已有 open Issues，
  注入提示词并要求聚焦发现全新问题，避免重复已有工作。
- Backlog 分类提示词包含所有 open Issues 摘要，让 Agent 了解全局上下文，
  做相对优先级判断（P2 vs P3）。
- Backlog 鼓励 Agent 在分类前用 Read/Bash 工具分析源码，结合代码上下文
  判断问题本质和修复复杂度，并增加 max_turns 到 30。
- Backlog 支持"分类标签过期重新评估"：P0-P3 / complexity:S/M/L 标签
  超过 `--since-days`（默认 2 天）未更新时，Issue 重新成为 backlog 候选。
- Backlog workflow_dispatch 支持空 issues 输入触发自动 plan。
- `parse_issue_numbers` 增强：支持 `#` 前缀（`#12`、`#12, #13`），
  空白输入返回空列表，非法 token 抛出含具体 token 的 ValueError。
- 所有 Agent 新增 `failure_reason` 字段，失败时必须返回原因，不再静默失败；
  Implement Agent 新增 3 次同测试失败自动停止约束。
- Implement Agent 要求 TDD 工作流（先写测试再实现）和 ready_for_review
  前置条件（测试通过 + lint 通过）。
- Review Agent 要求测试覆盖率，缺失测试必须标记为 warning。
- Evaluator 每条评分结果须包含明确理由说明。
- 新增 `agents/shared/prompt_helpers.py`，提供 `format_issues_summary()`
  格式化 issue 列表为 Markdown prompt 上下文，audit 和 backlog 共用。
- README"快速开始"与"当前架构"之间新增"本地验证"小节，
  含 pytest / ruff check / mypy 三个基本检查命令。
- `--since-days` CLI 选项透传到 `build_backlog_plan`，支持配置重新分类阈值。
- `since_days` 作为 workflow_dispatch input 暴露给用户。

### 变更

- Audit Agent cwd 改为目标仓库克隆目录，不再错误指向 gearbox 自身源码。
- Backlog Agent cwd 改为目标仓库克隆目录，使源码分析工具（Read/Bash）
  分析的是正确仓库而非 gearbox 自身。
- `clone_repository()` 从 audit.py 提取到 `agents/shared/git.py`，
  audit、backlog 共用同一克隆逻辑。
- Audit 使用共享的 `IssueSummary` 数据模型和 `format_issues_summary()`
  格式化提示词上下文。
- Backlog 使用共享的 `format_issues_summary()` 格式化所有 open issues。
- Backlog cron 调度从每天改为每 2 小时，与 audit 每小时调度保持一致节奏。
- `comment_mode=never` 的语义明确：仅抑制评论，标签更新不受影响。

### 修复

- 修复 matrix 表达式优先级：YAML 中 `&&` 优先级高于 `||`，
  导致 parallel_runs='1' 时总是走到错误分支。
- 修复 backlog workflow_dispatch issues 为必填导致无法触发自动 plan 的问题。
- 修复 plan job 中 `Setup Gearbox runtime` step 仅在 schedule 触发时运行，
  导致 workflow_dispatch 触发时 `GEARBOX_ACTION_ROOT` 未定义。
- 修复 backlog cron 测试间隔与 2 小时 schedule 不匹配。
- 修复 audit 发布时每个 issue 缺少 repo 字段导致所有 issues 在发布时被跳过。
- 修复 `needs_clarification` / `clarification_question` 死代码：
  schema 中已移除但 `commands/shared.py` 中仍有读取逻辑，现已清理。
- 修复 cleanup workflow 不识别 `gearbox/issue-N` 分支模式，导致相关 issue
  的 `has-pr` 标签无法清除的问题。
- 修复 audit 生成的 issues 标签（如 security、high、critical）被
  `VALID_ISSUE_LABELS` 过滤导致无法创建的问题。

### 重构

- 将 `clone_repository()` 提取为共享模块，backlog 不再复用错误的项目根路径。
- 新增 `agents/shared/prompt_helpers.py` 作为共享 prompt 工具模块。
- Backlog Agent prompt 中内联的 SYSTEM_PROMPT 说明文字移入各 agent 文件。

## [v1.1.5] - 2026-04-27

### 新增

- 新增 `backlog dispatch flow`，支持从 `ready-to-implement` backlog 按优先级和
  复杂度选择 Issue，并自动创建 PR。
- 新增 P0 dispatch 专用调度 lane，支持高优先级 Issue 的独立调度策略。
- 新增定时 quiet backlog planning，在非活跃时段自动规划 backlog。
- 新增 `cleanup` action，用于清理候选分支。
- 新增 dispatch 失败自动恢复与自动合并能力。
- 新增 `workflow-entry` action，统一 GitHub event 解析（issue number、target repo、
  skip logic）。
- 新增 `matrix` action，标准化 matrix 生成，替代 6 个 workflow 文件中的内联脚本。
- 审计定时触发默认创建 Issue。

### 变更

- 将 `src/gearbox/cli.py` 拆分为 `src/gearbox/commands/` 命令模块。
- 将 `audit-select`、`review-select`、`implement-select` 的重复逻辑收敛到
  `commands/shared.py` 的 `_select_single()` 辅助函数。
- 移除废弃的兼容性路径。
- Dispatch 支持矩阵化并行处理多个 Issue。
- Implement agent 从 action 源码目录运行，artifact 写入 workspace。
- Review 命令通过 PR 评论路由。

### 修复

- 修复 dispatch PR 创建、推送、分支保护的 PAT 凭证问题。
- 修复 dispatch 失败时清理 progress 标签。
- 修复 issue/PR 未合并关闭时恢复 Issue 状态。
- 修复 implement 结果标记为 not ready 的边界条件。
- 修复 dispatch 聚合并行实现时的路径问题。
- 修复 artifact 下载的 single artifact 布局支持。
- 修复 `deptry` 输出解析。
- 修复 matrix action manifest 格式。
- 修复 review 失败时正确报错。
- 修复 `gh review` flags 使用。
- 修复 `has-pr` 标签标记逻辑。
- 修复 dispatch dry-run 状态保持。

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
