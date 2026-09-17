#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Offline AVD VP9 resize queue/reference-state validator (omarchy-m1-video#42).

No decoder device, no privileged access, no network, no third-party packages.
Synthetic fixtures only. A completed proposed sequence is not decoded-frame
evidence and does not qualify parent omarchy-m1-video#16.

Usage:
  python3 experiments/vp9-state/validate.py
  python3 experiments/vp9-state/validate.py --self-test
  python3 experiments/vp9-state/validate.py --source-map
  python3 experiments/vp9-state/validate.py --experiment-plan
"""
from __future__ import annotations

import argparse
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from model import (  # noqa: E402
    SCHEMA, FixtureError, load_source_map, run_fixture,
)


def fixture_paths():
    files = sorted((HERE / "fixtures").glob("*.json"))
    if not files:
        raise SystemExit("no fixtures in experiments/vp9-state/fixtures")
    return files


def load_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FixtureError(f"unreadable or malformed JSON: {type(exc).__name__}") from exc


def run_one(path):
    name = Path(path).name
    result = run_fixture(load_json(path))
    result["fixture"] = name
    return result


def print_source_map():
    doc = load_source_map()
    pins = doc["pins"]["kernel"]
    print(f"kernel {pins['tag']} {pins['commit']}")
    print(f"schema {doc['schema']}")
    for item in doc["invariants"]:
        cite = item.get("cite") or {}
        loc = ""
        if cite:
            loc = f"  {cite.get('file', '')}:{cite.get('lines', '')}"
        print(f"{item['kind']:20} {item['id']:28}{loc}")
        print(f"  {item['text']}")


def print_experiment_plan():
    text = (HERE / "EXPERIMENT_PLAN.md").read_text()
    sys.stdout.write(text if text.endswith("\n") else text + "\n")


def run_all_fixtures():
    results = []
    failures = []
    for path in fixture_paths():
        try:
            results.append(run_one(path))
        except FixtureError as exc:
            failures.append((path.name, str(exc)))
    return results, failures


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("fixtures", nargs="*", help="fixture JSON files (default: all)")
    parser.add_argument("--self-test", action="store_true",
                        help="run unittest regressions")
    parser.add_argument("--source-map", action="store_true")
    parser.add_argument("--experiment-plan", action="store_true")
    args = parser.parse_args(argv)

    if args.source_map:
        print_source_map()
        return 0
    if args.experiment_plan:
        print_experiment_plan()
        return 0

    exit_code = 0
    if args.fixtures:
        for path in args.fixtures:
            try:
                result = run_one(path)
            except FixtureError as exc:
                print(f"FAIL {Path(path).name}: {exc}")
                exit_code = 1
                continue
            print(_format(result))
            if not result.get("ok"):
                exit_code = 1
    else:
        results, failures = run_all_fixtures()
        for result in results:
            print(_format(result))
        for name, message in failures:
            print(f"FAIL {name}: {message}")
            exit_code = 1
        print(f"{len(results)} fixtures ok, {len(failures)} failed; "
              f"decoded_frame_evidence=false for every result")

    if args.self_test:
        loader = unittest.defaultTestLoader
        suite = loader.discover(str(HERE), pattern="tests.py")
        runner = unittest.TextTestRunner(verbosity=1)
        test_result = runner.run(suite)
        if not test_result.wasSuccessful():
            exit_code = 1
    return exit_code


def _format(result):
    code = result.get("code") or "-"
    return (f"OK {result['id']}: status={result['status']} code={code} "
            f"kind={result['kind']} class={result['classification']} "
            f"decoded_frame_evidence=false")


if __name__ == "__main__":
    sys.exit(main())
