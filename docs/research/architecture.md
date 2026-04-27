# Gearbox 架构设计文档

## 项目定位

**Gearbox** 是一个 AI 驱动的 GitHub 仓库自动化飞轮系统。

> Gearbox = 变速箱/齿轮箱 — 将 Issue 转化为 Code，Code 转化为 PR，PR 转化为 Merge 的传动装置。

**核心价值：** 一个可复用的 GitHub Action 套件仓库，其他项目只需一行 `uses: gqy20/gearbox-action@v1` 即可接入完整的 AI 驱动开发闭环。

## 飞轮模型

```
                        ┌─────────────────────┐
                        │   Audit             │
                        │   仓库审计/生成Issue │
                        └──────────┬──────────┘
                                   │ 创建 Issue
                                   ▼
┌─────────────────────┐  ┌─────────────────────┐  ┌─────────────────────┐
│   Backlog            │→ │   Implement         │→ │   Code Review       │
│   (分类/排序/标签)    │  │   (实现 → 提 PR)    │  │   (审查/评论)        │
└─────────────────────┘  └─────────────────────┘  └──────────┬──────────┘
        ▲                                                    │
        │                                                    ▼
        │                                          ┌─────────────────────┐
        │                                          │   Merge             │
        │                                          └──────────┬──────────┘
        │                                                     │
        │                                                     ▼
        │                                          ┌─────────────────────┐
        └──────────────────────────────────────────│   Report            │
           定时触发新巡检                              │   巡检报告          │
                                                   └─────────────────────┘
```

## 技术架构

### 分层设计

```
┌────────────────────────────────────────────────────────────┐
│                    消费者仓库 (Consumer Repo)                │
│                                                            │
│  一行 YAML 接入                                             │
└──────────────────────────┬─────────────────────────────────┘
                           │ uses: gqy20/gearbox-action@v1
                           ▼
┌────────────────────────────────────────────────────────────┐
│                  开发仓内部编排 (gqy20/gearbox)             │
│                                                            │
│  .github/workflows/audit.yml     — 内部 audit 入口       │
│  .github/workflows/backlog.yml    — 内部 backlog 入口       │
│  .github/workflows/dispatch.yml   — 内部 dispatch 入口      │
│  .github/workflows/review.yml     — 内部 review 入口         │
│                                                            │
│  .github/workflows/reusable-*.yml — 保留给外部调用的模板    │
└──────────────────────────┬─────────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────────┐
│                      Action 执行层                          │
│                                                            │
│  actions/*/action.yml   — composite action，各自调用 CLI      │
│  actions/_runtime/      — uv + Python + gh + 项目依赖      │
│  actions/_setup/        — audit 扫描工具（semgrep 等）      │
└──────────────────────────┬─────────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────────┐
│                      核心逻辑层                             │
│                                                            │
│  src/gearbox/agents/*.py    — audit / backlog / review /  │
│                                 implement 等 agent 逻辑     │
│  src/gearbox/agents/shared/ — runtime / scanner /        │
│                                 structured / selection       │
│  src/gearbox/flow/*.py     — 确定性编排逻辑（dispatch）    │
│  src/gearbox/core/gh.py    — GitHub API 封装              │
└────────────────────────────────────────────────────────────┘
```

### 双模运行

| 模式 | 场景 | 入口 |
|------|------|------|
| **CLI 本地模式** | 开发调试、一次性审计 | `uv run gearbox audit --repo owner/name` |
| **Action 远程模式** | 生产环境持续运行 | `uses: gqy20/gearbox-action@v1` |

两种模式共享同一套核心逻辑（Agent、Scanner、工具），仅入口不同。

## 目录结构

```
gearbox/
├── README.md                       # 使用文档 + Quick Start
├── CHANGELOG.md                   # 版本变更记录
├── LICENSE                        # MIT
├── pyproject.toml                 # Python 包定义
│
├── actions/                        # Composite Action 套件
│   ├── _runtime/                  # 运行时：uv + Python + gh + 项目依赖
│   ├── _setup/                    # 扫描工具：semgrep / deptry / cloc / trivy 等
│   ├── main/                      # 内部路由层，导出后成为根 action.yml
│   ├── audit/                     # 审计 action
│   ├── backlog/                   # Issue 分类 action
│   ├── dispatch/                  # 从 ready backlog 选择并触发实现
│   ├── review/                    # PR 审查 action
│   ├── implement/                 # 实现 action（Issue → PR）
│   ├── publish/                   # 发布 action（issues.json → GitHub Issues）
│   └── cleanup/                   # 清理 action（候选分支清理）
│
├── src/gearbox/                    # 核心 Python 包
│   ├── __init__.py
│   ├── __main__.py                # CLI 入口
│   ├── cli.py                     # Click CLI 入口（root 命令）
│   ├── config.py                  # 配置加载
│   │
│   ├── agents/                    # Agent 实现
│   │   ├── audit.py              # Audit Agent
│   │   ├── backlog.py            # Backlog Agent（分类打标）
│   │   ├── review.py            # Review Agent
│   │   ├── implement.py         # Implement Agent
│   │   ├── evaluator.py         # 多实例选优 Agent
│   │   └── shared/             # Agent 共享能力
│   │       ├── runtime.py       # Claude Agent SDK 调用 + 流式日志
│   │       ├── structured.py    # 结构化输出提取
│   │       ├── scanner.py       # 克隆后静态扫描（cloc/semgrep/trivy/deptry）
│   │       ├── artifacts.py     # Artifact 文件管理
│   │       ├── selection.py     # 多实例结果选优
│   │       ├── git.py          # Git 克隆（shared）
│   │       └── prompt_helpers.py # Prompt 格式化工具
│   │
│   ├── core/                     # GitHub API 封装
│   │   └── gh.py                # Issue / PR / Label / Comment 等操作
│   │
│   ├── flow/                     # 确定性编排（无 LLM 调用）
│   │   ├── backlog.py           # Backlog plan 构建与 issue 过滤
│   │   ├── dispatch.py         # Dispatch 计划与选择逻辑
│   │   └── models.py           # Flow 数据模型
│   │
│   └── commands/                  # CLI 命令模块
│       ├── agent.py              # agent 子命令（audit-select 等）
│       ├── backlog.py            # backlog plan 子命令
│       ├── config.py            # config 子命令
│       └── release.py           # release / package 子命令
│
├── .github/workflows/
│   ├── ci.yml                    # ruff / mypy / pytest
│   ├── audit.yml                # 内部 audit matrix 编排
│   ├── backlog.yml             # 内部 backlog matrix 编排
│   ├── dispatch.yml             # 内部 dispatch 入口
│   ├── review.yml              # 内部 review 入口
│   ├── cleanup.yml             # 清理候选分支
│   ├── reusable-*.yml          # 保留给外部调用的模板
│   └── release-marketplace.yml  # Marketplace 发布流程
│
├── tests/                        # pytest 测试套件
├── docs/                         # 文档
│   ├── index.md                 # 架构文档入口
│   ├── roadmap.md              # 开发路线图
│   └── research/               # 调研文档
│       ├── architecture.md      # ← 本文件
│       ├── claude-code-actions.md
│       ├── composite-actions.md
│       ├── flywheel-workflow.md
│       └── security-governance.md
│
└── dist/                        # Marketplace 发布产物（自动生成）
```

## 六大核心 Action

### 1. Audit — 仓库审计

- **触发**: 定时（每小时）或手动 `workflow_dispatch` / `@audit`
- **输入**: 仓库标识、对标仓库列表
- **输出**: `issues.json`（可发布为改进建议 Issue）
- **特点**: 始终克隆目标仓库，scanner 和 Agent 基于同一克隆目录运行；提示词包含已有 open Issues 摘要，引导 Agent 聚焦新发现

### 2. Backlog — Issue 分类

- **触发**: `@backlog` 评论 / `workflow_dispatch` / 定时
- **输入**: 仓库标识、Issue 编号列表
- **输出**: 标签写回（P0-P3 / complexity:S/M/L / ready-to-implement）
- **特点**: 鼓励 Agent 分析源码判断问题本质；包含所有 open issues 摘要做相对优先级决策；标签过期（默认 2 天）重新评估

### 3. Dispatch — 实现计划

- **触发**: `@dispatch` 评论 / `workflow_dispatch`
- **输入**: 仓库标识、最大选择数量、dry-run 开关
- **输出**: 计划输出（默认 dry-run，不创建 PR）
- **特点**: 从 ready-to-implement backlog 中按优先级/复杂度选择；需要显式关闭 dry-run 才进入实现阶段

### 4. Implement — Issue 实现

- **触发**: Dispatch 选择后自动调用
- **输入**: 仓库标识、Issue 编号
- **输出**: 新分支 + Commit + PR
- **特点**: 要求 TDD（先写测试再实现）；要求测试通过 + lint 通过才能提交；同一测试失败 3 次自动停止

### 5. Review — PR 审查

- **触发**: `@review` 评论 / `workflow_dispatch`
- **输入**: 仓库标识、PR 编号
- **输出**: Review comments + 评分
- **特点**: 要求测试覆盖率，缺失测试标记 warning；支持基于前次 review 的增量 review

### 6. Publish — 发布 Issues

- **触发**: CLI / action 手动调用
- **输入**: `issues.json` 文件路径
- **输出**: GitHub Issues

## 从旧架构的演进

| 旧（设计阶段） | 当前（实现） |
|---|---|
| `tools/` 目录 | `agents/` 目录 |
| `prompts/` 目录 | Prompt 内联在 Agent Python 文件中 |
| `config/flywheel.py` | 消费者配置未实现，保持简洁 |
| `triage` action | `backlog` action |
| `core/engine.py` | 直接使用 `claude_agent_sdk` |
| `auto-merge` action | 未实现，保持简洁 |
| `setup/` action | 未实现，保持简洁 |
