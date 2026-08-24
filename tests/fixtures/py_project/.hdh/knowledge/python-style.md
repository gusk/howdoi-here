# ACME Python Conventions

## Collections

Use list comprehensions, never `map()` with a lambda. Our ruff config enables C417,
which flags `map(lambda ...)` at CI time. A comprehension is also faster for the
small-to-medium row counts our ingest pipeline sees.

For row-to-model conversion specifically, go through `pydantic.BaseModel.model_validate`
rather than constructing dataclasses by hand — it gives us validation errors with field
paths, which our on-call runbook depends on.

## Outbound HTTP

All outbound HTTP must go through `src/retry.with_retry`. Direct `httpx` calls will be
rejected in review — we need the backoff for the ACME upstream, which rate-limits hard.
