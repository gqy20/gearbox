---
name: trivy
description: Security vulnerability scanner for containers and code. Use when auditing a repository for known CVEs, security issues in dependencies, or supply-chain risks. Supports Python, Go, Node.js, Docker images, and more.
---

# trivy — Vulnerability Scanner

## Quick Scan

```bash
# Scan a directory (e.g., a repo checkout)
trivy fs .

# Scan a Docker image
trivy image <image-name>

# Scan a GitHub repo (remote)
trivy repo --repo-ref https://github.com/owner/repo
```

## Common Options

```bash
# Output formats
trivy fs . --format table    # human-readable (default)
trivy fs . --format json    # machine-readable
trivy fs . --format cyclonedx  # SBOM format

# Severity filter
trivy fs . --severity HIGH,CRITICAL

# Security advisories
trivy fs . --security-checks vuln,config,secret
```

## When to Use

- **Initial security audit** of a repository
- Check for known CVEs in dependencies (Python pip, Go mod, npm, etc.)
- Scan Dockerfiles and container images
- Generate a security report as part of `issues.json`

## Examples

```bash
# Full scan with all checks
trivy fs . --security-checks vuln,config,secret

# Only vulnerabilities, high severity+
trivy fs . --security-checks vuln --severity HIGH,CRITICAL

# Scan a specific path
trivy fs ./src --format json -o scan.json
```
