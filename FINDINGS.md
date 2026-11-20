# Findings

Every place the CleanedWeb documentation, the engine and the live service disagree, found while
writing `openapi.yaml`. Engine paths are relative to `cleanedweb-com/cleanedweb/` (checkout
`3ae0dacbb0`; production release `22f7252a87`). Doc paths are relative to
`cleanedweb-site/docs/content/`. Checked 2026-11-20. The spec and the conformance cases cite these
by number.

**Status 2026-11-20:** findings 2, 5 and 10 are fixed in the engine at `577f32222e`, released and live:
`/openapi.json` and `/docs` answer `404`, and source health answers `200` to a `read` key (live run below).
Findings 1, 3, 4, 6, 7, 8, 9 and 11 are fixed in the site docs and are live. The SDKs default to
`https://api.cleanedweb.com`. Findings 12 to 16 come from the live runs and are documented in `openapi.yaml`.

## 1. The API origin is `https://api.cleanedweb.com`, not the broker

The docs and the first SDKs send runs to `https://broker.cleanedweb.com`. They should use
`https://api.cleanedweb.com` for everything.

- The broker mounts only build and source-version routes plus its own fetch and control routes
  (`broker/builder_routes.py:134`). `/v1/runs`, `/v1/schedules` and `/v1/catalog/public` live in
  the standalone builder (`builder/server.py:687,691`, `builder/catalog_routes.py:196-336`).
- The broker refuses scoped credentials (`broker/server.py:662`,
  `ScopedCredentialBoundary(allow_scoped=False)`). Every customer key is scoped, so a real key gets
  `403` there (`builder/access.py:480-509`).
- `Location` and `links` are relative (`/v1/runs/{id}`, `builder/runs/routes.py:350,498`), so they
  resolve only on the API origin.
- The console adds `api_origin: https://api.cleanedweb.com` to every contract
  (`cleanedweb_portal/catalog_routes.py:168`); the site's `index.json` and `contract.json` agree.
- A `401` proves nothing about whether a route exists. The broker answers `404` without an
  `Authorization` header and `401` for every path with one, `/openapi.json` and `/ready` included.
  The API origin answers `401` for any `/v1/` path, `/v1/nonexistent` included.
- The API origin also serves the no-key catalog reads (`/v1/catalog/public/apis`, detail,
  contract), so one origin is enough.

Docs to change: `reference/run-catalog-api.md:9,18,22,110`, `reference/catalog-apis.md:78`,
`getting-started/introduction.md:15`, `llms.txt:47`, `auth.md:11`, and the site scripts
`scripts/catalog-fields.mjs:8` and `scripts/catalog-openapi.mjs:340`.

## 2. A `run`-only key cannot read source run results

`reference/run-api.md:140` says the GET run routes accept `run` or `results`, and `errors.md:64`
and `idempotency.md:44` tell callers to recover through `/v1/runs/{id}/result`. But
`builder/access.py:466-470` skips `run` for any path ending in `/result`. `authorize_request` with a
customer key of each scope:

| Route | `run` | `read` | `results` |
| --- | --- | --- | --- |
| `GET /v1/runs/{id}/result` | 403 | 403 | ok |
| `GET /v1/sources/{s}/runs/{id}/result` | 403 | 403 | ok |
| `GET /v1/sources/{s}/runs/{id}` | 403 | 403 | ok |
| catalog `/result` | ok | ok | 403 |
| catalog `/filters` | ok | ok | 403 |

A source run that answers `202` is charged and keeps running, but a `run`-only key cannot read its
result. Derived from `authorize_request`; not yet confirmed with a production key.

## 3. Schedules exist; the docs say they do not

`guides/scheduled-runs.md:3` says there is no native scheduling endpoint. The engine serves
`/v1/schedules` (`builder/agent_schedule_routes.py`, `builder/server.py:689-691`), the live spec
lists it, and `guides/mcp.md:106` documents the MCP equivalents.

## 4. Source connection details carry no origin

`reference/run-api.md:3,25` says to copy the API origin from the connection details, but
`GET /v1/sources/{id}/connection` (`builder/onboarding.py:227-262`) returns paths and
`$CLEANEDWEB_API_BASE` in its curl text, not an origin.

## 5. `GET /v1/sources/{id}/health` is unreachable with any customer scope

It is listed under no scope in `access.scoped_routes`, so `run`, `read`, `results`, and all three
together, get `403`.

## 6. The documented 409 `result_not_*` codes are no longer produced

`errors.md:49` documents them, but the current run routes answer `202` while a run is going
(`builder/runs/routes.py:344-353`). The codes survive only in the older `delivered_results.py`.
SDK handling for them is harmless dead code.

## 7. Error shapes differ

- The wait appears as `retryAfterSeconds` (source errors), `retry_after_seconds`
  (`engine_request_limited`, `builder/server.py:174-185`) and `run.error.retry_after`. Only the
  `Retry-After` header is stable.
- `engine_request_limited` is in no customer doc.

## 8. Catalog list validation differs by origin

`reference/catalog-apis.md:18` documents `invalid_catalog_query`, which only the console origin
returns. The API origin returns a FastAPI validation list for `limit=0` and ignores unknown
parameters.

## 9. The site's catalog `openapi.json` is wrong and incomplete

It puts runs on the broker, `scripts/catalog-openapi.mjs:175` says `api_origin` is an empty string
(the console answers the API origin), and it has no runs, schedules or source routes. This spec
can replace it.

## 10. The live FastAPI spec is public and nearly schema-free

`https://api.cleanedweb.com/openapi.json` is served without a credential and lists 143 paths,
including admin, control and pipeline-suite routes. Most response schemas are `{}`.

## 11. Smaller mismatches

- `next_cursor` is a string or null; the docs say it starts at `0`.
- `Retry-After` and `poll_after_seconds` on a `202` are always 30.
- `Idempotent-Replayed` is sent only by `/runs` and schedules.
- `required` and `available` on a `402` are decimal strings.
- `stop_reason` is an open set; the store keeps `page_limit` and derives the public value.
- `/filters` and `/v1/credential` are reachable but undocumented.

## 12. `/filters` errors use a different envelope

An endpoint without category filters answers `404`
`{"error": {"code": "category_filters_unavailable", "details": {"reason": "no_category_filters_evidence"}, "message": ...}}`;
every other route wraps errors in `detail`. SDKs that read only `detail` lose the code. The same envelope carries
a `category` the site does not know (`404` `category_filters_unavailable`, reason `filter_list_not_found`, the message
still says the API has no category filters) and a `filters` value that is not a JSON object (`422` `filters_invalid`).

## 13. A refused run input is a failed run, not a validation error

An unknown input field answers `422` whose `detail` is the failed-run marker (`error_code: run_failed`,
`run_id`, `retryable: false`, `classification: source_input_invalid`, `reason: input_invalid`,
`constraint: additionalProperties`) plus a `Location` header. A failed run is recorded and nothing is charged.
The docs listed `source_input_invalid` as a `detail.code`. The Python, JS and Go SDKs already raise the
failed-run error for it.

## 14. A malformed run or schedule id answers `403`

`GET /v1/runs/notahexid` and `GET /v1/schedules/notanid` answer `403`
`Customer credential cannot access this route`, not `404` or `422`: the scope patterns only match 32 hex
characters, so the path is no customer route at all.

## 15. Smaller differences seen live

- `GET /v1/runs/{id}/result` has no top-level `version`; the catalog `/result` has one.
- Schedules carry `version` (pinned major) and `last_run_rerouted` on catalog schedules.
- Every response carries `Cache-Control: no-store`.
- A finished, bounded run read through `getSourceRun` reports `run.outcome: partial` and
  `recovery.state: unconfirmed`.

## 16. An aborted run's result reads as usable

Aborting a queued run answers `200` at once with `status: aborted` and `units_charged: 0` (not `202`). Its
`GET /v1/runs/{id}/result` then answers `200` with no records and `summary.status: bounded`,
`summary.within_scope_passed: true`: the pair the docs and the SDKs treat as usable. A caller that checks only the
summary takes an empty, aborted run for a complete bounded one.

**Fixed:** engine `65bdf2c894` answers an aborted run with `summary.status: partial` and
`within_scope_passed: false` (the published contract allows `partial` only with `false`); live once released.
The Python, JS and Go SDKs, the n8n node and the Action also require `run.status: finished` when the body
carries a run (case `runs_result_aborted_is_not_usable`).

## Live run 2026-11-20

One small run (RubyGems gem search, `max_items` 3) through each client on a customer key with the `read`,
`run` and `results` scopes: Python, JS and Go SDKs and the n8n node got `202` then `200` from `/result`
after `Retry-After: 30`; the GitHub Action got `200` directly. All parsed the records, items pages
(`X-Next-Cursor`), run reads and run lists as specified, and never resent the run while polling. Free errors
observed: `401` (`{"detail": "Unauthorized"}`), `404` (`catalog_not_found`, `Run not found`,
`catalog_delivery_not_found`, `schedule_not_found`), `422` (`run_option_invalid`, `idempotency_key_required`,
`run_items_query_invalid`, `run_nulls_invalid`, `run_list_query_invalid`), `409`
(`delivery_identity_conflict` for a reused Idempotency-Key with another body, charged nothing; the same body
replays `200`; `schedule_idempotency_conflict`, `schedule_not_paused`). Schedule create (`201`), replay
(`200`, `Idempotent-Replayed: true`), pause, delete and get-after-delete (`404`) match the spec.

Second pass, same day and key (raw captures `s_*`, `a_*`, `f*` in the run's operations folder): the account's own
source `generated_b4994166c5cfc78e99c910e7` with `max_items` 3.

- `runSource`: `200` with 3 records, `run.stop_reason: max_items`, `units_charged: 3`, `delivery`, `Location`.
- `streamSourceRun`: `200` `application/x-ndjson` with `Location`; lines `progress` (run `status: queued`),
  `records` (3), `done` (`summary`, `run`, `delivery`, `elapsedMs`), `sequence` 1 to 3. 3 Units.
- `startSourceRun`: `202` with the run, `poll_after_seconds: 30`. `abortRun` while queued: `200` `aborted`, nothing
  charged (finding 16); again: `200`, unchanged. A run that had finished: `200` `finished`. An unknown run: `404`
  `Run not found`. The window between `queued` and `finished` was under a second, so a `202` abort was not seen.
- `/filters` on Tori.fi (`generated_59d3c28862b88d7b702b71de_search`): `200` for describe, `search` and `category`;
  `404` for an unknown category and `422` for bad `filters` JSON, both in the `error` envelope (finding 12); `401`
  without a key.

Still not observed: `402` and `429` (only by draining credit or flooding production), `5xx`, a `202` abort, and
finding 2 with a key that has `run` but not `results` (needs a new key).
