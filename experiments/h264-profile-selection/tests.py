#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Synthetic regressions for the H.264 profile-selection prototype.

Fixtures are generated JSON inventories, not corpus bitstreams. Removing a
proposed feature check makes the matching reject fixture fail.
"""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
from selection import (  # noqa: E402
    SCHEMA, DEFAULT_ADVERTISED, DEFAULT_CHECKS,
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

    def test_high10_requires_explicit_stub_advertisement(self):
        case = load("proposed-main-exact.json")
        case["pictures"][0]["sps"].update(profile_idc=110,
            bit_depth_luma_minus8=2, bit_depth_chroma_minus8=2)
        self.assertEqual(select_proposed(case, advertised=DEFAULT_ADVERTISED[:-1])["reason"],
                         "va_profile_not_advertised")


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
            "proposed-reject-midstream-high10.json": "sps_incompatible",
            "proposed-reject-sp.json": "sp_slice",
            "proposed-reject-si.json": "si_slice",
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

    def test_midstream_high10_is_not_the_first_picture(self):
        result = run_fixture(load("proposed-reject-midstream-high10.json"))
        self.assertEqual(result["picture_index"], 1)

    def test_reviewer_high10_after_baseline_does_not_keep_constrained_baseline(self):
        case = load("proposed-mr2.json")
        nxt = copy.deepcopy(case["pictures"][0])
        nxt["sps"].update(
            profile_idc=110, bit_depth_luma_minus8=2, bit_depth_chroma_minus8=2)
        case["pictures"].append(nxt)
        result = select_proposed(case)
        self.assertEqual(result["status"], "reject")
        self.assertEqual(result["reason"], "sps_incompatible")
        self.assertIsNone(result["va_profile"])
        self.assertEqual(result["picture_index"], 1)

    def test_reviewer_extended_sp_and_si_do_not_map_to_main(self):
        for kind, reason in (("SP", "sp_slice"), ("SI", "si_slice")):
            with self.subTest(kind):
                case = load("proposed-ba3.json")
                case["pictures"][0]["slices"] = [{
                    "nal_unit_type": 1, "slice_type": kind,
                    "field_pic_flag": 0, "parse_ok": True,
                    "first_mb_in_slice": 0, "redundant_pic_cnt": 0,
                }]
                result = select_proposed(case)
                self.assertEqual(result["status"], "reject")
                self.assertEqual(result["reason"], reason)
                self.assertIsNone(result["va_profile"])

    def test_later_422_sps_is_incompatible_with_constrained_baseline(self):
        case = load("proposed-mr2.json")
        nxt = copy.deepcopy(case["pictures"][0])
        nxt["sps"]["chroma_format_idc"] = 2
        case["pictures"].append(nxt)
        result = select_proposed(case)
        self.assertEqual(result["status"], "reject")
        self.assertEqual(result["reason"], "sps_incompatible")


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

    def test_removing_sps_compat_would_keep_constrained_baseline_after_high10(self):
        checks = dict(DEFAULT_CHECKS)
        checks["sps_compat"] = False
        result = run_fixture(
            load("proposed-reject-midstream-high10.json"), checks=checks)
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "select")
        self.assertEqual(result["va_profile"], "VAProfileH264ConstrainedBaseline")

    def test_removing_slice_type_check_would_map_sp_and_si_to_main(self):
        checks = dict(DEFAULT_CHECKS)
        checks["slice_types"] = False
        for name in ("proposed-reject-sp.json", "proposed-reject-si.json"):
            with self.subTest(name):
                result = run_fixture(load(name), checks=checks)
                self.assertFalse(result["ok"])
                self.assertEqual(result["status"], "select")
                self.assertEqual(result["va_profile"], "VAProfileH264Main")


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


class AdversarialInventory(unittest.TestCase):
    def case(self):
        return load("proposed-mr2.json")

    def test_every_required_field_is_required_on_both_paths(self):
        original = self.case()
        for section in ("sps", "pps", "slices"):
            sample = original["pictures"][0][section]
            fields = sample[0] if section == "slices" else sample
            for key in fields:
                case = copy.deepcopy(original)
                target = case["pictures"][0][section]
                if section == "slices":
                    target = target[0]
                del target[key]
                for choose in (select_current, select_proposed):
                    with self.subTest(section=section, key=key, path=choose.__name__):
                        with self.assertRaises(FixtureError):
                            choose(case)

    def test_missing_empty_and_wrong_nested_shapes(self):
        for key, values in {"sps": [None, [], {}], "pps": [None, [], {}],
                            "slices": [None, {}, []]}.items():
            for value in values:
                case = self.case()
                case["pictures"][0][key] = value
                with self.subTest(key=key, value=value), self.assertRaises(FixtureError):
                    select_proposed(case)
        for key in ("sps", "pps", "slices"):
            case = self.case()
            del case["pictures"][0][key]
            with self.assertRaises(FixtureError):
                select_proposed(case)

    def test_no_numeric_or_boolean_coercion(self):
        for value in (None, True, False, "0", "bad", -1, 7, 0.0):
            case = self.case()
            case["pictures"][0]["sps"]["bit_depth_luma_minus8"] = value
            with self.subTest(value=value), self.assertRaises(FixtureError):
                select_proposed(case)
        case = self.case()
        case["pictures"][0]["pps"]["parse_ok"] = 1
        with self.assertRaises(FixtureError):
            select_proposed(case)

    def test_unsupported_depths_and_unequal_planes_reject(self):
        for luma, chroma in ((1, 1), (3, 3), (2, 0), (0, 2)):
            case = self.case()
            case["pictures"][0]["sps"].update(profile_idc=110,
                bit_depth_luma_minus8=luma, bit_depth_chroma_minus8=chroma)
            self.assertEqual(select_proposed(case)["reason"], "sps_incompatible")

    def test_cabac_and_high_transform_do_not_remap_baseline_or_extended(self):
        for profile in (66, 88):
            for field, reason in (("entropy_coding_mode_flag", "unsupported_entropy"),
                                  ("transform_8x8_mode_flag", "unsupported_transform")):
                case = self.case()
                case["pictures"][0]["sps"]["profile_idc"] = profile
                case["pictures"][0]["pps"][field] = 1
                self.assertEqual(select_proposed(case)["reason"], reason)

    def test_redundancy_and_slice_order_reject(self):
        for target, field, value, reason in (
                ("pps", "redundant_pic_cnt_present_flag", 1, "redundant_picture"),
                ("slice", "redundant_pic_cnt", 1, "redundant_picture"),
                ("slice", "first_mb_in_slice", 10, "slice_order")):
            case = self.case()
            pic = case["pictures"][0]
            obj = pic["slices"][0] if target == "slice" else pic[target]
            obj[field] = value
            self.assertEqual(select_proposed(case)["reason"], reason)
        case = self.case()
        case["pictures"][0]["slices"][1]["first_mb_in_slice"] = 0
        self.assertEqual(select_proposed(case)["reason"], "slice_order")

    def test_unknown_and_extension_nals_cannot_masquerade_as_slices(self):
        for nal in (0, 6, 7, 8, 13, 19, 20, 21, 31):
            case = self.case()
            case["pictures"][0]["slices"][0]["nal_unit_type"] = nal
            self.assertEqual(select_proposed(case)["reason"], "unsupported_nal")

    def test_later_baseline_sps_does_not_inherit_main_b_permission(self):
        case = load("proposed-ba3.json")
        later = copy.deepcopy(case["pictures"][0])
        later["sps"]["profile_idc"] = 66
        case["pictures"].append(later)
        self.assertEqual(select_proposed(case)["reason"], "baseline_with_b_slices")
        self.assertEqual(select_proposed(case)["picture_index"], 1)

    def test_high10_intra_rejects_inter_slices(self):
        case = self.case()
        case["pictures"][0]["sps"].update(profile_idc=110, constraint_set3_flag=1,
            bit_depth_luma_minus8=2, bit_depth_chroma_minus8=2)
        self.assertEqual(select_proposed(case)["reason"], "disallowed_slice")

    def test_every_picture_checked_for_new_exclusions(self):
        for field, reason in (("entropy_coding_mode_flag", "unsupported_entropy"),
                              ("redundant_pic_cnt_present_flag", "redundant_picture")):
            case = self.case()
            later = copy.deepcopy(case["pictures"][0])
            later["pps"][field] = 1
            case["pictures"].append(later)
            result = select_proposed(case)
            self.assertEqual((result["reason"], result["picture_index"]), (reason, 1))

    def test_main_fields_are_only_rejected_by_proposed_path(self):
        case = load("proposed-main-exact.json")
        case["pictures"][0]["sps"]["frame_mbs_only_flag"] = 0
        self.assertEqual(select_current(case)["status"], "select")
        self.assertEqual(select_proposed(case)["reason"], "fields")

    def test_real_default_capabilities_and_missing_capabilities(self):
        case = self.case()
        self.assertEqual(select_proposed(case, advertised=DEFAULT_ADVERTISED[:-1])["status"],
                         "select")
        self.assertEqual(select_proposed(case, advertised=[])["reason"], "va_profile_not_advertised")
        del case["advertised"]
        with self.assertRaises(FixtureError):
            select_proposed(case)

    def test_malformed_json_is_rejected(self):
        import tempfile
        from validate import load_json
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.json"
            for text in ('{"a":1,"a":2}', '{"a":NaN}', '{"a":Infinity}'):
                path.write_text(text)
                with self.assertRaises(FixtureError):
                    load_json(path)
