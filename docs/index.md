# Repo Auditor

`repo-auditor` 是一个基于 Claude Agent SDK 的仓库审计原型工具。

当前版本重点在于打通以下链路：

- CLI 调用入口
- 配置读写
- Claude Agent 调度
- GitHub Actions 集成骨架

核心分析能力仍在完善中，因此当前更适合原型验证与内部迭代，不建议视为已完成的正式审计产品。

## 当前实现范围

已实现：

- `audit` 命令
- `publish-issues` 命令
- `config list` / `config set` / `config path`
- Agent 主流程与自定义工具注册
- workflow 产物上传和基于 `issues.json` 的 issue 创建流程

未完成或仍为占位实现：

- 真实仓库画像生成
- 真实 benchmark 自动发现
- 基于证据的能力对比矩阵
- 对审计输出的严格 schema 校验

## 安装

```bash
uv sync
```

## 配置

执行审计前，需要提供 Anthropic 认证信息。

方式一：配置文件

```bash
uv run repo-auditor config set anthropic-api-key YOUR_KEY
uv run repo-auditor config set anthropic-model glm-5.1
```

方式二：环境变量

```bash
set ANTHROPIC_AUTH_TOKEN=YOUR_KEY
```

可选环境变量：

- `ANTHROPIC_AUTH_TOKEN`
- `ANTHROPIC_API_KEY`
- `ANTHROPIC_BASE_URL`
- `ANTHROPIC_MODEL`
- `GITHUB_TOKEN`

## 使用

```bash
uv run repo-auditor audit --repo owner/repo
uv run repo-auditor audit --repo owner/repo --benchmarks click/click,tiangolo/typer
uv run repo-auditor audit --repo . --output ./audit-output
uv run repo-auditor publish-issues --input ./audit-output/issues.json
```

查看命令帮助：

```bash
uv run repo-auditor --help
uv run repo-auditor audit --help
uv run repo-auditor config --help
```

## 输出

Agent 预期会在输出目录中生成以下文件：

```text
audit-output/
  profile.json
  comparison.md
  issues.json
```

注意：当前版本对这些文件的生成仍主要依赖 Agent 行为，不保证每次运行都完全满足格式要求。

## 开发状态

如果要把项目推进到最小可用版本，优先级建议如下：

1. 实现 `tools/profile.py` 的真实仓库分析
2. 实现 `tools/compare.py` 的真实能力判断
3. 实现 `tools/benchmark.py` 的真实 GitHub 搜索
4. 为输出文件增加 schema 校验与失败兜底
5. 增加端到端测试
