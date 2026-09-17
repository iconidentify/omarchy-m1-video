#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Reproduce the complete-controls campaign decision from public metadata."""
import argparse
import collections
import copy
import hashlib
import json
from pathlib import Path
import re
import normalize as n

HERE=Path(__file__).resolve().parent
DEFAULT=HERE/'capture'
PRIOR=HERE.parent/'hevc-avd-trace/captures/2026-09-17-schema2'
REFERENCE=HERE.parent/'hevc-controls/captures/2026-09-17/reference-frames.json'
need=n.need


def read(path, lines=False):
    raw=n.base.load(path).decode('utf-8')
    def parse(s):return json.loads(s,object_pairs_hook=n.base.unique,parse_constant=lambda _: (_ for _ in ()).throw(ValueError('invalid constant')))
    return [parse(s) for s in raw.splitlines()] if lines else parse(raw)


def digest(path):return hashlib.sha256(n.base.load(path)).hexdigest()


def validate_controls(rows,refs,run):
    need(len(rows)==len(refs)==300,'incomplete control/reference extent')
    writers={}; logical=[]
    for i,(row,ref) in enumerate(zip(rows,refs),1):
        need(row['schema']=='hevc-full-controls/1' and row['picture']==ref['pic']==i
             and row['run']==ref['run']==run and row['target']==ref['target'] and row['poc']==ref['poc'],
             'mixed control/reference identity')
        cs=row['controls'];need(set(cs)==set(n.SIZES),'missing payload')
        changes=row['input_changes'];seen=set()
        for change in changes:
            need(set(change)=={'control','field','submitted','returned'},'invalid correction record')
            name,field=change['control'],change['field']
            need(name in row['submitted'] and name in cs and field in cs[name]
                 and (name,field) not in seen,'unbound/duplicate correction')
            seen.add((name,field))
            need(change['returned']==cs[name][field] and change['submitted']!=change['returned'],'correction does not match return')
            raw=copy.deepcopy(cs[name]);raw[field]=change['submitted']
            need(name!='DECODE_PARAMS','unexpected reference correction')
            if 'flags' in raw:raw['flags']='|'.join(raw['flags'])
            n.payload(raw,'v4l2_ctrl_hevc_'+name.lower())
        # Restore symbolic input shapes only to validate every numeric field,
        # array length and flag. These are not reconstructed raw timestamps.
        for name,data in cs.items():
            raw=copy.deepcopy(data)
            if name=='DECODE_PARAMS':
                for ent in raw['dpb']:
                    writer=ent.pop('timestamp_writer')
                    need(writer is None or type(writer) is int and 1<=writer<i,'invalid writer')
                    ent['timestamp']=0 if writer is None else writer*1000
                    need(set(ent['flags'])<= {'V4L2_HEVC_DPB_ENTRY_LONG_TERM_REFERENCE'},'unknown DPB flag')
                    ent['flags']='V4L2_HEVC_PPS_FLAG_DEPENDENT_SLICE_SEGMENT_ENABLED' if ent['flags'] else ''
            if 'flags' in raw:
                need(type(raw['flags']) is list,'invalid public flags')
                raw['flags']='|'.join(raw['flags'])
            checked=n.payload(raw,'v4l2_ctrl_hevc_'+name.lower())
            if name=='DECODE_PARAMS':
                for ent in checked['dpb']:
                    token=ent.pop('timestamp');ent['timestamp_writer']=token//1000 if token else None
            need(checked==data,'noncanonical payload')
        need(row['submitted']==sorted(set(row['submitted'])) and set(row['submitted'])<=set(cs)
             and set(row['submitted'])>={'PPS','DECODE_PARAMS','SLICE_PARAMS','SCALING_MATRIX'},'invalid explicit control set')
        if 'SPS' in row['submitted']:need(row['sps_from_picture']==i,'bad SPS source')
        else:
            need(i>1 and row['sps_from_picture']==rows[i-2]['sps_from_picture']
                 and cs['SPS']==rows[i-2]['controls']['SPS'],'invented inherited SPS')
        dp,sl=cs['DECODE_PARAMS'],cs['SLICE_PARAMS']
        need(dp['pic_order_cnt_val']==sl['slice_pic_order_cnt']==row['poc'],'POC mismatch')
        need(dp['num_active_dpb_entries']==len(ref['dpb']),'DPB extent mismatch')
        for slot,ent in enumerate(dp['dpb']):
            w=ent['timestamp_writer']
            if slot>=dp['num_active_dpb_entries']:
                need(w is None,'inactive timestamp was not omitted');continue
            need(w is not None and writers.get(ref['dpb'][slot]['buf'])==w,'stale/incorrect logical writer')
            actual=ref['dpb'][slot]
            need(ent['pic_order_cnt_val']==actual['poc']==rows[w-1]['poc'] and ent['field_pic']==actual['field']
                 and bool(ent['flags'])==bool(actual['lt']),'control/reference DPB mismatch')
        for key,suffix in [('st_before','st_curr_before'),('st_after','st_curr_after'),('lt_curr','lt_curr')]:
            count=dp['num_poc_'+suffix]
            need(dp['poc_'+suffix][:count]==ref[key],'RPS list mismatch')
        typ=sl['slice_type'];need(typ in (0,1,2) and ('B','P','I')[typ]==ref['slices'][0]['type'],'type mismatch')
        lists={}
        for key,count in [('l0',0 if typ==2 else sl['num_ref_idx_l0_active_minus1']+1),('l1',sl['num_ref_idx_l1_active_minus1']+1 if typ==0 else 0)]:
            slots=sl['ref_idx_'+key][:count];need(slots==ref['slices'][0][key],'slice reference mismatch')
            lists[key]=[dp['dpb'][j]['timestamp_writer'] for j in slots]
        logical.append(lists)
        writers[row['target']]=i
    return logical


def nonreference(row):
    cs=copy.deepcopy(row['controls'])
    # These slot/DPB fields remain in the full artifact and are separately
    # checked against the reference trace, not silently treated as equal.
    for k in ('dpb','poc_st_curr_before','poc_st_curr_after','poc_lt_curr'):cs['DECODE_PARAMS'].pop(k)
    for k in ('ref_idx_l0','ref_idx_l1'):cs['SLICE_PARAMS'].pop(k)
    return {control+'.'+field:value for control,data in cs.items() for field,value in data.items()}


def summarize(root):
    files=read(root/'files.json')
    actual={p.name for p in root.iterdir() if p.is_file()}-{'files.json','summary.json','README.md'}
    need(set(files)==actual and all(Path(name).name==name for name in files),'incomplete/unsafe file inventory')
    for name,sha in files.items():need(digest(root/name)==sha,'published input digest mismatch')
    provenance=read(root/'provenance.json')
    need(digest(REFERENCE)==provenance['reference_frames_sha256'] and digest(PRIOR/'provenance.json')==provenance['prior_provenance_sha256'],'reference evidence changed')
    need(provenance['loaded_build_id_note_matches'] is True and provenance['module_changed'] is False
         and provenance['loaded_module_sha256']=='e50540e1d0fc48c7e0bf9b21ff028758bdb35f94aa7070af00de88e61e5c70e9'
         and provenance['final_idle'] is True and provenance['new_faults']==0,'invalid module/final state')
    reference=read(REFERENCE)
    private={r['path']:r for r in read(root/'private-artifacts.json')['files']}
    runs=read(root/'runs.json');ids=[f'{v}-{c}-{m}' for v in 'BE' for c in ('va','gst') for m in ('off','on')]
    need([r['id'] for r in runs]==ids,'missing/duplicate/reordered workload')
    results={};data={};extras={};logic={}
    guard_ids=set()
    for r in runs:
        name=r['id'];v,c,mode=name.split('-')
        need((r['vector'],r['client'],r['mode'])==(v,c,mode),'wrong run identity')
        need(r['frames']==300 and r['actual_child_exit']==r['actual_child']['child_exit']==r['outer_status']['returncode']==0
             and r['actual_child']['child_reaped'] is True,'actual child incomplete/failed')
        guards=r['guard'];need([g['event'] for g in guards]==['preflight','start','final'],'incomplete guard')
        gid=guards[0]['run_id'];need(gid not in guard_ids and all(g['run_id']==gid for g in guards),'reused/mixed guard');guard_ids.add(gid)
        final=guards[-1];need(guards[0]['idle'] and final['status']=='ok' and final['returncode']==0 and final['idle']
             and not final['holders'] and not final['timed_out'] and not final['wedged'] and final['abort_reason'] is None,'guard failure')
        need(r['command']['guard_lease']==gid,'wrong guard/command association')
        hashes=r['frames_md5'];need(len(hashes)==300 and all(re.fullmatch('[0-9a-f]{32}',h) for h in hashes),'invalid outputs')
        need(hashes==[x[1] for x in read(PRIOR/'frames'/f'{v}-{c}-off.json')],'prior frames changed')
        wrong=[i for i,(a,b) in enumerate(zip(hashes,reference[v]['frame_md5'])) if a!=b]
        need(wrong==r['wrong_indices'] and len(wrong)==(0 if v=='B' else 26 if c=='va' else 25),'wrong output result')
        results[name]=dict(frames=300,wrong_outputs=len(wrong),wrong_indices=wrong)
        if mode=='on':
            raw=[x for x in private if x.startswith(name+'/') and x.endswith('_trace.json')]
            need(len(raw)==1 and private[raw[0]]['sha256']==r['raw_sha256'],'raw capture attribution mismatch')
            rows=read(root/f'{v}-{c}-controls.jsonl',True);refs=read(root/f'{v}-{c}-refs.jsonl',True)
            logic[v,c]=validate_controls(rows,refs,r['raw_sha256'][:16]);data[v,c]=rows
            extra=read(root/f'{v}-{c}-input.json');extras[v,c]=extra
            need(len(extra['encoded_inputs'])==300 and [p['picture'] for p in extra['encoded_inputs']]==list(range(1,301)),'incomplete encoded input hashes')
            need(all(type(p['bytes']) is int and p['bytes']>0 and re.fullmatch('[0-9a-f]{64}',p['sha256']) for p in extra['encoded_inputs']),'invalid input digest')
            modes={k:x['value'] for k,x in extra['modes'].items()}
            need(modes=={n.base.CID+'DECODE_MODE':'V4L2_STATELESS_HEVC_DECODE_MODE_FRAME_BASED',n.base.CID+'START_CODE':'V4L2_STATELESS_HEVC_START_CODE_NONE'},'wrong/unknown global mode')
            assoc=read(root/f'{v}-{c}-association.json')
            need(len(assoc)==300 and [a['output_index'] for a in assoc]==list(range(300)) and sorted(a['pic'] for a in assoc)==list(range(1,301)),'incomplete output association')
            need(all(a['poc']==refs[a['pic']-1]['poc'] for a in assoc),'wrong output association')
            bad=[assoc[i] for i in wrong]
            results[name].update(first_bad_output=bad[0] if bad else None,first_bad_decode=min(bad,key=lambda a:a['pic']) if bad else None)
    vectors={}
    for v in 'BE':
        need(extras[v,'va']['encoded_inputs']==extras[v,'gst']['encoded_inputs'],'different submitted encoded inputs')
        need(logic[v,'va']==logic[v,'gst'],'different logical slice references')
        diffs={}; corrections={}
        for i,(left,right) in enumerate(zip(data[v,'va'],data[v,'gst']),1):
            a,b=nonreference(left),nonreference(right)
            need(a['SPS.sps_max_num_reorder_pics']==0 and b['SPS.sps_max_num_reorder_pics']==7,'unexpected reorder metadata')
            need(set(a['PPS.flags']) ^ set(b['PPS.flags']) == {'V4L2_HEVC_PPS_FLAG_UNIFORM_SPACING'}
                 and all('V4L2_HEVC_PPS_FLAG_TILES_ENABLED' not in flags for flags in (a['PPS.flags'],b['PPS.flags'])),
                 'unexpected active PPS difference')
            if a['SLICE_PARAMS.flags']!=b['SLICE_PARAMS.flags']:
                need(a['SLICE_PARAMS.slice_type']==b['SLICE_PARAMS.slice_type']==2
                     and set(a['SLICE_PARAMS.flags']) ^ set(b['SLICE_PARAMS.flags']) <=
                     {'V4L2_HEVC_SLICE_PARAMS_FLAG_MVD_L1_ZERO','V4L2_HEVC_SLICE_PARAMS_FLAG_CABAC_INIT','V4L2_HEVC_SLICE_PARAMS_FLAG_COLLOCATED_FROM_L0'},
                     'unexpected active slice flag difference')
            for key in a.keys()|b.keys():
                if a.get(key)!=b.get(key):
                    row=diffs.setdefault(key,dict(pictures=[],first_example=dict(picture=i,poc=left['poc'],va=a.get(key),gst=b.get(key))))
                    row['pictures'].append(i)
        need(set(diffs)=={'PPS.flags','SPS.sps_max_num_reorder_pics','SLICE_PARAMS.flags'},'additional returned control discrepancy')
        for c in ('va','gst'):
            counts=collections.Counter(x['control']+'.'+x['field'] for r in data[v,c] for x in r['input_changes'])
            corrections[c]=dict(counts)
        vectors[v]=dict(encoded_inputs_equal=300,logical_slice_references_equal=300,
                        nonreference_returned_differences=diffs,observed_kernel_input_corrections=corrections)
    return dict(schema='hevc-full-controls.decision/1',workloads=8,frames=2400,runs=results,vectors=vectors,
                decision='Submitted encoded bytes match; returned PCM fields are zero. No RPS_E correction or attributable source-consumed non-reference control difference established.',
                limits=['Ioctl results and pre-QBUF dumps, not kernel job snapshots or firmware reads.','Remaining actual commands, compressed-reference contents and firmware contract/state remain open.','Private evidence digests cannot independently authenticate raw captures.'])


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--directory',type=Path,default=DEFAULT);ap.add_argument('--verify',action='store_true');args=ap.parse_args()
    result=summarize(args.directory)
    if args.verify:
        need(result==read(args.directory/'summary.json'),'committed summary differs');print('PASS: eight complete runs, preserved outputs, four full controls, identical encoded inputs and observed kernel corrections')
    else:print(json.dumps(result,indent=2))
