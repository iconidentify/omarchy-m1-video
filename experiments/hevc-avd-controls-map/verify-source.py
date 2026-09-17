#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Fetch/check exact primary sources, apply shipped patches offline, audit map.

No module build, device access, privileged action or persistent system change.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import urllib.request
import validate
import scan

HERE=Path(__file__).resolve().parent
REPO=HERE.parent.parent

def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def require(ok, reason):
    if not ok: raise ValueError(reason)

def macros(path):
    return {m.group(1): re.sub(r'\s+', '', m.group(2)) for m in
            re.finditer(r'^#define\s+(\w+)((?:\([^\n]*?\))?\s+[^\n]+)',path.read_text(),re.M)}

def verify(pristine, work):
    pins=json.loads((HERE/'source-map.json').read_text())
    manifest=json.loads((REPO/'experiments/hevc-avd-trace/sources.json').read_text())
    require(manifest['kernel_revision']==pins['kernel_revision'], 'kernel pin drift')
    for name,digest in manifest['upstream_files'].items():
        require(sha(pristine/name)==digest, 'source hash: '+name)
    work.mkdir()
    for name in manifest['upstream_files']: shutil.copyfile(pristine/name,work/name)
    patches=[]
    for item in manifest['patches']['files']:
        p=REPO/item['path'];require(sha(p)==item['sha256'],'patch hash');patches.append(p)
    require(hashlib.sha256(b''.join(p.read_bytes() for p in patches)).hexdigest()==pins['patches']['concatenated_sha256'],'patch concat')
    for p in patches: subprocess.run(['patch','--batch','--fuzz=0','-p6','-i',str(p)],cwd=work,check=True,stdout=subprocess.PIPE,timeout=30)
    hevc=work/'avd-hevc.c'
    require(sha(hevc)==pins['patched_avd_hevc_c']['sha256'],'patched source differs')
    for key in ('avd_inst_h','v4l2_controls_h'):
        item=pins[key]; dest=work/('v4l2-controls.h' if key=='v4l2_controls_h' else 'avd-inst.h')
        if not dest.exists():
            url=item['url'].replace('https://github.com/','https://raw.githubusercontent.com/').replace('/blob/','/')
            with urllib.request.urlopen(url,timeout=30) as r: data=r.read(1024*1024+1)
            require(hashlib.sha256(data).hexdigest()==item['sha256'],'extra primary source changed');dest.write_bytes(data)
        require(sha(dest)==item['sha256'],'extra source hash')
    for local,upstream in [('avd-control-bits.h',work/'avd-inst.h'),('hevc-flags.h',hevc)]:
        actual=macros(upstream)
        require(all(actual.get(k)==v for k,v in macros(HERE/local).items()),'copied macro differs from primary source')
    campaign=REPO/pins['campaign']['path']
    for name,key in [('summary.json','summary_sha256'),('README.md','readme_sha256')]:
        require(sha(campaign/name)==pins['campaign'][key],'campaign pin')
    require(sha(REPO/'experiments/hevc-avd-trace/sources.json')==pins['campaign']['sources_json_sha256'],'manifest pin')
    require(sha(REPO/'experiments/hevc-avd-map/source-map.json')==pins['campaign']['hevc_avd_map_source_map_sha256'],'original map pin')
    require(not validate.compare_source(hevc,validate.load_inventory()['fields']),'unaccounted function-local reads/calls')
    validate.check_inventory()
    # Execute exact pinned C bodies with a bounded userspace push collector.
    # Preserve upstream macro expressions; no rewritten branch model substitutes
    # for the source functions under test.
    definitions=re.findall(r'^#define\s+AVD_[^\n]*', (work/'avd-inst.h').read_text().replace('\\\n',''), re.M)
    (work/'selected-macros.h').write_text('\n'.join(definitions)+'\n')
    functions=scan.functions(hevc.read_text())
    (work/'selected-functions.h').write_text(functions['stream_weights']+'\n'+functions['stream_slice_dqtblk'])
    binary=work/'branches'
    subprocess.run(['cc','-std=gnu11','-Wall','-Werror','-fsanitize=undefined','-fno-sanitize-recover=all',
                    '-I',str(work),str(HERE/'source-branches.c'),'-o',str(binary)],check=True,timeout=30)
    subprocess.run([str(binary)],check=True,timeout=5)
    print('PASS: immutable sources, 15 patches, imported macros, campaign, function-local field/call coverage')
    return hevc

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--source-dir',type=Path);args=ap.parse_args()
    with tempfile.TemporaryDirectory() as temp:
        root=Path(temp);pristine=args.source_dir
        if pristine is None:
            spec=importlib.util.spec_from_file_location('fetch_avd',REPO/'experiments/hevc-avd-trace/fetch.py')
            f=importlib.util.module_from_spec(spec);spec.loader.exec_module(f)
            pristine=root/'pristine';f.fetch(pristine)
        hevc=verify(pristine.resolve(),root/'patched')
        subprocess.run(['python3',str(HERE/'validate.py'),'--self-test'],check=True,
                       env={**__import__('os').environ,'HEVC_AVD_HEVC_C':str(hevc)},timeout=60)
if __name__=='__main__':main()
