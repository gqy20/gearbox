# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Gearbox** — an AI-driven GitHub repository audit tool built on Claude Agent SDK. It analyzes target repos, discovers benchmark projects, generates capability comparison matrices, and produces actionable improvement issues.

Language: Python 3.10+ | Package manager: `uv` | CLI framework: Click | Agent SDK: `claude-agent-sdk`

## Commands

```bash
# Install dependencies
uv sync

# Run all tests
uv run pytest -v

# Run a single test file
uv run pytest tests/test_cli.py -v

# Lint (ruff: linter + formatter combined)
uv run ruff check src tests && uv run ruff format --check src tests

# Type check
uv run mypy src

# Run the CLI tool
uv run gearbox --help
```

Pre-commit hooks enforce ruff lint/format + YAML formatting on every commit.

## Architecture

```
src/gearbox/
├── cli.py              # Click-based CLI entry point (audit, publish-issues, config)
├── audit.py            # Core audit orchestration — creates Agent, runs query(), streams results
├── publish.py          # Reads issues.json → creates GitHub Issues via `gh` CLI
├── config/
│   ├── settings.py     # TOML config at ~/.config/gearbox/config.toml (env vars take priority)
│   └── mcp.py          # MCP server definitions (web-search-prime, context7) + allowed tools allowlist
└── tools/              # Custom MCP tools registered via claude_agent_sdk.tool()
    ├── profile.py      # generate_profile — analyzes local or remote repo → structured JSON profile
    ├── benchmark.py    # discover_benchmarks — scores & ranks candidate repos by language/type/stars
    ├── compare.py      # create_comparison — 15-dimension capability matrix with gap analysis
    └── issue.py        # generate_issue_content / create_issue — formats issue templates
```

### Data Flow

1. **CLI** (`cli.py`) → calls `run_audit_sync()` in `audit.py`
2. **audit.py** builds `ClaudeAgentOptions` with system prompt, MCP servers (external + custom "auditor" server), and allowed tools allowlist
3. The **Claude Agent** autonomously executes: `generate_profile` → `discover_benchmarks` → `create_comparison` → writes `issues.json`
4. **publish.py** reads `issues.json` and creates real GitHub Issues via `gh issue create`

### Key Design Decisions

- **GitHub operations use `gh` CLI subprocess calls**, not MCP github server — see `profile.py:_gh_api()`, `benchmark.py:_search_candidates_via_gh()`, `publish.py:publish_issues_from_file()`
- **Config priority**: environment variables > `~/.config/gearbox/config.toml`. Key env vars: `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_BASE_URL`, `ANTHROPIC_MODEL`, `GITHUB_TOKEN`
- **MCP servers** are defined in two places: `.mcp.json` (for local dev / Claude Code) and `config/mcp.py` (for the Agent runtime). They may differ — `mcp.py` is the authoritative source for the audit agent
- **Custom tools** use `claude_agent_sdk.tool()` decorator and return `{"content": [...], "structured_output": ...}` dicts
- **Tests mock `subprocess.run`** via `monkeypatch` for `gh` CLI calls — pattern in `test_tools.py`

## Code Style

- Ruff line length: 100
- Ruff rules: E, F, I, N, W (E501 ignored)
- Mypy strict mode enabled (`warn_return_any`, `warn_unused_configs`)
- Tests use `pytest` + `pytest-asyncio` (tools are async), CLI tests use `click.testing.CliRunner`
