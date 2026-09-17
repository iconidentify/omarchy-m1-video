#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Build the exact rejected proposal and verify specific failures. No device/install."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile
import urllib.request

HERE = Path(__file__).resolve().parent
PIN = 'bf1b838f2ab88b4f8fd83443325c782ea0e0f7fa'
ARCHIVE_SHA = 'fb1931fd4eb29297ee1c1017a24f800c4d8fbea35b4f2aaeb28308a48a9149b4'
FLAGS = ['--disable-everything', '--disable-autodetect', '--disable-asm',
         '--disable-doc', '--enable-decoder=h264', '--enable-parser=h264',
         '--enable-vaapi', '--enable-hwaccel=h264_vaapi']
SYMBOLS = ['ff_h264_vaapi_' + s for s in
           ('mark_unsupported', 'mark_malformed', 'gate_start', 'gate_slice', 'gate_end')]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def run(command, cwd, log):
    result = subprocess.run(command, cwd=cwd, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=240)
    log.write_bytes(result.stdout)
    return result.returncode, result.stdout.decode(errors='replace')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    parser.add_argument('--archive', type=Path, help='optional cached hash-checked source archive')
    args = parser.parse_args()
    root = args.destination.resolve()
    root.mkdir(parents=True, exist_ok=False)
    archive = args.archive.read_bytes() if args.archive else urllib.request.urlopen(
        f'https://codeload.github.com/FFmpeg/FFmpeg/tar.gz/{PIN}', timeout=60).read()
    if sha(archive) != ARCHIVE_SHA:
        raise ValueError('source archive identity mismatch')
    tar = root / 'source.tar.gz'
    tar.write_bytes(archive)
    with tarfile.open(tar) as stream:
        stream.extractall(root, filter='data')
    tree = root / ('FFmpeg-' + PIN)
    source_map = json.loads((HERE / 'source-map.json').read_text())
    for rel, expected in source_map['ffmpeg']['files'].items():
        if sha((tree / rel).read_bytes()) != expected:
            raise ValueError('source file identity mismatch: ' + rel)
    rc, out = run(['./configure', *FLAGS], tree, root / 'configure.log')
    if rc or '#define CONFIG_H264_VAAPI_HWACCEL 1' not in (tree / 'config_components.h').read_text():
        raise RuntimeError('VAAPI baseline configuration unavailable; inspect configure.log')
    build = ['make', '-j' + str(min(6, os.cpu_count() or 1)), 'ffmpeg']
    rc, out = run(build, tree, root / 'baseline.log')
    if rc:
        raise RuntimeError('unpatched baseline failed; not an accepted reproduction')
    baseline_sha = sha((tree / 'ffmpeg').read_bytes())
    patch = HERE / 'rejected/ffmpeg-n9.0.1-h264-vaapi-select.patch'
    rc, out = run(['patch', '-p0', '--fuzz=0', '-i', str(patch)], tree, root / 'patch.log')
    if rc:
        raise RuntimeError('patch application failed')
    for name in ('h264_vaapi_select.c', 'h264_vaapi_select.h'):
        if (tree / 'libavcodec' / name).read_bytes() != (HERE / 'rejected' / name).read_bytes():
            raise ValueError('patch/model identity mismatch: ' + name)
    rc, out = run(build, tree, root / 'rejected-link.log')
    if rc == 0 or 'undefined reference' not in out or not all(s in out for s in SYMBOLS):
        raise RuntimeError('expected five missing real glue symbols were not reproduced')
    rc, symbols = run(['nm', 'libavcodec/h264_vaapi_select.o'], tree, root / 'symbols.log')
    if rc or any(s in symbols for s in SYMBOLS):
        raise RuntimeError('unexpected glue object contents')
    # Controlled diagnostic only: enabling the omitted section exposes more errors.
    path = tree / 'libavcodec/h264_vaapi_select.c'
    path.write_text('#include "config_components.h"\n' + path.read_text())
    rc, out = run(['make', 'libavcodec/h264_vaapi_select.o'], tree, root / 'enabled-glue.log')
    if rc == 0 or 'H264_NAL_SLICE' not in out or 'AVCodecInternal' not in out:
        raise RuntimeError('expected enum collision and incomplete internal type were not reproduced')
    report = {
        'schema': 'omarchy-m1-video.h264-rejected-build/1',
        'status': 'blocked-design-not-a-working-client',
        'ffmpeg_commit': PIN, 'source_archive_sha256': ARCHIVE_SHA,
        'patch_sha256': sha(patch.read_bytes()), 'configure_flags': FLAGS,
        'compiler': subprocess.check_output(['cc', '--version'], text=True).splitlines()[0],
        'libva_version': subprocess.check_output(['pkg-config', '--modversion', 'libva'], text=True).strip(),
        'architecture': os.uname().machine, 'baseline_link': 'pass',
        'baseline_binary_sha256': baseline_sha, 'rejected_link': 'missing-five-glue-symbols',
        'enabled_glue': 'NAL-macro-collision-and-incomplete-AVCodecInternal',
        'logs': {p.name: sha(p.read_bytes()) for p in sorted(root.glob('*.log'))},
        'hardware': 'none', 'installed_changes': 'none',
    }
    (root / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
