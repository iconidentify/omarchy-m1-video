#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Compile and execute pinned C packing, never an assumed firmware oracle.

No device access. Address/reference helpers are explicit stubs: the accepted
schema-2 validator remains mandatory for that separate evidence. The complete
selected non-address command sequence comes from the real C function bodies.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import urllib.request

import packing
import parser

HERE=Path(__file__).resolve().parent
REPO=HERE.parent.parent

def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()

def source_base(pristine, out):
    manifest=json.loads((REPO/'experiments/hevc-avd-trace/sources.json').read_text())
    out.mkdir()
    for name,digest in manifest['upstream_files'].items():
        parser.need(sha(pristine/name)==digest,'primary source hash: '+name)
        shutil.copyfile(pristine/name,out/name)
    for entry in manifest['patches']['files']:
        p=REPO/entry['path'];parser.need(sha(p)==entry['sha256'],'shipped patch hash')
        subprocess.run(['patch','--batch','--fuzz=0','-p6','-i',str(p)],cwd=out,check=True,capture_output=True,timeout=30)
    return out

def build(source, candidate, out, uapi=None):
    pins=json.loads((REPO/'experiments/hevc-avd-controls-map/source-map.json').read_text())
    parser.need(sha(source/'avd-hevc.c')==pins['patched_avd_hevc_c']['sha256'],'packing source changed')
    parser.need(sha(source/'avd-inst.h')==pins['avd_inst_h']['sha256'],'instruction macros changed')
    out.mkdir()
    info=pins['v4l2_controls_h']
    if uapi is None:
        url=info['url'].replace('https://github.com/','https://raw.githubusercontent.com/').replace('/blob/','/')
        with urllib.request.urlopen(url,timeout=30) as r: data=r.read(1024*1024+1)
    else: data=uapi.read_bytes()
    parser.need(hashlib.sha256(data).hexdigest()==info['sha256'],'UAPI hash')
    (out/'v4l2-controls.h').write_bytes(data)
    text=(source/'avd-hevc.c').read_text()
    # Names/expressions copied without rewriting from the pinned primary source.
    macros=[]
    for name in ('avd-inst.h','avd-hevc.c','avd.h'):
        macros+=re.findall(r'^#define\s+(?:AVD_|HEVC_|NEW_)[^\n]*',(source/name).read_text().replace('\\\n',''),re.M)
    (out/'macros.h').write_text('\n'.join(macros)+'\n#define AVD_CODEC_HEVC 0\n')
    for name in ('cmd-core.h','control-layout.inc'):
        shutil.copyfile(candidate/name,out/name)
    kernel=(candidate/'avd-cmdtrace.c').read_text()
    serializer='\n'.join(packing.extract(kernel,n) for n in ('pack_bytes','pack_u16','pack_u32','pack_u64','pack_controls'))
    (out/'serializer.h').write_text(serializer+'\n')
    builds={}
    for name,src in [('baseline',source),('candidate',candidate)]:
        work=out/name;work.mkdir()
        original=(src/'avd-hevc.c').read_text()
        (work/'functions.h').write_text(original[:original.index('#include')]+'\n'+
                                      '\n\n'.join(packing.extract(original,n) for n in packing.FUNCTIONS)+'\n')
        command=['cc','-std=gnu11','-Wall','-Werror',
                 '-fsanitize=address,undefined','-fno-sanitize-recover=all','-I',str(work),'-I',str(out),
                 str(HERE/'packing-host.c'),'-o',str(work/'packing')]
        r=subprocess.run(command,capture_output=True,text=True,timeout=60)
        (work/'build.log').write_text(r.stdout+r.stderr)
        parser.need(r.returncode==0,r.stderr)
        builds[name]={'command':command,'source_sha256':sha(src/'avd-hevc.c'),
                      'extracted_sha256':sha(work/'functions.h'),'binary_sha256':sha(work/'packing')}
    ident={'schema':1,'compiler':subprocess.check_output(['cc','--version'],text=True).splitlines()[0],
           'uapi_sha256':sha(out/'v4l2-controls.h'),'harness_sha256':sha(HERE/'packing-host.c'),
           'layout_sha256':sha(out/'control-layout.inc'),'serializer_sha256':sha(out/'serializer.h'),
           'builds':builds,'tool_sha256':{n:sha(HERE/n) for n in ('oracle.py','parser.py','packing.py')}}
    (out/'identity.json').write_text(json.dumps(ident,indent=2)+'\n')
    return out

def site_ids():
    text=(HERE/'kernel/cmd-core.h').read_text()
    body=re.search(r'enum cmd_site\s*\{(.*?)\}',text,re.S).group(1)
    result={};number=0
    for tok in body.split(','):
        if not tok.strip():continue
        bits=tok.strip().split('=');number=int(bits[1]) if len(bits)>1 else number+1
        result[bits[0].strip().removeprefix('CMD_SITE_')]=number
    return result

SITES=site_ids()

def execute(binary,row):
    c=parser.unpack_controls(row['controls']);parser.validate_controls(c)
    args=[str(binary)]+[str(row[k]) for k in ('decomp','revision','quirks','bytesperline')]
    r=subprocess.run(args,input=row['controls'][:parser.CMD_PACKED],capture_output=True,timeout=10)
    parser.need(r.returncode==0,'C packing execution failed: '+r.stderr.decode(errors='replace'))
    pushes=[];traces=[];inactive=[];meta=[]
    for line in r.stdout.decode().splitlines():
        k,*v=line.split(' ',2)
        if k=='P':pushes.append((int(v[0],16),v[1]))
        elif k=='T':traces.append((int(v[1]),int(v[0],16)))
        elif k=='I':inactive.append(int(v[0]))
        elif k=='M':
            values=list(map(int,' '.join(v).split()));meta+=values
            traces.extend((SITES['SLICE_META'],x) for x in values)
        else:raise parser.MissingInput('unknown C output')
    return dict(pushes=pushes,traces=traces,inactive=inactive,meta=meta)

def expected_from_source(result,c):
    selected=[];coded_flags=None
    for word,label in result['pushes']:
        site=packing.SITES.get(label)
        if label in ('','zero'):site='HDR_ZERO'
        if site:selected.append((SITES[site],word))
        if label=='cm3_cmd_set_coded_slice':coded_flags=word & 0x6000
        if label=='slc_bdc_slice_size':
            parser.need(coded_flags is not None,'missing coded header')
            selected.extend((SITES['SLICE_META'],v) for v in (word,0,coded_flags,c['data_byte_offset']))
    inactive=([SITES['SCL_OFF']] if not c['sps_flags']&2 else [])+([SITES['WT_SKIP']] if c['slice_type']==2 else [])
    return selected,inactive

def predict(build_dir,row,check_hooks=False):
    c=parser.unpack_controls(row['controls']);parser.validate_controls(c)
    result=execute(build_dir/'baseline/packing',row)
    words,inactive=expected_from_source(result,c)
    if check_hooks:
        hooked=execute(build_dir/'candidate/packing',row)
        parser.need(hooked['pushes']==result['pushes'],'instrumentation changed decode pushes')
        parser.need(hooked['traces']==words,'hook omits/reorders/changes selected words')
        parser.need(sorted(hooked['inactive'])==sorted(inactive),'inactive hook placement')
    return words,sum(1 << site for site in inactive)

def verify_window(build_dir,row):
    if len(row['sites']) != len(row['words']) or len(row['words']) != row['nwords']:
        return False
    words,inactive=predict(build_dir,row)
    return list(zip(row['sites'],row['words']))==words and row['inactive']==inactive

def verify_identity(build_dir):
    ident=json.loads((build_dir/'identity.json').read_text())
    parser.need(ident['schema']==1 and ident['harness_sha256']==sha(HERE/'packing-host.c') and
                ident['layout_sha256']==sha(HERE/'kernel/control-layout.inc'), 'stale oracle identity')
    for name,digest in ident['tool_sha256'].items():
        parser.need(sha(HERE/name)==digest,'oracle tool hash: '+name)
    for name in ('baseline','candidate'):
        parser.need(ident['builds'][name]['binary_sha256']==sha(build_dir/name/'packing'), 'oracle binary hash')
    return ident

def read_text(path,limit):
    with path.open('rb') as f:data=f.read(limit+1)
    parser.need(len(data)<=limit,'oversized snapshot file')
    return data.decode('ascii')

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    sub=ap.add_subparsers(dest='action',required=True)
    prep=sub.add_parser('prepare');prep.add_argument('--source',type=Path,required=True)
    prep.add_argument('--candidate',type=Path,required=True);prep.add_argument('--output',type=Path,required=True)
    check=sub.add_parser('check');check.add_argument('--build',type=Path,required=True)
    check.add_argument('--snapshot',type=Path,required=True);check.add_argument('--reference-snapshot',type=Path,required=True)
    check.add_argument('--run',type=int,required=True)
    a=ap.parse_args()
    if a.action=='prepare':
        a.output.mkdir()
        base=source_base(a.source.resolve(),a.output/'baseline')
        build(base,a.candidate.resolve(),a.output/'compiled')
        print('PASS: pinned C oracle prepared; no decoder or module execution')
        return 0
    verify_identity(a.build)
    capture=parser.parse_snapshot(read_text(a.snapshot,512*1024),a.run)
    refdir=REPO/'experiments/hevc-avd-trace';sys.path.insert(0,str(refdir))
    for name,expected in json.loads((HERE/'sources.json').read_text())['accepted_trace_files'].items():
        parser.need(sha(refdir/name)==expected,'accepted reference source drift')
    spec=importlib.util.spec_from_file_location('accepted_trace_check',refdir/'check.py')
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    ref=mod.read_capture(read_text(a.reference_snapshot,4*1024*1024),a.run)
    validated=mod.validate(ref)
    # Existing reference discrepancies remain visible, never accepted silently.
    parser.bind_history(capture,ref)
    findings=[row['picture'] for row in capture['windows'] if not verify_window(a.build,row)]
    print(json.dumps({'run':a.run,'command_mismatch_pictures':findings,'reference_validation':validated},indent=2))
    return bool(findings or validated['findings'])

if __name__=='__main__':raise SystemExit(main())
