# 开发指南

## 项目结构

```text
gearbox/
├── actions/              # GitHub Action 定义
│   ├── main/             # 根路由层
│   ├── _runtime/         # 轻量运行时
│   ├── _setup/           # 扫描工具安装
│   ├── audit/            # 审计 action
│   ├── backlog/          # 分类 action
│   ├── dispatch/         # 调度 action
│   ├── review/           # 审查 action
│   ├── implement/        # 实现 action
│   └── publish/          # 发布 action
├── .github/workflows/    # CI/CD 与编排 workflow
├── src/gearbox/
│   ├── cli.py            # Click CLI 入口
│   ├── core/             # GitHub API 封装
│   ├── release.py        # Marketplace 打包与发布说明
│   └── agents/           # Agent 实现
│       ├── shared/       # 共享模块
│       │   ├── runtime.py      # SDK 运行时与流式日志
│       │   ├── structured.py   # 结构化输出提取
│       │   ├── scanner.py      # 静态扫描
│       │   ├── artifacts.py    # 输出文件管理
│       │   └── selection.py    # 多实例选优
│       ├── audit.py
│       ├── triage.py
│       ├── review.py
│       └── implement.py
└── tests/                # 测试用例
```

## 测试

```bash
# 运行全部测试
uv run pytest -q

# 运行单个测试文件
uv run pytest tests/test_audit.py -q

# 详细输出
uv run pytest -v

# 覆盖率
uv run pytest --cov=src/gearbox --cov-report=term-missing
```

## Lint 与格式化

```bash
# Ruff lint
uv run ruff check src tests

# Ruff 格式检查
uv run ruff format --check src tests

# 自动修复格式问题
uv run ruff format src tests

# Mypy 类型检查
uv run mypy src
```

## Pre-commit

```bash
# 安装钩子
uvx pre-commit install

# 手动全量运行
uvx pre-commit run --all-files
```

## 代码风格

| 规则 | 配置 | 文件 |
| --- | --- | --- |
| 行长度 | 100 字符 | `pyproject.toml` `[tool.ruff]` |
| Lint 规则 | E, F, I, N, W (忽略 E501) | `pyproject.toml` `[tool.ruff.lint]` |
| 类型检查 | Python 3.10, strict mode | `pyproject.toml` `[tool.mypy]` |

## 添加新 Agent

1. 在 `src/gearbox/agents/` 下创建新的 agent 模块。
2. 在 `src/gearbox/cli.py` 中注册对应的 CLI 子命令。
3. 在 `actions/` 下创建对应的 action.yml。
4. 更新 `actions/main/action.yml` 的路由表。
5. 编写测试并确保通过 CI。

## 添加新扫描工具

1. 在 `src/gearbox/agents/shared/scanner.py` 中添加工具逻辑。
2. 在 `actions/_setup/action.yml` 中添加工具安装步骤。
3. 更新文档中的扫描工具表格。
