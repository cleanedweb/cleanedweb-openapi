#!/usr/bin/env python3
"""Compare openapi.yaml with the live FastAPI document of the API origin.

    python scripts/check_drift.py                      # fetch https://api.cleanedweb.com/openapi.json
    python scripts/check_drift.py --live-file x.json   # compare with a saved document (offline)
    python scripts/check_drift.py --strict             # unclassified live routes also fail

Reports, for the paths this repository serves from the API origin:

* MISSING   a curated method and path the live document does not have (exit 1),
* PARAMS    a query parameter the live document declares and openapi.yaml lacks (exit 1). A parameter only
  openapi.yaml documents is a note: several run routes read their query themselves and declare nothing,
* UNCLASSIFIED  a live route that is neither curated nor listed in scripts/internal-routes.txt
  (a new route: decide whether it is public; exit 1 only with --strict),
* a count of curated routes that are live.

Paths under another origin (the console's /api/catalog reads and the catalog site files) are not in the
live document and are skipped. Needs PyYAML:  pip install pyyaml
Exit codes: 0 no drift, 1 drift, 2 the live document could not be read.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
LIVE_URL = "https://api.cleanedweb.com/openapi.json"
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


def internal_patterns() -> list[re.Pattern]:
    patterns = []
    for line in (ROOT / "scripts" / "internal-routes.txt").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            patterns.append(re.compile("^" + line + "$"))
    return patterns


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--live-file", help="read the live document from a file instead of the network")
    ap.add_argument("--url", default=LIVE_URL)
    ap.add_argument("--strict", action="store_true", help="unclassified live routes also fail")
    args = ap.parse_args()

    spec = yaml.safe_load((ROOT / "openapi.yaml").read_text())
    try:
        if args.live_file:
            live_doc = json.loads(Path(args.live_file).read_text())
        else:
            request = urllib.request.Request(args.url, headers={"User-Agent": "cleanedweb-openapi-drift-check"})
            with urllib.request.urlopen(request, timeout=30) as response:
                live_doc = json.load(response)
    except Exception as exc:  # network, TLS, JSON
        print(f"cannot read the live document: {exc}", file=sys.stderr)
        return 2

    ours, theirs = curated_routes(spec), live_routes(live_doc)
    internal = internal_patterns()
    missing = sorted(set(ours) - set(theirs))
    params, undeclared = [], []
    for key in sorted(set(ours) & set(theirs)):
        extra_curated, extra_live = ours[key] - theirs[key], theirs[key] - ours[key]
        if extra_live:
            params.append((key, sorted(extra_live)))
        if extra_curated:
            undeclared.append((key, sorted(extra_curated)))
    unclassified = sorted(
        key for key in set(theirs) - set(ours)
        if not any(rx.match(key[1]) for rx in internal)
    )

    for method, path in missing:
        print(f"MISSING       {method} {path}: curated, but not in the live document")
    for (method, path), only_live in params:
        print(f"PARAMS        {method} {path}: the live document declares {only_live}, openapi.yaml does not")
    for (method, path), only_curated in undeclared:
        print(f"note          {method} {path}: {only_curated} documented here, undeclared in the live document (the route reads them itself)")
    for method, path in unclassified:
        print(f"UNCLASSIFIED  {method} {path}: live, neither curated nor listed as internal")
    live_count = len(set(ours) & set(theirs))
    print(f"{live_count}/{len(ours)} curated routes are live; {len(unclassified)} unclassified live routes; "
          f"{len(theirs)} routes in the live document")
    failed = bool(missing or params or (args.strict and unclassified))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
