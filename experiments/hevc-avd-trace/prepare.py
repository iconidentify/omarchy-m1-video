#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Verify exact pinned sources and prepare/build an isolated experimental module.

Never installs, loads, unloads or opens a decoder. Fetch source separately.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def need(condition, reason):
    if not condition:raise ValueError(reason)


def run(command, **kw):
    return subprocess.run(command, check=True, timeout=300, **kw)


def prepare(source, destination, headers=None):
    manifest=json.loads((HERE/'sources.json').read_text())
    need(source.is_dir(), 'source directory missing')
    for name, sha in manifest['upstream_files'].items():
        need((source/name).is_file() and not (source/name).is_symlink(), 'missing/symlink source: '+name)
        need(digest(source/name)==sha, 'upstream source hash mismatch: '+name)
    patches=[]
    for item in manifest['patches']['files']:
        path=REPO/item['path']
        need(digest(path)==item['sha256'], 'shipped patch changed: '+item['path'])
        patches.append(path)
    need(hashlib.sha256(b''.join(p.read_bytes() for p in patches)).hexdigest()==manifest['patches']['concatenated_sha256'], 'patch stack differs')
    if headers:
        need((headers/'include/config/kernel.release').read_text().strip()==manifest['kernel_release'], 'headers release differs from pinned kernel')
        need('CONFIG_ARM64=y' in (headers/'.config').read_text(), 'headers are not ARM64')
    # Exclusive creation: no in-place edit or deletion of an existing build/source.
    destination.mkdir(parents=False, exist_ok=False)
    for name in manifest['upstream_files']:
        shutil.copyfile(source/name,destination/name)
    for patch in patches:
        run(['patch','--batch','--fuzz=0','-p6','-i',str(patch)],cwd=destination,stdout=subprocess.PIPE)
    run(['patch','--batch','--fuzz=0','-p1','-i',str(HERE/'hooks.patch')],cwd=destination,stdout=subprocess.PIPE)
    for p in (HERE/'kernel').iterdir():
        if p.suffix in ('.h','.c'):shutil.copyfile(p,destination/p.name)
    provenance=dict(schema='hevc-avd-trace.build/1',source_manifest_sha256=digest(HERE/'sources.json'),
                    kernel_revision=manifest['kernel_revision'],patch_stack_sha256=manifest['patches']['concatenated_sha256'],
                    hooks_sha256=digest(HERE/'hooks.patch'),
                    candidate_files={p.name:digest(p) for p in sorted(destination.iterdir()) if p.is_file()},
                    hardware_used=False,installed=False,loaded=False)
    if headers:
        provenance['headers']={name:digest(headers/name) for name in ('.config','Module.symvers','include/generated/autoconf.h','include/generated/utsrelease.h')}
        provenance['kernel_release']=manifest['kernel_release']
        provenance['compiler']=subprocess.check_output(['cc','--version'],text=True).splitlines()[0]
        command=['make','-s','-C',str(headers),'M='+str(destination),'CONFIG_VIDEO_APPLE_AVD=m','modules','-j4']
        provenance['command']=command
        with (destination/'build.log').open('w') as log:run(command,stdout=log,stderr=subprocess.STDOUT)
        provenance['module_sha256']=digest(destination/'apple-avd.ko')
        provenance['vermagic']=subprocess.check_output(['modinfo','-F','vermagic',str(destination/'apple-avd.ko')],text=True).strip()
    (destination/'provenance.json').write_text(json.dumps(provenance,indent=2)+'\n')
    return provenance


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True,help='pristine pinned AVD directory')
    p.add_argument('--destination',type=Path,required=True,help='new local directory (must not exist)')
    p.add_argument('--headers',type=Path,help='matching pinned ARM64 kernel headers; omission prepares source only')
    a=p.parse_args()
    try:
        result=prepare(a.source.resolve(),a.destination.resolve(),a.headers.resolve() if a.headers else None)
        print(json.dumps(result,indent=2));return 0
    except (ValueError,OSError,subprocess.SubprocessError) as e:
        print('ERROR: '+str(e),file=sys.stderr);return 1

if __name__=='__main__':sys.exit(main())
