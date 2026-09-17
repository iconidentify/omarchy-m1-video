#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Mutate real campaign artifacts, refreshing inventories to reach semantic checks."""
import argparse
import copy
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('paired_report',HERE/'campaign-report.py')
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)

def save(p,value):p.write_text(json.dumps(value,indent=2)+'\n')
def update(root,name,fn):
    p=root/name;obj=r.read(p);fn(obj);save(p,obj)

def command_binding(root):
    name='B-va-on';h=r.sha(root/(name+'-command.snapshot'))
    update(root,'runs.json',lambda runs:runs[1]['execution']['snapshots']['command'].update(sha256=h))
    def private(data):
        next(x for x in data['files'] if x['path']==f'campaign/{name}/kernel/command.snapshot')['sha256']=h
    update(root,'private-artifacts.json',private)

def command_word(root):
    p=root/'B-va-on-command.snapshot';lines=p.read_text().splitlines();word=lines[301].split();word[12]=str(int(word[12])^1);lines[301]=' '.join(word);p.write_text('\n'.join(lines)+'\n');command_binding(root)

def copied_control(root):
    p=root/'B-va-on-command.snapshot';lines=p.read_text().splitlines();c=r.parser.unpack_controls(bytes(map(int,lines[302].split()[1:])));c['init_qp_minus26']+=1
    lines[302]='C '+' '.join(map(str,r.parser.pack_controls(c)));p.write_text('\n'.join(lines)+'\n');command_binding(root)

def run(build):
    expected=r.summarize(r.DEFAULT,build);assert expected==r.read(r.DEFAULT/'summary.json')
    cases={
      'child-exit':lambda p:update(p,'runs.json',lambda x:x[1]['execution'].update(child_exit=23)),
      'cross-lease':lambda p:update(p,'runs.json',lambda x:x[1]['command'].update(guard_lease='unbound')),
      'same-count-wrong-pixels':lambda p:update(p,'runs.json',lambda x:x[5]['frames_md5'].__setitem__(31,'0'*32)),
      'wrong-full-output':lambda p:update(p,'runs.json',lambda x:x[0].update(md5='0'*32)),
      'missing-window':lambda p:(p/'B-va-on-command.snapshot').write_text('\n'.join((p/'B-va-on-command.snapshot').read_text().splitlines()[:-2])+'\n'),
      'actual-word':command_word,
      'copied-control':copied_control,
      'late-recorder-error':lambda p:update(p,'runs.json',lambda x:x[1]['execution']['status']['command'].update(errors=1)),
      'reference-record-extent':lambda p:update(p,'runs.json',lambda x:x[1]['execution']['status']['reference'].update(count=1)),
      'foreign-terminal-holder':lambda p:update(p,'campaign-events.json',lambda x:next(row for row in x if row['event']=='terminal-state')['holders'].append({'pid':'redacted'})),
      'failed-restoration':lambda p:update(p,'final-state.json',lambda x:x.update(loaded_original_build_id_matches=False)),
      'wrong-paired-context':lambda p:update(p,'B-va-on-reference.json',lambda x:x.update(context=x['context']+1)),
      'wrong-writer':lambda p:update(p,'B-va-on-reference.json',lambda x:next(row for row in x['records'] if row['kind']==3).update(writer=299)),
    }
    for name,mutate in cases.items():
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'capture';shutil.copytree(r.DEFAULT,root);mutate(root)
            files=r.read(root/'files.json');save(root/'files.json',{n:r.sha(root/n) for n in files})
            try:r.summarize(root,build)
            except (ValueError,AssertionError) as exc:print('PASS reject',name,':',exc)
            else:raise AssertionError('accepted evidence mutation: '+name)
    print('PASS: reproduced measured decision and rejected thirteen semantic evidence mutations')

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--oracle',type=Path,required=True);a=ap.parse_args();run(a.oracle)
