# demo-taskboard-api

Task API

Owned by @ika100.

## Quick start

```bash
devbox shell                  # enter the dev environment
devbox run quality            # ruff + mypy
devbox run test               # pytest with coverage
devbox run -- uv run uvicorn demo_taskboard_api.main:app --reload --port 8080
```

Then `curl http://localhost:8080/ping`.

## Conventions

- Config from environment variables only
- `/health` (liveness) and `/ready` (readiness) on every HTTP service
- Structured JSON logging
- `devbox run <script>` is the only sanctioned entry point for tooling

See `CLAUDE.md` for the full agent workflow and `devbox.json` for the canonical recipes.

## Deploy

| Target | Command |
|---|---|
| Staging / prod | Open a PR in the platform gitops repo or `/instance:promote demo-taskboard-api --to <env>` |

Image: `ghcr.io/ika100/demo-taskboard-api` — built and tagged automatically by CI.
