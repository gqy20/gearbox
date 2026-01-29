"""MCP 服务器配置"""

from .settings import get_anthropic_api_key

# MCP 服务器配置（移除 GitHub MCP，使用 gh 命令代替）
MCP_SERVERS = {
    "web-search-prime": {
        "type": "http",
        "url": "https://open.bigmodel.cn/api/mcp/web_search_prime/mcp",
        "headers": {
            "Authorization": f"Bearer {get_anthropic_api_key() or ''}"
        },
    },
    "context7": {
        "type": "http",
        "url": "https://open.bigmodel.cn/api/mcp/context7/mcp",
        "headers": {
            "Authorization": f"Bearer {get_anthropic_api_key() or ''}"
        },
    },
}


# 允许的工具列表
ALLOWED_TOOLS = [
    "Read",
    "Write",
    "Edit",
    "Glob",
    "Grep",
    "Bash",  # 用于执行 gh 命令
    "mcp__web_search_prime__*",
    "mcp__context7__*",
]
