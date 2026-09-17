#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Reproduce the failed pre-decoder attempt; never infer restoration from idle."""
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent

def summarize(root):
    execution=json.loads((root/'execution.json').read_text())
    events=[json.loads(line) for line in (root/'campaign-events.jsonl').read_text().splitlines()]
    guard=json.loads((root/'guard-result.json').read_text())
    def need(ok,reason):
        if not ok:raise ValueError(reason)
    need(execution['run']==1 and execution['enabled'] is False,'unexpected run')
    need(execution['child_exit'] is None and not execution['child_reaped'] and not execution['child_released'],'decoder was started')
    need(execution['errors'] and not execution['snapshots'],'lost failed status')
    starts=[r for r in events if r['event']=='run-start']
    need(len(starts)==1 and starts[0]['name']=='B-va-off','attempt count changed')
    need(not any(r['event'] in ('original-restored','complete') for r in events),'false restoration/completion')
    failures=[r for r in events if r['event']=='transition-result' and r['returncode']]
    need(len(failures)==1 and failures[0]['argv']==['rmmod','apple_avd'] and failures[0]['returncode']==-11,'missing unload failure')
    need(any(r['event']=='restoration-not-completed' for r in events),'missing restoration failure')
    need(guard['status']=='child-error' and guard['returncode']==1,'failed guard changed')
    stack=(root/'kernel-oops.txt').read_text()
    need(all(x in stack for x in ('Internal error: Oops','avd_trace_exit','debugfs_remove','down_write')),'missing kernel fault')
    return dict(decoder_workloads_started=0,attempts=1,unattempted_workloads=7,
                original_loaded_module_restored=False,kernel_oops=True,
                support_count_gain=0,next_hardware_gate='clean boot and corrected reviewed candidate')

if __name__=='__main__':print(json.dumps(summarize(HERE/'failed-attempt-2026-09-17'),indent=2))
