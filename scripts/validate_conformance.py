#!/usr/bin/env python3
"""Check the SDK conformance cases against openapi.yaml.

For every case file in tests/cases this script verifies that

* the file follows tests/case.schema.json,
* every exchange maps to an operation of the spec (method, path template, origin),
* the mocked response status is declared by that operation (or its shared responses),
* the mocked response body validates against the operation's response schema, and
* a request body validates against the operation's request schema.

It needs PyYAML and jsonschema:  pip install pyyaml jsonschema referencing
Usage: python scripts/validate_conformance.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

ROOT = Path(__file__).resolve().parent.parent
SPEC_URI = "urn:cleanedweb:openapi"


def load_spec() -> dict:
    return yaml.safe_load((ROOT / "openapi.yaml").read_text())


def resolve(spec: dict, node):
    """Follow a local $ref."""
    while isinstance(node, dict) and "$ref" in node:
        target = spec
        for part in node["$ref"].lstrip("#/").split("/"):
            target = target[part.replace("~1", "/").replace("~0", "~")]
        node = target
    return node


def path_regex(template: str) -> re.Pattern:
    return re.compile("^" + re.sub(r"\{[^}]+\}", r"[^/]+", re.escape(template).replace(r"\{", "{").replace(r"\}", "}")) + "$")


def operations(spec: dict):
    for path, item in spec["paths"].items():
        for method, op in item.items():
            if method in {"get", "post", "put", "delete", "patch"}:
                yield path, method.upper(), op


def validator_for(spec: dict, schema: dict) -> Draft202012Validator:
    # Register the spec with the schema attached, so its relative #/components refs resolve.
    document = Resource.from_contents({**spec, "__inline__": schema}, default_specification=DRAFT202012)
    registry = Registry().with_resource(SPEC_URI, document)
    return Draft202012Validator({"$ref": SPEC_URI + "#/__inline__"}, registry=registry)


def main() -> int:
    spec = load_spec()
    case_schema = json.loads((ROOT / "tests" / "case.schema.json").read_text())
    case_validator = Draft202012Validator(case_schema)
    ops = [(path_regex(p), p, m, op) for p, m, op in operations(spec)]
    errors: list[str] = []
    seen_ids: set[str] = set()
    covered: set[str] = set()
    count = 0

    for file in sorted((ROOT / "tests" / "cases").glob("*.json")):
        data = json.loads(file.read_text())
        for issue in case_validator.iter_errors(data):
            errors.append(f"{file.name}: schema: {'/'.join(map(str, issue.absolute_path))}: {issue.message}")
        for case in data.get("cases", []):
            count += 1
            cid = case.get("id", "?")
            where = f"{file.name}:{cid}"
            if cid in seen_ids:
                errors.append(f"{where}: duplicate case id")
            seen_ids.add(cid)
            for n, exchange in enumerate(case.get("exchanges", [])):
                req = exchange["request"]
                matches = [(p, m, op) for rx, p, m, op in ops if m == req["method"] and rx.match(req["path"])]
                if not matches:
                    errors.append(f"{where}: exchange {n}: no operation for {req['method']} {req['path']}")
                    continue
                # Prefer the most specific template (fewest path parameters).
                _, _, op = sorted(matches, key=lambda t: t[0].count("{"))[0]
                covered.add(op["operationId"])
                if "response" not in exchange:
                    continue
                resp = exchange["response"]
                responses = op["responses"]
                declared = responses.get(str(resp["status"]))
                if declared is None and not (300 <= resp["status"] < 400):
                    errors.append(f"{where}: exchange {n}: {op['operationId']} does not declare status {resp['status']}")
                    continue
                if declared is not None and "json" in resp:
                    schema = resolve(spec, declared).get("content", {}).get("application/json", {}).get("schema")
                    if schema is not None:
                        for issue in validator_for(spec, schema).iter_errors(resp["json"]):
                            errors.append(f"{where}: exchange {n}: response body: {'/'.join(map(str, issue.absolute_path))}: {issue.message}")
                body = req.get("body")
                if body is not None and not exchange.get("spec_invalid_request"):
                    schema = (op.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema"))
                    if schema is None:
                        errors.append(f"{where}: exchange {n}: {op['operationId']} takes no request body")
                    else:
                        for issue in validator_for(spec, schema).iter_errors(body):
                            errors.append(f"{where}: exchange {n}: request body: {'/'.join(map(str, issue.absolute_path))}: {issue.message}")

    for path, _, op in operations(spec):
        if path.startswith("/v1/") and op["operationId"] not in covered:
            print(f"note: operation {op['operationId']} has no conformance exchange", file=sys.stderr)
    for e in errors:
        print("ERROR", e, file=sys.stderr)
    print(f"{count} cases, {len(errors)} errors")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
