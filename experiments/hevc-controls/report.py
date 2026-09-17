#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Recompute the published HEVC capture decision from metadata, without a device.

HEVC_REFTRACE_CHECKER must name a trusted, reviewed driver checker (see README).
Private raw captures are deliberately not required or reconstructed here.
"""
import argparse
from datetime import datetime
import hashlib
import re
import json
import os
from pathlib import Path
import subprocess
import sys


def require(condition, message="inconsistent capture metadata"):
    if not condition:
        raise ValueError(message)


def read(path):
    require(path.stat().st_size <= 8 * 1024 * 1024, "oversized metadata")
    return json.loads(path.read_text())


def semantic(record):
    """Logical picture identities, alongside layout differences; not all controls."""
    dpb = record["dpb"]
    result = {k: record[k] for k in ("poc", "irap", "idr", "ltr_sps", "total_curr")}
    for key in ("st_before", "st_after", "lt_curr"):
        result[key] = [dpb[i]["poc"] for i in record[key]]
    ordered = [[e["poc"], e["lt"], e["field"]] for e in dpb]
    result["dpb_membership"] = sorted(ordered)
    result["dpb_order"] = ordered
    result["slices"] = []
    for s in record["slices"]:
        item = {k: s[k] for k in ("type", "nal", "tmvp")}
        for key in ("l0", "l1"):
            item[key] = [dpb[i]["poc"] for i in s[key]]
        if s["tmvp"] and s["type"] != "I":
            item["col_l0"] = s["col_l0"]
            item["col"] = s["col"]
            selected = item["l0"] if s["type"] == "P" or s["col_l0"] else item["l1"]
            item["collocated_poc"] = selected[s["col"]]
        # I-slice collocated bytes stay in the raw reference trace. The pinned
        # AVD stream_slice_mv() returns before interpreting them for I-slices.
        result["slices"].append(item)
    return result


def driver_check(checker, args, expected_status):
    result = subprocess.run([sys.executable, checker] + args, capture_output=True,
                            text=True, timeout=30)
    require(result.returncode == expected_status, result.stderr)
    return json.loads(result.stdout)


def summarize(root, checker):
    manifest = read(root / "results.json")
    reference = read(root / "reference-frames.json")
    provenance = read(root / "provenance.json")
    recovery = read(root / "recovery.json")
    require([e["event"] for e in recovery] == ["authorized-recovery-start", "unload", "load", "recovery-complete"])
    require(recovery[1]["returncode"] == recovery[2]["returncode"] == 0)
    require(recovery[-1]["idle"] and recovery[-1]["module_loaded"] and recovery[-1]["new_fault_count"] == 0)
    require(recovery[0]["boundary"] == provenance["recovery_boundary"])
    boundary = datetime.fromisoformat(provenance["recovery_boundary"]).timestamp()
    inventory = {f["path"]: f for f in read(root / "private-artifacts.json")["files"]}
    inputs = {"B": "a5e2097201740c15824b75540b6d0d5050763681bedf7209cde80d93a3b88996",
              "E": "b82c5c8c251943cc41b59e7f63f72890641fdcdbcec8e916223e4ee28a16c7ad"}
    runs = manifest["runs"]
    expected_ids = {f"{v}-{c}-{t}" for v in ("B", "E") for c in ("va", "gst")
                    for t in (("off", "on") if c == "va" else ("off", "on", "on-outputlog"))}
    require({r["id"] for r in runs} == expected_ids)
    require(len({r["guard_run_id"] for r in runs}) == 10)
    require(len(runs) == 10)
    run_results = []
    for run in runs:
        require(run["id"] == f"{run['vector']}-{run['client']}-{run['trace']}")
        require(run["input_sha256"] == inputs[run["vector"]])
        require(boundary < run["start_unix"] < run["end_unix"])
        require(run["frames"] == 300)
        expected = reference[run["vector"]]["frame_md5"]
        require(all(re.fullmatch(r"[0-9a-f]{32}", h) for h in expected + run["frame_md5"]))
        # Whole-stream MD5 is recorded, not derivable from separate frame hashes.
        require(re.fullmatch(r"[0-9a-f]{32}", run["md5"]) is not None)
        require(len(expected) == len(run["frame_md5"]) == 300)
        require(run["tracee_status"] == run["wrapper_status"] == 0)
        guard_path = Path(run["guard_file"])
        require(guard_path.parent == Path("guards") and guard_path.suffix == ".jsonl")
        guard = [json.loads(x) for x in (root / guard_path).read_text().splitlines()]
        require([e["event"] for e in guard] == ["preflight", "start", "final"])
        require(not guard[-1]["timed_out"] and guard[-1]["abort_reason"] is None and not guard[-1]["holders"])
        require(datetime.fromisoformat(guard[1]["time"]).timestamp() <= run["start_unix"])
        require(run["end_unix"] < datetime.fromisoformat(guard[-1]["time"]).timestamp() + 1)

        require(guard[0]["event"] == "preflight" and guard[0]["idle"])
        require(guard[-1]["event"] == "final" and guard[-1]["status"] == "ok")
        require(guard[-1]["returncode"] == 0 and guard[-1]["idle"] and not guard[-1]["wedged"])
        require(all(e.get("run_id") == run["guard_run_id"] for e in guard))
        wrong = [i for i, (a, b) in enumerate(zip(expected, run["frame_md5"])) if a != b]
        require(wrong == run["wrong_indices"])
        run_results.append(dict(id=run["id"], frames=300, wrong_indices=wrong,
                                md5=run["md5"], association=run["association"] ))
    summary = dict(schema="hevc-controls.capture-decision/1", runs=run_results, vectors={})
    for vector in ("B", "E"):
        traces = {}
        maps = {}
        for client in ("va", "gst"):
            selected_id = f"{vector}-{client}-" + ("on" if client == "va" else "on-outputlog")
            require(manifest["selected"][f"{vector}-{client}"] == selected_id)
            selected = next(r for r in runs if r["id"] == selected_id)
            require(selected["association"] == "selected/published")
            filename = root / "refs" / f"{vector}-{client}.jsonl"
            if client == "va":
                require(hashlib.sha256(filename.read_bytes()).hexdigest() == inventory[f"{selected_id}/refs.jsonl"]["sha256"],
                        "VA trace differs from captured source inventory")
            driver_check(checker, ["compare", str(filename), str(filename),
                                  "--expected-pictures", "300", "--json"], 0)
            records = [json.loads(line) for line in filename.read_text().splitlines()]
            require(len(records) == 300 and len({r["poc"] for r in records}) == 300)
            require(all(r["pic"] == i + 1 for i, r in enumerate(records)))
            require({r["poc"] for r in records} == set(range(300)))
            if client == "gst":
                raw = [f for name, f in inventory.items() if name.startswith(selected_id + "/")
                       and name.endswith(".json") and Path(name).name[0].isdigit()]
                require(len(raw) == 1)
                require(all(r["run"] == raw[0]["sha256"][:16] for r in records))
            traces[client] = records
            assoc = read(root / "associations" / f"{vector}-{client}.json")
            require(len(assoc) == 300)
            require([p["output_index"] for p in assoc] == list(range(300)))
            require(sorted(p["pic"] for p in assoc) == list(range(1, 301)))
            require(all(p["poc"] == records[p["pic"] - 1]["poc"] for p in assoc))
            if client == "va":
                require(all(p["layer"] == 0 for p in assoc))
            else:
                require(all(p["system_frame_number"] == p["pic"] - 1 for p in assoc))
            maps[client] = assoc
            matching = [run for run in runs if run["vector"] == vector and run["client"] == client]
            require(len({json.dumps(r["frame_md5"]) for r in matching}) == 1, "tracing altered pixels")
            require(len({r["md5"] for r in matching}) == 1)
        require([r["poc"] for r in traces["va"]] == [r["poc"] for r in traces["gst"]])
        first = driver_check(checker, ["compare", str(root / "refs" / f"{vector}-va.jsonl"),
                                      str(root / "refs" / f"{vector}-gst.jsonl"),
                                      "--expected-pictures", "300", "--json"], 1)
        sem = {c: [semantic(r) for r in traces[c]] for c in traces}
        differences = {}
        for field in sem["va"][0]:
            indices = [i for i in range(300) if sem["va"][i][field] != sem["gst"][i][field]]
            differences[field] = dict(count=len(indices),
                                      first_picture=indices[0] + 1 if indices else None,
                                      first_poc=sem["va"][indices[0]]["poc"] if indices else None)
        first_bad = {}
        for client in traces:
            run = next(r for r in runs if r["vector"] == vector and r["client"] == client)
            assoc = maps[client]
            bad = [assoc[i] for i in run["wrong_indices"]]
            if bad:
                out = bad[0]
                decoded = min(bad, key=lambda x: x["pic"])
                first_bad[client] = dict(first_output=out, first_decode=decoded,
                                        first_decode_references=sem[client][decoded["pic"] - 1])
            else:
                first_bad[client] = None
        summary["vectors"][vector] = dict(first_strict_difference=first,
                                          semantic_differences=differences, first_bad=first_bad)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    checker = os.environ.get("HEVC_REFTRACE_CHECKER")
    if not checker:
        parser.error("set HEVC_REFTRACE_CHECKER to the trusted pinned checker")
    summary = summarize(args.directory, checker)
    if args.verify:
        require(summary == read(args.directory / "summary.json"), "published summary differs")
        print("10 complete 300-frame captures, associations and comparison summary verified")
    else:
        print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
