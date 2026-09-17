#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Verify published selected-workload evidence without hardware or private media."""
import hashlib
import json
from pathlib import Path
import re

HERE=Path(__file__).resolve().parent
STAGES=('baseline','candidate','restored')


def check(evidence, identities):
    guard=evidence['guard_result']
    assert guard==dict(status='ok',returncode=0,timed_out=False,wedged=False,abort_reason=None,busy_owner=None)
    state=evidence['final_state']
    assert state['module_loaded'] and state['video_node'] and state['media_node']
    assert not state['holders'] and not state['stuck_tasks'] and not state['faults']
    assert evidence['final_loaded_note_hex']==identities['module_notes']['original_note_hex']
    assert evidence['final_original_sha256']==identities['original_sha256']
    assert evidence['config_sha256']==identities['private_config_sha256']
    jobs={j['name']:j for j in identities['jobs']}
    assert len(jobs)==10 and sum(j['frames'] for j in jobs.values())==1704
    assert set(evidence['results'])==set(STAGES)
    for stage in STAGES:
        rows=evidence['results'][stage]
        assert set(rows)==set(jobs)
        for name,actual in rows.items():
            job=jobs[name]
            digest=hashlib.sha256(json.dumps(actual,separators=(',',':')).encode()).hexdigest()
            assert digest==job['expected_sha256'],(stage,name,'output changed')
            if job['kind']=='shared':
                matches=[re.fullmatch(r'stream (\d+) frames=(\d+) MD5=([0-9a-f]{32})',r) for r in actual]
                assert all(matches) and [int(m[1]) for m in matches]==list(range(4))
                assert sum(int(m[2]) for m in matches)==168
            else:
                assert len(actual)==job['frames'] and all(re.fullmatch('[0-9a-f]{32}',h) for h in actual)
    events=evidence['events']
    assert events[-1]['event']=='complete'
    assert events[-1]['commands']==30 and events[-1]['frame_comparisons']==5112
    assert {e['lease'] for e in events}=={evidence['lease']}
    assert not any(e['event'] in ('failed','restore-incomplete','restored-stage-failed') for e in events)
    accepted=[(e['stage'],e['name'],e['frames']) for e in events if e['event']=='job-accepted']
    assert accepted==[(stage,name,jobs[name]['frames']) for stage in STAGES for name in jobs]
    exited=[(e['stage'],e['name'],e['returncode']) for e in events if e['event']=='job-exit']
    assert exited==[(stage,name,0) for stage in STAGES for name in jobs]
    transitions=[e for e in events if e['event']=='transition-result']
    assert [e['argv'] for e in transitions]==[['rmmod','apple_avd'],['insmod','$CANDIDATE'],['rmmod','apple_avd'],['modprobe','apple_avd']]
    assert all(e['returncode']==0 for e in transitions)
    ordered=[]
    for e in events:
        if e['event']=='job-accepted':ordered.append((e['stage'],e['name']))
        elif e['event']=='transition-result':ordered.append(tuple(e['argv']))
    expected_order=[('baseline',n) for n in jobs]+[('rmmod','apple_avd'),('insmod','$CANDIDATE')]
    expected_order += [('candidate',n) for n in jobs]+[('rmmod','apple_avd'),('modprobe','apple_avd')]
    expected_order += [('restored',n) for n in jobs]
    assert ordered==expected_order
    assert len([e for e in events if e['event']=='original-restored'])==1
    health=[e for e in events if e['event']=='health']
    assert health and all(not e['holders'] and not e['stuck_tasks'] and not e['faults'] for e in health)
    assert health[-1]['module_loaded'] and health[-1]['video_node']
    guards=evidence['guard_events']
    assert guards[0]['event']=='preflight' and guards[-1]['event']=='final'
    assert guards[-1]['status']=='ok' and guards[-1]['idle'] and guards[-1]['returncode']==0
    assert guards[-1]['run_id']==evidence['lease'] and not guards[-1]['holders']
    old=json.loads((HERE.parent/'hevc-avd-command-capture/capture-2026-09-17/summary.json').read_text())
    wrong={n:old['runs'][n+'-off']['wrong_indices'] for n in ('B-va','B-gst','E-va','E-gst')}
    assert evidence['retained_historical_wrong_indices']==wrong
    for stage in STAGES:
        for name in wrong:
            prior=json.loads((HERE.parent/'hevc-avd-trace/captures/2026-09-17-schema2/frames'/f'{name}-off.json').read_text())
            assert evidence['results'][stage][name]==[r[1] for r in prior]
    assert evidence['early_export_checks']=={stage:168 for stage in STAGES}
    return dict(commands=30,decoded_frames=5112,individual_frame_hashes=4104,frames_in_counted_stream_digests=1008,
                original_restored=True,new_support_claim=False)


if __name__=='__main__':
    evidence=json.loads((HERE/'evidence.json').read_text())
    identities=json.loads((HERE/'identities.json').read_text())
    print(json.dumps(check(evidence,identities),indent=2))
