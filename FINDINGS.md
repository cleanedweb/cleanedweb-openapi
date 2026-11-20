# Findings

Every place the CleanedWeb documentation, the engine and the live service disagree, found while
writing `openapi.yaml`. Engine paths are relative to `cleanedweb-com/cleanedweb/` (checkout
`3ae0dacbb0`; production release `22f7252a87`). Doc paths are relative to
`cleanedweb-site/docs/content/`. Checked 2026-11-20. The spec and the conformance cases cite these
by number.

**Status 2026-11-20:** findings 2, 5 and 10 are fixed in the engine at `577f32222e` (live after the next
engine release). Findings 1, 3, 4, 6, 7, 8, 9 and 11 are fixed in the site docs and are live. The SDKs default
to `https://api.cleanedweb.com`.

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

## Needs a real API key

- Confirm finding 2 with a production `run`-only key.
- Exact `202` and `200` bodies and headers of a real run; real `402`, `409` and `429` bodies.
- Schedule routes, `getSourceRun`, `getSourceVersionContract`, `getSourceConnection`,
  `listSourceVersions`, `/filters`, and a real `/stream` run.
