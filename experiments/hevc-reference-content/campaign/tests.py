#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Offline tests for the campaign controller. No device, module or client."""
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import unittest

HERE = pathlib.Path(__file__).resolve().parent
CONTROLLER = pathlib.Path(os.environ.get("CAMPAIGN_CONTROLLER", HERE / "controller.py"))
spec = importlib.util.spec_from_file_location("controller", CONTROLLER)
c = importlib.util.module_from_spec(spec)
sys.modules["controller"] = c
spec.loader.exec_module(c)

GST_POOL = 16
VA_OUTPUT_COUNT = 20
GST_E = (2, 5, 9)
GST_B = (3,)
VA_E = (1, 4, 7)
VA_B = (2,)
LAST_INPUTS = {"gst": {"E": 9, "B": 4}, "va": {"E": 12, "B": 6}}


def good_plan(**build_overrides):
    values = {
        "gst_pool_size": GST_POOL,
        "va_output_count": VA_OUTPUT_COUNT,
        "gst_frames": {"E": GST_E, "B": GST_B},
        "va_outputs": {"E": VA_E, "B": VA_B},
        "last_required_inputs": LAST_INPUTS,
        "parameter_set_change_inputs": None,
        "run_id": "test",
    }
    values.update(build_overrides)
    return c.build_plan(**values)


def workload(plan, name):
    return next(item for item in plan.workloads if item.name == name)


def good_auth():
    return c.Authorization(operator="operator", guard_lease_id="lease-1",
                           approved_manifest_sha256="a" * 64,
                           issue_authorization_url="https://example.invalid/82",
                           hardware_window="2026-09-19T12:00Z/PT1H")


def good_pre():
    return c.Preconditions(healthy_idle=True, foreign_client_absent=True,
                           journal_boundary="2026-09-19T12:00:00Z",
                           module_loaded=True, decoder_refcount=0)


class PlanShape(unittest.TestCase):
    def test_valid_plan_has_no_problems(self):
        self.assertEqual(c.validate_plan(good_plan()), [])

    def test_plan_is_the_eight_workload_matrix(self):
        names = sorted(item.name for item in good_plan().workloads)
        self.assertEqual(names, sorted({f"{v}-{client}-{mode}" for v in ("B", "E")
                                        for client in ("va", "gst")
                                        for mode in ("off", "on")}))

    def test_copy_off_and_on_select_the_same_targets(self):
        plan = good_plan()
        for client in c.CLIENTS:
            for vector in c.VECTORS:
                self.assertEqual(workload(plan, f"{vector}-{client}-off").selectors,
                                 workload(plan, f"{vector}-{client}-on").selectors)

    def test_copy_budget_counts_on_rows_not_control_observations(self):
        plan = good_plan()
        all_observations = sum(len(item.selectors) for item in plan.workloads)
        copied = sum(len(item.selectors) for item in plan.workloads if item.copy)
        self.assertEqual(all_observations, 16)
        self.assertEqual(copied, c.MAX_SNAPSHOTS)
        self.assertEqual(copied * c.SNAPSHOT_BYTES, c.TOTAL_BYTES)

    def test_missing_workload_is_rejected(self):
        plan = good_plan()
        plan.workloads = [item for item in plan.workloads if item.name != "E-va-on"]
        self.assertTrue(any("eight" in problem for problem in c.validate_plan(plan)))

    def test_duplicate_workload_is_rejected(self):
        plan = good_plan()
        plan.workloads.append(plan.workloads[0])
        self.assertTrue(any("duplicate" in problem for problem in c.validate_plan(plan)))


class Selections(unittest.TestCase):
    def test_copy_off_without_selection_is_rejected(self):
        plan = good_plan()
        workload(plan, "E-va-off").selectors = ()
        self.assertTrue(any("selects no outputs" in problem
                            for problem in c.validate_plan(plan)))

    def test_copy_off_on_selector_mismatch_rejected(self):
        plan = good_plan()
        workload(plan, "E-va-off").selectors = (1, 4, 8)
        self.assertTrue(any("copy-off/on selectors differ" in problem
                            for problem in c.validate_plan(plan)))

    def test_copy_off_on_stream_contract_mismatch_rejected(self):
        plan = good_plan()
        workload(plan, "E-va-off").parameter_set_change_inputs = (13,)
        workload(plan, "B-gst-off").gst_pool_size = GST_POOL + 1
        problems = c.validate_plan(plan)
        self.assertTrue(any("stream-change inputs differ" in problem for problem in problems))
        self.assertTrue(any("selector limits differ" in problem for problem in problems))

    def test_selector_domain_mismatch_rejected(self):
        plan = good_plan()
        workload(plan, "E-va-on").selector_domain = c.GST_SELECTOR
        self.assertTrue(any("selector domain" in problem for problem in c.validate_plan(plan)))

    def test_duplicate_selectors_rejected(self):
        plan = good_plan()
        workload(plan, "E-va-on").selectors = (1, 1, 4)
        self.assertTrue(any("distinct output_ordinals" in problem
                            for problem in c.validate_plan(plan)))

    def test_too_many_selections_rejected(self):
        plan = good_plan()
        workload(plan, "E-va-on").selectors = tuple(range(c.MAX_SELECTION + 1))
        self.assertTrue(any("outside 1.." in problem for problem in c.validate_plan(plan)))

    def test_gst_publication_boundary_rejected(self):
        plan = good_plan()
        for mode in ("off", "on"):
            workload(plan, f"E-gst-{mode}").selectors = (2, 5, GST_POOL)
        self.assertTrue(any("publication boundary" in problem
                            for problem in c.validate_plan(plan)))

    def test_va_output_count_boundary_rejected(self):
        plan = good_plan()
        for mode in ("off", "on"):
            workload(plan, f"E-va-{mode}").selectors = (1, 4, VA_OUTPUT_COUNT)
        self.assertTrue(any("exceed decoded output count" in problem
                            for problem in c.validate_plan(plan)))

    def test_va_ordinal_does_not_use_gst_publication_boundary(self):
        plan = good_plan()
        for mode in ("off", "on"):
            workload(plan, f"E-va-{mode}").selectors = (1, 4, 17)
        self.assertEqual(c.validate_plan(plan), [])

    def test_client_specific_limit_fields_cannot_cross(self):
        plan = good_plan()
        workload(plan, "E-va-on").gst_pool_size = GST_POOL
        workload(plan, "E-gst-on").va_output_count = VA_OUTPUT_COUNT
        problems = c.validate_plan(plan)
        self.assertTrue(any("Gst pool size attached to a VA" in problem for problem in problems))
        self.assertTrue(any("VA output count attached to a Gst" in problem for problem in problems))

    def test_parameter_change_uses_input_window_not_va_ordinal(self):
        plan = good_plan(parameter_set_change_inputs={"E": (10,), "B": ()})
        problems = c.validate_plan(plan)
        self.assertTrue(any(problem.startswith("E-va-") and "input [10]" in problem
                            for problem in problems), problems)
        self.assertFalse(any(problem.startswith("E-gst-") and "input [10]" in problem
                             for problem in problems), problems)

    def test_parameter_change_after_input_window_is_allowed(self):
        plan = good_plan(parameter_set_change_inputs={"E": (13,), "B": (7,)})
        self.assertEqual(c.validate_plan(plan), [])

    def test_invalid_input_window_rejected(self):
        plan = good_plan()
        workload(plan, "E-va-on").last_required_input_index = -1
        self.assertTrue(any("invalid input window" in problem
                            for problem in c.validate_plan(plan)))

    def test_slot_shape_enforced(self):
        plan = good_plan()
        for mode in ("off", "on"):
            workload(plan, f"E-va-{mode}").selectors = (1, 4)
        self.assertTrue(any("expected 3" in problem for problem in c.validate_plan(plan)))

    def test_copy_budget_enforced(self):
        plan = good_plan(gst_frames={"E": (1, 2, 3, 4), "B": GST_B},
                         va_outputs={"E": (1, 2, 3, 4), "B": VA_B})
        self.assertTrue(any("copied snapshots exceeds" in problem
                            for problem in c.validate_plan(plan)))


class GstProperties(unittest.TestCase):
    def test_fresh_element_guard(self):
        plan = good_plan()
        plan.gst.fresh_element_per_observation = False
        self.assertTrue(any("fresh decoder element" in problem
                            for problem in c.validate_plan(plan)))

    def test_streaming_owner_guard(self):
        plan = good_plan()
        plan.gst.arm_on_streaming_owner = False
        self.assertTrue(any("streaming owner" in problem for problem in c.validate_plan(plan)))

    def test_flow_error_guard(self):
        plan = good_plan()
        plan.gst.treat_flow_error_as_failure = False
        self.assertTrue(any("GST_FLOW_ERROR" in problem for problem in c.validate_plan(plan)))

    def test_lifecycle_guard(self):
        plan = good_plan()
        plan.gst.finish_before_lifecycle_ops = False
        self.assertTrue(any("before flush" in problem for problem in c.validate_plan(plan)))


class VAProperties(unittest.TestCase):
    def test_fresh_decoder_guard(self):
        plan = good_plan()
        plan.va.fresh_decoder_per_observation = False
        self.assertTrue(any("fresh decoder" in problem for problem in c.validate_plan(plan)))

    def test_threads_guard(self):
        plan = good_plan()
        plan.va.decoder_threads = 2
        self.assertTrue(any("decoder_threads=1" in problem
                            for problem in c.validate_plan(plan)))

    def test_active_thread_type_guard(self):
        plan = good_plan()
        plan.va.active_thread_type = 1
        self.assertTrue(any("active_thread_type=0" in problem
                            for problem in c.validate_plan(plan)))

    def test_single_owner_guard(self):
        plan = good_plan()
        plan.va.single_application_owner = False
        self.assertTrue(any("one application owner" in problem
                            for problem in c.validate_plan(plan)))

    def test_owner_operations_are_exact(self):
        plan = good_plan()
        plan.va.owner_operations = ("send", "receive", "finish", "close")
        self.assertTrue(any("owner_operations" in problem for problem in c.validate_plan(plan)))

    def test_finish_before_close_guard(self):
        plan = good_plan()
        plan.va.finish_before_close = False
        self.assertTrue(any("before avcodec_free_context" in problem
                            for problem in c.validate_plan(plan)))

    def test_fatal_cleanup_guard(self):
        plan = good_plan()
        plan.va.fatal_cleanup_is_failure = False
        self.assertTrue(any("fatal quarantined" in problem
                            for problem in c.validate_plan(plan)))

    def test_sticky_failure_guard(self):
        plan = good_plan()
        plan.va.sticky_failure_invalidates_result = False
        self.assertTrue(any("invalidate result" in problem
                            for problem in c.validate_plan(plan)))


class Contracts(unittest.TestCase):
    def test_va_contract_has_exact_private_options_and_cleanup(self):
        plan = good_plan()
        off = c.client_contract(plan, workload(plan, "E-va-off"))
        on = c.client_contract(plan, workload(plan, "E-va-on"))
        self.assertEqual(off["private_options"]["va_observer_outputs"], "1,4,7")
        self.assertEqual(on["private_options"]["va_observer_outputs"], "1,4,7")
        self.assertEqual(off["private_options"]["va_observer_copy"], 0)
        self.assertEqual(on["private_options"]["va_observer_copy"], 1)
        self.assertEqual(on["private_options"]["threads"], 1)
        self.assertEqual(on["persistent_end_failure"], "fatal_quarantine")
        self.assertEqual(on["result_report"], {
            "private_option": "va_observer_report",
            "destination": "runner_allocated_exclusive_path",
            "schema": "omarchy.hevc.va-observer-result/v1",
            "publication": "renameat2(RENAME_NOREPLACE)",
            "max_bytes": 8192,
            "require_process_exit_zero": True,
        })
        self.assertEqual(tuple(on["requirements"]["owner_operations"]),
                         c.VA_OWNER_OPERATIONS)

    def test_gst_contract_names_its_api_and_domain(self):
        plan = good_plan()
        contract = c.client_contract(plan, workload(plan, "B-gst-off"))
        self.assertEqual(contract["arm_api"], "gst_hevc_callsite_arm_frames")
        self.assertEqual(contract["selector"],
                         {"domain": c.GST_SELECTOR, "values": list(GST_B)})
        self.assertFalse(contract["copy"])

    def test_json_is_deterministic_and_keeps_domains_distinct(self):
        first = good_plan().to_json()
        second = good_plan().to_json()
        self.assertEqual(first, second)
        document = json.loads(first)
        self.assertTrue(document["valid"])
        self.assertEqual(document["problems"], [])
        self.assertFalse(document["execution_authorized"])
        by_name = {item["name"]: item for item in document["workloads"]}
        self.assertEqual(by_name["E-va-on"]["selector_domain"], c.VA_SELECTOR)
        self.assertEqual(by_name["E-gst-on"]["selector_domain"], c.GST_SELECTOR)

    def test_invalid_json_carries_reasons_and_never_authorizes(self):
        plan = good_plan()
        plan.va.decoder_threads = 2
        document = json.loads(plan.to_json())
        self.assertFalse(document["valid"])
        self.assertTrue(any("decoder_threads=1" in item for item in document["problems"]))
        self.assertIs(document["execution_authorized"], False)


class Preconditions(unittest.TestCase):
    def test_healthy_state_has_no_problems(self):
        self.assertEqual(good_pre().problems(), [])

    def test_each_unhealthy_state_is_named(self):
        for field, bad, expect in (("healthy_idle", False, "healthy idle"),
                                   ("foreign_client_absent", False, "foreign client"),
                                   ("journal_boundary", "", "journal boundary"),
                                   ("module_loaded", False, "not loaded"),
                                   ("decoder_refcount", 3, "refcount")):
            precondition = good_pre()
            setattr(precondition, field, bad)
            self.assertTrue(any(expect in problem for problem in precondition.problems()))


class Authorization(unittest.TestCase):
    def test_complete_authorization_checks_out(self):
        good_auth().check()

    def test_each_missing_field_refuses(self):
        for field in ("operator", "guard_lease_id", "approved_manifest_sha256",
                      "issue_authorization_url", "hardware_window"):
            authorization = c.Authorization(**{**vars(good_auth()), field: ""})
            with self.assertRaises(c.AuthorizationError):
                authorization.check()

    def test_manifest_digest_must_be_sha256(self):
        authorization = c.Authorization(**{
            **vars(good_auth()), "approved_manifest_sha256": "abc"})
        with self.assertRaises(c.AuthorizationError):
            authorization.check()


class Execution(unittest.TestCase):
    def test_execute_refuses_even_with_valid_plan_and_authorization(self):
        with self.assertRaises(c.AuthorizationError) as caught:
            c.Controller(good_plan()).execute(good_auth(), good_pre())
        self.assertIn("not authorized", str(caught.exception))

    def test_execute_reports_plan_problems_before_refusing(self):
        plan = good_plan()
        plan.va.decoder_threads = 2
        with self.assertRaises(c.PlanError):
            c.Controller(plan).execute(good_auth(), good_pre())

    def test_execute_reports_precondition_problems(self):
        precondition = good_pre()
        precondition.decoder_refcount = 2
        with self.assertRaises(c.PlanError):
            c.Controller(good_plan()).execute(good_auth(), precondition)

    def test_execute_refuses_incomplete_authorization_first(self):
        authorization = c.Authorization(**{**vars(good_auth()), "guard_lease_id": ""})
        with self.assertRaises(c.AuthorizationError):
            c.Controller(good_plan()).execute(authorization, good_pre())


class Cli(unittest.TestCase):
    def _valid(self):
        return [
            "--gst-pool-size", str(GST_POOL),
            "--va-output-count", str(VA_OUTPUT_COUNT),
            "--gst-e-frames", *map(str, GST_E),
            "--gst-b-frames", *map(str, GST_B),
            "--va-e-outputs", *map(str, VA_E),
            "--va-b-outputs", *map(str, VA_B),
            "--gst-e-last-input", "9", "--gst-b-last-input", "4",
            "--va-e-last-input", "12", "--va-b-last-input", "6",
        ]

    def _run(self, *args):
        return subprocess.run([sys.executable, str(CONTROLLER), *args],
                              capture_output=True, text=True)

    def test_valid_plan_exits_zero_and_says_it_is_unauthorized(self):
        result = self._run(*self._valid())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("NOT authorized", result.stdout)

    def test_bad_gst_plan_exits_nonzero_with_reason(self):
        arguments = self._valid()
        arguments[1] = "4"
        result = self._run(*arguments)
        self.assertEqual(result.returncode, 1)
        self.assertIn("publication boundary", result.stdout)

    def test_json_output_contains_machine_contracts(self):
        result = self._run(*self._valid(), "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        document = json.loads(result.stdout.split("\n\n")[0])
        self.assertEqual(len(document["workloads"]), 8)
        self.assertTrue(all("client_contract" in item for item in document["workloads"]))

    def test_rejected_json_is_machine_readable_and_marks_invalid(self):
        arguments = self._valid()
        arguments[1] = "4"
        result = self._run(*arguments, "--json")
        self.assertEqual(result.returncode, 1)
        document = json.loads(result.stdout.split("\n\n")[0])
        self.assertFalse(document["valid"])
        self.assertFalse(document["execution_authorized"])
        self.assertTrue(any("publication boundary" in item
                            for item in document["problems"]))

    def test_ambiguous_legacy_cli_is_rejected(self):
        result = self._run("--pool-size", "16", "--e-frames", "2", "5", "9",
                           "--b-frames", "3")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--gst-pool-size", result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
