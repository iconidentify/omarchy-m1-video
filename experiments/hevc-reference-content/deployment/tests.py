#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""No-device tests for deployment identity, target and admission gates."""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import admission
import manifest


def load_controller():
    path = HERE.parent / "campaign/controller.py"
    spec = importlib.util.spec_from_file_location("deployment_test_controller", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


controller = load_controller()


class Fixture:
    def __init__(self, root: Path):
        self.root = root
        source = root / "tiny.c"
        source.write_text(
            "void v4l2r_observer_client_abi(void){}\n"
            "void v4l2r_observer_open(void){}\n"
            "void v4l2r_observer_select(void){}\n"
            "void v4l2r_observer_begin(void){}\n"
            "void v4l2r_observer_end(void){}\n"
            "void v4l2r_observer_close(void){}\n"
            "void v4l2r_content_init(void){}\n"
            "void v4l2r_content_snapshot(void){}\n"
            'const char observer_tokens[] = "va_observer_outputs va_observer_copy '
            'va_observer_report hevc-observer-frames hevc-observer-copy '
            'hevc-observer-report observer-queue h265parse videoconvert filesink";\n'
            "int main(void){return observer_tokens[0] == 0;}\n")
        self.elf = root / "artifact"
        subprocess.run(["cc", "-Wl,--build-id", "-Wl,--export-dynamic",
                        str(source), "-o", str(self.elf)],
                       check=True, capture_output=True)
        self.dependencies = manifest.dependency_closure(self.elf)
        self.patch = root / "observer.patch"
        self.patch.write_text("fixture patch\n")
        self.corpus = {}
        for vector in ("B", "E"):
            path = root / (vector + ".bit")
            path.write_bytes((vector.encode() + b"-") * 32)
            self.corpus[vector] = {"path": str(path), "sha256": manifest.digest(path),
                                   "bytes": path.stat().st_size, "frames": 300}
        self.reference = root / "reference.json"
        self.reference.write_text('{"locked":true}\n')
        self.provenance = root / "recorder-provenance.json"
        self.targets = [
            self.target("gst", "B", [3], 6, 300, 16, 1),
            self.target("gst", "E", [2, 5, 9], 12, 300, 16, 3),
            self.target("va", "B", [2], 6, 300, None, None),
            self.target("va", "E", [1, 4, 7], 12, 300, None, None),
        ]
        plan = controller.build_plan(
            gst_pool_sizes={"B": 16, "E": 16},
            va_output_counts={"B": 300, "E": 300},
            gst_frames={"B": (3,), "E": (2, 5, 9)},
            va_outputs={"B": (2,), "E": (1, 4, 7)},
            last_required_inputs={"gst": {"B": 6, "E": 12},
                                  "va": {"B": 6, "E": 12}},
            run_id="fixture-run")
        self.plan = root / "plan.json"
        self.plan.write_text(plan.to_json() + "\n")
        artifact = manifest.file_record(self.elf)
        self.provenance.write_text(json.dumps({"module_sha256": artifact["sha256"]}) + "\n")
        dependency = [manifest.file_record(path) for path in self.dependencies]
        modules = {name: copy.deepcopy(artifact) for name in manifest.EXPECTED_MODULES}
        reference = manifest.file_record(self.reference)
        reference["frames_sha256"] = hashlib.sha256(b"frames").hexdigest()
        self.document = {
            "schema": manifest.SCHEMA, "state": "reviewed",
            "repo": {"commit": "1" * 40, "dirty": False},
            "host": {"architecture": "aarch64", "compatible": ["apple,t8103"],
                     "kernel_release": "fixture", "linux_asahi": "linux-asahi fixture"},
            "sources": {name: {"revision": str(index + 1) * 40,
                                "source_sha256": hashlib.sha256(name.encode()).hexdigest()}
                        for index, name in enumerate(sorted(manifest.EXPECTED_SOURCES))},
            "patches": [{"order": 0, "component": "fixture", "path": str(self.patch),
                         "sha256": manifest.digest(self.patch)}],
            "build": {"commands": [{"argv": ["cc", "tiny.c"],
                                      "cwd": str(root.resolve())}]},
            "tools": {name: "fixture" for name in
                      ("cc", "ld", "make", "meson", "ninja", "pkg_config", "python")},
            "artifacts": {name: copy.deepcopy(artifact)
                          for name in manifest.EXPECTED_ARTIFACTS},
            "dependencies": {name: copy.deepcopy(dependency)
                             for name in manifest.EXPECTED_DEPENDENCIES},
            "kernel": {"vermagic": "fixture", "config_sha256": "2" * 64,
                       "modules": modules,
                       "recorder_endpoints": ["/sys/kernel/debug/apple_avd_hevc_cmdtrace",
                                              "/sys/kernel/debug/apple_avd_hevc_trace"]},
            "corpus": self.corpus, "reference": reference,
            "targets": self.targets,
            "plan": manifest.file_record(self.plan), "commands": [],
            "limits": {"snapshot_bytes": 184320, "snapshots": 8,
                       "total_bytes": 1474560, "copy_ms": 20,
                       "drain_seconds": 2, "run_seconds": 120,
                       "campaign_seconds": 1200},
        }
        self.path = root / "manifest.json"
        self.document["artifacts"]["recorder_provenance"] = \
            manifest.file_record(self.provenance)
        for target in self.document["targets"]:
            target["evidence_sha256"] = self.document["artifacts"][
                "target_evidence"]["sha256"]
        import build
        artifacts = {name: Path(row["path"])
                     for name, row in self.document["artifacts"].items()}
        self.document["commands"] = build.command_matrix(
            artifacts, self.document["corpus"], self.document["targets"])
        self.write()

    @staticmethod
    def target(client, vector, selectors, last_input, output_count, pool_size, reserve):
        return {"client": client, "vector": vector,
                "selector_domain": ("output_ordinal" if client == "va"
                                    else "system_frame_number"),
                "selectors": selectors, "last_input": last_input,
                "output_count": output_count, "gst_pool_size": pool_size,
                "gst_reserve": reserve,
                "parameter_set_change_inputs": [],
                "evidence_sha256": "0" * 64}

    def write(self):
        self.path.write_text(json.dumps(self.document, indent=2, sort_keys=True) + "\n")
        return manifest.digest(self.path)


class DeploymentTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="hevc-deployment-")
        self.addCleanup(self.temporary.cleanup)
        self.fixture = Fixture(Path(self.temporary.name))

    def verify(self, document=None):
        value = document or self.fixture.document
        manifest.validate(value, root_owned=False, check_files=True,
                          dependency_reader=lambda _path: self.fixture.dependencies)

    def rejected(self, change, text):
        value = copy.deepcopy(self.fixture.document)
        change(value)
        with self.assertRaisesRegex(manifest.ManifestError, text):
            self.verify(value)

    def test_builder_resolves_local_helper_imports(self):
        import build
        helper = build.module("deployment_test_va_callsite",
                              HERE.parent / "va-callsite/tests.py")
        self.assertTrue(callable(helper.fetch_tree))

    def test_va_symbol_contract_matches_ffmpeg_loader(self):
        patch = (HERE.parent / "va-callsite/ffmpeg-n9.0.1-va-observer-callsite.patch").read_text()
        loaded = tuple(re.findall(r'LOAD\([^,]+,\s+"([^"]+)"\);', patch))
        self.assertEqual(len(loaded), len(set(loaded)))
        self.assertEqual(set(loaded), set(manifest.VA_OBSERVER_SYMBOLS))

    def test_complete_manifest_and_admission(self):
        self.verify()
        approved = self.fixture.write()
        result = admission.admitted_document(self.fixture.path, approved,
                                             live=False, root_owned=False)
        self.assertFalse(result["execution_authorized"])
        self.assertEqual(len(result["workloads"]), 8)
        self.assertEqual(result["plan_sha256"], manifest.digest(self.fixture.plan))

    def test_candidate_cannot_self_approve(self):
        self.rejected(lambda value: value.__setitem__("state", "candidate"),
                      "not reviewed")

    def test_exact_manifest_digest_is_required(self):
        with self.assertRaisesRegex(manifest.ManifestError, "reviewed digest"):
            manifest.verify(self.fixture.path, "0" * 64, live=False,
                            root_owned=False)

    def test_dirty_repo_is_rejected(self):
        self.rejected(lambda value: value["repo"].__setitem__("dirty", True),
                      "dirty source")

    def test_source_and_patch_drift_are_rejected(self):
        self.rejected(lambda value: value["sources"]["ffmpeg"].__setitem__(
            "source_sha256", "x" * 64), "source.ffmpeg")
        original = self.fixture.patch.read_text()
        self.fixture.patch.write_text(original + "drift\n")
        with self.assertRaisesRegex(manifest.ManifestError, "patch drift"):
            self.verify()

    def test_artifact_and_dependency_drift_are_rejected(self):
        self.rejected(lambda value: value["artifacts"]["ffmpeg"].__setitem__(
            "sha256", "0" * 64), "artifact.ffmpeg hash drift")
        with self.assertRaisesRegex(manifest.ManifestError, "dependency closure drift"):
            manifest.validate(self.fixture.document, root_owned=False, check_files=True,
                              dependency_reader=lambda _path: ())

    def test_missing_observer_artifact_is_rejected(self):
        self.rejected(lambda value: value["artifacts"].pop("gst_plugin"),
                      "artifact set")

    def test_identityless_vb2_is_rejected(self):
        self.rejected(lambda value: value["kernel"]["modules"]["videobuf2_common"].__setitem__(
            "build_id", "none"), "identity-less")

    def test_corpus_and_reference_drift_are_rejected(self):
        self.fixture.corpus["E"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(manifest.ManifestError, "corpus drift"):
            self.verify()

    def test_target_shape_capacity_and_domains_are_rejected(self):
        self.rejected(lambda value: value["targets"][1].__setitem__("selectors", [2, 5]),
                      "selector shape")
        self.rejected(lambda value: value["targets"][1].__setitem__("gst_reserve", 2),
                      "capacity")
        self.rejected(lambda value: value["targets"][3].__setitem__("gst_pool_size", 1),
                      "carries Gst capacity")
        self.rejected(lambda value: value["targets"][1].__setitem__(
            "parameter_set_change_inputs", [1]), "enters the armed window")
        self.rejected(lambda value: value["targets"][1].__setitem__(
            "evidence_sha256", "0" * 64), "not the staged evidence")
        self.rejected(lambda value: value["targets"][1].__setitem__(
            "selector_domain", "output_ordinal"), "selector domain")

    def test_plan_and_command_drift_are_rejected(self):
        value = copy.deepcopy(self.fixture.document)
        value["plan"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(manifest.ManifestError, "plan hash drift"):
            self.verify(value)
        value = copy.deepcopy(self.fixture.document)
        value["commands"][0]["name"] = value["commands"][1]["name"]
        with self.assertRaisesRegex(manifest.ManifestError, "identity is invalid"):
            self.verify(value)

    def test_admission_reconstructs_plan_and_commands(self):
        value = json.loads(self.fixture.plan.read_text())
        value["workloads"][0]["client_contract"]["copy"] = True
        self.fixture.plan.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
        self.fixture.document["plan"] = manifest.file_record(self.fixture.plan)
        approved = self.fixture.write()
        with self.assertRaisesRegex(admission.AdmissionError, "reconstruction"):
            admission.admitted_document(self.fixture.path, approved,
                                        live=False, root_owned=False)

        second = Path(self.temporary.name) / "second"
        second.mkdir()
        self.fixture = Fixture(second)
        self.fixture.document["commands"][0]["argv"][-1] += "-drift"
        approved = self.fixture.write()
        with self.assertRaisesRegex(admission.AdmissionError, "deterministic builder"):
            admission.admitted_document(self.fixture.path, approved,
                                        live=False, root_owned=False)

    def test_untrusted_writable_and_symlink_manifest_are_rejected(self):
        self.fixture.path.chmod(0o666)
        with self.assertRaisesRegex(manifest.ManifestError, "writable"):
            manifest.verify(self.fixture.path, manifest.digest(self.fixture.path),
                            live=False, root_owned=False)
        self.fixture.path.chmod(0o600)
        link = self.fixture.root / "manifest-link.json"
        link.symlink_to(self.fixture.path)
        with self.assertRaisesRegex(manifest.ManifestError, "direct regular"):
            manifest.verify(link, manifest.digest(self.fixture.path), live=False,
                            root_owned=False)

    def test_duplicate_and_extra_json_fields_are_rejected(self):
        duplicate = self.fixture.path.read_text().replace(
            '"state": "reviewed",', '"state": "reviewed", "state": "reviewed",', 1)
        self.fixture.path.write_text(duplicate)
        with self.assertRaisesRegex(manifest.ManifestError, "duplicate JSON key"):
            manifest.read_document(self.fixture.path)
        value = copy.deepcopy(self.fixture.document)
        value["authorization"] = True
        with self.assertRaisesRegex(manifest.ManifestError, "unexpected fields"):
            self.verify(value)

    def test_live_preflight_checks_loaded_modules_and_recorder_state(self):
        endpoints = self.fixture.root / "debug"
        cmd = endpoints / "apple_avd_hevc_cmdtrace/status"
        ref = endpoints / "apple_avd_hevc_trace/status"
        cmd.parent.mkdir(parents=True); ref.parent.mkdir(parents=True)
        cmd.write_text("phase=off contexts=0 errors=0\n")
        ref.write_text("phase=off contexts=0 errors=0\n")
        value = copy.deepcopy(self.fixture.document)
        value["host"]["kernel_release"] = os.uname().release
        value["kernel"]["recorder_endpoints"] = [str(cmd.parent), str(ref.parent)]
        compatible = mock.mock_open(read_data=b"apple,t8103\0")
        expected = next(iter(value["kernel"]["modules"].values()))["build_id"]
        with mock.patch.object(manifest.Path, "read_bytes", compatible), \
             mock.patch.object(manifest, "_loaded_note", return_value=expected):
            # The endpoint list is deliberately fixed by schema; a caller cannot
            # redirect the live verifier to synthetic files.
            with self.assertRaisesRegex(manifest.ManifestError, "endpoint set"):
                manifest.validate(value, root_owned=False, check_files=False)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mutation", choices=(
        "manifest-digest", "source", "dependency", "corpus", "capacity",
        "target", "plan", "execution-refusal"))
    args, remaining = parser.parse_known_args()
    if args.mutation:
        os.environ["HEVC_DEPLOYMENT_MUTATION"] = args.mutation
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(DeploymentTest)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return not result.wasSuccessful()


if __name__ == "__main__":
    raise SystemExit(main())
