---
name: deptry
description: Python dependency health checker. Use to audit Python projects for missing dependencies, unused imports, transitive dependencies, and other dependency-related issues.
---

# deptry — Python Dependency Checker

## Basic Usage

```bash
# Scan current directory (must have pyproject.toml or requirements.txt)
deptry .

# Scan specific package
deptry ./src/my_package

# With virtual environment
deptry . --venv .venv
```

## Common Options

```bash
# Output format
deptry . --output-format json     # JSON
deptry . --output-format table    # table (default)

# Exclude directories
deptry . --exclude .build,__pycache__,tests

# Ignore specific dependencies
deptry . --ignore numpy,pandas
```

## What It Detects

| Issue | Description |
|-------|-------------|
| **Missing dependencies** | Used in code but not in pyproject.toml/requirements.txt |
| **Unused dependencies** | In pyproject.toml but never imported |
| **Transitive deps** | Indirect dependencies that should be explicit |
| **Importable packages** | Packages importable but not in requirements |

## When to Use

- **Python dependency audit** — check if pyproject.toml/requirements.txt is accurate
- Find "phantom" dependencies (used but not declared)
- Find dead dependencies (declared but never imported)
- Compare dependency quality against benchmark projects

## Examples

```bash
# Full audit with JSON output
deptry . --output-format json -o deptry.json

# With custom venv path
deptry . --venv .venv

# Quiet mode (only issues)
deptry . --output-format json 2>/dev/null | jq '.issues'
```
