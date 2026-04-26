---
name: ctx7
description: Query official library/framework documentation. Use when looking up API references, usage examples, or official best practices for a specific library or framework. Invoke when analyzing code that uses unfamiliar dependencies.
---

# ctx7 — Official Documentation Lookup

## Command

```bash
npx ctx7 docs <LIBRARY_ID> <QUERY>
```

## Common Library IDs

| Library | ID |
|---------|-----|
| React | `/reactjs/react.dev` |
| Next.js | `/vercel/next.js` |
| Vue | `/vuejs/core` |
| FastAPI | `/tiangoto/fastapi` |
| Django | `/django/django` |
| pytest | `/pytest-dev/pytest` |
| Python | `/python/cpython` |
| Rust | `/rust-lang/rust` |

Find more: `npx ctx7 library <keyword>`

## Examples

```bash
# Look up React useEffect
npx ctx7 docs /reactjs/react.dev "useEffect hook"

# Look up FastAPI router
npx ctx7 docs /tiangoto/fastapi "router"

# Search for a library
npx ctx7 library react
```

## When to Use

- Codebase uses an unfamiliar library/framework → look up its official docs
- Need to verify correct API usage
- Analyzing dependencies from pyproject.toml / package.json
