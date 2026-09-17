#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""One configured capture and its offline validation; caller owns campaign guard."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

HERE=Path(__file__).resolve().parent
REPO=HERE.parent.parent
sys.path.insert(0,str(HERE.parent/'hevc-full-controls'))
import normalize as full
import report as full_report
import compare
import oracle
import parser

def save(path,data):path.write_text(json.dumps(data,indent=2)+'\n')
def lines(path,rows):path.write_text(''.join(json.dumps(r,separators=(',',':'))+'\n' for r in rows))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def run(config,vector,client,mode,run_id):
    if not os.environ.get('LIBVA_HW_GUARD_LEASE') or os.geteuid()==0:raise ValueError('unprivileged hardware guard required')
    if vector not in 'BE' or len(vector)!=1 or client not in ('va','gst') or mode not in ('off','on'):raise ValueError('run domain')
    root=Path(config['root']);run=root/f'{vector}-{client}-{mode}';run.mkdir(mode=0o700)
    video=Path(config['inputs'][vector]['path'])
    if sha(video)!=config['inputs'][vector]['sha256']:raise ValueError('input changed')
    env=os.environ.copy();env['LC_ALL']='C';env.pop('LIBVA_V4L2_HEVC_REFTRACE',None)
    if client=='va':
        env['LIBVA_V4L2_HEVC_REFTRACE']=str(run/'native-refs.jsonl')
        decoder=[config['helper'],'vaapi',str(video),'yuv420p']
    else:
        env.update(GST_DEBUG_NO_COLOR='1',GST_DEBUG='v4l2codecs*:6',GST_DEBUG_FILE=str(run/'gst.log'))
        decoder=['gst-launch-1.0','-e','filesrc','location='+str(video),'!','h265parse','!',
                 'v4l2slh265dec','name=refprobe','!','videoconvert','!','video/x-raw,format=I420','!',
                 'filesink','location='+str(run/'output.yuv')]
    cmd=['v4l2-tracer','-u','trace',sys.executable,str(HERE/'capture.py'),'--run',str(run_id),
         '--trace',mode,'--deadline','60','--output',str(run/'kernel'),'--']+decoder
    save(run/'command.json',dict(argv=cmd,decoder=decoder,run_id=run_id,guard_lease=os.environ['LIBVA_HW_GUARD_LEASE'],
         start=time.time(),input_sha256=sha(video),supervisor_sha256=sha(HERE/'capture.py'),measure_sha256=sha(Path(__file__)),
         environment={k:env.get(k) for k in ('LC_ALL','LIBVA_DRIVERS_PATH','LIBVA_DRIVER_NAME','LIBVA_V4L2_HEVC_REFTRACE','GST_DEBUG_NO_COLOR','GST_DEBUG','GST_DEBUG_FILE')}))
    with (run/'stdout.log').open('w') as out,(run/'stderr.log').open('w') as err:
        p=subprocess.run(cmd,cwd=run,env=env,stdout=out,stderr=err,timeout=90)
    save(run/'outer-status.json',dict(returncode=p.returncode,end=time.time()))
    execution=json.loads((run/'kernel/execution.json').read_text())
    if p.returncode or execution['child_exit']!=0 or not execution['child_reaped'] or execution['errors']:
        raise ValueError('unsuccessful actual child/recorder; stop without retry')
    if client=='va':
        text=(run/'stdout.log').read_text()
        frames=[[int(i),h] for i,h in re.findall(r'^frame (\d+) 416x240 yuv420p ([0-9a-f]{32})$',text,re.M)]
        whole=re.findall(r'^MD5=([0-9a-f]{32})$',text,re.M)
        if len(whole)!=1:raise ValueError('missing whole output hash')
        whole=whole[0]
    else:
        data=(run/'output.yuv').read_bytes()
        if len(data)!=44928000:raise ValueError('output extent')
        frames=[[i,hashlib.md5(data[i*149760:(i+1)*149760]).hexdigest()] for i in range(300)]
        whole=hashlib.md5(data).hexdigest()
    save(run/'frames.json',frames)
    if [i for i,_ in frames]!=list(range(300)):raise ValueError('output picture extent')
    prior=REPO/'experiments/hevc-avd-trace/captures/2026-09-17-schema2/frames'/f'{vector}-{client}-off.json'
    if frames!=json.loads(prior.read_text()):raise ValueError('prior exact pixels changed; stop and inspect')
    if mode=='on' and frames!=json.loads((root/f'{vector}-{client}-off/frames.json').read_text()):raise ValueError('instrumentation changes pixels')
    files=list(run.glob('*_trace.json'))
    if len(files)!=1 or not 0<files[0].stat().st_size<=128*1024*1024:raise ValueError('ioctl trace extent')
    raw=files[0].read_bytes();token=hashlib.sha256(raw).hexdigest()[:16]
    events=full.base.parse(raw);rows,refs,pics=full.normalize(events,300,token)
    full_report.validate_controls(rows,refs,token)
    lines(run/'controls.jsonl',rows);lines(run/'refs.jsonl',refs);save(run/'input.json',full.extra_evidence(events,300))
    checker=config['checker']
    for other in [run/'refs.jsonl']+([run/'native-refs.jsonl'] if client=='va' else []):
        r=subprocess.run([sys.executable,checker,'compare',str(run/'refs.jsonl'),str(other),'--expected-pictures','300','--json'],capture_output=True,text=True,timeout=30)
        if r.returncode:raise ValueError('reference lifecycle check: '+r.stderr)
    if client=='va':
        pairs=[tuple(map(int,x)) for x in re.findall(r'Output frame with POC (\d+)/(-?\d+)',(run/'stderr.log').read_text())]
        by_poc={r['poc']:r['pic'] for r in refs}
        if len(pairs)!=300 or len(set(pairs))!=300 or not all(layer==0 for layer,poc in pairs) or len(by_poc)!=300 or set(by_poc)!={poc for _,poc in pairs}:raise ValueError('VA output association')
        assoc=[dict(output_index=i,pic=by_poc[poc],poc=poc) for i,(_,poc) in enumerate(pairs)]
    else:assoc=[{k:r[k] for k in ('output_index','pic','poc')} for r in full.base.associate((run/'gst.log').read_text(),pics,300,execution['child_exit'])]
    save(run/'association.json',assoc)
    result=dict(vector=vector,client=client,mode=mode,run_id=run_id,frames=300,md5=whole,actual_child_exit=0,
                ioctl_sha256=sha(files[0]),controls_sha256=sha(run/'controls.jsonl'),kernel_control_differences=[],command_mismatch_pictures=[])
    if mode=='on':
        build=Path(config['oracle']);oracle.verify_identity(build)
        capture=parser.parse_snapshot((run/'kernel/command.snapshot').read_text(),run_id)
        result['kernel_control_differences']=compare.compare(capture,rows,compare.flag_values(Path(config['uapi'])))
        env['HEVC_REFTRACE_CHECKER']=checker
        cmd=[sys.executable,str(REPO/'experiments/hevc-avd-trace/check.py'),str(run/'kernel/reference.snapshot'),
             '--run',str(run_id),'--userspace',str(run/'refs.jsonl')]
        r=subprocess.run(cmd,capture_output=True,text=True,env=env,timeout=30)
        (run/'reference-check.stdout').write_text(r.stdout);(run/'reference-check.stderr').write_text(r.stderr)
        if r.returncode:raise ValueError('paired same-run reference validation failed: '+r.stderr)
        # Parse with accepted reader and bind all 300 actual start histories.
        spec=importlib.util.spec_from_file_location('accepted_check',REPO/'experiments/hevc-avd-trace/check.py')
        refcheck=importlib.util.module_from_spec(spec);spec.loader.exec_module(refcheck)
        ref=refcheck.read_capture((run/'kernel/reference.snapshot').read_text(),run_id);parser.bind_history(capture,ref)
        result['command_mismatch_pictures']=[w['picture'] for w in capture['windows'] if not oracle.verify_window(build,w)]
        save(run/'comparison.json',result)
        if result['kernel_control_differences'] or result['command_mismatch_pictures']:raise ValueError('measured control/command discrepancy; preserve and stop')
    save(run/'result.json',result);print(json.dumps(result),flush=True)

if __name__=='__main__':
    config=json.loads(Path(sys.argv[1]).read_text());run(config,*sys.argv[2:5],int(sys.argv[5]))
