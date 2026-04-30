# 贡献指南

感谢你对 Gearbox 的关注！本文档帮助你快速参与贡献。

## 开发环境搭建

### 前置条件

- **Python** 3.10 或更高版本
- [**uv**](https://docs.astral.sh/uv/) — 快速 Python 包管理器

### 克隆与安装

```bash
git clone https://github.com/gqy20/gearbox.git
cd gearbox
uv sync
```

`uv sync` 会根据 `pyproject.toml` 和 `uv.lock` 安装所有依赖（含开发依赖），并创建虚拟环境。

### 验证安装

```bash
uv run gearbox --help
```

## 代码规范

### Lint 与格式化

项目使用 **Ruff** 统一处理 lint 检查和代码格式化：

```bash
# Lint 检查
uv run ruff check src tests

# 自动修复可修复的问题
uv run ruff check --fix src tests

# 格式化
uv run ruff format src tests
```

**规则配置**（见 `pyproject.toml`）：

| 配置项 | 值 |
| --- | --- |
| 行宽 | 100 字符 |
| 启用规则 | E, F, I, N, W |
| 忽略规则 | E501（行宽由 ruff format 管理） |

### 类型检查

使用 **mypy** 对 `src/` 进行静态类型检查：

```bash
uv run mypy src
```

### Pre-commit 钩子

推荐在本地启用 pre-commit，提交前自动执行检查：

```bash
uvx pre-commit install
uvx pre-commit run --all-files
```

当前 pre-commit 钩子覆盖：trailing-whitespace、YAML/JSON/TOML 校验、actionlint、ruff check、ruff format、mypy。

## 测试

```bash
# 运行全部测试
uv run pytest -q

# 运行单个测试文件
uv run pytest tests/test_audit.py -q

# 运行带详细输出
uv run pytest -v
```

测试框架为 **pytest**。新增功能时请同步添加对应测试。

## 提交 Pull Request

### 分支命名

- 功能：`feat/描述性名称`
- 修复：`fix/描述性名称`
- 文档：`docs/描述性名称`

### PR 流程

1. **Fork** 本仓库并从 `main` 创建特性分支。
2. 编写代码并确保：
   - 新增功能遵循 **TDD** 原则（先写测试，再实现）。
   - `uv run pytest -q` 全部通过。
   - `uv run ruff check src tests` 无报错。
   - `uv run mypy src` 无报错。
3. **提交**并推送到你的 fork。
4. 在 GitHub 上创建 **Pull Request**，填写清晰的标题和变更说明。

### Commit Message

使用简洁的中文或英文描述变更目的，格式参考：

```
简短摘要（一行）

可选的详细说明。

Co-Authored-By: Claude <noreply@anthropic.com>
```

## 项目结构概览

```
gearbox/
├── actions/              # GitHub Action 定义
│   ├── main/action.yml   # Marketplace 路由入口
│   ├── audit/action.yml  # 审计 action
│   └── ...
├── src/gearbox/
│   ├── cli.py            # Click CLI 入口
│   ├── core/gh.py        # GitHub API 封装
│   ├── release.py        # Marketplace 打包与发布
│   └── agents/           # Agent 实现
│       ├── audit.py
│       ├── backlog.py
│       ├── review.py
│       ├── implement.py
│       └── shared/       # 共享工具模块
├── tests/                # 测试
├── .github/workflows/    # CI / 内部工作流
└── docs/                 # 架构文档与调研
```

## 需要帮助？

- 查看 [架构文档](docs/index.md) 了解整体设计。
- 打开 [Issue](https://github.com/gqy20/gearbox/issues) 讨论问题或提出建议。
