# Gearbox

> AI 驱动的 GitHub 仓库自动化飞轮系统

开发母仓，用于产出 `gearbox-action` 的 Marketplace 发布产物。当前仓库保留源码、测试、文档和内部 workflow，不直接作为 Marketplace 商品使用。

```
Audit → Issue → Triage → Implement → Review → Merge → Report
```

## 安装

```bash
uv sync
```

## 使用

```bash
# CLI（本地调试）
uv run gearbox --help
uv run gearbox agent audit-repo --repo owner/repo --output-dir ./audit-output
uv run gearbox publish-issues --input ./output/issues.json

# 配置
uv run gearbox config set anthropic-api-key YOUR_KEY
uv run gearbox config list
```

## 架构

```
轻量入口:
  gqy20/gearbox-action@v1
      │
      └── 根 action.yml（由 actions/main 导出）
              │
              └── uses: ./actions/${{ inputs.action }}

高级入口:
  .github/workflows/reusable-*.yml
      │
      ├── workflow matrix 并行
      ├── artifact 聚合
      └── evaluator 选优

执行层:
  actions/*/action.yml
      │
      └── uses: ./actions/_setup
              │
              └── uv run gearbox agent ...
```

## GitHub Actions

### Marketplace 产物导出

```yaml
# 生成 gearbox-action 发布目录
uv run gearbox package-marketplace --output-dir ./dist/gearbox-action
```

### 发布约定

- 开发仓使用根目录的 [CHANGELOG.md](/home/qy/workspace/project/hub/gearbox/CHANGELOG.md) 作为唯一版本说明来源
- 每次发布 `vX.Y.Z` tag 前，都需要先补对应版本段落
- `release-marketplace.yml` 会在发布时自动提取该版本条目，并写入 `gearbox-action` 的 GitHub Release notes

### 本项目使用

```bash
# 审计当前项目
gh workflow run audit.yml

# 分类指定 Issue
gh workflow run triage.yml -f issue_number=123

# 审查指定 PR
gh workflow run review.yml -f pr_number=456
```

### 对外接入方式

轻量单步 Action：

```yaml
- uses: gqy20/gearbox-action@v1
  with:
    action: audit
    repo: owner/repo
    anthropic_api_key: ${{ secrets.ANTHROPIC_AUTH_TOKEN }}
```

高级并行 Reusable Workflow：

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

### 配置 Secrets / Variables

在 GitHub Repository `Settings → Secrets and variables → Actions` 中添加：

| Secret | 必须 | 说明 |
|---------|------|------|
| `ANTHROPIC_AUTH_TOKEN` | ✅ | LLM Provider API Key |
| `ANTHROPIC_BASE_URL` | ❌ | 自定义兼容网关地址 |
| `GH_PAT` | ❌ | `create_issues=true` 或需要写入 GitHub 副作用时使用 |

| Variable | 默认值 | 说明 |
|----------|--------|------|
| `ANTHROPIC_MODEL` | `glm-5.1` | 默认模型名 |

## 项目结构

```text
gearbox/
├── actions/
│   ├── _setup/                  # 环境准备 (Python, gh, 工具链)
│   ├── main/                    # 内部路由层 / 导出时成为根 action.yml
│   ├── audit/                   # 审计 action
│   ├── triage/                  # 分类 action
│   ├── review/                  # 审查 action
│   ├── implement/               # 实现 action
│   └── publish/                 # 发布 action
├── .github/
│   └── workflows/
│       ├── audit.yml            # 薄入口：审计
│       ├── triage.yml           # 薄入口：Issue 分类
│       ├── review.yml           # 薄入口：PR 审查
│       ├── reusable-audit.yml   # 高级并行编排：审计
│       ├── reusable-triage.yml  # 高级并行编排：分类
│       └── reusable-review.yml  # 高级并行编排：审查
└── src/gearbox/
    ├── cli.py                   # CLI 入口
    ├── core/
    │   └── gh.py                # GitHub 操作封装
    └── agents/
        ├── *.py                 # 具体 Agent
        └── shared/              # 共享 runtime / structured / artifacts / selection
```

## 开发

```bash
uv run pytest -v
uv run ruff check src tests && uv run ruff format --check src tests
uv run mypy src
```

详见 [docs/index.md](docs/index.md) 了解完整架构设计与路线图。
