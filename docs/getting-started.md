# 安装与配置

## 前置要求

- **Python** >= 3.10
- **[uv](https://docs.astral.sh/uv/)** — 项目包管理器
- **[gh](https://cli.github.com/)** — GitHub CLI（可选，用于调试 workflow）

## 安装

```bash
# 克隆仓库
git clone https://github.com/gqy20/gearbox.git
cd gearbox

# 同步依赖
uv sync
```

## 配置 API Key

```bash
# 设置 Anthropic API Key（或兼容网关的 Key）
uv run gearbox config set anthropic-api-key YOUR_KEY

# （可选）设置自定义 Base URL
uv run gearbox config set anthropic-base-url https://your-gateway.example.com

# 查看当前配置
uv run gearbox config list
```

## 验证安装

```bash
uv run gearbox --help
```

输出应显示所有可用的命令和子命令。
