# Gearbox

> AI 驱动的 GitHub 仓库自动化飞轮系统

可复用的 GitHub Action 套件。消费者仓库一行 `uses: gqy20/gearbox@main` 接入完整闭环：

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
uv run gearbox audit --repo owner/repo
uv run gearbox publish-issues --input ./output/issues.json

# 配置
uv run gearbox config set anthropic-api-key YOUR_KEY
uv run gearbox config list
```

## 架构

```
外部仓库: uses: gqy20/gearbox@main
    │
    ▼
action.yml (根入口，路由层)
    │
    └── uses: ./actions/${{ inputs.action }}
              │
              ├── audit/action.yml
              ├── triage/action.yml
              ├── review/action.yml
              ├── implement/action.yml
              └── publish/action.yml
                      │
                      └── uses: ./_setup (环境准备)
                              │
                              └── python3 -m gearbox.cli agent $action
                                      │
                                      └── src/gearbox/core/gh.py (GitHub 操作)
```

## GitHub Actions

### 外部仓库接入

```yaml
# .github/workflows/audit.yml
name: Audit
on:
  workflow_dispatch:
    inputs:
      benchmarks:
        description: '对标仓库'
        required: false
        default: ''

jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - uses: gqy20/gearbox@main
        with:
          action: audit
          repo: ${{ github.repository }}
          benchmarks: ${{ inputs.benchmarks }}
          anthropic_api_key: ${{ secrets.ANTHROPIC_AUTH_TOKEN }}
```

### 本项目使用

```bash
# 审计当前项目（每周一自动执行）
gh workflow run audit.yml

# 审计指定仓库
gh workflow run audit.yml -f target_repo=owner/other-repo

# 带对标仓库
gh workflow run audit.yml -f target_repo=owner/other-repo -f benchmarks=github/copilot

# 审计当前项目自身
gh workflow run audit.yml -f is_self_audit=true -f benchmarks=github/copilot
```

### 配置环境变量

在 GitHub Repository `Settings → Secrets and variables → Actions` 中添加：

| Secret | 必须 | 说明 |
|---------|------|------|
| `ANTHROPIC_AUTH_TOKEN` | ✅ | API Key（MiniMax/GLM/Claude） |
| `GH_PAT` | ❌ | 创建 issues 时需要 |

| Variable | 默认值 | 说明 |
|----------|--------|------|
| `ANTHROPIC_MODEL` | `glm-5.1` | 模型名（推荐 `glm-5v-turbo` 或 `MiniMax-M2.7-highspeed`） |

## 项目结构

```text
gearbox/
├── action.yml                    # 根入口 (外部 uses: gqy20/gearbox@main)
├── actions/
│   ├── _setup/                  # 环境准备 (Python, gh, 工具链)
│   ├── audit/                   # 审计 action
│   ├── triage/                  # 分类 action
│   ├── review/                  # 审查 action
│   ├── implement/               # 实现 action
│   └── publish/                 # 发布 action
├── .github/
│   └── workflows/
│       └── audit.yml            # 内部 workflow (编排层)
└── src/gearbox/
    ├── cli.py                   # CLI 入口
    ├── core/
    │   ├── gh.py               # GitHub 操作封装
    │   └── parallel.py          # 并行执行
    └── agents/                  # Agent 实现
```

## 开发

```bash
uv run pytest -v
uv run ruff check src tests && uv run ruff format --check src tests
uv run mypy src
```

详见 [docs/index.md](docs/index.md) 了解完整架构设计与路线图。
