# Claude Code Actions 调研

## 概述

Claude Code 是 Anthropic 官方的终端 AI 编程工具（`claude-code-action@v1`），2025 年 9 月随 2.0 版本发布 GA。

**两种运行模式：**

| 模式 | 触发方式 | 适用场景 |
|------|---------|---------|
| **交互模式** | PR/Issue 中的 `@claude` 提及 | 人工驱动的按需任务 |
| **自动模式** | workflow 中 `prompt` 参数 | 定时、事件触发的自动化 |

## 核心能力

### 1. 自定义命令 (`.claude/commands/*.md`)

每个 Markdown 文件成为一个斜杠命令：

```markdown
---
description: 审查当前分支的变更
argument-hint: [pr-number]
---

## 变更文件
!`git diff --name-only main...HEAD`

## 完整 Diff
!`git diff main...HEAD`

审查每个变更文件的：
1. 缺失的输入校验
2. SQL 注入或数据泄露风险
3. 缺失或不完整的测试覆盖
4. 性能问题（N+1 查询、缺失索引）
```

**关键特性：**
- Shell 命令注入：`` !`git diff main...HEAD` `` 将真实输出注入 prompt
- 参数传递：`$ARGUMENTS` 接收命令参数
- YAML frontmatter：`description`, `argument-hint`, `allowed-tools`

### 2. Skills (`.claude/skills/<name>/SKILL.md`)

自动触发的工作流，基于任务描述由 Claude 自主调用：

```yaml
---
name: deploy
description: 部署 API 到 staging 或生产环境
argument-hint: [staging|production]
allowed-tools: Read, Bash, Grep
model: sonnet
context: fork           # 在隔离子 agent 中运行
user-invocable: false   # 仅 Claude 可调用
---
```

### 3. Agents (`.claude/agents/*.md`)

专用子 Agent，在隔离上下文窗口中运行：

```yaml
---
name: code-reviewer
description: 代码审查专家。主动用于审查 PR、检查实现
model: sonnet
tools: Read, Grep, Glob     # 限制工具
maxTurns: 20
memory: project             # 持久化记忆
isolation: worktree        # 在隔离 git worktree 中运行
background: true            # 后台运行
---
```

### 4. Settings & 权限 (`.claude/settings.json`)

```json
{
  "permissions": {
    "allow": [
      "Bash(npm run *)",
      "Bash(git diff *)",
      "Read", "Write", "Edit", "Glob", "Grep"
    ],
    "deny": [
      "Bash(rm -rf *)",
      "Read(.env)",
      "Read(.env.*)"
    ]
  },
  "env": {
    "NODE_ENV": "development"
  },
  "hooks": {
    "PreToolUse": [{
      "matcher": "Bash",
      "hooks": [{
        "type": "command",
        "command": ".claude/hooks/validate-bash.sh",
        "timeout": 10
      }]
    }]
  }
}
```

**配置合并优先级（后覆盖前）：**
Managed Policy < `~/.claude/settings.json` < `.claude/settings.json` < `.claude/settings.local.json`

## `.claude/` 目录完整结构

```
your-project/
├── CLAUDE.md                      # 项目指令（每次会话加载）
├── CLAUDE.local.md                # 个人覆盖（gitignore）
├── .mcp.json                      # MCP 服务配置
│
└── .claude/
    ├── settings.json              # 权限、钩子、环境变量
    ├── settings.local.json        # 个人覆盖
    │
    ├── rules/                     # 主题作用域指令
    │   ├── code-style.md          #   每次加载
    │   └── api-design.md          #   paths: ["src/api/**"] 条件加载
    │
    ├── commands/                  # 自定义斜杠命令
    │   ├── review.md              # → /project:review
    │   ├── fix-issue.md          # → /project:fix-issue 123
    │   └── deploy-check.md       # → /project:deploy-check
    │
    ├── skills/                    # 自动调用工作流
    │   └── security-review/
    │       ├── SKILL.md
    │       └── checklist.md      # @ 引用
    │
    ├── agents/                    # 专用子 agent
    │   ├── code-reviewer.md
    │   └── security-auditor.md
    │
    └── hooks/                     # 事件驱动脚本
        └── validate-bash.sh
```

## 决策指南

| 目标 | 机制 |
|------|------|
| 项目指令 (<200 行) | `CLAUDE.md` |
| 可扩展指令 (>200 行) | `.claude/rules/*.md` + `paths:` 作用域 |
| 可复用的手动工作流 | `.claude/commands/name.md` |
| 自动感知上下文工作流 | `.claude/skills/name/SKILL.md` |
| 专家委托 | `.claude/agents/name.md` |
| 权限控制 | `.claude/settings.json` |
| 事件驱动自动化 | Hooks in `settings.json` + `.claude/hooks/` |
| 外部工具集成 | `.mcp.json` |
| 跨会话记忆 | `~/.claude/projects/<hash>/memory/` |

## GitHub Actions 集成

### 官方 Action: `anthropics/claude-code-action@v1`

**认证方式（4 种）：**

| 后端 | 所需 Secret | 说明 |
|------|------------|------|
| Anthropic Direct API | `ANTHROPIC_API_KEY` | 最简单 |
| Claude Code OAuth | `CLAUDE_CODE_OAUTH_TOKEN` | Max 订阅用户 |
| AWS Bedrock | `AWS_ROLE_TO_ASSUME` + OIDC | 无需 API Key |
| Google Vertex AI | `GCP_WORKLOAD_IDENTITY_PROVIDER` | Workload Identity |

**核心参数：**

| 参数 | 必填 | 说明 |
|------|------|------|
| `prompt` | 否* | Claude 指令（省略则响应 @claude 提及） |
| `claude_args` | 否 | CLI 参数 |
| `anthropic_api_key` | 是** | API Key（Bedrock/Vertex 不需要） |
| `github_token` | 否 | GitHub Token |
| `trigger_phrase` | 否 | 触发短语（默认 `@claude`） |
| `use_bedrock` / `use_vertex` | 否 | 使用对应后端 |

### 典型 Workflow 模式

#### 模式 1: 交互评论触发

```yaml
name: Claude Code
on:
  issue_comment:
    types: [created]
  pull_request_review_comment:
    types: [created]
jobs:
  claude:
    runs-on: ubuntu-latest
    steps:
      - uses: anthropics/claude-code-action@v1
        with:
          anthropic_api_key: ${{ secrets.ANTHROPIC_API_KEY }}
```

#### 模式 2: 自动 PR Review

```yaml
name: Claude PR Review
on:
  pull_request:
    types: [opened, synchronize]
    paths-ignore: ['*.md', 'docs/**']
jobs:
  review:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: write
    concurrency:
      group: claude-review-${{ github.event.pull_request.number }}
      cancel-in-progress: true
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: anthropics/claude-code-action@v1
        with:
          anthropic_api_key: ${{ secrets.ANTHROPIC_API_KEY }}
          prompt: |
            审查这个 PR。关注逻辑错误、安全漏洞、性能问题、测试缺失。
          claude_args: "--max-turns 5"
```

#### 模式 3: CI 失败自动修复（飞轮关键环节）

```yaml
name: Auto Fix CI Failures
on:
  workflow_run:
    workflows: ["CI"]
    types: [completed]
jobs:
  auto-fix:
    if: |
      github.event.workflow_run.conclusion == 'failure' &&
      github.event.workflow_run.pull_requests[0] &&
      !startsWith(github.event.workflow_run.head_branch, 'claude-auto-fix-ci-')
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ github.event.workflow_run.head_branch }}
          fetch-depth: 0
      - run: |
          git config --global user.email "claude[bot]@users.noreply.github.com"
          git config --global user.name "claude[bot]"
          BRANCH="claude-auto-fix-${{ github.event.workflow_run.head_branch }}-${{ github.run_id }}"
          git checkout -b "$BRANCH"
      - uses: anthropics/claude-code-action@v1
        with:
          prompt: |
            CI 构建失败了。分析失败日志并修复根因。
            失败 Run: ${{ github.event.workflow_run.html_url }}
          anthropic_api_key: ${{ secrets.ANTHROPIC_API_KEY }}
          claude_args: "--max-turns 10"
```

**关键防护：** `!startsWith(..., 'claude-auto-fix-ci-')` 防止无限循环。

#### 模式 4: 定时报告

```yaml
name: Daily Report
on:
  schedule:
    - cron: "0 9 * * *"
jobs:
  report:
    runs-on: ubuntu-latest
    steps:
      - uses: anthropics/claude-code-action@v1
        with:
          anthropic_api_key: ${{ secrets.ANTHROPIC_API_KEY }}
          prompt: "生成昨天的 commit 和 issue 摘要报告"
          claude_args: "--model opus"
```

## 成本控制

| 控制手段 | 方式 | 效果 |
|---------|------|------|
| `--max-turns N` | 硬性轮次上限 | 最直接的成本控制 |
| Concurrency group | `cancel-in-progress: true` | 取消排队中的重复运行 |
| 事件过滤 | `types: [opened]` 非 `[opened, synchronize]` | 每个 PR 只触发一次 |
| 路径过滤 | `paths-ignore: ['*.md']` | 跳过文档变更 |
| 模型选择 | Sonnet vs Opus | Sonnet 成本约 Opus 的 40% |
| 超时 | `timeout-minutes: 10` | 终止失控的任务 |
| 工具限制 | `--allowedTools 'Edit,Read'` | 减少不必要的轮次 |

**预估成本（Sonnet 模型）：**

| PR 规模 | 预估成本/次 |
|---------|------------|
| 小 (<200 行) | $0.01 - $0.03 |
| 中 (200-1000 行) | $0.05 - $0.15 |
| 大 (1000+ 行) | $0.20 - $0.50 |

月均 ~50 个 PR 的团队约 **$5-15/月**。

## 安全特性

- **访问控制：** 默认只有仓库 write 权限的贡献者可触发
- **Prompt 注入保护：** 自动剥离隐藏内容（HTML 注释、不可见字符等）
- **最小权限原则：** workflow 的 `permissions:` 匹配实际需求
- **不自动合并：** Claude 创建修复分支和 PR — 人类必须审核批准

## 快速开始

```bash
# 方式 1: 在 Claude Code 终端中执行
/install-github-app

# 方式 2: 手动安装
# 1. 访问 https://github.com/apps/claude 安装到仓库
# 2. Settings → Secrets → Add ANTHROPIC_API_KEY
# 3. 从 examples/ 复制 workflow 模板
```

## Sources

- [Claude Code GitHub Actions - Official Docs](https://code.claude.com/docs/en/github-actions)
- [anthropics/claude-code-action - GitHub](https://github.com/anthropics/claude-code-action)
- [Explore the .claude directory - Claude Code Docs](https://code.claude.com/docs/en/claude-directory)
- [Custom Slash Commands - DEV Community](https://dev.to/subprime2010/claude-code-custom-slash-commands-the-commands-directory-youre-probably-not-using-5a18)
- [How to Integrate Claude Code with CI/CD - Skywork](https://skywork.ai/blog/how-to-integrate-claude-code-ci-cd-guide-2025/)
