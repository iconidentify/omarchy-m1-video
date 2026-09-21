#!/usr/bin/env python3
"""Validate and apply the opt-in overlay to an isolated Chromium 153 tree."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

HERE = Path(__file__).resolve().parent
VERSION = 'MAJOR=153\nMINOR=0\nBUILD=8010\nPATCH=36\n'
TARGETS = ('content/common/gpu_pre_sandbox_hook_linux.cc',
           'content/common/BUILD.gn', 'content/test/BUILD.gn')


def prepare(source, apply=False):
    source = source.resolve(strict=True)
    if (source / 'chrome/VERSION').read_text() != VERSION:
        raise ValueError('Expected exactly Chromium 153.0.8010.36')
    pins = {row['path']: row['sha256'] for row in json.loads((HERE / 'sources.json').read_text())}
    overlay = list((HERE / 'overlay').rglob('*'))
    overlay = [path for path in overlay if path.is_file()]
    for relative in TARGETS:
        target = source / relative
        if target.resolve() != target or hashlib.sha256(target.read_bytes()).hexdigest() != pins[relative]:
            raise ValueError('Modified, symlinked or wrong-version input: ' + relative)
    for path in overlay:
        target = source / path.relative_to(HERE / 'overlay')
        if target.exists() or target.is_symlink() or target.parent.resolve() != target.parent:
            raise ValueError('Overlay target already exists or traverses symlinks: ' + str(target))
    command = ['patch', '--batch', '--forward', '--fuzz=0', '-p1',
               '-i', str(HERE / 'chromium-153-avd-hook.patch')]
    subprocess.run(command + ['--dry-run'], cwd=source, check=True)
    if not apply:
        return
    subprocess.run(command, cwd=source, check=True)
    for path in overlay:
        shutil.copyfile(path, source / path.relative_to(HERE / 'overlay'))
    print('Applied experimental source overlay. No build, install or browser launch.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--apply', action='store_true', help='otherwise validate/dry-run only')
    args = parser.parse_args()
    prepare(args.source, args.apply)
