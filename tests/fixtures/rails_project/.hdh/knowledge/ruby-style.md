# ACME Ruby & Rails Conventions

## Collections

Use Enumerable — `map`, `select`, `each_with_object`. Never write a `for` loop; RuboCop's
`Style/For` is enabled and fails the build. Prefer `each_with_object({})` over `reduce` when
building a Hash, because the accumulator reads left-to-right and rubocop flags `inject` here.

When turning ingest rows into records, build with `User.new` and let ActiveRecord validations
run. Only reach for `insert_all` on bulk paths where you have already validated upstream —
it skips callbacks and validations entirely.

## Outbound HTTP

All outbound HTTP goes through `AcmeClient.connection`, which configures Faraday's retry
middleware. Direct `Faraday.new` or `Net::HTTP` calls are rejected in review — the ACME
upstream rate-limits aggressively and we need the backoff.
