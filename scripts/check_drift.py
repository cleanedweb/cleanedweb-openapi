#!/usr/bin/env python3
"""Compare openapi.yaml with the engine's FastAPI document.

The API origin no longer serves /openapi.json (engine 577f32222e), so the document is built from an
engine checkout: the script runs the engine's own Python to call create_app().openapi().

    python scripts/check_drift.py --engine-dir ../cleanedweb-com   # build the document from the engine
    python scripts/check_drift.py --live-file x.json               # compare with a saved document
    python scripts/check_drift.py --url URL                        # fetch a document that is still served
    add --strict to fail on unclassified engine routes as well
    add --write-snapshot FILE to save the curated part of the engine document (the CI fixture)

Reports, for the paths this repository serves from the API origin:

* MISSING   a curated method and path the engine document does not have (exit 1),
* PARAMS    a query parameter the engine document declares and openapi.yaml lacks (exit 1). A parameter only
  openapi.yaml documents is a note: several run routes read their query themselves and declare nothing,
* UNCLASSIFIED  a live route that is neither curated nor listed as internal (a new route: decide whether it is
  public; exit 1 only with --strict). The internal-route list names routes that are not public, so it lives in
  the engine checkout (docs/customer-api-internal-routes.txt, the default with --engine-dir) or comes from
  --internal-routes; without one, unclassified routes are not checked,
* a count of curated routes that are live.

Paths under another origin (the console's /api/catalog reads and the catalog site files) are not in the
live document and are skipped. Needs PyYAML:  pip install pyyaml
Exit codes: 0 no drift, 1 drift, 2 the engine document could not be read.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
ENGINE_DUMP = (
    "import json, sys, warnings; warnings.simplefilter('ignore');"
    "from cleanedweb.builder.server import create_app;"
    "json.dump(create_app().openapi(), sys.stdout)"
)


def engine_document(engine_dir: str) -> dict:
    root = Path(engine_dir).resolve()
    python = root / ".venv" / "bin" / "python"
    if not python.exists():
        raise FileNotFoundError(f"{python} not found; create the engine's .venv first")
    out = subprocess.run(
        [str(python), "-c", ENGINE_DUMP], cwd=root, capture_output=True, text=True, check=True,
        env={"PYTHONDONTWRITEBYTECODE": "1", "PATH": "/usr/bin:/bin"},
    )
    return json.loads(out.stdout)
METHODS = {"get", "post", "put", "delete", "patch"}


def norm(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "{}", path)


def curated_routes(spec: dict) -> dict[tuple[str, str], set[str]]:
    routes: dict[tuple[str, str], set[str]] = {}
    for path, item in spec["paths"].items():
        if "servers" in item:  # another origin
            continue
        for method, op in item.items():
            if method in METHODS:
                names = set()
                for param in op.get("parameters") or []:
                    if "$ref" in param:
                        param = spec["components"]["parameters"][param["$ref"].split("/")[-1]]
                    if param["in"] == "query":
                        names.add(param["name"])
                routes[(method.upper(), norm(path))] = names
    return routes


def live_routes(doc: dict) -> dict[tuple[str, str], set[str]]:
    routes: dict[tuple[str, str], set[str]] = {}
    for path, item in doc["paths"].items():
        for method, op in item.items():
            if method in METHODS:
                routes[(method.upper(), norm(path))] = {p["name"] for p in op.get("parameters", []) if p["in"] == "query"}
    return routes


INTERNAL_ROUTES = Path("docs") / "customer-api-internal-routes.txt"  # in the engine checkout


def internal_patterns(path: Path) -> list[re.Pattern]:
    patterns = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            patterns.append(re.compile("^" + line + "$"))
    return patterns


def curated_snapshot(doc: dict, ours: dict[tuple[str, str], set[str]]) -> dict:
    """The engine document cut down to the curated routes and their query parameters.

    That is all the offline check reads, and all of it is public: the fixture names no internal route.
    """
    paths: dict[str, dict] = {}
    for path, item in sorted(doc["paths"].items()):
        for method, op in sorted(item.items()):
            if method in METHODS and (method.upper(), norm(path)) in ours:
                query = [{"name": p["name"], "in": "query"} for p in op.get("parameters", []) if p["in"] == "query"]
                paths.setdefault(path, {})[method] = {"parameters": query} if query else {}
    return {"openapi": doc.get("openapi", "3.1.0"),
            "info": {"title": "CleanedWeb engine routes in openapi.yaml",
                     "description": "Written by scripts/check_drift.py --write-snapshot from the engine's FastAPI document."},
            "paths": paths}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    source = ap.add_mutually_exclusive_group(required=True)
    source.add_argument("--engine-dir", help="engine checkout (cleanedweb-com) whose .venv builds the document")
    source.add_argument("--live-file", help="read the document from a file")
    source.add_argument("--url", help="fetch the document from a URL")
    ap.add_argument("--strict", action="store_true", help="unclassified live routes also fail")
    ap.add_argument("--internal-routes", help="internal-route patterns (default with --engine-dir: "
                    f"ENGINE/{INTERNAL_ROUTES})")
    ap.add_argument("--write-snapshot", help="write the curated part of the engine document to this file")
    args = ap.parse_args()

    spec = yaml.safe_load((ROOT / "openapi.yaml").read_text())
    try:
        if args.engine_dir:
            live_doc = engine_document(args.engine_dir)
        elif args.live_file:
            live_doc = json.loads(Path(args.live_file).read_text())
        else:
            request = urllib.request.Request(args.url, headers={"User-Agent": "cleanedweb-openapi-drift-check"})
            with urllib.request.urlopen(request, timeout=30) as response:
                live_doc = json.load(response)
    except Exception as exc:  # network, TLS, JSON
        print(f"cannot read the engine document: {exc}", file=sys.stderr)
        return 2

    ours, theirs = curated_routes(spec), live_routes(live_doc)
    if args.write_snapshot:
        Path(args.write_snapshot).write_text(json.dumps(curated_snapshot(live_doc, ours), indent=2) + "\n")
    routes_file = Path(args.internal_routes) if args.internal_routes else (
        Path(args.engine_dir) / INTERNAL_ROUTES if args.engine_dir else None)
    if routes_file and not routes_file.exists():
        print(f"cannot read the internal-route list: {routes_file} not found", file=sys.stderr)
        return 2
    if args.strict and not routes_file:
        print("--strict needs an internal-route list (--engine-dir or --internal-routes)", file=sys.stderr)
        return 2
    internal = internal_patterns(routes_file) if routes_file else None
    missing = sorted(set(ours) - set(theirs))
    params, undeclared = [], []
    for key in sorted(set(ours) & set(theirs)):
        extra_curated, extra_live = ours[key] - theirs[key], theirs[key] - ours[key]
        if extra_live:
            params.append((key, sorted(extra_live)))
        if extra_curated:
            undeclared.append((key, sorted(extra_curated)))
    unclassified = [] if internal is None else sorted(
        key for key in set(theirs) - set(ours)
        if not any(rx.match(key[1]) for rx in internal)
    )

    for method, path in missing:
        print(f"MISSING       {method} {path}: curated, but not in the engine document")
    for (method, path), only_live in params:
        print(f"PARAMS        {method} {path}: the engine document declares {only_live}, openapi.yaml does not")
    for (method, path), only_curated in undeclared:
        print(f"note          {method} {path}: {only_curated} documented here, undeclared in the engine document (the route reads them itself)")
    for method, path in unclassified:
        print(f"UNCLASSIFIED  {method} {path}: live, neither curated nor listed as internal")
    live_count = len(set(ours) & set(theirs))
    classified = "not checked (no internal-route list)" if internal is None else str(len(unclassified))
    print(f"{live_count}/{len(ours)} curated routes are live; unclassified live routes: {classified}; "
          f"{len(theirs)} routes in the engine document")
    failed = bool(missing or params or (args.strict and unclassified))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
