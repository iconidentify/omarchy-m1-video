#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Reproduce a REJECTED FFmpeg proposal in a fresh directory. Never install it."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
PIN = "bf1b838f2ab88b4f8fd83443325c782ea0e0f7fa"
BASE = f"https://raw.githubusercontent.com/FFmpeg/FFmpeg/{PIN}/"


def digest(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(destination: Path):
    pins = json.loads((HERE / "source-map.json").read_text())["ffmpeg"]["files"]
    destination.mkdir(parents=True, exist_ok=False)
    codec = destination / "libavcodec"
    codec.mkdir()
    for rel, sha in pins.items():
        url = BASE + rel
        data = urllib.request.urlopen(url, timeout=30).read()
        if hashlib.sha256(data).hexdigest() != sha:
            raise ValueError("source hash mismatch: " + rel)
        (destination / rel).write_bytes(data)
    patch = HERE / "rejected/ffmpeg-n9.0.1-h264-vaapi-select.patch"
    subprocess.run(["patch", "-p0", "--fuzz=0", "-i", str(patch)],
                   cwd=destination, check=True, timeout=30)
    ident = {
        "ffmpeg": PIN,
        "patch_sha256": digest(patch),
        "status": "rejected-do-not-deploy",
        "patched_files": {str(p.relative_to(destination)): digest(p)
                          for p in sorted(codec.iterdir()) if p.is_file()},
    }
    (destination / "ident.json").write_text(json.dumps(ident, indent=2) + "\n")
    print("REJECTED proposal prepared for offline reproduction only:", destination)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--reproduce-rejected", action="store_true",
                   help="acknowledge this is known-broken research, not an accepted patch")
    p.add_argument("destination", type=Path)
    args = p.parse_args()
    if not args.reproduce_rejected:
        p.error("proposal rejected; use --reproduce-rejected only for offline diagnosis")
    prepare(args.destination.resolve())
