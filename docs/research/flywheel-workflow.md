# 飞轮 Workflow 设计

## 飞轮闭环模型

```
                    ┌─────────────────────┐
                    │   定时巡检 / 报告     │
                    │   发现新改进点        │
                    └──────────┬──────────┘
                               │ 创建 Issue
                               ▼
┌─────────────────────┐  ┌─────────────────────┐  ┌─────────────────────┐
│   Auto Triage       │→ │   Implement         │→ │   Code Review       │
│   分类/排序/标签     │  │   实现 → 提 PR       │  │   审查/评论          │
└─────────────────────┘  └─────────────────────┘  └──────────┬──────────┘
        ▲                                                    │
        │                                                    ▼
        │                                          ┌─────────────────────┐
        │                                          │   CI 检查            │
        │                                          └──────────┬──────────┘
        │                                                     │ 失败
        │                                                     ▼
        │                                          ┌─────────────────────┐
        └──────────────────────────────────────────│   CI Fix             │
           Merge 后触发新巡检                         │   自动修复            │
                                                   └─────────────────────┘
```

## 六大 Workflow 详细设计

### 1. Triage — Issue 自动分类

**触发条件：** Issue opened / edited

**流程：**
```
Issue Created
    ↓
Claude 分析 title + body + labels
    ↓
判断: 类型(bug/feature/docs/question/refactor)
       优先级(P0-P3)
       复杂度(S/M/L)
    ↓
执行: gh api 添加 labels
      gh api 设置优先级
      [可选] 评论追问缺失信息
      [可选] 标记 ready-to-implement
```

**配置示例：**
```yaml
triage:
  enabled: true
  label_schema:
    - { pattern: "bug", labels: ["bug", "priority-high"], color: "d73a4a" }
    - { pattern: "feature", labels: ["enhancement"], color: "a2eeef" }
    - { pattern: "docs", labels: ["documentation"], color: "0075ca" }
    - { pattern: "question", labels: ["question"], color: "d876e3" }
  ask_clarification: true
```

**推荐模型：** Sonnet 4.6（高频低成本）

---

### 2. Implement — Issue → PR

**触发条件：** Issue labeled `ready-to-implement`

**流程：**
```
Issue marked ready
    ↓
Claude 阅读 Issue + 分析代码库
    ↓
创建分支: feat/issue-{n} 或 gearbox/implement-{n}
    ↓
编写代码 + 写测试
    ↓
Commit + Push
    ↓
gh pr create (关联 Issue)
    ↓
Request Review
```

**安全约束：**
- 分支必须有特殊前缀（`gearbox-*` 或 `feat/issue-*`）
- 永远创建 PR，绝不直接 push 到 main
- 运行测试和 lint 后才提交

**配置示例：**
```yaml
implement:
  enabled: true
  trigger_label: ready-to-implement
  branch_prefix: "gearbox/implement-"
  model: claude-sonnet-4-6
  max_turns: 20
  auto_test: true
  pr_labels: [auto-generated, gearbox-implemented]
```

**推荐模型：** Sonnet（常规）/ Opus（复杂任务）

---

### 3. Review — PR Code Review

**触发条件：** PR opened / synchronize

**流程：**
```
PR Opened/Updated
    ↓
Claude 获取 PR diff + 变更文件列表
    ↓
逐文件审查:
  - 逻辑错误
  - 安全漏洞
  - 性能问题
  - 测试覆盖
  - 代码规范
    ↓
发布 inline comments + summary comment
    ↓
评分: LGTM / Request Changes
```

**并发控制：** `cancel-in-progress: true`（同一 PR 取消旧的 review）

**配置示例：**
```yaml
review:
  enabled: true
  trigger: [opened, synchronize]
  focus_areas: [security, performance, testing, style]
  skip_patterns: ["dist/", "*.lock", "*.min.*"]
  require_fix_suggestions: true
  max_findings: 50
```

**推荐模型：** Sonnet 4.6

---

### 4. CI Fix — CI 失败自动修复

**触发条件：** CI workflow failed

**流程：**
```
CI Workflow Failed
    ↓
获取失败日志 (GitHub API)
    ↓
解析错误信息 + 定位相关代码
    ↓
创建分支: gearbox/ci-fix-{run_id}
    ↓
尝试修复（安全模式：不改配置、不删文件）
    ↓
Commit + Push + 创建 Fix PR
    ↓
报告修复结果
```

**关键防护（防死循环）：**
```yaml
if: |
  !startsWith(github.event.workflow_run.head_branch, 'gearbox-*') &&
  !startsWith(github.event.workflow_run.head_branch, 'claude-*')
```

**配置示例：**
```yaml
ci_fix:
  enabled: true
  watch_workflows: ["CI", "test", "build"]
  model: claude-opus-4-7     # 排查需要强推理
  max_turns: 15
  safe_operations_only: true
  max_repair_attempts: 3
```

**推荐模型：** Opus 4.7（排查需要强推理能力）

---

### 5. Auto-Merge — 条件合并

**触发条件：** PR ready_for_review + checks passed

**注意：** 这是纯 GitHub Actions 逻辑，不需要 AI。

**合并条件（全部满足）：**
- PR 不是 draft
- 至少 1 个 approval
- 所有 checks 通过
- 没有 `wip` 或 `do-not-merge` 标签

**配置示例：**
```yaml
auto_merge:
  enabled: true
  require_approval: true
  require_checks_pass: true
  exclude_labels: [wip, do-not-merge, work-in-progress]
```

---

### 6. Report — 定时巡检

**触发条件：** Cron（每日/每周）

**流程：**
```
定时触发 (cron)
    ↓
分析仓库状态:
  - 最近一周 commits / PRs / Issues
  - TODO / HACK / FIXME 注释统计
  - 未关闭 Issue 趋势
  - 技术债务发现
    ↓
生成健康报告
    ↓
[可选] 发现新改进点 → 创建新 Issue
    ↓
发布为 Issue (标签: repo-status)
```

**配置示例：**
```yaml
report:
  enabled: true
  schedule: "0 9 * * *"       # 每天 9 点 UTC
  create_issue: true
  label: repo-status
  analyze_debt: true          # 分析技术债务
  suggest_improvements: true   # 建议新改进点
```

**推荐模型：** Sonnet 4.6

---

## 消费者接入方式

### 方式一：使用主编排器（最简）

消费者只需 **2 个文件**：

**`.github/flywheel.yml`**（声明式配置）：
```yaml
version: "1.0"

project:
  type: backend
  language: typescript
  main_branch: main

triage:
  enabled: true
  auto_label: true

implement:
  enabled: true
  trigger_label: ready-to-implement

review:
  enabled: true
  focus_areas: [security, testing]

ci_fix:
  enabled: true

auto_merge:
  enabled: true
  require_approval: true

report:
  enabled: true
  schedule: "0 9 * * *"
```

**`.github/workflows/flywheel.yml`**（极简路由）：
```yaml
name: AI Flywheel

on:
  issues:
    types: [opened, edited, labeled]
  pull_request:
    types: [opened, synchronize, ready_for_review]
  check_run:
    types: [completed]
  schedule:
    - cron: "0 9 * * *"
  workflow_run:
    workflows: ["CI"]
    types: [completed]

permissions:
  issues: write
  pull-requests: write
  contents: write

jobs:
  flywheel:
    uses: gqy20/gearbox@v1
    secrets: inherit
```

**总计 ~80 行 YAML，一次配置永久生效。**

### 方式二：单独引用各 Action（精细控制）

```yaml
jobs:
  triage:
    if: github.event_name == 'issues' && github.event.action == 'opened'
    uses: gqy20/gearbox/actions/triage@v1
    with:
      anthropic_api_key: ${{ secrets.ANTHROPIC_API_KEY }}

  implement:
    if: contains(github.event.issue.labels.*.name, 'ready-to-implement')
    uses: gqy20/gearbox/actions/implement@v1
    with:
      anthropic_api_key: ${{ secrets.ANTHROPIC_API_KEY }}

  review:
    if: github.event_name == 'pull_request'
    uses: gqy20/gearbox/actions/review@v1
    with:
      anthropic_api_key: ${{ secrets.ANTHROPIC_API_KEY }}
```

## 一键初始化 Action

`actions/setup/action.yml` 帮消费者自动生成全套文件：

```yaml
name: 'Gearbox - Setup'
description: '一键初始化飞轮系统：生成配置文件和 workflow 模板'

inputs:
  github_token:
    description: 'GitHub Token (repo write access)'
    required: true
  preset:
    description: '预设模板: frontend/backend/monorepo/minimal'
    required: false
    default: 'minimal'

runs:
  using: 'composite'
  steps:
    - name: 'Generate flywheel.yml'
      shell: bash
      run: |
        PRESET="${{ inputs.preset }}"
        case "$PRESET" in
          frontend) TEMPLATE="templates/frontend.yaml" ;;
          backend)  TEMPLATE="templates/backend.yaml" ;;
          monorepo) TEMPLATE="templates/monorepo.yaml" ;;
          *)        TEMPLATE="templates/minimal.yaml" ;;
        esac
        cp "$TEMPLATE" .github/flywheel.yml

    - name: 'Generate workflow'
      shell: bash
      run: |
        mkdir -p .github/workflows
        cat > .github/workflows/flywheel.yml << 'EOF'
        name: AI Flywheel
        on:
          issues: [opened, edited, labeled]
          pull_request: [opened, synchronize, ready_for_review]
          schedule: [{ cron: "0 9 * * *" }]
        permissions:
          issues: write
          pull-requests: write
          contents: write
        jobs:
          flywheel:
            uses: gqy20/gearbox@v1
            secrets: inherit
        EOF

    - name: Commit scaffold
      shell: bash
      run: |
        git config --global user.email "gearbox[bot]@users.noreply.github.com"
        git config --global user.name "gearbox[bot]"
        git add .github/flywheel.yml .github/workflows/flywheel.yml
        git commit -m "chore: initialize gearbox flywheel" || true
        git push
```

## 预设模板系统

### minimal.yaml（最安全，仅 Triage + Report）
```yaml
version: "1.0"
triage: { enabled: true, auto_label: true }
implement: { enabled: false }
review: { enabled: false }
ci_fix: { enabled: false }
auto_merge: { enabled: false }
report: { enabled: true, schedule: "0 9 * * 1" }  # 每周一
guardrails:
  cost_limit_usd: 2.00
```

### backend.yaml（后端项目推荐）
```yaml
version: "1.0"
agent: { model: "claude-sonnet-4-6", max_turns: 15 }
triage: { enabled: true, auto_label: true }
implement: { enabled: false }
review:
  enabled: true
  focus_areas: [security, performance, testing]
  custom_rules:
    - "Validate all input schemas"
    - "Check SQL injection vectors"
    - "Proper error responses (no stack traces)"
ci_fix: { enabled: true, safe_operations_only: true }
auto_merge: { enabled: true, require_approval: true }
report: { enabled: true, schedule: "0 9 * * *" }
guardrails:
  cost_limit_usd: 5.00
  forbidden_paths: [".env*", "secrets/", "*.key"]
```

### frontend.yaml（前端项目推荐）
```yaml
version: "1.0"
agent: { model: "claude-sonnet-4-6", max_turns: 15 }
triage: { enabled: true, auto_label: true }
implement: { enabled: false }
review:
  enabled: true
  focus_areas: [accessibility, performance, style]
  custom_rules:
    - "Components must be properly typed"
    - "No console.log in production code"
    - "Follow existing component patterns"
ci_fix: { enabled: true, safe_operations_only: true }
auto_merge: { enabled: false }
report: { enabled: true, schedule: "0 9 * * 1" }
```

## 配置合并优先级

```
内置默认值 (最低)
    ↓ 覆盖
预设模板 (preset)
    ↓ 覆盖
消费者的 .github/flywheel.yml
    ↓ 覆盖（最高）
workflow 中的 with: inputs
```

## Sources

- [anthropics/claude-code-action - Examples](https://github.com/anthropics/claude-code-action/tree/main/examples)
- [Automate repository tasks with GitHub Agentic Workflows - GitHub Blog (Feb 2026)](https://github.blog/ai-and-ml/automate-repository-tasks-with-github-agentic-workflows/)
- [GitHub Agentic Workflows Documentation](https://github.github.com/gh-aw/)
