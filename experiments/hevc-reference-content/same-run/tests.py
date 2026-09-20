#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Offline same-run join and supervisor-interface tests; no device or sudo."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import join
import supervisor

VA_COLLECTOR_SPEC = importlib.util.spec_from_file_location(
    "same_run_va_collector", HERE.parent / "va-callsite/collector.py")
assert VA_COLLECTOR_SPEC and VA_COLLECTOR_SPEC.loader
va_collector = importlib.util.module_from_spec(VA_COLLECTOR_SPEC)
VA_COLLECTOR_SPEC.loader.exec_module(va_collector)


def base_request(pic: int, target: int, poc: int) -> dict[str, object]:
    return {
        "schema": join.VA_TRACE_SCHEMA, "run": "00000000000000aa", "seq": pic,
        "ctx": 1, "va_context": "direct-v4l2", "pic": pic, "req": pic,
        "first": 1, "last": 1, "target": target, "poc": poc,
        "irap": int(pic == 1), "idr": int(pic == 1), "ltr_sps": 0,
        "reorder": 1, "total_curr": 0, "dpb": [],
        "slices": [{"i": 0, "type": "I", "nal": 19 if pic == 1 else 1,
                    "l0": [], "l1": [], "tmvp": 0}],
        "st_before": [], "st_after": [], "lt_curr": [],
    }


def evidence() -> join.KernelEvidence:
    pocs = (0, 5, 2, 4)
    requests = tuple(base_request(pic, pic - 1, pocs[pic - 1]) for pic in range(1, 5))
    associations = tuple({"pic": pic, "poc": pocs[pic - 1],
                          "system_frame_number": 100 + pic}
                         for pic in range(1, 5))
    records: list[dict[str, object]] = []
    for pic in range(1, 5):
        common = {"buffer": pic - 1, "writer": pic, "allocation": 1000 + pic,
                  "length": 345600, "comp_start": 161280, "comp_size": 177152,
                  "mv_size": 7168, "mv_offset": 338432, "picture": pic}
        records.append(common | {"kind": 1, "completed": 0})
        records.append(common | {"kind": 2, "completed": 1, "result": 5})
    hashes = {name: hashlib.sha256(name.encode()).hexdigest() for name in
              ("execution", "v4l2_trace", "command_snapshot", "reference_snapshot")}
    return join.KernelEvidence(run=77, context=88, child_pid=999,
                               requests=requests, associations=associations,
                               reference_records=tuple(records), hashes=hashes)


def hex16(value: int) -> str:
    return f"{value:016x}"


def va_material(copy_mode: bool = True):
    ev = evidence(); run = ("1111111111111111", "2222222222222222")
    queue = []
    for row in ev.requests:
        pic = row["pic"]
        queue.append(row | {"observer": {
            "run": "".join(run), "context": 50, "allocation": 200 + pic,
            "surface": 300 + pic, "writer": 400 + pic}})
    associations = [
        {"output_index": 0, "pic": 1, "poc": 0},
        {"output_index": 1, "pic": 3, "poc": 2},
        {"output_index": 2, "pic": 4, "poc": 4},
        {"output_index": 3, "pic": 2, "poc": 5},
    ]
    selected = queue[2]
    report = {"schema": join.VA_SCHEMA, "count": 1, "outputs": [{
        "output_ordinal": 1, "surface": 73, "run": list(run),
        "context_generation": hex16(50), "session": hex16(60),
        "allocation_generation": hex16(selected["observer"]["allocation"]),
        "writer": hex16(selected["observer"]["writer"]),
        "submitted": hex16(3), "completed": hex16(3),
        "capture_index": selected["target"], "copied": copy_mode,
        "sha256": "ab" * 32 if copy_mode else None,
    }]}
    raw = b"".join(json.dumps(row, separators=(",", ":")).encode() + b"\n"
                    for row in queue)
    return ev, report, raw, associations


def gst_material(copy_mode: bool = True):
    ev = evidence(); run = ("3333333333333333", "4444444444444444")
    queue = []
    lines = []
    for item, request in zip(ev.associations, ev.requests):
        pic = item["pic"]
        row = {"run": list(run), "context": 70, "allocation": 800 + pic,
               "request": 900 + pic, "writer": 1000 + pic,
               "frame": item["system_frame_number"], "capture": request["target"]}
        queue.append(row)
        lines.append("0:00 TRACE v4l2codecs observer-queue " +
                     f"run={run[0]}{run[1]} context={row['context']} " +
                     f"allocation={row['allocation']} request={row['request']} " +
                     f"writer={row['writer']} frame={row['frame']} capture={row['capture']}\n")
    selected = queue[2]
    report = {"schema": join.GST_SCHEMA, "count": 1, "outputs": [{
        "system_frame_number": selected["frame"], "request": hex16(selected["request"]),
        "run": list(run), "context_generation": hex16(selected["context"]),
        "session": hex16(80), "allocation_generation": hex16(selected["allocation"]),
        "writer": hex16(selected["writer"]), "submitted": hex16(3),
        "completed": hex16(3), "capture_index": selected["capture"],
        "copied": copy_mode, "sha256": "cd" * 32 if copy_mode else None,
    }]}
    associations = [
        {"output_index": 0, "pic": 1, "poc": 0},
        {"output_index": 1, "pic": 3, "poc": 2},
        {"output_index": 2, "pic": 4, "poc": 4},
        {"output_index": 3, "pic": 2, "poc": 5},
    ]
    return ev, report, "".join(lines).encode(), associations


class ClientJoin(unittest.TestCase):
    def test_va_exact_identity_chain(self):
        ev, report, raw, associations = va_material()
        result = join.join_va(ev, report, raw, associations, (1,), True, join.digest(raw))
        self.assertEqual(result["selected"][0]["bridge"], {
            "picture": 3, "poc": 2, "capture_index": 2,
            "client_surface_generation": "303",
            "kernel_allocation": "1003", "kernel_writer": 3,
            "kernel_completed": True})
        encoded = join.encode(result)
        self.assertLessEqual(len(encoded), join.MAX_OUTPUT_BYTES)
        def keys(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    yield key
                    yield from keys(child)
            elif isinstance(value, list):
                for child in value:yield from keys(child)
        for key in keys(result):
            self.assertFalse(any(word in key.lower() for word in
                                 ("timestamp", "fd", "dma", "pointer", "lease", "bytes")))

    def test_gst_exact_identity_chain(self):
        ev, report, raw, associations = gst_material()
        result = join.join_gst(ev, report, raw, associations, (103,), True,
                               join.digest(raw))
        self.assertEqual(result["selected"][0]["bridge"]["picture"], 3)
        self.assertEqual(result["selected"][0]["client"]["request"], hex16(903))

    def test_copy_off_has_no_digest(self):
        ev, report, raw, associations = va_material(False)
        result = join.join_va(ev, report, raw, associations, (1,), False, join.digest(raw))
        self.assertIsNone(result["selected"][0]["client"]["sha256"])

    def test_va_report_queue_mismatches_reject(self):
        changes = {
            "run": lambda output: output["run"].__setitem__(0, "9999999999999999"),
            "context": lambda output: output.__setitem__("context_generation", hex16(51)),
            "allocation": lambda output: output.__setitem__("allocation_generation", hex16(999)),
            "writer": lambda output: output.__setitem__("writer", hex16(999)),
            "capture": lambda output: output.__setitem__("capture_index", 1),
        }
        for name, change in changes.items():
            with self.subTest(name=name):
                ev, report, raw, associations = va_material(); change(report["outputs"][0])
                with self.assertRaises(join.JoinError):
                    join.join_va(ev, report, raw, associations, (1,), True, join.digest(raw))

    def test_gst_report_queue_mismatches_reject(self):
        for field in ("context_generation", "allocation_generation", "request", "writer"):
            with self.subTest(field=field):
                ev, report, raw, associations = gst_material()
                report["outputs"][0][field] = hex16(9999)
                with self.assertRaises(join.JoinError):
                    join.join_gst(ev, report, raw, associations, (103,), True, join.digest(raw))

    def test_va_queue_must_be_the_same_raw_process(self):
        ev, report, raw, associations = va_material()
        rows = join.json_lines(raw, maximum=join.MAX_QUEUE_BYTES, name="fixture")
        rows[0]["poc"] = 99
        raw = b"".join(json.dumps(row, separators=(",", ":")).encode() + b"\n" for row in rows)
        with self.assertRaisesRegex(join.JoinError, "raw V4L2 request"):
            join.join_va(ev, report, raw, associations, (1,), True, join.digest(raw))

    def test_gst_queue_must_bridge_raw_timestamp_and_capture(self):
        ev, report, raw, associations = gst_material()
        bad = raw.replace(b"frame=101 capture=0", b"frame=999 capture=0")
        with self.assertRaisesRegex(join.JoinError, "raw V4L2 timestamp bridge"):
            join.join_gst(ev, report, bad, associations, (103,), True, join.digest(bad))
        bad = raw.replace(b"frame=101 capture=0", b"frame=101 capture=3")
        with self.assertRaisesRegex(join.JoinError, "capture lifetime"):
            join.join_gst(ev, report, bad, associations, (103,), True, join.digest(bad))

    def test_ambiguous_raw_timestamp_and_stale_client_identity_reject(self):
        ev, report, raw, associations = gst_material()
        ambiguous = list(ev.associations)
        ambiguous[1] = ambiguous[1] | {
            "system_frame_number": ambiguous[0]["system_frame_number"]}
        evidence_with_ambiguous_frame = join.KernelEvidence(
            ev.run, ev.context, ev.child_pid, ev.requests, tuple(ambiguous),
            ev.reference_records, ev.hashes)
        with self.assertRaisesRegex(join.JoinError, "timestamps are ambiguous"):
            join.join_gst(evidence_with_ambiguous_frame, report, raw, associations,
                          (103,), True, join.digest(raw))

        ev, report, raw, associations = gst_material()
        lines = join.parse_gst_queue(raw, len(ev.requests))
        stale = lines[0]
        output = report["outputs"][0]
        output["allocation_generation"] = hex16(stale["allocation"])
        output["request"] = hex16(stale["request"])
        output["writer"] = hex16(stale["writer"])
        output["capture_index"] = stale["capture"]
        with self.assertRaisesRegex(join.JoinError, "identity mismatch"):
            join.join_gst(ev, report, raw, associations, (103,), True, join.digest(raw))

    def test_kernel_lifetime_must_be_complete_and_exact(self):
        for field, value in (("buffer", 3), ("writer", 99), ("completed", 0),
                             ("allocation", 0)):
            with self.subTest(field=field):
                ev, report, raw, associations = gst_material()
                records = list(copy.deepcopy(ev.reference_records))
                target = next(row for row in records
                              if row["picture"] == 3 and
                              (row["kind"] == 2 if field == "completed" else row["kind"] == 1))
                target[field] = value
                bad = join.KernelEvidence(ev.run, ev.context, ev.child_pid, ev.requests,
                                          ev.associations, tuple(records), ev.hashes)
                with self.assertRaises(join.JoinError):
                    join.join_gst(bad, report, raw, associations, (103,), True, join.digest(raw))

    def test_report_frontier_and_queue_extent_reject(self):
        ev, report, raw, associations = gst_material()
        report["outputs"][0]["completed"] = hex16(2)
        with self.assertRaisesRegex(join.JoinError, "drained completion frontier"):
            join.join_gst(ev, report, raw, associations, (103,), True, join.digest(raw))
        ev, report, raw, associations = gst_material()
        with self.assertRaisesRegex(join.JoinError, "wrong request extent"):
            join.join_gst(ev, report, raw.splitlines(keepends=True)[0], associations,
                          (103,), True, join.digest(raw))

    def test_duplicate_json_and_malformed_queue_reject(self):
        with self.assertRaisesRegex(join.JoinError, "duplicate JSON key"):
            join.json_document(b'{"a":1,"a":2}\n', maximum=100, name="fixture")
        ev, report, raw, associations = va_material()
        report["outputs"][0]["raw_pointer"] = "0x1234"
        with self.assertRaisesRegex(join.JoinError, "unexpected fields"):
            join.join_va(ev, report, raw, associations, (1,), True, join.digest(raw))
        ev, report, raw, associations = gst_material()
        raw = raw.replace(b"observer-queue", b"observer-queue broken", 1)
        with self.assertRaisesRegex(join.JoinError, "malformed"):
            join.join_gst(ev, report, raw, associations, (103,), True, join.digest(raw))


class VACollectorHardening(unittest.TestCase):
    def valid(self):
        _, report, _, _ = va_material()
        return report

    def encoded(self, report):
        return json.dumps(report, separators=(",", ":")).encode() + b"\n"

    def test_valid_report_and_external_expectations(self):
        report = self.valid()
        self.assertEqual(va_collector.parse_report(
            self.encoded(report), expected_outputs=(1,), expected_copy=True), report)
        for outputs in ((), (1, 1), (-1,), (1 << 64,)):
            with self.assertRaises(va_collector.ReportError):
                va_collector.parse_report(self.encoded(report), expected_outputs=outputs)

    def test_zero_and_reversed_identity_or_noncanonical_record_reject(self):
        mutations = []
        for field in ("context_generation", "session", "allocation_generation", "writer"):
            def change(document, field=field):document["outputs"][0][field] = "0" * 16
            mutations.append(change)
        mutations += [
            lambda document: document["outputs"][0].__setitem__("run", ["0" * 16, "0" * 16]),
            lambda document: document["outputs"][0].__setitem__("completed", hex16(2)),
        ]
        for change in mutations:
            report = self.valid(); change(report)
            with self.assertRaises(va_collector.ReportError):
                va_collector.parse_report(self.encoded(report))
        valid = self.encoded(self.valid())
        for raw in (valid + b"{}\n", valid.replace(b"\n", b"\r\n")):
            with self.assertRaises(va_collector.ReportError):
                va_collector.parse_report(raw)


class SupervisorBoundary(unittest.TestCase):
    def test_va_association_accepts_ffmpeg_debug_prefix(self):
        evidence = SimpleNamespace(requests=({"poc": 4, "pic": 1}, {"poc": 2, "pic": 2}))
        raw = b"[hevc @ 0xab12] Output frame with POC 0/2.\n[hevc @ 0xab12] Output frame with POC 0/4.\n"
        self.assertEqual(supervisor.va_associations(raw, evidence), [
            {"output_index": 0, "pic": 2, "poc": 2},
            {"output_index": 1, "pic": 1, "poc": 4}])
        with self.assertRaises(join.JoinError):
            supervisor.va_associations(raw.replace(b"hevc @", b"h264 @"), evidence)

    def test_va_command_is_exact_and_placeholder_is_private(self):
        command = ("ffmpeg", "-threads:v:0", "1", "-hwaccel", "vaapi",
                   "-va_observer_outputs:v:0", "1,3", "-va_observer_copy:v:0", "1",
                   "-va_observer_report:v:0", supervisor.PLACEHOLDER, "-i", "input.hevc")
        configured = supervisor.configure_command("va", command, (1, 3), True,
                                                   Path("/private/result.json"))
        self.assertIn("/private/result.json", configured)
        self.assertNotIn(supervisor.PLACEHOLDER, configured)

    def test_gst_command_is_exact_and_never_a_shell(self):
        command = ("gst-launch-1.0", "v4l2slh265dec",
                   "hevc-observer-frames=2,5", "hevc-observer-copy=false",
                   "hevc-observer-report=" + supervisor.PLACEHOLDER)
        configured = supervisor.configure_command("gst", command, (2, 5), False,
                                                   Path("/private/result.json"))
        self.assertEqual(configured[-1], "hevc-observer-report=/private/result.json")
        for bad in (("sh", "-c", "decoder"), command[1:],
                    tuple(value.replace("2,5", "2,6") for value in command),
                    ("gst-launch-1.0", "v4l2slh265dec", "!", "fakesink") + command[2:],
                    command + ("hevc-observer-frames=2,5",)):
            with self.assertRaises(join.JoinError):
                supervisor.configure_command("gst", bad, (2, 5), False,
                                             Path("/private/result.json"))

    def test_publication_is_private_exclusive_and_stable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); path = root / "result.json"
            supervisor.publish(path, b'{"ok":true}\n')
            self.assertEqual(path.read_bytes(), b'{"ok":true}\n')
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            with self.assertRaises((join.JoinError, OSError)):
                supervisor.publish(path, b'{"ok":false}\n')
            self.assertEqual(path.read_bytes(), b'{"ok":true}\n')

    def test_publication_race_cannot_replace_a_new_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            original = supervisor._write_all
            def raced(fd, raw):
                original(fd, raw)
                path.write_bytes(b"intruder\n")
            with mock.patch.object(supervisor, "_write_all", side_effect=raced):
                with self.assertRaises(OSError):
                    supervisor.publish(path, b'{"ok":true}\n')
            self.assertEqual(path.read_bytes(), b"intruder\n")

    def test_publication_write_failure_leaves_no_result(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); path = root / "result.json"
            with mock.patch.object(supervisor, "_write_all",
                                   side_effect=OSError("injected write failure")):
                with self.assertRaisesRegex(OSError, "injected write failure"):
                    supervisor.publish(path, b'{"ok":true}\n')
            self.assertFalse(path.exists())
            self.assertEqual(list(root.iterdir()), [])

    def test_tracer_wraps_the_supervisor_worker_not_the_decoder(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); spec = root / "worker-spec.json"; spec.write_text("{}\n")
            process = SimpleNamespace(wait=mock.Mock(return_value=0), pid=123)
            with mock.patch.object(supervisor.subprocess, "Popen", return_value=process) as popen:
                self.assertEqual(supervisor._run_tracer(root, spec, 3), 0)
            command = popen.call_args.args[0]
            self.assertEqual(command[:3], ["v4l2-tracer", "-u", "trace"])
            self.assertEqual(Path(command[3]), Path(sys.executable))
            self.assertEqual(command[-2:], ["--worker-spec", str(spec)])
            self.assertNotIn("ffmpeg", command)
            self.assertNotIn("gst-launch-1.0", command)

    def test_paired_supervisor_binds_environment_cwd_logs_and_exact_pid(self):
        class Fake:
            def __init__(self, name, calls):
                self.name = name; self.calls = calls
                self.state = {"run": 0, "context": 0, "phase": 0, "errors": 0,
                              "pictures": 0, "completions": 0, "opens": 0}
            def status(self):return copy.deepcopy(self.state)
            def control(self, operation):
                self.calls.append((self.name, operation))
                if operation.startswith("arm "):
                    _, run, _ = operation.split(); self.state.update(run=int(run), phase=1)
                elif operation.startswith("seal "):
                    self.state.update(context=55, phase=4, pictures=300, completions=300)
                elif operation == "off":
                    self.state = {key: 0 for key in self.state}
                else:raise AssertionError(operation)
            def snapshot(self):return (self.name + " snapshot\n").encode()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); work = root / "work"; work.mkdir()
            calls = []; backends = {name: Fake(name, calls) for name in supervisor.capture.PATHS}
            environment = os.environ.copy(); environment["SAME_RUN_TEST"] = "bound"
            result = supervisor.capture.supervise(
                [sys.executable, "-c", "import os,sys;print(os.environ['SAME_RUN_TEST']);print(os.getcwd(),file=sys.stderr)"],
                91, True, 3, backends, supervisor.capture.Store(root / "kernel"),
                environment=environment, working_directory=work,
                stdout_path=root / "stdout", stderr_path=root / "stderr")
            self.assertEqual(result["child_exit"], 0)
            self.assertEqual((root / "stdout").read_text(), "bound\n")
            self.assertEqual((root / "stderr").read_text(), str(work) + "\n")
            arms = [operation.split() for _, operation in calls if operation.startswith("arm ")]
            self.assertEqual(len(arms), 2)
            self.assertTrue(all(int(words[2]) == result["child_pid"] for words in arms))
            self.assertEqual(stat.S_IMODE((root / "stdout").stat().st_mode), 0o600)

    def test_paired_supervisor_optional_contract_rejects_before_fork(self):
        backends = {name: object() for name in supervisor.capture.PATHS}
        with self.assertRaises(ValueError):
            supervisor.capture.supervise(["true"], 1, True, 3, backends,
                                         environment={"bad": 1})
        with self.assertRaises(ValueError):
            supervisor.capture.supervise(["true"], 1, True, 3, backends,
                                         stdout_path=Path("only-one-log"))

    def test_paired_supervisor_preserves_nonzero_child_without_clearing(self):
        class Fake:
            def __init__(self, name, calls):
                self.name = name; self.calls = calls
                self.state = {"run": 0, "context": 0, "phase": 0, "errors": 0,
                              "pictures": 0, "completions": 0, "opens": 0}
            def status(self):return copy.deepcopy(self.state)
            def control(self, operation):
                self.calls.append((self.name, operation))
                if operation.startswith("arm "):
                    self.state.update(run=int(operation.split()[1]), phase=1)
                elif operation.startswith("seal "):
                    self.state.update(context=55, phase=4,
                                      pictures=300, completions=300)
                elif operation == "off":
                    self.state = {key: 0 for key in self.state}
                else:raise AssertionError(operation)
            def snapshot(self):return (self.name + " failed-child snapshot\n").encode()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); calls = []
            backends = {name: Fake(name, calls) for name in supervisor.capture.PATHS}
            result = supervisor.capture.supervise(
                [sys.executable, "-c", "raise SystemExit(23)"], 92, True, 3,
                backends, supervisor.capture.Store(root / "kernel"))
            self.assertEqual(result["child_exit"], 23)
            self.assertTrue(result["child_reaped"])
            self.assertNotIn(("reference", "off"), calls)
            self.assertNotIn(("command", "off"), calls)
            self.assertEqual(set(result["snapshots"]), {"reference", "command"})


class RawValidatorBoundary(unittest.TestCase):
    def fixture(self, root: Path):
        command = b"command snapshot\n"; reference = b"reference snapshot\n"
        events = [{"stage": stage, "recorder": recorder,
                   "seconds": float(index) / 100}
                  for index, (stage, recorder) in enumerate(supervisor.validator.SUCCESS_EVENTS)]
        execution = {
            "schema": "hevc-avd-command-capture.execution/1", "run": 77,
            "enabled": True, "child_pid": 999, "child_exit": 0,
            "child_reaped": True, "child_released": True, "errors": [],
            "elapsed_seconds": 0.15, "events": events,
            "status": {
                "reference": {"run": 77, "context": 88, "phase": 4,
                              "errors": 0, "count": 600, "attempted": 600,
                              "pictures": 300, "completions": 300, "opens": 0},
                "command": {"run": 77, "context": 88, "phase": 4,
                            "errors": 0, "pictures": 300,
                            "completions": 300, "opens": 0},
            },
            "snapshots": {
                "reference": {"bytes": len(reference),
                              "sha256": hashlib.sha256(reference).hexdigest()},
                "command": {"bytes": len(command),
                            "sha256": hashlib.sha256(command).hexdigest()},
            },
        }
        values = {"execution": json.dumps(execution).encode() + b"\n",
                  "trace": b"trace\n", "command": command, "reference": reference,
                  "uapi": b"uapi\n", "identity": b"{}\n"}
        paths = {}
        for name, raw in values.items():
            path = root / name; path.write_bytes(raw); path.chmod(0o600); paths[name] = path
        oracle = root / "oracle"; oracle.mkdir(mode=0o700)
        paths["identity"].replace(oracle / "identity.json")
        paths["oracle"] = oracle
        return paths

    def test_execution_event_transcript_is_exact(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = self.fixture(Path(directory))
            document = json.loads(paths["execution"].read_bytes())
            snapshots = {"command": paths["command"].read_bytes(),
                         "reference": paths["reference"].read_bytes()}
            self.assertEqual(supervisor.validator._execution(document, snapshots),
                             (77, 88, 999))
            document["events"].pop(3)
            with self.assertRaisesRegex(join.JoinError, "event transcript"):
                supervisor.validator._execution(document, snapshots)

    def test_execution_rejects_child_recorder_context_and_stale_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = self.fixture(Path(directory))
            original = json.loads(paths["execution"].read_bytes())
            snapshots = {"command": paths["command"].read_bytes(),
                         "reference": paths["reference"].read_bytes()}
            mutations = {
                "child death/nonzero": lambda document: document.__setitem__("child_exit", 9),
                "recorder loss": lambda document:
                    document["status"]["reference"].__setitem__("pictures", 299),
                "recorder error": lambda document:
                    document["status"]["command"].__setitem__("errors", 1),
                "foreign context": lambda document:
                    document["status"]["command"].__setitem__("context", 89),
                "stale snapshot": lambda document:
                    document["snapshots"]["command"].__setitem__("sha256", "0" * 64),
            }
            for name, mutation in mutations.items():
                with self.subTest(name=name):
                    document = copy.deepcopy(original); mutation(document)
                    with self.assertRaises(join.JoinError):
                        supervisor.validator._execution(document, snapshots)

    def test_actual_validator_chain_is_invoked_before_evidence_exists(self):
        ev = evidence()
        with tempfile.TemporaryDirectory() as directory:
            paths = self.fixture(Path(directory))
            reference_checker = SimpleNamespace(
                read_capture=mock.Mock(return_value={"context": 88}),
                validate=mock.Mock(return_value={"findings": [],
                                                 "records": list(ev.reference_records)}),
                model=SimpleNamespace(map_records=mock.Mock(return_value=["mapped"])))
            command_capture = {"context": 88, "windows": [{"picture": 24}]}
            with mock.patch.object(supervisor.validator.full.base, "parse", return_value=["events"]) as parse, \
                 mock.patch.object(supervisor.validator.full, "normalize",
                                   return_value=([], list(ev.requests), list(ev.associations))) as normalize, \
                 mock.patch.object(supervisor.validator.full_report, "validate_controls") as lifecycle, \
                 mock.patch.object(supervisor.validator.command_parser, "parse_snapshot",
                                   return_value=command_capture) as command_parse, \
                 mock.patch.object(supervisor.validator, "_load_reference_checker",
                                   return_value=reference_checker), \
                 mock.patch.object(supervisor.validator.command_parser, "bind_history") as bind, \
                 mock.patch.object(supervisor.validator.command_compare, "flag_values",
                                   return_value={}) as flags, \
                 mock.patch.object(supervisor.validator.command_compare, "compare",
                                   return_value=[]) as controls, \
                 mock.patch.object(supervisor.validator.command_oracle, "verify_identity") as identity, \
                 mock.patch.object(supervisor.validator.command_oracle, "verify_window",
                                   return_value=True) as oracle:
                actual = supervisor.validator.validate(
                    execution_path=paths["execution"], v4l2_trace_path=paths["trace"],
                    command_snapshot_path=paths["command"],
                    reference_snapshot_path=paths["reference"],
                    uapi_path=paths["uapi"], oracle_path=paths["oracle"])
            self.assertEqual((actual.run, actual.context, actual.child_pid), (77, 88, 999))
            for called in (parse, normalize, lifecycle, command_parse, bind, flags,
                           controls, identity, oracle, reference_checker.read_capture,
                           reference_checker.validate, reference_checker.model.map_records):
                called.assert_called()

    def test_raw_validator_rejects_control_or_oracle_mismatch(self):
        ev = evidence()
        for failure in ("controls", "oracle"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                paths = self.fixture(Path(directory))
                checker = SimpleNamespace(
                    read_capture=mock.Mock(return_value={"context": 88}),
                    validate=mock.Mock(return_value={"findings": [],
                                                     "records": list(ev.reference_records)}),
                    model=SimpleNamespace(map_records=mock.Mock(return_value=[])))
                with mock.patch.object(supervisor.validator.full.base, "parse", return_value=[]), \
                     mock.patch.object(supervisor.validator.full, "normalize",
                                       return_value=([], list(ev.requests), list(ev.associations))), \
                     mock.patch.object(supervisor.validator.full_report, "validate_controls"), \
                     mock.patch.object(supervisor.validator.command_parser, "parse_snapshot",
                                       return_value={"context": 88, "windows": [{"picture": 24}]}), \
                     mock.patch.object(supervisor.validator, "_load_reference_checker",
                                       return_value=checker), \
                     mock.patch.object(supervisor.validator.command_parser, "bind_history"), \
                     mock.patch.object(supervisor.validator.command_compare, "flag_values",
                                       return_value={}), \
                     mock.patch.object(supervisor.validator.command_compare, "compare",
                                       return_value=["bad"] if failure == "controls" else []), \
                     mock.patch.object(supervisor.validator.command_oracle, "verify_identity"), \
                     mock.patch.object(supervisor.validator.command_oracle, "verify_window",
                                       return_value=failure != "oracle"):
                    with self.assertRaises(join.JoinError):
                        supervisor.validator.validate(
                            execution_path=paths["execution"],
                            v4l2_trace_path=paths["trace"],
                            command_snapshot_path=paths["command"],
                            reference_snapshot_path=paths["reference"],
                            uapi_path=paths["uapi"], oracle_path=paths["oracle"])

    def test_paired_kernel_context_must_match_supervisor(self):
        ev = evidence()
        with tempfile.TemporaryDirectory() as directory:
            paths = self.fixture(Path(directory))
            checker = SimpleNamespace(
                read_capture=mock.Mock(return_value={"context": 88}),
                validate=mock.Mock(return_value={"findings": [],
                                                 "records": list(ev.reference_records)}),
                model=SimpleNamespace(map_records=mock.Mock(return_value=[])))
            with mock.patch.object(supervisor.validator.full.base, "parse", return_value=[]), \
                 mock.patch.object(supervisor.validator.full, "normalize",
                                   return_value=([], list(ev.requests), list(ev.associations))), \
                 mock.patch.object(supervisor.validator.full_report, "validate_controls"), \
                 mock.patch.object(supervisor.validator.command_parser, "parse_snapshot",
                                   return_value={"context": 89, "windows": []}), \
                 mock.patch.object(supervisor.validator, "_load_reference_checker",
                                   return_value=checker), \
                 mock.patch.object(supervisor.validator.command_parser, "bind_history"):
                with self.assertRaisesRegex(join.JoinError, "paired kernel context"):
                    supervisor.validator.validate(
                        execution_path=paths["execution"], v4l2_trace_path=paths["trace"],
                        command_snapshot_path=paths["command"],
                        reference_snapshot_path=paths["reference"],
                        uapi_path=paths["uapi"], oracle_path=paths["oracle"])

    def test_readonly_root_owned_tool_input_is_not_a_private_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'tool-input'
            path.write_bytes(b'locked')
            path.chmod(0o644)
            original = os.fstat
            def root_stat(fd):
                source = original(fd)
                fields = {name: getattr(source, name) for name in dir(source)
                          if name.startswith('st_')}
                return SimpleNamespace(**(fields | {'st_uid': 0}))
            with mock.patch.object(os, 'fstat', side_effect=root_stat), \
                 mock.patch.object(os, 'geteuid', return_value=1001):
                self.assertEqual(supervisor.validator.safe_read(path, 10, 'tool', private=False), b'locked')
                with self.assertRaisesRegex(join.JoinError, 'ownership'):
                    supervisor.validator.safe_read(path, 10, 'capture')
                path.chmod(0o666)
                with self.assertRaisesRegex(join.JoinError, 'publicly writable'):
                    supervisor.validator.safe_read(path, 10, 'tool', private=False)

    def test_stable_private_file_boundary_rejects_mode_and_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); path = root / "evidence"; path.write_bytes(b"x")
            path.chmod(0o644)
            with self.assertRaisesRegex(join.JoinError, "not private"):
                supervisor.validator.safe_read(path, 10, "fixture")
            path.chmod(0o600); link = root / "link"; link.symlink_to(path)
            with self.assertRaisesRegex(join.JoinError, "cannot open"):
                supervisor.validator.safe_read(link, 10, "fixture")


if __name__ == "__main__":
    unittest.main()
