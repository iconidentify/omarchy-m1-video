#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Compile the isolated candidate with explicit matching headers; never install/load."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tests as support
source = support.load_retry()

HERE = Path(__file__).resolve().parent

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('destination', type=Path)
    p.add_argument('--headers', required=True, type=Path)
    p.add_argument('--source-cache', type=Path)
    args = p.parse_args()
    root = args.destination.resolve(); root.mkdir(parents=True, exist_ok=False)
    headers = args.headers.resolve()
    identities = ['.config','Module.symvers','include/config/kernel.release',
                  'include/generated/utsrelease.h','include/generated/compile.h']
    header_hashes = {n:sha(headers/n) for n in identities}
    release = (headers/'include/config/kernel.release').read_text().strip()
    if 'CONFIG_ARM64=y' not in (headers/'.config').read_text() or os.uname().machine != 'aarch64':
        raise ValueError('this qualification requires native ARM64 and ARM64 headers')
    expected = json.loads((HERE/'patch-identities.json').read_text())
    for name,digest in expected.items():
        path = support.RETRY/'candidate.patch' if name == 'base_candidate' else HERE/name
        if sha(path) != digest: raise ValueError('candidate identity drift: '+name)
    tree = source.prepare(root/'source', cache=args.source_cache)
    module = source.patch(tree,support.RETRY/'candidate.patch',root/'candidate')
    subprocess.run(['patch','--batch','--fuzz=0','-p1','-i',str(HERE/'av1-unwind.patch')],cwd=module,check=True,stdout=subprocess.PIPE,timeout=30)
    inputs = {f.name:sha(f) for f in sorted(module.iterdir()) if f.is_file()}
    command = ['make','-C',str(headers),'M='+str(module),'CONFIG_VIDEO_APPLE_AVD=m',
               'KCFLAGS=-Werror','-j4','modules']
    result = subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=300)
    (root/'build.log').write_bytes(result.stdout)
    if result.returncode or re.search(rb'\bwarning:',result.stdout,re.I):
        raise RuntimeError('module build failed or warned; see build.log')
    output = module/'apple-avd.ko'
    vermagic = subprocess.check_output(['modinfo','-F','vermagic',str(output)],text=True).strip()
    if vermagic.split()[0] != release: raise ValueError('vermagic/header mismatch')
    if header_hashes != {n:sha(headers/n) for n in identities}: raise ValueError('headers changed during build')
    report = dict(schema='omarchy-m1-video.avd-av1-lifecycle-build/1',
        kernel_revision='94fb23346d522edf53722357c426a3e58030beea',
        shipped_patches_sha256='029f57377a00f3584678f80a8011d8ba7a17c83f1708d9a429d3c91dbb2d0390',
        candidate_patches=expected, candidate_sources=inputs, header_identities=header_hashes,
        header_release=release, vermagic=vermagic,
        compiler=subprocess.check_output(['cc','--version'],text=True).splitlines()[0],
        command=command, build_log_sha256=sha(root/'build.log'),module_sha256=sha(output),
        load_performed=False, installed_changes=False, hardware_qualified=False)
    (root/'build-evidence.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))

if __name__ == '__main__': main()
