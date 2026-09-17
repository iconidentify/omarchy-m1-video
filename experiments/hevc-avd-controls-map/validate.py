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
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from inventory import BINDINGS, CLASSES, SCHEMA, document  # noqa: E402
from scan import TARGETS, scan  # noqa: E402


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


def compare_source(hevc: Path, fields):
    observed = scan(hevc)
    accounted = all_members(fields)
    leftover = {}
    covered = {row["function"] for row in fields}
    missing_fn = [name for name in TARGETS if name not in covered]
    if missing_fn:
        leftover["functions"] = missing_fn
    for name in TARGETS:
        got = set(observed[name]) - BINDINGS
        extra = sorted(got - accounted)
        if extra:
            leftover[name] = dict(unaccounted=extra, observed=sorted(got))
    return leftover


def compile_packing():
    binary = Path(tempfile.mkdtemp()) / "packing"
    subprocess.run(
        ["cc", "-O0", "-Wall", "-Werror", "-o", str(binary), str(HERE / "packing.c")],
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
