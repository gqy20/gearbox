---
name: govulncheck
description: Official Go vulnerability scanner by the Go team. Use when auditing Go repositories to check for known vulnerabilities in dependencies using the Go vulnerability database.
---

# govulncheck — Go Vulnerability Scanner

## Basic Usage

```bash
# Scan current Go module (must be in a module directory)
govulncheck ./...

# Scan a specific package
govulncheck ./internal/...
```

## Common Options

```bash
# Output format
govulncheck ./...              # human-readable (default)
govulncheck ./... -json         # JSON output
govulncheck ./... -mode=binary # scan compiled binary

# Full analysis (slower but more thorough)
govulncheck ./... -full
```

## What It Detects

- Vulnerabilities in direct and indirect Go dependencies
- Uses the official **Go Vulnerability Database** (govulncheck.golang.org)
- Only scans code within `$GOPATH` or module cache

## When to Use

- **Go dependency audit** — mandatory for Go projects
- Check `go.mod` / `go.sum` for known CVEs
- Compare vulnerability count against benchmark Go projects
- Generate security findings for `issues.json`

## Examples

```bash
# JSON output for parsing
govulncheck ./... -json > govulncheck.json

# Summary only
govulncheck ./... 2>&1 | grep -E "^(Found|No vulnerabilities)"

# Scan specific packages
govulncheck ./cmd/... ./internal/...
```

## Prerequisites

govulncheck requires the Go toolchain. Download and install from https://go.dev/dl/
