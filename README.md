# cleanedweb-openapi

The OpenAPI 3.1 description of the public [CleanedWeb](https://cleanedweb.com/?utm_source=github&utm_medium=cleanedweb-openapi)
API, and the language-neutral conformance cases every CleanedWeb SDK runs in CI. CleanedWeb turns public website
collections (listings, products, jobs, articles, profiles) into maintained REST APIs that return structured records.

> **Private preview.** This repository is private and the contract may change before the first public release.
> Nothing here is published. SDKs: [cleanedweb-go](https://github.com/cleanedweb/cleanedweb-go),
> [cleanedweb-python](https://github.com/cleanedweb/cleanedweb-python), [cleanedweb-js](https://github.com/cleanedweb/cleanedweb-js).

**Pricing:** 5,000 records free once, then prepaid credit from $1 per 1,000 records delivered, no subscription.
[Pricing](https://cleanedweb.com/pricing/?utm_source=github&utm_medium=cleanedweb-openapi)

## What is here

| Path | What |
| --- | --- |
| [`openapi.yaml`](openapi.yaml) | The curated customer-facing contract: public catalog, catalog runs, runs, source APIs, schedules. Admin, control, pipeline and builder routes are not in it. |
| [`tests/cases/*.json`](tests) | Conformance cases as data: request, mocked responses, expected SDK outcome. Each SDK runs them. See [`tests/README.md`](tests/README.md). |
| [`scripts/validate_conformance.py`](scripts/validate_conformance.py) | Checks every case against `openapi.yaml` (routes, statuses, request and response bodies). |
| [`scripts/check_drift.py`](scripts/check_drift.py) | Diffs the curated paths and methods against the engine's FastAPI document, built from an engine checkout (the API origin no longer serves it). |
| `FINDINGS.md` | Every place the docs, the engine and the live service disagree, with evidence. |

## The origin

Every `/v1/` route is served by **`https://api.cleanedweb.com`**. Run requests sent to `broker.cleanedweb.com`
do not work: that host is the acquisition broker, has no run routes and refuses customer keys. No-key catalog reads are
also served on `https://app.cleanedweb.com/api/catalog/` and, as static files, on `https://cleanedweb.com/catalog/`.
`openapi.yaml` marks these on the paths that use them.

## Contract in one page

- `Authorization: Bearer <key>`. Scopes `read`, `run` and `results`; each operation lists what opens it
  (`x-scopes-any-of`). Catalog reads need no key.
- Every run needs an `Idempotency-Key`. `200` returns the final body, `202` means the run goes on: read the result with
  the **same key** after `Retry-After`, never POST again. A failed run carries `error_code` `run_failed` or
  `failed_run_replayed` and is final for its key; use a new key to run again.
- `429` `engine_request_limited` and `502/503/504` without that marker are retried with the same key.
- Cursor pagination on `/v1/runs` and `/v1/runs/{id}/items`; offset pagination on the catalog list.

## Use it

```bash
pip install -r requirements.txt            # pyyaml, jsonschema, referencing
npx --yes @redocly/cli@latest lint openapi.yaml
python scripts/validate_conformance.py     # cases vs. spec
python scripts/check_drift.py --engine-dir ../cleanedweb-com --strict   # spec vs. the engine checkout
python scripts/check_drift.py --live-file tests/fixtures/engine-curated-routes.json   # offline snapshot
```

Generate a client from `openapi.yaml` with any OpenAPI 3.1 tool, or hand-write one against it as the CleanedWeb SDKs do.
An SDK must pass the conformance cases: copy `tests/cases` and `tests/case.schema.json` into the SDK (the SDKs sync them
with a script, since this repository is private) and run each case against a mock server.

## CI

`.github/workflows/ci.yml` lints the spec with Redocly, validates the conformance cases against it and runs the drift
script offline against `tests/fixtures/engine-curated-routes.json`: the engine's routes that `openapi.yaml` documents,
with their query parameters, and nothing else. The engine repository is private and `api.cleanedweb.com` no longer
serves its FastAPI document, so the full comparison runs locally with `--engine-dir`. It also reports engine routes
that are neither documented here nor listed as internal; that list names internal routes, so it lives in the engine
checkout (`docs/customer-api-internal-routes.txt`). When the engine changes a customer route, run it and refresh the
fixture:

```bash
python scripts/check_drift.py --engine-dir ../cleanedweb-com --strict --write-snapshot tests/fixtures/engine-curated-routes.json
```

## Changing the contract

Change `openapi.yaml` and the cases together, keep `operationId`s stable (SDK method names derive from them) and add
a case for new behaviour. Record disagreements with the docs or the engine in `FINDINGS.md`.

## License

MIT. See [LICENSE](LICENSE). [CleanedWeb](https://cleanedweb.com/?utm_source=github&utm_medium=cleanedweb-openapi) ·
[Docs](https://cleanedweb.com/docs/?utm_source=github&utm_medium=cleanedweb-openapi) ·
[Run a catalog API](https://cleanedweb.com/docs/run-catalog-api/?utm_source=github&utm_medium=cleanedweb-openapi)
