# Gearbox 架构设计文档

## 项目定位

**Gearbox** 是一个 AI 驱动的 GitHub 仓库自动化飞轮系统。

> Gearbox = 变速箱/齿轮箱 — 将 Issue 转化为 Code，Code 转化为 PR，PR 转化为 Merge 的传动装置。

**核心价值：** 一个可复用的 GitHub Action 套件仓库，其他项目只需一行 `uses: gqy20/gearbox/triage@v1` 即可接入完整的 AI 驱动开发闭环。

## 飞轮模型

```
                        ┌─────────────────────┐
                        │   定时巡检 / 报告     │
                        │   (发现新问题)        │
                        └──────────┬──────────┘
                                   │ 创建 Issue
                                   ▼
┌─────────────────────┐    ┌─────────────────────┐    ┌─────────────────────┐
│   Auto Triage       │───→│   Implement         │───→│   Code Review       │
│   (分类/排序/标签)    │    │   (实现 → 提 PR)     │    │   (审查/评论)        │
└─────────────────────┘    └─────────────────────┘    └──────────┬──────────┘
        ▲                                                    │
        │                                                    ▼
        │                                          ┌─────────────────────┐
        │                                          │   CI 检查            │
        │                                          └──────────┬──────────┘
        │                                                     │ 失败
        │                                                     ▼
        │                                          ┌─────────────────────┐
        └──────────────────────────────────────────│   CI Fix             │
           Merge 后触发新巡检                         │   (自动修复)          │
                                                   └─────────────────────┘
```

## 技术架构

### 分层设计

```
┌────────────────────────────────────────────────────────────┐
│                    消费者仓库 (Consumer Repo)                │
│                                                            │
│  .github/flywheel.yml  ← 声明式配置（项目特性）              │
│  .github/workflows/    ← 事件路由（极简，~80行）              │
└──────────────────────────┬─────────────────────────────────┘
                           │ uses: gqy20/gearbox/action@v1
                           ▼
┌────────────────────────────────────────────────────────────┐
│                  Gearbox Action 仓库（集中管控）               │
│                                                            │
│  Layer 1: actions/*/action.yml                             │
│  ├─ 入口定义 (inputs / outputs / runs)                      │
│  ├─ 安全护栏 (branch prefix 检查、权限校验)                   │
│  └─ 配置读取 (flywheel.yml 解析)                            │
│                                                            │
│  Layer 2: src/gearbox/core/                                │
│  ├─ Agent 引擎 (基于 Claude Agent SDK)                      │
│  ├─ Prompt 管理 (模板 + 动态注入)                           │
│  ├─ 工具集 (GitHub API、代码分析、对比)                      │
│  └─ Guard 系统 (防死循环、成本控制、审计日志)                 │
│                                                            │
│  Layer 3: anthropics/claude-code-action@v1                 │
│  └─ 官方执行引擎（可选后端）                                 │
│                                                            │
│  Layer 4: 输出 & 反馈                                      │
│  ├─ GitHub API 操作 (label、comment、PR、merge)             │
│  └─ 审计日志 & 成本追踪                                     │
└────────────────────────────────────────────────────────────┘
```

### 双模运行

| 模式 | 场景 | 入口 |
|------|------|------|
| **CLI 本地模式** | 开发调试、一次性审计 | `uv run gearbox audit --repo owner/name` |
| **Action 远程模式** | 生产环境持续运行 | `uses: gqy20/gearbox/triage@v1` |

两种模式共享同一套核心逻辑（Agent、Prompt、工具），仅入口不同。

## 目录结构

```
gearbox/
├── README.md                       # 使用文档 + Quick Start
├── LICENSE
├── pyproject.toml                  # Python 包定义
│
├── src/gearbox/                     # 核心包
│   ├── __init__.py
│   ├── __main__.py                 # CLI 入口
│   ├── cli.py                      # Click CLI 命令
│   ├── config/                     # 配置管理
│   │   ├── __init__.py
│   │   ├── settings.py             # 设置加载
│   │   └── flywheel.py             # flywheel.yml 解析
│   ├── core/                       # Agent 核心
│   │   ├── __init__.py
│   │   ├── engine.py               # Agent 引擎封装
│   │   ├── session.py              # 会话管理
│   │   └── guards.py               # 安全护栏
│   ├── prompts/                    # Prompt 模板
│   │   ├── triage.md
│   │   ├── implement.md
│   │   ├── review.md
│   │   ├── ci_fix.md
│   │   └── report.md
│   ├── tools/                      # 工具集
│   │   ├── __init__.py
│   │   ├── triage.py               # 分类工具
│   │   ├── implement.py            # 实现工具
│   │   ├── review.py               # Review 工具
│   │   ├── ci_fix.py               # CI 修复工具
│   │   ├── profile.py              # 仓库画像（已有）
│   │   ├── compare.py              # 对比分析（已有）
│   │   ├── issue.py                # Issue 生成（已有）
│   │   └── benchmark.py            # 对标分析（已有）
│   └── utils/                      # 工具函数
│       ├── github_api.py           # GitHub API 封装
│       └── logger.py               # 统一日志
│
├── actions/                         # Composite Action 套件
│   ├── triage/
│   │   └── action.yml             # Issue 自动分类排序
│   ├── implement/
│   │   └── action.yml             # Issue → 实现 → PR
│   ├── review/
│   │   └── action.yml             # PR Code Review
│   ├── ci-fix/
│   │   └── action.yml             # CI 失败修复
│   ├── auto-merge/
│   │   └── action.yml             # 条件自动合并
│   ├── report/
│   │   └── action.yml             # 定时健康报告
│   └── setup/
│       └── action.yml             # 一键初始化
│
├── templates/
│   └── flywheel.yml               # 默认配置模板
│
├── tests/
│   ├── test_actions/
│   ├── test_tools/
│   └── test_core/
│
├── docs/
│   ├── index.md
│   ├── research/                  # 调研文档
│   │   ├── architecture.md        # ← 本文件
│   │   ├── claude-code-actions.md # Claude Code Actions 调研
│   │   ├── composite-actions.md   # Composite Action 设计
│   │   ├── flywheel-workflow.md   # 飞轮 Workflow 设计
│   │   └── security-governance.md # 安全与治理
│   └── guides/
│       ├── getting-started.md
│       ├── configuration.md
│       └── customization.md
│
└── .github/
    ├── workflows/
    │   ├── release.yml            # tag push → 自动发版
    │   ├── test.yml               # 测试
    │   └── validate.yml           # 校验所有 action.yml
    └── CODEOWNERS
```

## 六大核心 Action

### 1. Triage — 自动分类

- **触发**: Issue opened / edited
- **输入**: Issue 内容 (title, body, labels)
- **输出**: 类型标签 + 优先级 + 是否 ready-to-implement
- **模型**: Sonnet (低成本高频)

### 2. Implement — 自动实现

- **触发**: Issue labeled `ready-to-implement`
- **输入**: Issue 内容 + 代码库上下文
- **输出**: 新分支 + Commit + PR
- **模型**: Sonnet (常规) / Opus (复杂任务)
- **安全**: branch 前缀 `feat/issue-{n}`

### 3. Review — 自动审查

- **触发**: PR opened / synchronize
- **输入**: PR diff + 变更文件
- **输出**: Review comments + LGTM/Request Changes
- **模型**: Sonnet
- **并发控制**: cancel-in-progress

### 4. CI Fix — 自动修复

- **触发**: CI workflow failed
- **输入**: 失败日志 + 相关代码
- **输出**: 修复分支 + Fix PR
- **模型**: Opus (排查需要强推理)
- **关键防护**: 排除 claude-* 分支防止死循环

### 5. Auto-Merge — 条件合并

- **触发**: PR ready_for_review + checks passed
- **条件**: 非 draft + approval ≥ 1 + checks pass + 无 wip 标签
- **技术**: 纯 GitHub Actions (无需 AI)
- **安全**: 永远不自动 merge AI 生成的 PR 到 main

### 6. Report — 定时巡检

- **触发**: Cron (每日/每周)
- **输入**: 仓库全量状态
- **输出**: 健康 Report Issue + 发现新改进点
- **模型**: Sonnet

## 从 repo-auditor 到 gearbox 的演进映射

| repo-auditor (旧) | gearbox (新) | 说明 |
|-------------------|-------------|------|
| `audit.py` | `core/engine.py` | Agent 引擎通用化 |
| `cli.py` (audit/publish) | `cli.py` (audit/triage/implement/review/report)` | 命令扩展 |
| `tools/issue.py` | `tools/triage.py` + `tools/implement.py` | 拆分+增强 |
| `tools/compare.py` | `tools/review.py` | 方向对齐 |
| `tools/profile.py` | `tools/report.py` | 复用+增强 |
| `tools/benchmark.py` | `tools/benchmark.py` | 保留 |
| `.github/workflows/audit.yml` | `actions/*/action.yml` | 从单 workflow → Action 套件 |
| `config/settings.py` | `config/flywheel.py` | 新增消费者配置解析 |
| (无) | `core/guards.py` | 新增安全护栏 |
| (无) | `prompts/*.md` | 新增 Prompt 模板管理 |
