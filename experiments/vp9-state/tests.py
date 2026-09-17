#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Synthetic regressions for the VP9 resize state validator.

Fixtures are generated JSON, not corpus bitstreams. Removing a reject check
makes the matching fixture fail its expected status.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from model import (  # noqa: E402
    SCHEMA, Era, FixtureError, KERNEL_COMMIT, INVARIANTS,
    fill_comp, load_source_map, run_events, run_fixture,
)


def fixtures():
    return sorted((HERE / "fixtures").glob("*.json"))


class Fixtures(unittest.TestCase):
    def test_every_shipped_fixture_passes(self):
        self.assertTrue(fixtures())
        for path in fixtures():
            with self.subTest(path.name):
                result = run_fixture(json.loads(path.read_text()))
                self.assertTrue(result["ok"])
                self.assertFalse(result["decoded_frame_evidence"])
                self.assertEqual(result["evidence_class"], "model_not_decoded_frames")

    def test_legal_and_adversarial_and_firmware_are_all_present(self):
        classes = {json.loads(p.read_text())["classification"] for p in fixtures()}
        self.assertEqual(classes, {"legal_stream", "adversarial_api", "firmware_unknown"})

    def test_stock_and_proposed_paths_are_both_present(self):
        paths = {json.loads(p.read_text())["path"] for p in fixtures()}
        self.assertEqual(paths, {"stock", "proposed"})


class SourceMap(unittest.TestCase):
    def test_every_source_observed_invariant_has_a_pinned_cite(self):
        doc = load_source_map()
        self.assertEqual(doc["pins"]["kernel"]["commit"], KERNEL_COMMIT)
        observed = [i for i in doc["invariants"] if i["kind"] == "source_observed"]
        self.assertGreaterEqual(len(observed), 10)
        for item in observed:
            cite = item.get("cite") or {}
            self.assertTrue(cite.get("file"), item["id"])
            self.assertTrue(cite.get("lines"), item["id"])
            if "avd.h" not in cite.get("file", ""):
                self.assertTrue(cite.get("sha256"), item["id"])

    def test_proposed_and_firmware_kinds_are_labeled(self):
        kinds = {i["kind"] for i in load_source_map()["invariants"]}
        self.assertEqual(kinds, {"source_observed", "proposed_contract", "firmware_unknown"})
        for item in load_source_map()["invariants"]:
            if item["kind"] == "source_observed":
                self.assertNotIn("firmware", item["id"])

    def test_invariants_module_matches_json(self):
        self.assertEqual(set(INVARIANTS), {i["id"] for i in load_source_map()["invariants"]})


class Layout(unittest.TestCase):
    def test_fill_comp_grows_with_frame_size(self):
        small, _ = fill_comp(320, 192, 8)
        large, _ = fill_comp(640, 368, 8)
        self.assertGreater(small, 0)
        self.assertGreater(large, small)

    def test_era_sizeimage_includes_comp_and_pixels(self):
        era = Era(0, 640, 360, 8)
        self.assertEqual(era.aligned_w, 640)
        self.assertEqual(era.aligned_h, 368)
        self.assertGreater(era.sizeimage, era.start_offset)
        self.assertEqual(era.fourcc, "NV12")
        era10 = Era(1, 640, 360, 10)
        self.assertEqual(era10.fourcc, "P010")
        self.assertGreater(era10.sizeimage, era.sizeimage)

    def test_shrink_reference_sizeimage_is_from_its_own_era(self):
        old = Era(0, 640, 360, 8)
        new = Era(1, 320, 180, 8)
        self.assertGreater(old.sizeimage, new.sizeimage)


class Rejects(unittest.TestCase):
    def test_destination_fallback_is_never_success(self):
        result = run_fixture(json.loads(
            (HERE / "fixtures/reject-destination-fallback.json").read_text()))
        self.assertEqual(result["status"], "reject")
        self.assertEqual(result["code"], "destination_fallback")
        self.assertEqual(result["kind"], "source_observed")
        self.assertNotEqual(result["status"], "model_accept")

    def test_old_generation_alias_is_rejected(self):
        result = run_fixture(json.loads(
            (HERE / "fixtures/reject-old-generation-alias.json").read_text()))
        self.assertEqual(result["code"], "old_generation_alias")

    def test_model_accept_is_not_a_hardware_pass(self):
        result = run_fixture(json.loads(
            (HERE / "fixtures/proposed-grow.json").read_text()))
        self.assertEqual(result["status"], "model_accept")
        self.assertEqual(result["kind"], "proposed_contract")
        self.assertFalse(result["decoded_frame_evidence"])
        self.assertIn("seg_map_policy_unknown", result["snapshot"]["lost"])
        self.assertTrue(result["snapshot"]["probabilities"])

    def test_stock_state_loss_matches_the_design_inventory(self):
        result = run_fixture(json.loads(
            (HERE / "fixtures/stock-state-loss.json").read_text()))
        lost = set(result["snapshot"]["lost"])
        self.assertTrue({"wrapper_metadata", "frame_context", "scratch",
                         "seg_map", "last_frame_info"} <= lost)
        self.assertFalse(result["snapshot"]["output_streaming"])

    def test_preflight_failure_does_not_poison_the_session(self):
        result = run_fixture(json.loads(
            (HERE / "fixtures/proposed-preflight-still-usable.json").read_text()))
        self.assertEqual(result["status"], "model_accept")
        self.assertFalse(result["snapshot"]["failed"])

    def test_orphaned_export_fails_when_registration_is_required(self):
        result = run_fixture(json.loads(
            (HERE / "fixtures/reject-orphaned-retained.json").read_text()))
        self.assertEqual(result["code"], "orphaned_retained_buffer")

    def test_dropping_the_unavailable_ref_check_would_fail_this_fixture(self):
        # The fixture expects reject. If _resolve_stock_userspace were a no-op
        # the later decode would hit unexpected_resolution or model completion
        # and _check_expect would raise. Pin that contract here.
        doc = json.loads((HERE / "fixtures/stock-unavailable-ref.json").read_text())
        self.assertEqual(doc["expect"]["code"], "unavailable_reference")
        result = run_fixture(doc)
        self.assertEqual(result["status"], "reject")


class Malformed(unittest.TestCase):
    def test_missing_schema(self):
        with self.assertRaises(FixtureError):
            run_fixture({"id": "x", "path": "stock", "classification": "legal_stream",
                         "expect": {"status": "observe"}, "events": [{"op": "open"}]})

    def test_incompatible_schema(self):
        with self.assertRaises(FixtureError):
            run_fixture({"schema": "nope/1", "id": "x", "path": "stock",
                         "classification": "legal_stream",
                         "expect": {"status": "observe"},
                         "events": [{"op": "open"}]})

    def test_empty_events(self):
        with self.assertRaises(FixtureError):
            run_fixture({"schema": SCHEMA, "id": "x", "path": "stock",
                         "classification": "legal_stream",
                         "expect": {"status": "observe"}, "events": []})

    def test_unknown_op(self):
        with self.assertRaises(FixtureError):
            run_fixture({"schema": SCHEMA, "id": "x", "path": "stock",
                         "classification": "legal_stream",
                         "expect": {"status": "observe"},
                         "events": [{"op": "rm_modprobe"}]})

    def test_truncated_expect_mismatch(self):
        doc = json.loads((HERE / "fixtures/stock-state-loss.json").read_text())
        doc["events"] = doc["events"][:3]
        with self.assertRaises(FixtureError):
            run_fixture(doc)

    def test_status_mismatch_is_a_fixture_error(self):
        doc = json.loads((HERE / "fixtures/proposed-grow.json").read_text())
        doc["expect"] = {"status": "reject", "code": "destination_fallback"}
        with self.assertRaises(FixtureError):
            run_fixture(doc)


class Command(unittest.TestCase):
    def test_cli_runs_without_extra_packages_or_devices(self):
        proc = subprocess.run(
            [sys.executable, str(HERE / "validate.py")],
            cwd=str(HERE.parent.parent),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("decoded_frame_evidence=false", proc.stdout)
        self.assertNotIn("/dev/video", proc.stdout)
        self.assertNotIn("sudo", proc.stdout)

    def test_source_map_and_experiment_plan_flags(self):
        root = HERE.parent.parent
        sm = subprocess.run([sys.executable, str(HERE / "validate.py"), "--source-map"],
                            cwd=str(root), stdout=subprocess.PIPE, text=True, check=True)
        self.assertIn(KERNEL_COMMIT, sm.stdout)
        self.assertIn("source_observed", sm.stdout)
        ep = subprocess.run([sys.executable, str(HERE / "validate.py"), "--experiment-plan"],
                            cwd=str(root), stdout=subprocess.PIPE, text=True, check=True)
        self.assertIn("experiment a", ep.stdout.lower())

    def test_single_fixture_path(self):
        proc = subprocess.run(
            [sys.executable, str(HERE / "validate.py"),
             str(HERE / "fixtures/stock-state-loss.json")],
            cwd=str(HERE.parent.parent), stdout=subprocess.PIPE, text=True, check=True)
        self.assertIn("stock-state-loss", proc.stdout)

    def test_temp_malformed_file_is_rejected(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            fh.write("{")
            name = fh.name
        try:
            proc = subprocess.run(
                [sys.executable, str(HERE / "validate.py"), name],
                cwd=str(HERE.parent.parent), stdout=subprocess.PIPE, text=True)
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("FAIL", proc.stdout)
        finally:
            Path(name).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
