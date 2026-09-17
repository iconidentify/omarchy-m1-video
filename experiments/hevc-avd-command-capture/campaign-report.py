#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Reproduce paired-command capture evidence using complete public metadata.

The C oracle is built from pinned primary source. Normalized reference replay uses
symbolic writer tokens, not private timestamps or independent raw authentication.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import compare
import oracle
import parser

HERE=Path(__file__).resolve().parent
REPO=HERE.parent.parent
DEFAULT=HERE/'capture-2026-09-17'

def load_module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod

sys.path.insert(0,str(HERE.parent/'hevc-full-controls'))
full=load_module('full_report',HERE.parent/'hevc-full-controls/report.py')
sys.path.insert(0,str(HERE.parent/'hevc-avd-trace'))
refs_report=load_module('reference_campaign',HERE.parent/'hevc-avd-trace/campaign-report.py')
need=parser.need

def read(p,lines=False):
    data=p.read_bytes();need(len(data)<=16*1024*1024,'file extent')
    def unique(pairs):
        result={}
        for k,v in pairs:
            need(k not in result,'duplicate JSON key');result[k]=v
        return result
    def parse(s):return json.loads(s,object_pairs_hook=unique,parse_constant=lambda s: (_ for _ in ()).throw(ValueError('nonfinite JSON')))
    return [parse(s) for s in data.splitlines()] if lines else parse(data)

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def verify_guard(guards):
    need([g['event'] for g in guards]==['preflight','start','final'],'guard event extent')
    gid=guards[0]['run_id'];need(all(g['run_id']==gid for g in guards),'mixed guard identity')
    need(guards[0]['idle'] and guards[0]['module_loaded'],'guard preflight failed')
    f=guards[-1]
    need(f['status']=='ok' and f['returncode']==0 and f['idle'] and not f['holders'] and not f['timed_out'] and not f['wedged'] and f['abort_reason'] is None,'guard failed')
    return gid

def verify_transitions(events,lease,expected_runs,original):
    need(all(r['lease']==lease for r in events),'transition lease mismatch')
    pairs=[r for r in events if r['event']=='transition-result']
    need([r['argv'][0] for r in pairs]==['rmmod','insmod','rmmod','modprobe'] and all(r['returncode']==0 for r in pairs),'module transition failure')
    need([r['argv'] for r in events if r['event']=='transition-attempt']==[r['argv'] for r in pairs],'unpaired module transition')
    need(all(not r['faults'] and not r['stuck_tasks'] and not r['holders'] for r in events if r['event']=='state'),'unhealthy intermediate state')
    pre=[r for r in events if r['event']=='recorder-preflight']
    need([r['recorder'] for r in pre]==['reference','command'],'missing paired endpoints')
    for r in pre:need(not any(r['status'].values()),'recorders not initially off/idle')
    starts=[r for r in events if r['event']=='run-start'];ends=[r for r in events if r['event']=='run-result']
    need([r['name'] for r in starts]==expected_runs and [r['name'] for r in ends]==expected_runs,'missing run transition')
    need([r['run_id'] for r in starts]==[r['run_id'] for r in ends]==list(range(1,len(expected_runs)+1)) and all(r['returncode']==0 for r in ends),'failed/mixed run result')
    restored=[r for r in events if r['event']=='original-restored']
    need(len(restored)==1 and restored[0]['installed_sha256']==original,'missing original restoration')
    terminal=[r for r in events if r['event']=='terminal-state']
    need(len(terminal)==1,'missing terminal state');f=terminal[0]
    need(f['original_restored'] and f['module_initstate']=='live' and f['module_loaded'] and f['video_node'] and not f['holders'] and not f['stuck_tasks'] and not f['faults'],'unhealthy terminal state')
    need(events[-1]['event']=='complete' and events[-1]['runs']==len(expected_runs) and events[-1]['restored'],'incomplete campaign')
    need(not any(r['event'] in ('campaign-failed','restoration-not-completed') for r in events),'hidden failure')

def summarize(root,build):
    files=read(root/'files.json');actual={p.name for p in root.iterdir() if p.is_file()}-{'files.json','summary.json','README.md'}
    need(set(files)==actual and all(Path(n).name==n for n in files),'unsafe/incomplete inventory')
    need(all(sha(root/n)==h for n,h in files.items()),'artifact digest changed')
    prov=read(root/'provenance.json');candidate=HERE.parent/'hevc-avd-command-trace/corrected-build.json'
    need(sha(candidate)==prov['candidate_build_sha256'] and read(candidate)['module_sha256']==prov['module_sha256'],'candidate attribution')
    reference_path=HERE.parent/'hevc-controls/captures/2026-09-17/reference-frames.json'
    need(sha(reference_path)==prov['reference_frames_sha256'],'pixel reference changed')
    reference=read(reference_path);oracle.verify_identity(build);flags=compare.flag_values(build/'v4l2-controls.h')
    need(prov['post_run_binary_verification']==dict(prov['binaries'],**{'v4l2_request_drv_video.so':prov['userspace_driver']['sha256'],'frame-check-debug':prov['helper']['binary_sha256']}),'selected userspace binary identity')
    recorded=read(root/'oracle-identity.json');current=read(build/'identity.json')
    for key in ('uapi_sha256','harness_sha256','layout_sha256','serializer_sha256','tool_sha256'):
        need(recorded[key]==current[key],'C oracle source mismatch: '+key)
    for variant in ('baseline','candidate'):
        for key in ('source_sha256','extracted_sha256'):need(recorded['builds'][variant][key]==current['builds'][variant][key],'packing C mismatch')
    recovery=read(root/'recovery.json');final=read(root/'final-state.json')
    need(recovery['boot_id']==prov['boot_id'] and recovery['original_loaded_build_id_matches'] and final['loaded_original_build_id_matches'],'loaded/boot identity')
    for r in (recovery,final):
        state=r['state'];need(state['module_loaded'] and state['video_node'] and not state['holders'] and not state['stuck_tasks'] and not state['faults'],'recovery/final health')
    need(recovery['installed_original_sha256']==final['installed_sha256']==prov['original_sha256'],'installed original changed')
    ids=[f'{v}-{c}-{m}' for v in 'BE' for c in ('va','gst') for m in ('off','on')]
    leases={}
    for stage,expected in [('probe',[]),('campaign',ids)]:
        leases[stage]=verify_guard(read(root/(stage+'-guard.json')))
        verify_transitions(read(root/(stage+'-events.json')),leases[stage],expected,prov['original_sha256'])
    need(leases['probe']!=leases['campaign'],'probe/campaign lease reused')
    private={r['path']:r for r in read(root/'private-artifacts.json')['files']}
    runs=read(root/'runs.json');need([r['id'] for r in runs]==ids,'missing/duplicate/reordered run')
    result={};data={};commands={};kernels={};inputs={}
    checker=refs_report.source_report.checker_path()
    for index,r in enumerate(runs,1):
        name=r['id'];v,c,mode=name.split('-');e=r['execution']
        need((r['run_id'],r['vector'],r['client'],r['mode'])==(index,v,c,mode),'wrong run identity')
        need(r['command']['guard_lease']==leases['campaign'] and r['command']['run_id']==index and r['command']['input_sha256']==prov['inputs'][v],'run lease/input binding')
        need(r['actual_child_exit']==r['outer']['returncode']==e['child_exit']==0 and e['child_reaped'] and e['child_released'] and not e['errors'],'failed child/supervisor')
        need(e['run']==index and e['enabled']==(mode=='on') and e['elapsed_seconds']<=90,'supervisor contract')
        need(r['command']['supervisor_sha256']==prov['tool_sha256']['capture.py'] and r['command']['measure_sha256']==prov['tool_sha256']['measure.py'],'execution tool binding')
        need(r['kernel_control_differences']==r['command_mismatch_pictures']==[],'recorded findings ignored')
        hashes=r['frames_md5'];need(len(hashes)==r['frames']==300 and all(re.fullmatch('[0-9a-f]{32}',h) for h in hashes),'frame extent/domain')
        prior=read(HERE.parent/'hevc-avd-trace/captures/2026-09-17-schema2/frames'/f'{v}-{c}-off.json')
        need(hashes==[h for _,h in prior],'prior exact frame set changed')
        wrong=[i for i,h in enumerate(hashes) if h!=reference[v]['frame_md5'][i]]
        need(wrong==r['wrong_indices'] and len(wrong)==(0 if v=='B' else 26 if c=='va' else 25),'wrong-frame set mismatch')
        expected_md5='6d1ed392b067050ebd3a24a37281da03' if v=='B' else 'b09ac8e0bd31a96d8354505d7c2ebdd5' if c=='va' else '53952960ec7512d9cb64f8c7020ece03'
        need(r['md5']==expected_md5,'whole-output hash mismatch')
        control_path=root/(name+'-controls.jsonl');refpath=root/(name+'-refs.jsonl')
        rows=read(control_path,True);refs=read(refpath,True)
        need(sha(control_path)==r['controls_sha256'],'same-run control hash')
        raw=[p for p in private if p.startswith('campaign/'+name+'/') and p.endswith('_trace.json')]
        need(len(raw)==1 and private[raw[0]]['sha256']==r['ioctl_sha256'],'raw ioctl binding')
        full.validate_controls(rows,refs,r['ioctl_sha256'][:16])
        subprocess.run([sys.executable,str(checker),'compare',str(refpath),str(refpath),'--expected-pictures','300','--json'],check=True,capture_output=True,timeout=30)
        assoc=read(root/(name+'-association.json'))
        need(len(assoc)==300 and [a['output_index'] for a in assoc]==list(range(300)) and sorted(a['pic'] for a in assoc)==list(range(1,301)),'output association extent')
        need(all(a['poc']==refs[a['pic']-1]['poc'] for a in assoc),'output POC binding')
        bad=[assoc[i] for i in wrong]
        result[name]=dict(frames=300,wrong_outputs=len(wrong),wrong_indices=wrong,first_bad_decode=min(bad,key=lambda a:a['pic']) if bad else None)
        extra=read(root/(name+'-input.json'));inputs[name]=extra['encoded_inputs']
        modes={k:x['value'] for k,x in extra['modes'].items()}
        need(modes=={full.n.base.CID+'DECODE_MODE':'V4L2_STATELESS_HEVC_DECODE_MODE_FRAME_BASED',full.n.base.CID+'START_CODE':'V4L2_STATELESS_HEVC_START_CODE_NONE'},'decode/start-code mode mismatch')
        need(len(inputs[name])==300 and [x['picture'] for x in inputs[name]]==list(range(1,301)) and all(x['bytes']>0 and re.fullmatch('[0-9a-f]{64}',x['sha256']) for x in inputs[name]),'coded-input extent')
        data[name]=hashes
        if mode=='on':
            need(hashes==data[f'{v}-{c}-off'],'recorder perturbs pixels')
            cmdpath=root/(name+'-command.snapshot');cmd=parser.parse_snapshot(cmdpath.read_text(),index)
            need(sha(cmdpath)==e['snapshots']['command']['sha256'] and private[f'campaign/{name}/kernel/command.snapshot']['sha256']==sha(cmdpath),'command snapshot binding')
            meta=read(root/(name+'-reference.json'))
            need((meta['run'],meta['context'])==(index,cmd['context']) and meta['userspace_sha256']==sha(refpath),'paired reference identity')
            need(meta['raw_sha256']==e['snapshots']['reference']['sha256']==private[f'campaign/{name}/kernel/reference.snapshot']['sha256'],'reference raw binding')
            ref_status=e['status']['reference']
            need(ref_status['count']==ref_status['attempted']==len(meta['records']),'reference record extent mismatch')
            need(e['snapshots']['command']['bytes']==cmdpath.stat().st_size and 0<e['snapshots']['reference']['bytes']<=4*1024*1024,'snapshot byte extent')
            for status in e['status'].values():need((status['run'],status['context'],status['phase'],status['errors'],status['pictures'],status['completions'],status['opens'])==(index,cmd['context'],4,0,300,300,0),'sealed status mismatch')
            refs_report.symbolic_replay(meta,meta['records'],refs_report.check.model.map_records(refs,300))
            parser.bind_history(cmd,meta)
            need(compare.compare(cmd,rows,flags)==[],'copied controls differ from same-run ioctl')
            need(all(oracle.verify_window(build,w) for w in cmd['windows']),'actual command differs from C source')
            commands[name]=cmd;kernels[name]=meta['records']
        else:
            need(not e['snapshots'] and all(not any(s.values()) for s in e['status'].values()),'off recorder produced data')
    vectors={}
    for v in 'BE':
        names=[f'{v}-{c}-{m}' for c in ('va','gst') for m in ('off','on')]
        need(all(inputs[n]==inputs[names[0]] for n in names),'submitted encoded bytes differ')
        left,right=(commands[f'{v}-{c}-on']['windows'] for c in ('va','gst'))
        need([r['poc'] for r in left]==[r['poc'] for r in right],'cross-client picture pairing')
        need(all((a['sites'],a['words'],a['inactive'])==(b['sites'],b['words'],b['inactive']) for a,b in zip(left,right)),'cross-client actual words differ')
        ref_windows=[refs_report.window(kernels[f'{v}-{c}-on']) for c in ('va','gst')]
        need(ref_windows[0]==ref_windows[1],'reference/motion logical projection differs')
        diffs={}
        for a,b in zip(left,right):
            x,y=parser.unpack_controls(a['controls']),parser.unpack_controls(b['controls'])
            for k in x:
                if x[k]!=y[k]:diffs.setdefault(k,[]).append(a['picture'])
        vectors[v]=dict(pictures=list(range(24,35)),pocs=[w['poc'] for w in left],words_per_client=sum(w['nwords'] for w in left),
                        commands_equal=True,copied_control_differences_between_clients=diffs,reference_motion_equal=True,encoded_inputs_equal=300)
    return dict(schema='hevc-avd-command-capture.decision/1',workloads=8,frames=2400,paired_histories=4,kernel_history_pictures=1200,
                detailed_pictures=44,selected_words=sum(x['words_per_client']*2 for x in vectors.values()),runs=result,vectors=vectors,
                original_restored=True,new_faults=0,decision='No discrepancy in copied controls or selected actual commands; RPS_E corruption unchanged. Next investigate compressed-reference contents/lifetime and DMA/cache/firmware state.',
                limits=['Pinned C is a source-packing oracle, not a proved firmware contract.','Encoded hashes precede QBUF, not a measurement of bytes later read by DMA.','Symbolic metadata replay cannot independently authenticate private raw output.','No HEVC fix, codec-count increase, full-suite, concurrency, boot or stability qualification.'])

if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--directory',type=Path,default=DEFAULT);ap.add_argument('--oracle',type=Path,required=True);ap.add_argument('--verify',action='store_true');a=ap.parse_args()
    result=summarize(a.directory,a.oracle)
    if a.verify:
        need(result==read(a.directory/'summary.json'),'committed summary differs');print('PASS: 8 x 300 frames, four paired histories, 44 command windows, exact same-run controls/C packing and restored original')
    else:print(json.dumps(result,indent=2))
