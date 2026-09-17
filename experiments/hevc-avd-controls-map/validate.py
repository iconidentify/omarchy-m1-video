#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Offline HEVC non-reference control coverage checker (omarchy-m1-video#66).

No decoder, no sudo, no network except optional documented source fetch.
Does not claim an RPS_E fix or decoded-frame evidence.

Usage:
  python3 experiments/hevc-avd-controls-map/validate.py --self-test
  python3 experiments/hevc-avd-controls-map/validate.py --source /tmp/avd-15patch/avd-hevc.c
  python3 experiments/hevc-avd-controls-map/validate.py --write-inventory
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from inventory import BINDINGS, CLASSES, SCHEMA, document  # noqa: E402
from scan import TARGETS, scan, coverage  # noqa: E402


def inventory_path():
    return HERE / "inventory.json"


def write_inventory():
    doc = document()
    inventory_path().write_text(json.dumps(doc, indent=2) + "\n")
    return doc


def load_inventory():
    return json.loads(inventory_path().read_text())


def all_members(fields):
    return {row["member"] for row in fields if row.get("member")}


def compare_source(hevc: Path, fields, check_hash=True):
    if check_hash:
        expected=json.loads((HERE/'source-map.json').read_text())['patched_avd_hevc_c']['sha256']
        if hashlib.sha256(hevc.read_bytes()).hexdigest()!=expected:
            raise ValueError('source is not the pinned 15-patch HEVC file')
    observed = scan(hevc)
    leftover = {}
    covered = {row["function"] for row in fields}
    missing_fn = [name for name in TARGETS if name not in covered]
    if missing_fn:
        leftover["functions"] = missing_fn
    for name in TARGETS:
        accounted = all_members([row for row in fields if row['function']==name])
        got = set(observed[name]) - BINDINGS
        extra = sorted(got - accounted)
        if extra:
            leftover[name] = dict(unaccounted=extra, observed=sorted(got))
    committed=json.loads((HERE/'source-coverage.json').read_text())
    actual=coverage(hevc.read_text())
    if actual!=committed:
        leftover['exact_source_reads_calls_flags_locations']='differ from reviewed coverage'
    return leftover


def check_inventory():
    doc=load_inventory(); ids=[f['id'] for f in doc['fields']]
    if doc['schema']!=SCHEMA or len(ids)!=len(set(ids)):
        raise ValueError('invalid inventory identity')
    cov=json.loads((HERE/'source-coverage.json').read_text())
    for row in doc['fields']:
        if row['function'] not in TARGETS or row['klass'] not in CLASSES:
            raise ValueError('invalid classification/function')
        if row['member'] and row['member'] not in cov[row['function']]['members']:
            raise ValueError('field not read in named function: '+row['id'])
        for key in ('activation','derivation','locations'):
            if not row.get(key): raise ValueError('missing field interpretation')
    for name in TARGETS:
        if set(cov[name]['members'])-BINDINGS-all_members([r for r in doc['fields'] if r['function']==name]):
            raise ValueError('unaccounted function-local read: '+name)


def compile_packing():
    with tempfile.TemporaryDirectory() as temp:
        binary = Path(temp) / "packing"
        subprocess.run(
            ["cc", "-O0", "-Wall", "-Werror", "-fsanitize=undefined", "-fno-sanitize-recover=all", "-o", str(binary), str(HERE / "packing.c")],
            check=True, timeout=30,
        )
        out = subprocess.run([str(binary)], check=True, capture_output=True, text=True, timeout=30)
        return out.stdout


def public_window_facts():
    """Facts taken only from the published schema-2 campaign README/summary."""
    return {
        "pictures": list(range(24, 35)),
        "E28": dict(pic=28, poc=32, type="I", motion="0x2d020000", measured="reference/motion"),
        "E29": dict(pic=29, poc=28, type="inter", motion="0x2d00889a",
                    measured="lookup intra collocated CRA; no motion address"),
        "E31": dict(pic=31, poc=31, type="inter", motion="0x2d0488ca",
                    measured="lookup inter collocated; dependent flag clear; motion address emitted"),
        "unknown": ["scaling", "weights", "qp", "deblock", "coded_data", "header_sps_pps_words"],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--write-inventory", action="store_true")
    parser.add_argument("--source", type=Path, help="patched avd-hevc.c")
    args = parser.parse_args(argv)
    if args.write_inventory:
        write_inventory()
        print("wrote", inventory_path())
        return 0
    if args.self_test:
        loader = unittest.TestLoader()
        suite = loader.discover(str(HERE), pattern="tests.py")
        result = unittest.TextTestRunner(verbosity=1).run(suite)
        return 0 if result.wasSuccessful() else 1
    doc = load_inventory()
    check_inventory()
    if doc.get("schema") != SCHEMA:
        print("bad schema", file=sys.stderr)
        return 2
    if args.source:
        leftover = compare_source(args.source, doc["fields"])
        if leftover:
            print(json.dumps(leftover, indent=2))
            return 1
        print("PASS: named functions accounted for against", args.source)
        return 0
    print("fields", len(doc["fields"]), "classes", sorted({f["klass"] for f in doc["fields"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
