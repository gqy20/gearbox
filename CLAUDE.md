# CLAUDE.md

This file guides Claude Code and other coding agents when working in this repository.

## Project Overview

**Gearbox** is an AI-driven GitHub automation system. The development repository owns source code, tests, docs, internal workflows, and the release process that exports the Marketplace repository `gqy20/gearbox-action`.

Language: Python 3.10+ | Package manager: `uv` | CLI framework: Click | Agent SDK: `claude-agent-sdk`

## Commands

```bash
# Install dependencies
uv sync

# Run checks
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy src
uv run pytest -q

# Run a focused test file
uv run pytest tests/test_audit.py -q

# Run the CLI
uv run gearbox --help

# Package the Marketplace action
uv run gearbox package-marketplace --output-dir ./dist/gearbox-action

# Preview release notes from CHANGELOG.md
uv run gearbox release-notes --version v1.1.2
```

Pre-commit uses `uv` and runs ruff, ruff format, mypy, and YAML checks:

```bash
uvx pre-commit install
uvx pre-commit run --all-files
```

## Architecture

```text
actions/
├── main/action.yml       # Router; exported as Marketplace root action.yml
├── _setup/action.yml     # uv, Python, gh, and scanner setup
├── audit/action.yml      # Audit action
├── triage/action.yml     # Issue triage action
├── review/action.yml     # PR review action
├── implement/action.yml  # Implementation action
└── publish/action.yml    # Publish issues.json to GitHub Issues

.github/workflows/
├── ci.yml                # ruff / mypy / pytest
├── audit.yml             # Verified internal audit matrix orchestration
├── triage.yml            # Issue triage entrypoint
├── review.yml            # PR review entrypoint
├── reusable-*.yml        # Advanced reusable workflow templates
└── release-marketplace.yml

src/gearbox/
├── cli.py                # Click CLI
├── core/gh.py            # GitHub API wrapper
├── release.py            # Marketplace bundle and release notes helpers
└── agents/
    ├── audit.py
    ├── triage.py
    ├── review.py
    ├── implement.py
    └── shared/
        ├── runtime.py    # Claude Agent SDK runtime and streaming logs
        ├── structured.py # Structured output extraction
        ├── scanner.py    # Cloned-repository static scanner
        ├── artifacts.py
        └── selection.py
```

## Current Audit Flow

1. `actions/audit/action.yml` prepares environment variables and calls `uv run gearbox agent audit-repo`.
2. `run_audit()` always clones the target repository into a temporary directory.
3. The scanner runs against that cloned directory and records tool statuses.
4. The prompt includes the local clone path, scan summary, target repo, and benchmark repos.
5. `ClaudeAgentOptions.cwd` points at the clone directory so SDK tool calls inspect the same code that was scanned.
6. Structured output is required; missing structured output is treated as an error rather than silently falling back.
7. Artifacts such as `issues.json`, `summary.md`, and `result.json` are written for workflow upload.

## Workflow Notes

- Marketplace users should normally call `gqy20/gearbox-action@v1`.
- The development repository's `audit.yml` uses inline GitHub Actions matrix orchestration because that path is currently verified.
- `reusable-*.yml` files remain as advanced templates, but avoid assuming local reusable workflow calls are the primary internal path.
- `release-marketplace.yml` exports `actions/`, `src/`, `pyproject.toml`, `uv.lock`, `CHANGELOG.md`, and a generated Marketplace README.
- Version release notes come from `CHANGELOG.md`; add the `vX.Y.Z` section before tagging.

## Logging And Observability

Shared SDK logging lives in `src/gearbox/agents/shared/runtime.py`.

The audit logs should expose:

- runtime config, including model, base URL, max turns, and cwd
- clone target and clone directory
- scanner counts and tool statuses
- SDK stream lifecycle events
- tool-use events with useful parameters, such as `Read path=...` and `Bash command=...`
- token usage returned by the SDK

Avoid token-by-token thinking logs. Prefer concise event-level logs that show what the agent is doing without flooding GitHub Actions output.

## Code Style

- Ruff line length: 100
- Ruff rules: E, F, I, N, W with E501 ignored
- Mypy is enabled for `src`
- Tests use `pytest`
- Prefer `uv run ...` for Python tooling
- Use `apply_patch` for manual edits
