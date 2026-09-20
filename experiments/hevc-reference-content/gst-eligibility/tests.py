#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Build the pinned plugin and test finite selected-output reservations."""
from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
PARENT = HERE.parent
BASE = Path("subprojects/gst-plugins-bad/sys/v4l2codecs")
MODES = """eligibility-default-off eligibility-late-selected
eligibility-reordered eligibility-duplicate eligibility-presupplied
eligibility-shortage eligibility-flush-wait eligibility-alias-sticky
eligibility-incomplete eligibility-bad-config""".split()


def module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


integration = module("content_integration", PARENT / "integration/tests.py")
sys.path.insert(0, str(PARENT / "gst-adapter"))
adapter = module("gst_adapter", PARENT / "gst-adapter/tests.py")
callsite = module("gst_callsite", PARENT / "gst-callsite/tests.py")
runner = module("gst_runner", PARENT / "gst-runner/tests.py")
run = integration.run


def configure_fixture(root: Path) -> None:
    directory = root / BASE
    runner_fixture = directory / "runner-api-test.c"
    source = integration.replace(
        runner_fixture.read_text(), "int\nmain (int argc, char **argv)",
        "int\nrunner_fixture_main (int argc, char **argv)")
    source += "\n" + (HERE / "eligibility-model.inc").read_text()
    (directory / "eligibility-api-test.c").write_text(source)

    meson = directory / "meson.build"
    text = meson.read_text()
    addition = text[text.rindex("runner_sources ="):]
    addition = addition.replace("runner_sources", "eligibility_sources")
    addition = addition.replace("runner-api", "eligibility-api")
    addition = addition.replace("runner-api-test.c", "eligibility-api-test.c")
    meson.write_text(text + "\n" + addition)


def compile_targets(build: Path) -> Path:
    run(["meson", "compile", "-C", build, "-j", "4", "gstv4l2codecs",
         "eligibility-api", "callsite-api", "content-api", "observer-api"])
    return build / BASE / "eligibility-api"


def run_mode(binary: Path, mode: str) -> str:
    with tempfile.TemporaryDirectory(prefix="hevc-gst-eligibility-") as temp:
        report = Path(temp) / "result.json"
        output = run([binary, mode, report])
        assert f"PASS Gst eligibility {mode}" in output, output
        if mode == "eligibility-late-selected":
            document = runner.collector.collect_report(
                report, process_exit_code=0, expected_frames=(31,),
                expected_copy=True)
            assert document["count"] == 1
            assert set(Path(temp).iterdir()) == {report}
        else:
            assert not report.exists(), mode
            assert not any(Path(temp).iterdir()), mode
        return output


def positive(binary: Path, sanitizer: str) -> None:
    for mode in MODES:
        print(sanitizer, run_mode(binary, mode).strip(), flush=True)


def replace_many(path: Path, changes: list[tuple[str, str]]) -> str:
    original = path.read_text()
    changed = original
    for before, after in changes:
        changed = integration.replace(changed, before, after)
    path.write_text(changed)
    return original


def mutations(root: Path, build: Path) -> None:
    directory = root / BASE
    cases = [
        ("reserve-sizing", "gstv4l2codech265dec.c", [(
            "GST_PAD_SRC, source_pool_size);",
            "GST_PAD_SRC, self->min_pool_size + min);"
        )], "eligibility-late-selected", "expected_total"),
        ("published-first", "gstv4l2codecallocator.c", [(
            "if (!selected)\n        return item;",
            "if (FALSE && !selected)\n        return item;"
        )], "eligibility-late-selected", "current == recycled"),
        ("selected-unpublished-only", "gstv4l2codecallocator.c", [(
            "if (!selected)\n        return item;",
            "if (TRUE)\n        return item;"
        )], "eligibility-late-selected",
         "eligibility_index (picture) != recycled"),
        ("remaining-reserve-accounting", "gstv4l2codecallocator.c", [(
            "unpublished > remaining_selected",
            "unpublished >= remaining_selected"
        )], "eligibility-flush-wait", "result == expected"),
        ("selector-allocation-unique", "gst-runner.inc", [(
            "if ((runner->allocated_mask & (1u << i)) || "
            "!runner->remaining_allocations)",
            "if (!runner->remaining_allocations)"
        ), (
            "if (runner->allocated_mask & (1u << i))\n      goto done;",
            "if (FALSE && (runner->allocated_mask & (1u << i)))\n"
            "      goto done;"
        )], "eligibility-duplicate", "result == expected"),
        ("default-off-isolation", "gstv4l2codech265dec.c", [(
            "if (active)\n    flow_ret = "
            "gst_v4l2_codec_pool_acquire_observer_buffer",
            "if (active || !self->content_runner)\n    flow_ret = "
            "gst_v4l2_codec_pool_acquire_observer_buffer"
        ), (
            "&buffer, selected, remaining);",
            "&buffer, active ? selected : TRUE, remaining);"
        )], "eligibility-default-off", "result == expected"),
    ]

    for label, filename, changes, mode, assertion in cases:
        path = directory / filename
        original = replace_many(path, changes)
        try:
            binary = compile_targets(build)
            with tempfile.TemporaryDirectory(
                    prefix="hevc-gst-eligibility-mutation-") as temp:
                result = subprocess.run(
                    [str(binary), mode, str(Path(temp) / "result.json")],
                    env=integration.ENV, text=True, capture_output=True,
                    timeout=120)
            output = result.stdout + result.stderr
            if (result.returncode != -signal.SIGABRT or assertion not in output or
                    "Sanitizer" in output or "runtime error:" in output):
                raise RuntimeError(
                    f"wrong eligibility mutation failure: {label}\n{output}")
            print("PASS named Gst eligibility mutation " + label, flush=True)
        finally:
            path.write_text(original)
    compile_targets(build)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep", required=True, type=Path)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--native-file", type=Path)
    args = parser.parse_args()
    destination = args.keep.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        parser.error("--keep must name an empty directory")

    root = adapter.source.fetch(destination, args.archive)
    for patch in ("unaligned-io.patch", "gstv4l2decoder-observer.patch"):
        run(["patch", "--batch", "--fuzz=0", "-p1", "-i",
             PARENT / "gst-adapter" / patch], cwd=root)
    for src, dst in (("public-api-test.c", "observer-api-test.c"),
                     ("unaligned-io-test.c", "unaligned-io-test.c")):
        shutil.copyfile(PARENT / "gst-adapter" / src, root / BASE / dst)
    meson = root / BASE / "meson.build"
    meson.write_text(meson.read_text() + "\n" +
                     (PARENT / "gst-adapter/test-meson.build").read_text())
    run(["patch", "--batch", "--fuzz=0", "-p1", "-i",
         PARENT / "integration/gst-integration.patch"], cwd=root)
    integration.sync(root, "gst")
    integration.fixture(root, "gst")
    integration.prepare_gst_fixture(root)
    run(["patch", "--batch", "--fuzz=0", "-p1", "-i",
         PARENT / "gst-callsite/client-hook.patch"], cwd=root)
    callsite.configure_fixture(root)
    for name in ("gst-runner.h", "gst-runner.inc"):
        shutil.copyfile(PARENT / "gst-runner" / name, root / BASE / name)
    run(["patch", "--batch", "--fuzz=0", "-p1", "-i",
         PARENT / "gst-runner/gst-runner.patch"], cwd=root)
    runner.configure_fixture(root)
    run(["patch", "--batch", "--fuzz=0", "-p1", "-i",
         HERE / "gst-eligibility.patch"], cwd=root)
    configure_fixture(root)

    archive = (args.archive.resolve() if args.archive else
               destination / "source.tar.gz")
    for sanitizer, label in (("address,undefined", "asan-ubsan"),
                             ("thread", "tsan")):
        build = destination / label
        adapter.configure(root, build, sanitizer, args.native_file)
        binary = compile_targets(build)
        adapter.pinned_linkage(build, binary)
        adapter.pinned_linkage(build, build / BASE / "libgstv4l2codecs.so")
        positive(binary, sanitizer)
        callsite.positive(build / BASE / "callsite-api", sanitizer)
        integration.positive(build / BASE / "content-api", "gst", sanitizer)
        adapter.positive(build, sanitizer)
        if label == "asan-ubsan":
            mutations(root, build)
        for name in ("libgstv4l2codecs.so", "eligibility-api"):
            artifact = build / BASE / name
            print(label, name, "sha256", adapter.source.digest(artifact),
                  flush=True)
    print("source archive sha256", adapter.source.digest(archive), flush=True)
    print("eligibility patch sha256",
          adapter.source.digest(HERE / "gst-eligibility.patch"), flush=True)
    print("PASS finite Gst allocation eligibility; synthetic syscalls only",
          flush=True)


if __name__ == "__main__":
    main()
