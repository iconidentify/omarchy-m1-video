#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Offline tests for the campaign controller. No device, module or client."""
import importlib.util
import pathlib
import subprocess
import sys
import unittest

HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("controller", HERE / "controller.py")
c = importlib.util.module_from_spec(spec)
# Register before exec: dataclasses resolves cls.__module__ through sys.modules,
# and a module loaded only through the spec is not there yet.
sys.modules["controller"] = c
spec.loader.exec_module(c)

POOL = 16
E_FRAMES = (2, 5, 9)
B_FRAMES = (3,)


def good_plan(**over):
    frames = {cl: {"E": E_FRAMES, "B": B_FRAMES} for cl in c.CLIENTS}
    plan = c.build_plan(over.pop("pool_size", POOL), frames,
                        over.pop("parameter_set_changes", None), run_id="test")
    for k, v in over.items():
        setattr(plan, k, v)
    return plan


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
        names = sorted(w.name for w in good_plan().workloads)
        self.assertEqual(len(names), 8)
        self.assertEqual(names, sorted({f"{v}-{cl}-{m}" for v in ("B", "E")
                                        for cl in ("va", "gst") for m in ("off", "on")}))

    def test_budget_is_exactly_consumed(self):
        selected = sum(len(w.frames) for w in good_plan().workloads)
        self.assertEqual(selected, c.MAX_SNAPSHOTS)
        self.assertEqual(selected * c.SNAPSHOT_BYTES, c.TOTAL_BYTES)

    def test_missing_workload_is_rejected(self):
        plan = good_plan()
        plan.workloads = [w for w in plan.workloads if w.name != "E-va-on"]
        self.assertTrue(any("eight" in p for p in c.validate_plan(plan)))

    def test_duplicate_workload_is_rejected(self):
        plan = good_plan()
        plan.workloads.append(plan.workloads[0])
        self.assertTrue(any("duplicate" in p for p in c.validate_plan(plan)))


class Selections(unittest.TestCase):
    def _first(self, plan):
        return [w for w in plan.workloads if w.name == "E-va-on"][0]

    def test_copy_off_control_must_not_select(self):
        plan = good_plan()
        [w for w in plan.workloads if w.name == "E-va-off"][0].frames = (1,)
        self.assertTrue(any("must select no frames" in p for p in c.validate_plan(plan)))

    def test_copy_on_without_selection_is_rejected(self):
        plan = good_plan()
        self._first(plan).frames = ()
        self.assertTrue(any("selects no frames" in p for p in c.validate_plan(plan)))

    def test_duplicate_frame_numbers_rejected(self):
        plan = good_plan()
        self._first(plan).frames = (2, 2, 5)
        self.assertTrue(any("distinct" in p for p in c.validate_plan(plan)))

    def test_too_many_selections_rejected(self):
        plan = good_plan()
        self._first(plan).frames = tuple(range(c.MAX_SELECTION + 1))
        self.assertTrue(any("outside 1.." in p for p in c.validate_plan(plan)))

    def test_selection_past_publication_boundary_rejected(self):
        plan = good_plan()
        self._first(plan).frames = (2, 5, POOL + 1)
        problems = c.validate_plan(plan)
        self.assertTrue(any("publication boundary" in p for p in problems), problems)

    def test_unknown_pool_size_rejected(self):
        plan = good_plan()
        self._first(plan).pool_size = 0
        self.assertTrue(any("pool_size must be known" in p for p in c.validate_plan(plan)))

    def test_parameter_set_change_inside_window_rejected(self):
        plan = good_plan(parameter_set_changes={"E": (4,), "B": ()})
        problems = c.validate_plan(plan)
        self.assertTrue(any("parameter-set change" in p for p in problems), problems)

    def test_parameter_set_change_after_window_is_allowed(self):
        plan = good_plan(parameter_set_changes={"E": (99,), "B": (99,)})
        self.assertEqual(c.validate_plan(plan), [])

    def test_slot_shape_enforced(self):
        plan = good_plan()
        self._first(plan).frames = (2, 5)     # two E slots, not three
        self.assertTrue(any("expected 3" in p for p in c.validate_plan(plan)))


class CallSiteProperties(unittest.TestCase):
    """Each documented limit of the merged call site must be checked, not assumed."""

    def test_reused_element_rejected(self):
        p = c.validate_plan(good_plan(fresh_element_per_observation=False))
        self.assertTrue(any("one observation per decoder element" in x for x in p))

    def test_arming_off_streaming_owner_rejected(self):
        p = c.validate_plan(good_plan(arm_on_streaming_owner=False))
        self.assertTrue(any("streaming owner" in x for x in p))

    def test_ignoring_flow_error_rejected(self):
        p = c.validate_plan(good_plan(treat_flow_error_as_failure=False))
        self.assertTrue(any("GST_FLOW_ERROR" in x for x in p))

    def test_lifecycle_before_finish_rejected(self):
        p = c.validate_plan(good_plan(finish_before_lifecycle_ops=False))
        self.assertTrue(any("finish" in x for x in p))


class Preconditions(unittest.TestCase):
    def test_healthy_state_has_no_problems(self):
        self.assertEqual(good_pre().problems(), [])

    def test_each_unhealthy_state_is_named(self):
        for field, bad, expect in (("healthy_idle", False, "healthy idle"),
                                   ("foreign_client_absent", False, "foreign client"),
                                   ("journal_boundary", "", "journal boundary"),
                                   ("module_loaded", False, "not loaded"),
                                   ("decoder_refcount", 3, "refcount")):
            pre = good_pre()
            setattr(pre, field, bad)
            self.assertTrue(any(expect in p for p in pre.problems()), f"{field} not reported")


class Authorization(unittest.TestCase):
    def test_complete_authorization_checks_out(self):
        good_auth().check()

    def test_each_missing_field_refuses(self):
        for field in ("operator", "guard_lease_id", "approved_manifest_sha256",
                      "issue_authorization_url", "hardware_window"):
            auth = c.Authorization(**{**vars(good_auth()), field: ""})
            with self.assertRaises(c.AuthorizationError):
                auth.check()

    def test_manifest_digest_must_be_sha256(self):
        auth = c.Authorization(**{**vars(good_auth()), "approved_manifest_sha256": "abc"})
        with self.assertRaises(c.AuthorizationError):
            auth.check()


class Execution(unittest.TestCase):
    def test_execute_refuses_even_with_valid_plan_and_authorization(self):
        ctrl = c.Controller(good_plan())
        with self.assertRaises(c.AuthorizationError) as caught:
            ctrl.execute(good_auth(), good_pre())
        self.assertIn("not authorized", str(caught.exception))

    def test_execute_reports_plan_problems_before_refusing(self):
        ctrl = c.Controller(good_plan(arm_on_streaming_owner=False))
        with self.assertRaises(c.PlanError):
            ctrl.execute(good_auth(), good_pre())

    def test_execute_reports_precondition_problems(self):
        ctrl = c.Controller(good_plan())
        pre = good_pre()
        pre.decoder_refcount = 2
        with self.assertRaises(c.PlanError):
            ctrl.execute(good_auth(), pre)

    def test_execute_refuses_incomplete_authorization_first(self):
        ctrl = c.Controller(good_plan())
        auth = c.Authorization(**{**vars(good_auth()), "guard_lease_id": ""})
        with self.assertRaises(c.AuthorizationError):
            ctrl.execute(auth, good_pre())


class Cli(unittest.TestCase):
    def _run(self, *args):
        return subprocess.run([sys.executable, str(HERE / "controller.py"), *args],
                              capture_output=True, text=True)

    def test_valid_plan_exits_zero_and_says_it_is_unauthorized(self):
        r = self._run("--pool-size", str(POOL), "--e-frames", "2", "5", "9",
                      "--b-frames", "3")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("NOT authorized", r.stdout)

    def test_bad_plan_exits_nonzero_with_reason(self):
        r = self._run("--pool-size", "4", "--e-frames", "2", "5", "9", "--b-frames", "3")
        self.assertEqual(r.returncode, 1)
        self.assertIn("publication boundary", r.stdout)

    def test_json_output_is_parseable(self):
        import json
        r = self._run("--pool-size", str(POOL), "--e-frames", "2", "5", "9",
                      "--b-frames", "3", "--json")
        doc = json.loads(r.stdout.split("\n\n")[0] if "\n\n" in r.stdout else r.stdout)
        self.assertEqual(len(doc["workloads"]), 8)


if __name__ == "__main__":
    unittest.main(verbosity=2)
