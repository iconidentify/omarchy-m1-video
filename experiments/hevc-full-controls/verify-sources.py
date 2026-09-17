#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Check pinned primary sources, serialized field inventory and C ABI sizes."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import urllib.request
import schema

HERE=Path(__file__).resolve().parent


def verify(directory):
    for entry in json.loads((HERE/'sources.json').read_text())['sources']:
        path=directory/Path(entry['path']).name
        if not path.exists():
            # Blob links in the prior manifest point at the same exact revision.
            url=entry['url'].replace('https://github.com/','https://raw.githubusercontent.com/').replace('/blob/','/')
            data=urllib.request.urlopen(url,timeout=30).read()
            if hashlib.sha256(data).hexdigest()!=entry['sha256']:raise ValueError('source mismatch')
            path.write_bytes(data)
        if hashlib.sha256(path.read_bytes()).hexdigest()!=entry['sha256']:raise ValueError('cached source mismatch')
    actual=schema.derive((directory/'v4l2-controls.h').read_text(),(directory/'v4l2-tracer-info-gen.h').read_text())
    if actual!=json.loads((HERE/'payload-schema.json').read_text()):raise ValueError('serialized shape inventory changed')
    # Compile against the exact pinned UAPI, not the host's newer control header.
    names=['sps','pps','slice_params','decode_params','scaling_matrix']
    c='#include <stdio.h>\n#include "v4l2-controls.h"\nint main(void){\n'
    c+=''.join('printf("%zu\\n", sizeof(struct v4l2_ctrl_hevc_'+n+'));\n' for n in names)+'}\n'
    with tempfile.TemporaryDirectory() as tmp:
        p=Path(tmp);(p/'sizes.c').write_text(c)
        subprocess.run(['cc','-Wall','-Wextra','-Werror','-I',str(directory),str(p/'sizes.c'),'-o',str(p/'sizes')],check=True,timeout=30)
        values=list(map(int,subprocess.check_output([str(p/'sizes')],text=True,timeout=5).split()))
        if values != [40,64,280,328,1000]:raise ValueError('unsupported control ABI')
    original=(HERE.parent/'hevc-controls/normalize.py').read_text()
    section=original[original.index('def normalize('):original.index('\n\ndef associate(')]
    replacement='''            # Successful OUTPUT STREAMOFF cancels any final source buffers
            # the client did not dequeue; CAPTURE completion is still mandatory.
            if e.get("from_userspace", {}).get("type") == OUT:
                output_buffers.clear()
            stopped = True
            continue'''
    section=section.replace('            stopped = True\n            continue',replacement)
    fork=(HERE/'lifecycle.py').read_text().split('def normalize(',1)[1]
    if 'def normalize('+fork.rstrip()!=section.rstrip():raise ValueError('unreviewed lifecycle drift')
    print('PASS: primary source hashes, complete serialized shapes, exact C ABI, scoped lifecycle delta')


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--source-dir',type=Path);args=ap.parse_args()
    if args.source_dir:verify(args.source_dir)
    else:
        with tempfile.TemporaryDirectory() as tmp:verify(Path(tmp))
