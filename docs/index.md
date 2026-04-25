# Gearbox

> 齿轮箱 — AI 驱动的 GitHub 仓库自动化飞轮系统

Gearbox 是一个可复用的 GitHub Action 套件仓库。其他项目只需一行 `uses: gqy20/gearbox/triage@v1` 即可接入完整的 AI 驱动开发闭环：

```
Issue 创建 → 自动分类 → Claude 实现 → PR 提交 → Code Review → CI 检查 → Merge → 巡检报告
    ↑                                                                              |
    └────────────────────────────────────── 闭环 ──────────────────────────────────┘
```

## 从 repo-auditor 演进而来

本项目前身为 `repo-auditor`（基于 Claude Agent SDK 的仓库审计工具），现已演进为 **Gearbox** 飞轮系统。

保留的核心资产：
- Agent SDK 集成与 MCP 工具链（web-search, zread, context7 等）
- CLI 本地调试能力
- GitHub Actions 执行骨架
- Python 包管理（uv + pyproject.toml）

新增的方向：
- **Composite Action 套件** — 可被其他仓库引用
- **飞轮闭环** — Issue → Triage → Implement → Review → CI Fix → Merge → Report
- **配置即服务** — 消费者通过 `.github/flywheel.yml` 一份配置接入
- **安全护栏** — 防死循环、成本控制、审计日志、最小权限

## 调研文档

| 文档 | 内容 |
|------|------|
| [架构设计](research/architecture.md) | 整体架构、目录结构、六大 Action 设计、从 auditor 到 gearbox 的演进映射 |
| [Claude Code Actions 调研](research/claude-code-actions.md) | 自定义命令、Skills、Agents、Settings、GitHub Actions 集成模式、成本控制 |
| [Composite Action 设计](research/composite-actions.md) | Action 类型对比、Monorepo 布局、action.yml 结构、嵌套编排、版本策略、包装第三方 Action |
| [飞轮 Workflow 设计](research/flywheel-workflow.md) | 六大 Workflow 详细流程、消费者接入方式、一键初始化、预设模板系统、配置合并优先级 |
| [安全与治理](research/security-governance.md) | 防无限循环、成本控制、OIDC 认证、最小权限、审计日志、禁止路径、人类在环 |

## 快速开始（目标态）

```yaml
# 消费者仓库 .github/workflows/flywheel.yml
name: AI Flywheel
on:
  issues: [opened, edited, labeled]
  pull_request: [opened, synchronize]
  schedule: [{ cron: "0 9 * * *" }]

permissions:
  issues: write
  pull-requests: write
  contents: write

jobs:
  flywheel:
    uses: gqy20/gearbox@v1
    secrets: inherit
```

```yaml
# 消费者仓库 .github/flywheel.yml
project:
  type: backend
  language: typescript

triage: { enabled: true }
review: { enabled: true, focus_areas: [security, testing] }
ci_fix: { enabled: true }
report: { enabled: true }
```

**2 个文件，~80 行 YAML，一次配置永久生效。**

## 开发路线图

- [ ] Phase 1: 重命名 + actions/ 目录 + 第一个 Composite Action (triage)
- [ ] Phase 2: 扩展 tools/ (triage.py, implement.py, review.py)
- [ ] Phase 3: 配置系统 (.github/flywheel.yml 解析)
- [ ] Phase 4: 全套 6 个 Action + Marketplace 发布
