# Contributing to Gearbox

感谢你对 Gearbox 项目的关注！本文档将帮助你快速上手开发环境、理解代码规范和提交流程。

## 开发环境搭建

### 前置要求

- **Python** >= 3.10
- **[uv](https://docs.astral.sh/uv/)** — 项目包管理器（替代 pip / poetry）
- **[gh](https://cli.github.com/)** — GitHub CLI（用于本地调试 workflow）
- **Git**

### 初始化步骤

```bash
# 克隆仓库
git clone https://github.com/gqy20/gearbox.git
cd gearbox

# 安装依赖（自动创建 .venv）
uv sync

# 验证安装
uv run gearbox --help
```

### 可选：Pre-commit 钩子

```bash
uvx pre-commit install
```

安装后每次 `git commit` 会自动运行 ruff、ruff format、mypy 和 YAML 检查。

## 测试命令

### 本地质量检查

```bash
# Lint（ruff）
uv run ruff check src tests

# 格式检查
uv run ruff format --check src tests

# 类型检查（mypy）
uv run mypy src

# 运行全部测试
uv run pytest -q

# 运行单个测试文件
uv run pytest tests/test_audit.py -q

# 运行带详细输出的测试
uv run pytest -v
```

### Pre-commit 全量检查

```bash
uvx pre-commit run --all-files
```

## 提交规范

### Commit Message 格式

采用 [Conventional Commits](https://www.conventionalcommits.org/) 格式：

```
<type>(<scope>): <subject>

<body>
```

#### Type 列表

| Type | 说明 |
| --- | --- |
| `feat` | 新功能 |
| `fix` | Bug 修复 |
| `docs` | 文档变更 |
| `style` | 代码格式（不影响功能） |
| `refactor` | 重构（非新功能、非修复） |
| `perf` | 性能优化 |
| `test` | 测试相关 |
| `chore` | 构建/工具链变更 |

#### 示例

```
feat(audit): add semgrep scanner integration

Add semgrep as an optional static analysis tool in the audit scanner.
Falls back gracefully when semgrep is not installed.

fix(cli): handle missing config file gracefully

Return a clear error message instead of traceback when
gearbox config list is run without an existing config.
```

### 分支命名

- 功能分支：`feat/<description>`
- 修复分支：`fix/<description>`
- Issue 关联分支：`feat/issue-<number>` 或 `gearbox/implement-<number>`

## PR 流程

### 1. Fork 与创建分支

```bash
# Fork 仓库后在本地添加 remote
git remote add fork https://github.com/<your-username>/gearbox.git

# 创建并切换到新分支
git checkout -b feat/my-feature main
```

### 2. 开发与提交

```bash
# 编写代码...

# 提交前运行检查
uvx pre-commit run --all-files

# 或手动执行
uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy src && uv run pytest -q

# 提交
git add <changed-files>
git commit -m "feat(scope): description"
```

### 3. 推送与创建 PR

```bash
git push fork feat/my-feature
```

然后在 GitHub 上从你的 fork 创建 Pull Request 到 `gqy20/gearbox:main`。

### PR Checklist

在提交 PR 前请确认：

- [ ] 代码通过所有 CI 检查（ruff / mypy / pytest）
- [ ] Commit message 符合 Conventional Commits 规范
- [ ] 新增功能包含对应测试
- [ ] 文档已更新（如涉及 API 变更或新功能）
- [ ] CHANGELOG.md 已更新（如涉及用户可见的变更）

### PR Review 流程

1. 至少一位维护者 review 后方可合并。
2. Reviewer 可能要求修改，请及时响应并推送新的 commit。
3. 通过 review 后由维护者 squash merge 到 `main`。

## 项目结构概览

```text
gearbox/
├── actions/              # GitHub Action 定义
├── .github/workflows/    # CI/CD 与内部编排 workflow
├── docs/                 # 文档（mkdocs-material 站点源码）
├── src/gearbox/
│   ├── cli.py            # Click CLI 入口
│   ├── core/             # GitHub API 封装
│   └── agents/           # Agent 实现（audit / backlog / review / implement）
└── tests/                # 测试用例
```

详见 [CLAUDE.md](CLAUDE.md) 了解完整的架构说明与开发约定。

## 代码风格

| 规则 | 配置 |
| --- | --- |
| 行长度 | 100 字符 |
| Linter | Ruff (E, F, I, N, W) |
| Formatter | Ruff format |
| Type checker | Mypy (Python 3.10) |
| E501 忽略 | 是（由 formatter 处理） |

配置文件：`pyproject.toml` → `[tool.ruff]` 和 `[tool.mypy]`。

## 常见问题

### Q: 我应该先看哪个文件？

建议阅读顺序：

1. [README.md](README.md) — 快速了解项目
2. [CLAUDE.md](CLAUDE.md) — 开发者指南（含架构、命令、约定）
3. [docs/index.md](docs/index.md) — 完整架构文档
4. 对应模块的源码与测试

### Q: 如何调试 Agent？

```bash
# 单次审计运行（输出到指定目录）
uv run gearbox agent audit-repo --repo owner/repo --output-dir ./audit-output

# 查看 agent 日志
cat ./audit-output/logs/*.log
```

### Q: 如何添加新的扫描工具？

1. 在 `src/gearbox/agents/shared/scanner.py` 中添加工具逻辑。
2. 在 `actions/_setup/action.yml` 中添加工具安装步骤。
3. 更新文档中的扫描工具表格。
4. 编写对应测试。
