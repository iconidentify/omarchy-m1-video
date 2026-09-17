#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Offline H.264 client profile-selection runner (omarchy-m1-video#41).

No decoder device, no privileged access, no network, no third-party packages.
Synthetic fixtures only. A selected VA profile is not decoded-frame evidence
and does not qualify parent libva-v4l2_request#37.

Usage:
  python3 experiments/h264-profile-selection/validate.py
  python3 experiments/h264-profile-selection/validate.py --self-test
  python3 experiments/h264-profile-selection/validate.py --source-map
  python3 experiments/h264-profile-selection/validate.py --decision
"""
from __future__ import annotations

import argparse
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from selection import (  # noqa: E402
    SCHEMA, FixtureError, run_fixture,
)


def fixture_paths():
    files = sorted((HERE / "fixtures").glob("*.json"))
    if not files:
        raise SystemExit("no fixtures in experiments/h264-profile-selection/fixtures")
    return files


def unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise FixtureError("duplicate JSON key: " + key)
        obj[key] = value
    return obj


def invalid_constant(value):
    raise FixtureError("non-finite JSON value: " + value)


def load_json(path):
    try:
        return json.loads(Path(path).read_text(), object_pairs_hook=unique_object,
                          parse_constant=invalid_constant)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FixtureError("unreadable or malformed JSON: %s" % type(exc).__name__) from exc


def run_one(path):
    result = run_fixture(load_json(path))
    result["fixture"] = Path(path).name
    return result


def run_all_fixtures():
    results = []
    failures = []
    for path in fixture_paths():
        try:
            results.append(run_one(path))
        except FixtureError as exc:
            failures.append((path.name, str(exc)))
    return results, failures


def print_source_map():
    doc = json.loads((HERE / "source-map.json").read_text())
    pins = doc["pins"]
    print("ffmpeg %s %s" % (pins["ffmpeg"]["tag"], pins["ffmpeg"]["commit"]))
    print("driver %s" % pins["driver"]["commit"])
    print("schema %s" % doc["schema"])
    for item in doc["invariants"]:
        cite = item.get("cite") or {}
        loc = ""
        if cite:
            loc = "  %s:%s" % (cite.get("file", ""), cite.get("lines", ""))
        print("%-20s %-32s%s" % (item["kind"], item["id"], loc))
        print("  %s" % item["text"])


def print_decision():
    text = (HERE / "README.md").read_text()
    marker = "## Decision"
    if marker not in text:
        raise SystemExit("README.md is missing the Decision section")
    sys.stdout.write(text[text.index(marker):])
    if not text.endswith("\n"):
        sys.stdout.write("\n")


def format_result(result):
    status = result.get("status")
    va = result.get("va_profile") or "-"
    reason = result.get("reason")
    evidence = "decoded_frame_evidence=%s" % str(result.get("decoded_frame_evidence")).lower()
    ok = "ok" if result.get("ok") else "FAIL"
    return "%s %s %s %s %s %s" % (
        ok, result.get("fixture") or result.get("id"), status, va, reason, evidence)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--source-map", action="store_true")
    parser.add_argument("--decision", action="store_true")
    args = parser.parse_args(argv)
    if args.source_map:
        print_source_map()
        return 0
    if args.decision:
        print_decision()
        return 0
    if args.self_test:
        results, load_failures = run_all_fixtures()
        failed = [r for r in results if not r.get("ok")]
        for name, err in load_failures:
            print("FAIL %s load %s decoded_frame_evidence=false" % (name, err))
        for result in results:
            print(format_result(result))
        loader = unittest.TestLoader()
        suite = loader.discover(str(HERE), pattern="tests.py")
        test_result = unittest.TextTestRunner(verbosity=1).run(suite)
        if load_failures or failed or not test_result.wasSuccessful():
            return 1
        print("self-test: %d fixtures, decoded_frame_evidence=false" % len(results))
        return 0
    results, load_failures = run_all_fixtures()
    for name, err in load_failures:
        print("FAIL %s load %s decoded_frame_evidence=false" % (name, err))
    for result in results:
        print(format_result(result))
    if load_failures or any(not r.get("ok") for r in results):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
