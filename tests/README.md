# SDK conformance cases

Language-neutral cases that every CleanedWeb SDK runs in CI. A case describes one SDK call against a mock server:
the calls the SDK must make, what the mock answers, and what the SDK must return or raise. `scripts/validate_conformance.py`
checks every case against `../openapi.yaml`, so the data cannot drift from the contract.

Files: `cases/*.json` (each `{"group", "cases": [...]}`), `case.schema.json` (the format),
`fixtures/engine-curated-routes.json` (input of the offline drift check: the engine's routes that `openapi.yaml`
documents, written by `scripts/check_drift.py --write-snapshot`).

## Running a case

1. Start a mock HTTP server. Build the client with `client.api_key`, `client.max_retries` and
   `client.max_retry_delay_seconds`, `base_url` set to the mock, and an injected **fake sleep** that records the
   requested durations and returns at once.
2. Call the SDK operation named by `operation` with `args` (names are snake_case; map them to your language).
3. For each request the SDK sends, in order, match it against `exchanges[n].request` and answer with
   `exchanges[n].response` (or fail the connection for `network_error`). The SDK must send exactly the listed requests:
   no more, no fewer. A case with no exchanges sends nothing.
4. Compare the outcome with `expect`.

### Request matching

- `method` and `path` are exact. `query` is a map of exact string values, and no other query parameter may be present.
- `headers`: each listed header must be present (names are case-insensitive) with that value. A `null` value means the
  header must be absent. Other headers are not checked.
- `$key`: the idempotency key of the call. It is `args.idempotency_key` when given; otherwise the SDK generated one: take
  it from the first request's `Idempotency-Key` header, and require that it matches `^[A-Za-z0-9._:-]{1,200}$`
  (`expect.generated_key` is then true) and is equal in every later request and in the returned result.
- `body` is compared as JSON (deep equality). Omit means not checked. A `GET` or `DELETE` sends no body.
- An exchange marked `spec_invalid_request` carries a request that is deliberately outside the spec to provoke a
  server-side refusal; the SDK must send it as given.

### Outcome

`expect.sleeps` lists the durations the SDK asked its sleep function for, in order.

`expect.result` (run results): any subset of `complete`, `usable`, `status_code`, `idempotency_key`, `run_id`, `record_count`,
`stop_reason`, `units_charged`, `version`, `rerouted`, `deprecation`, `sunset`. `complete` is true for a `200`.
`usable` is true when `complete` and `summary.status` is `completed` or `bounded` and `summary.within_scope_passed` is true
and `run.status`, when present, is `finished` (an aborted run is never usable; `FINDINGS.md`, finding 16).

`expect.run` (run object): `run_id`, `status`, `stop_reason`, `ended` (status is `finished`, `failed` or `aborted`),
`items` (`progress.items`), `units_charged`, `abort_requested`, `replayed` (the `Idempotent-Replayed` header).
Also `expect.run_ids`, `expect.items` (records in order), `expect.schedule`, `expect.schedules`, `expect.limit`,
`expect.deleted`, `expect.events` (stream events in order) and `expect.data` (parsed JSON; every listed key must be present with an
equal value, recursively, extra keys allowed).

`expect.error`: the SDK must raise an error of `kind` and every other listed field must hold:

| `kind` | Raised for |
| --- | --- |
| `missing_api_key` | a call that needs a key made without one; nothing is sent |
| `invalid_argument` | a bad argument (key grammar, `max_items < 1`, both version selectors); nothing is sent |
| `connection` | no answer arrived (reset, timeout, DNS); `unsure` is true; carries the idempotency key |
| `authentication` | 401 |
| `permission_denied` | 403 |
| `not_found` | 404 |
| `version_not_found` | 404 `catalog_version_not_found`; `available_versions` |
| `insufficient_credit` | 402 or code `insufficient_units`; `required`, `available` (decimal strings) |
| `usage_budget_exceeded` | 409 `usage_budget_exceeded` |
| `idempotency_conflict` | 409 `delivery_identity_conflict` or `schedule_idempotency_conflict` |
| `version_conflict` | 409 with a code starting `builder_definition_version` |
| `invalid_request` | 400, 415, 422 |
| `rate_limited` | 429 |
| `server` | 5xx |
| `redirect` | 3xx: the request went to the wrong origin and nothing ran; redirects are never followed |
| `api_status` | any other error status |

Fields: `status_code`, `code` (`detail.code`), `run_failed`, `replayed`, `unsure`, `run_id`, `error_code`
(`run_failed` or `failed_run_replayed`), `retry_after` (seconds), `idempotency_key`.

Classification order: status first (as the table), and a **failed-run marker** (`detail.error_code` is `run_failed` or
`failed_run_replayed`) sets `run_failed` whatever the status. `unsure` is true for a status of 408 or at least 500, and
for `connection`, unless the marker is present.

## Behavioural rules the cases pin

- **Idempotency.** A run call sends `Idempotency-Key` (given or generated, UUIDv4) and returns it. A key outside
  1 to 200 of `[A-Za-z0-9._:-]` is refused before any request.
- **202.** The POST is never resent. Wait, then `GET` the result route with the same key (catalog) or the run (`/v1/runs/{id}/result`
  for sources and runs). The wait is `Retry-After`, else `run.poll_after_seconds`, else 30, clamped to 1 to 60. A 409
  `result_not_available`, `result_not_complete` or `result_not_running` while polling is pending: wait for its `Retry-After`
  and read again. With `wait=false` the POST body carries `wait_seconds: 0` and the 202 is returned as an incomplete result.
  With `poll_timeout`, return the incomplete result instead of a wait that would pass the deadline.
- **Retries.** A `429`, `502`, `503` or `504` without a failed-run marker is retried up to `max_retries` times with the same key
  and request. The wait is `Retry-After`, else `detail.retry_after_seconds`/`retryAfterSeconds`/`retry_after`, else
  `0.5 * 2^attempt`, capped at `max_retry_delay_seconds`. A server-asked wait longer than the cap is not waited for: the
  error is raised with `retry_after`. A transport failure is not retried; the error carries the key so the caller can read the result.
- **A failed run is final for its key.** It is never retried, whatever the status.
- **Pagination.** Follow `next_cursor` until it is null. Without `follow`, `runs.items` also stops at an empty page.
- **Schedules.** `create` sends its key as the `Idempotency-Key` header and not in the body; `replayed` comes from
  the `Idempotent-Replayed: true` header.

## Adding a case

Add it to the group file, keep ids unique and snake_case, and run `python scripts/validate_conformance.py` from the repo
root. Cases that record a surprising behaviour carry a `spec_note` that points at `FINDINGS.md`.
