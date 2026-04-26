---
name: ts-prune
description: Find and remove unused TypeScript imports. Use when auditing TypeScript/JavaScript projects to identify dead code and clean up import statements.
---

# ts-prune — TypeScript Pruner

## Basic Usage

```bash
# Run in project root
ts-prune

# Run in specific directory
ts-prune --dir ./src

# Dry run (show what would be removed)
ts-prune --dry-run
```

## Common Options

```bash
# Output formats
ts-prune --format table   # human-readable (default)
ts-prune --format json    # JSON output
ts-prune --format csv     # CSV output

# Remove unused imports (interactive)
ts-prune --remove

# Skip specific modules
ts-prune --ignore=node_modules,dist,.next
```

## Output Fields

| Field | Description |
|-------|-------------|
| `file` | File path with unused import |
| `import` | The unused import statement |
| `type` | "import" or "type" |

## When to Use

- **TypeScript audit** — find unused imports/dead code
- Clean up `import` statements in a codebase
- Identify which modules are truly used vs. legacy code
- Compare code cleanliness metrics against benchmarks

## Examples

```bash
# JSON output for parsing
ts-prune --format json > ts-prune.json

# Dry run to see what can be cleaned
ts-prune --dry-run

# Remove unused imports (careful — backup first)
ts-prune --remove
```

## Note

ts-prune works on TypeScript projects. For JavaScript-only projects, use `depcheck` instead.
