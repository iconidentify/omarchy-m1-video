#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Reproduce the two missing GLib generators and their Meson override."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import stat
import subprocess


GLIB_REVISION = "43bc79ea8803e33c5eb368085e2d5906f9f98079"
GLIB_VERSION = "2.88.3"
SYSTEM_PC = Path("/usr/lib/pkgconfig/glib-2.0.pc")
SYSTEM_PC_SHA256 = "4fd4451660f4e7c4156a270c4c7569bccc9324682ed0410db90352d8d6bf3269"
TEMPLATES = {
    "glib-mkenums": "0de6a9a6d8db2106b30a8626830d87671f271c35df95d357d5d7138d06f3c061",
    "glib-genmarshal": "8691d1119845a6b8e90cfe83a99cd567c8643d62fc5831ea607cf5491a067e81",
}
OUTPUTS = {
    "glib-mkenums": "25f76c960677aca54b1b77d924a59063b923ad51ae3d91cb3760831f46d94577",
    "glib-genmarshal": "e840ba247b6f15ca832d6a96178c01dd3391283d6aa59acd56bf9862d123d1cf",
}
SOURCE_SHA256 = "0a0a176548084e8439eb9b61a4b6fd452f5dc09cf72ba758bd806460bcef7528"


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest(path: Path) -> str:
    return digest_bytes(path.read_bytes())


def render_template(raw: bytes) -> bytes:
    if raw.count(b"@PYTHON@") != 1 or raw.count(b"@VERSION@") != 1:
        raise ValueError("unexpected GLib template substitutions")
    value = raw.replace(b"@PYTHON@", b"/usr/bin/python")
    value = value.replace(b"@VERSION@", GLIB_VERSION.encode())
    if b"@PYTHON@" in value or b"@VERSION@" in value:
        raise ValueError("unresolved GLib template substitution")
    return value


def render_pc(raw: bytes, bindir: Path) -> bytes:
    text = raw.decode("utf-8")
    old = "bindir=${prefix}/bin"
    if text.count(old) != 1:
        raise ValueError("unexpected system glib-2.0.pc bindir")
    return text.replace(old, "bindir=" + str(bindir), 1).encode()


def native_contents(pkgconfig: Path) -> str:
    return "[built-in options]\npkg_config_path = ['" + str(pkgconfig) + "']\n"


def prepare(source: Path, output: Path) -> dict[str, Path]:
    source = source.resolve(strict=True)
    output = output.resolve()
    if output.exists():
        raise ValueError("GLib tool output must not already exist")
    revision = subprocess.run(
        ["git", "-C", str(source), "rev-parse", "HEAD"], check=True,
        text=True, capture_output=True, timeout=30).stdout.strip()
    dirty = subprocess.run(
        ["git", "-C", str(source), "status", "--porcelain"], check=True,
        text=True, capture_output=True, timeout=30).stdout
    if revision != GLIB_REVISION or dirty:
        raise ValueError("GLib tool source is not the clean pinned revision")

    rendered: dict[str, bytes] = {}
    combined = hashlib.sha256()
    for name, expected in TEMPLATES.items():
        path = source / "gobject" / (name + ".in")
        raw = path.read_bytes()
        if digest_bytes(raw) != expected:
            raise ValueError("GLib tool template identity mismatch: " + name)
        combined.update(raw)
        value = render_template(raw)
        if digest_bytes(value) != OUTPUTS[name]:
            raise ValueError("generated GLib tool identity mismatch: " + name)
        rendered[name] = value
    if combined.hexdigest() != SOURCE_SHA256:
        raise ValueError("combined GLib tool source identity mismatch")
    if digest(SYSTEM_PC) != SYSTEM_PC_SHA256:
        raise ValueError("system glib-2.0.pc identity mismatch")

    bin_dir = output / "bin"
    pc_dir = output / "pkgconfig"
    bin_dir.mkdir(parents=True)
    pc_dir.mkdir()
    paths: dict[str, Path] = {}
    for name, value in rendered.items():
        path = bin_dir / name
        path.write_bytes(value)
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        paths[name.replace("-", "_")] = path
    pc_path = pc_dir / "glib-2.0.pc"
    pc_path.write_bytes(render_pc(SYSTEM_PC.read_bytes(), bin_dir))
    native_path = output / "native.ini"
    native_path.write_text(native_contents(pc_dir))
    paths["glib_pc"] = pc_path
    paths["glib_native_file"] = native_path

    for name in ("glib-mkenums", "glib-genmarshal"):
        result = subprocess.run([str(bin_dir / name), "--version"], text=True,
                                capture_output=True, timeout=30)
        if result.returncode or GLIB_VERSION not in result.stdout + result.stderr:
            raise ValueError("generated GLib tool does not run: " + name)
    return paths


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        paths = prepare(args.source, args.output)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print("GLIB TOOL PREPARATION REFUSED: " + str(error))
        return 125
    print(json.dumps({name: {"path": str(path.resolve()), "sha256": digest(path)}
                      for name, path in sorted(paths.items())}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
