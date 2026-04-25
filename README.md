# Gearbox

> AI 驱动的 GitHub 仓库自动化飞轮系统

可复用的 GitHub Action 套件。消费者仓库一行 `uses: gqy20/gearbox@v1` 接入完整闭环：

```
Issue → Triage → Implement → Review → CI Fix → Merge → Report
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

环境变量：`ANTHROPIC_AUTH_TOKEN`、`ANTHROPIC_BASE_URL`、`ANTHROPIC_MODEL`、`GITHUB_TOKEN`

## 开发

```bash
uv run pytest -v
uv run ruff check src tests && uv run ruff format --check src tests
uv run mypy src
```

## 项目结构

```text
src/gearbox/
  cli.py       # CLI 入口
  audit.py     # Agent 审计主流程
  publish.py   # Issue 发布逻辑
  config/      # 配置与 MCP 设置
  tools/       # 自定义 MCP 工具
tests/
```

详见 [docs/index.md](docs/index.md) 了解完整架构设计与路线图。
