#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Synthetic regressions for the H.264 profile-selection prototype.

Fixtures are generated JSON inventories, not corpus bitstreams. Removing a
proposed feature check makes the matching reject fixture fail.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
from selection import (  # noqa: E402
    SCHEMA, DEFAULT_ADVERTISED, DEFAULT_CHECKS, DRIVER_ADVERTISED,
    FFMPEG_COMMIT, DRIVER_COMMIT, FixtureError, run_fixture,
    select_current, select_proposed, vaapi_current_match,
    ffmpeg_profile_from_sps,
)


def fixtures():
    return sorted((HERE / "fixtures").glob("*.json"))


def load(name):
    return json.loads((HERE / "fixtures" / name).read_text())


class Fixtures(unittest.TestCase):
    def test_every_shipped_fixture_passes(self):
        self.assertTrue(fixtures())
        for path in fixtures():
            with self.subTest(path.name):
                result = run_fixture(json.loads(path.read_text()))
                self.assertTrue(result["ok"], path.name + " " + json.dumps(result))
                self.assertFalse(result["decoded_frame_evidence"])
                self.assertEqual(result["evidence_class"], "model_not_decoded_frames")

    def test_current_and_proposed_paths_are_both_present(self):
        paths = {json.loads(p.read_text())["path"] for p in fixtures()}
        self.assertEqual(paths, {"current", "proposed"})

    def test_five_candidates_are_labelled(self):
        labels = {json.loads(p.read_text()).get("vector_label") for p in fixtures()}
        for name in ("BA3_SVA_C", "MR2_TANDBERG_E", "MR3_TANDBERG_B",
                     "MR4_TANDBERG_C", "MR5_TANDBERG_C"):
            self.assertIn(name, labels)

    def test_schema_and_no_bitstream_payloads(self):
        for path in fixtures():
            doc = json.loads(path.read_text())
            self.assertEqual(doc["schema"], SCHEMA)
            blob = path.read_text()
            self.assertNotIn("\\x00\\x00\\x01", blob)
            self.assertNotIn("/home/", blob)


class CurrentRefusal(unittest.TestCase):
    def test_baseline_without_cs1_is_not_constrained_baseline(self):
        self.assertEqual(ffmpeg_profile_from_sps(
            {"profile_idc": 66, "constraint_set1_flag": 0, "parse_ok": True}),
            "H264_BASELINE")
        self.assertEqual(ffmpeg_profile_from_sps(
            {"profile_idc": 66, "constraint_set1_flag": 1, "parse_ok": True}),
            "H264_CONSTRAINED_BASELINE")

    def test_baseline_and_extended_refuse_without_mismatch_flag(self):
        for name in ("current-mr2-refused.json", "current-ba3-refused.json"):
            result = run_fixture(load(name))
            self.assertEqual(result["status"], "refuse")
            self.assertEqual(result["reason"], "profile_mismatch")
            self.assertIsNone(result["va_profile"])

    def test_allow_profile_mismatch_picks_high_not_a_subset(self):
        result = run_fixture(load("current-mismatch-picks-high.json"))
        self.assertEqual(result["va_profile"], "VAProfileH264High")
        self.assertEqual(result["reason"], "allow_profile_mismatch")

    def test_driver_advertised_profiles_match_the_stub(self):
        self.assertEqual(tuple(DRIVER_ADVERTISED), DEFAULT_ADVERTISED)


class ProposedRemap(unittest.TestCase):
    def test_tandberg_maps_to_constrained_baseline(self):
        for name in ("proposed-mr2.json", "proposed-mr3.json",
                     "proposed-mr4.json", "proposed-mr5.json"):
            result = run_fixture(load(name))
            self.assertEqual(result["va_profile"], "VAProfileH264ConstrainedBaseline")
            self.assertEqual(result["reason"], "baseline_constrained_subset")

    def test_ba3_maps_to_main_because_of_b_slices(self):
        result = run_fixture(load("proposed-ba3.json"))
        self.assertEqual(result["va_profile"], "VAProfileH264Main")
        self.assertNotEqual(result["va_profile"], "VAProfileH264ConstrainedBaseline")

    def test_ordinary_main_is_unchanged(self):
        cur = run_fixture(load("current-main-exact.json"))
        prop = run_fixture(load("proposed-main-exact.json"))
        self.assertEqual(cur["va_profile"], prop["va_profile"])
        self.assertEqual(prop["reason"], "exact_profile_match")


class ProposedRejects(unittest.TestCase):
    def test_fmo_fields_partitions_malformed_and_midstream(self):
        cases = {
            "proposed-reject-fmo.json": "fmo",
            "proposed-reject-fields.json": "fields",
            "proposed-reject-partition.json": "data_partition",
            "proposed-reject-malformed.json": "malformed_header",
            "proposed-reject-midstream-fmo.json": "fmo",
        }
        for name, reason in cases.items():
            with self.subTest(name):
                result = run_fixture(load(name))
                self.assertEqual(result["status"], "reject")
                self.assertEqual(result["reason"], reason)
                self.assertIsNone(result["va_profile"])

    def test_midstream_fmo_is_not_the_first_picture(self):
        result = run_fixture(load("proposed-reject-midstream-fmo.json"))
        self.assertEqual(result["picture_index"], 2)


class NegativeChecks(unittest.TestCase):
    """These fail if the proposed feature checks are removed."""

    def test_removing_fmo_check_would_accept_fmo_as_constrained_baseline(self):
        checks = dict(DEFAULT_CHECKS)
        checks["fmo"] = False
        result = run_fixture(load("proposed-reject-fmo.json"), checks=checks)
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "select")
        self.assertEqual(result["va_profile"], "VAProfileH264ConstrainedBaseline")

    def test_removing_field_check_would_accept_fields(self):
        checks = dict(DEFAULT_CHECKS)
        checks["fields"] = False
        result = run_fixture(load("proposed-reject-fields.json"), checks=checks)
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "select")

    def test_removing_partition_check_would_accept_nal2(self):
        checks = dict(DEFAULT_CHECKS)
        checks["partitions"] = False
        result = run_fixture(load("proposed-reject-partition.json"), checks=checks)
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "select")

    def test_first_picture_only_would_miss_midstream_fmo(self):
        checks = dict(DEFAULT_CHECKS)
        checks["scan_all_pictures"] = False
        result = run_fixture(load("proposed-reject-midstream-fmo.json"), checks=checks)
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "select")
        self.assertEqual(result["va_profile"], "VAProfileH264ConstrainedBaseline")


class SourceMap(unittest.TestCase):
    def test_pins_match_the_ticket(self):
        doc = json.loads((HERE / "source-map.json").read_text())
        self.assertEqual(doc["pins"]["ffmpeg"]["commit"], FFMPEG_COMMIT)
        self.assertEqual(doc["pins"]["driver"]["commit"], DRIVER_COMMIT)
        kinds = {i["kind"] for i in doc["invariants"]}
        self.assertEqual(kinds, {"source_observed", "proposed_contract"})

    def test_decision_section_exists(self):
        text = (HERE / "README.md").read_text()
        self.assertIn("## Decision", text)
        self.assertIn("cannot express this safely", text.lower())
        self.assertIn("allow_profile_mismatch", text)
        self.assertNotIn("Fixes https://github.com/iconidentify/libva-v4l2_request/issues/37", text)


class MalformedFixtures(unittest.TestCase):
    def test_wrong_schema_is_a_fixture_error(self):
        doc = load("proposed-mr2.json")
        doc["schema"] = "nope"
        with self.assertRaises(FixtureError):
            run_fixture(doc)

    def test_select_helpers_do_not_claim_frames(self):
        stream = load("proposed-mr2.json")
        self.assertFalse(select_proposed(stream)["decoded_frame_evidence"])
        self.assertFalse(select_current(stream)["decoded_frame_evidence"])
        mismatch = vaapi_current_match("H264_BASELINE", DEFAULT_ADVERTISED, True)
        self.assertEqual(mismatch["va_profile"], "VAProfileH264High")
