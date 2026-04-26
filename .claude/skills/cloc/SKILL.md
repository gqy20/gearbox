---
name: cloc
description: Count lines of code, blank lines, comment lines, and files by language. Use when quickly assessing the size, complexity, and composition of a repository during an audit.
---

# cloc — Code Line Counter

## Basic Usage

```bash
# Count all code in current directory
cloc .

# Count specific directory
cloc ./src

# Count multiple repos
cloc /path/to/repo1 /path/to/repo2
```

## Common Options

```bash
# Output formats
cloc . --csv              # CSV output
cloc . --json             # JSON output
cloc . --yaml             # YAML output

# Exclude directories
cloc . --exclude-dir=node_modules,.git,build,dist

# Show file-level details
cloc . --by-file

# Hide comments/blanks (code only)
cloc . --code-only
```

## When to Use

- **Initial assessment** of a repository's size and language distribution
- Compare repository composition against benchmarks
- Identify areas with high code volume (potential maintenance burden)
- Fill in `profile.json` with language statistics

## Examples

```bash
# JSON output for parsing
cloc . --json --out=cloc.json

# Exclude common non-source dirs
cloc . --exclude-dir=node_modules,.venv,__pycache__,vendor,.git

# Summary only (no per-file details)
cloc . --quiet
```

## Output Fields

| Field | Description |
|-------|-------------|
| `Language` | Programming language |
| `files` | Number of files |
| `blank` | Blank lines |
| `comment` | Comment lines |
| `code` | Actual code lines |
| `SUM` | Totals row |
