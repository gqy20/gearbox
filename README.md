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
uv run gearbox audit --repo owner/repo
uv run gearbox publish-issues --input ./output/issues.json

# 配置
uv run gearbox config set anthropic-api-key YOUR_KEY
uv run gearbox config list
```

## 架构

```
开发仓内部: uses: ./actions/main
    │
    ▼
actions/main/action.yml (路由层)
    │
    └── uses: ./actions/${{ inputs.action }}
              │
              ├── audit/action.yml
              ├── triage/action.yml
              ├── review/action.yml
              ├── implement/action.yml
              └── publish/action.yml
                      │
                      └── uses: ./actions/_setup (环境准备)
                              │
                              └── python3 -m gearbox.cli agent $action
                                      │
                                      └── src/gearbox/core/gh.py (GitHub 操作)
```

## GitHub Actions

### Marketplace 产物导出

```yaml
# 生成 gearbox-action 发布目录
uv run gearbox package-marketplace --output-dir ./dist/gearbox-action
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
