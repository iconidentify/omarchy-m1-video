#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Reproduce a source-derived AVD decision from immutable public metadata."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import model as m

ROOT = Path(__file__).resolve().parent
CAPTURES = ROOT.parent / 'hevc-controls/captures/2026-09-17'


def unique(pairs):
    result = {}
    for k,v in pairs:
        m.require(k not in result, 'duplicate JSON key')
        result[k]=v
    return result


def parse(text):
    def constant(value):raise m.Reject('non-JSON number: '+value)
    return json.loads(text,object_pairs_hook=unique,parse_constant=constant)


def read(path):
    with path.open('rb') as stream:raw=stream.read(8*1024*1024+1)
    m.require(len(raw)<=8*1024*1024,'oversized metadata')
    return raw


def digest(path):return hashlib.sha256(read(path)).hexdigest()


def checker_path():
    value=os.environ.get('HEVC_REFTRACE_CHECKER')
    m.require(value is not None,'set HEVC_REFTRACE_CHECKER to the trusted pinned checker')
    path=Path(value)
    source=parse(read(ROOT/'source-map.json'))
    m.require(digest(path)==source['checker']['sha256'],'checker differs from immutable reviewed pin')
    return path


def check_inputs():
    source=parse(read(ROOT/'source-map.json'))
    for row in source['capture_inputs']:
        path=Path(row['path'])
        m.require(not path.is_absolute() and '..' not in path.parts,'invalid input inventory path')
        m.require(digest(ROOT.parent/path)==row['sha256'],'public capture changed: '+str(path))
    patches=[]
    for row in source['patches']['files']:
        p=ROOT.parent.parent/row['path']
        m.require(digest(p)==row['sha256'],'shipped patch differs from analyzed snapshot')
        patches.append(read(p))
    m.require(hashlib.sha256(b''.join(patches)).hexdigest()==source['patches']['concatenated_sha256'],
              'patch content hash differs')
    return source


def logical(row):
    def identity(writer):return [writer['picture'],writer['poc'],writer['is_intra']]
    return dict(dpb=sorted([*identity(e['writer']),e['long_term']] for e in row['dpb']),
                l0=[identity(e['writer']) for e in row['lists']['l0']],
                l1=[identity(e['writer']) for e in row['lists']['l1']],
                collocated=identity(row['motion']['collocated']) if row['motion']['collocated'] else None,
                gate=row['motion']['expected_ref_valid'])


def sequence(row):
    return [e['header_if_slice_poc_equals_decode_poc'] for e in row['dpb']] if row['reference_table_emitted'] else []


def list_words(row):return {k:[e['word'] for e in v] for k,v in row['lists'].items()}


def decision():
    source=check_inputs();checker=checker_path()
    subprocess.run([sys.executable,str(ROOT.parent/'hevc-controls/report.py'),str(CAPTURES),'--verify'],
                   check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30)
    results=parse(read(CAPTURES/'results.json'))
    manifest={r['id']:r for r in results['runs']}
    report=dict(schema='hevc-avd-map.decision/1',scope='source-derived predictions, not emitted firmware traces',
                capture_commit=source['capture_commit'],vectors={})
    for vector in ('B','E'):
        clients={}
        for client in ('va','gst'):
            filename=CAPTURES/'refs'/f'{vector}-{client}.jsonl'
            subprocess.run([sys.executable,str(checker),'compare',str(filename),str(filename),
                            '--expected-pictures','300','--json'],check=True,
                           stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30)
            records=[parse(line) for line in read(filename).splitlines()]
            rows=m.map_records(records,300)
            association=parse(read(CAPTURES/'associations'/f'{vector}-{client}.json'))
            run=manifest[results['selected'][f'{vector}-{client}']]
            out={a['pic']:a['output_index'] for a in association}
            for row in rows:
                row['output_index']=out[row['picture']]
                row['wrong_output']=row['output_index'] in run['wrong_indices']
            clients[client]=rows
        a,b=clients['va'],clients['gst']
        diffs={}
        projections=dict(logical_reference_and_intra_state=logical,
                         conditional_reference_header_sequence=sequence,
                         reference_list_words=list_words,
                         known_motion_bits=lambda r:[r['motion']['word']['known_mask'],r['motion']['word']['known_value']])
        for key,project in projections.items():
            indices=[i for i,(x,y) in enumerate(zip(a,b)) if project(x)!=project(y)]
            diffs[key]=dict(count=len(indices),first_picture=indices[0]+1 if indices else None,
                            first_poc=a[indices[0]]['poc'] if indices else None)
        # Conditional headers sorted by picture identity must agree even when slots differ.
        def by_identity(row):
            return sorted((e['writer']['picture'],e['header_if_slice_poc_equals_decode_poc']) for e in row['dpb'])
        m.require(all(by_identity(x)==by_identity(y) for x,y in zip(a,b)),'different per-picture conditional headers')
        stats={}
        for client,rows in clients.items():
            bad=[r for r in rows if r['wrong_output']]
            stats[client]=dict(pictures=len(rows),buffer_count=len({r['destination']['buffer'] for r in rows}),
                               destination_reuse=sum(r['previous_destination_writer'] is not None for r in rows),
                               i_slices=sum(r['slice_type']=='I' for r in rows),
                               motion_gate_false=sum(r['motion']['expected_ref_valid'] is False for r in rows),
                               motion_gate_unknown=sum(r['motion']['expected_ref_valid'] is None for r in rows),
                               full_motion_words_known=sum(r['motion']['word']['value'] is not None for r in rows),
                               first_bad_decode=None if not bad else dict(picture=bad[0]['picture'],poc=bad[0]['poc'],
                                   collocated=bad[0]['motion']['collocated'],
                                   expected_ref_valid=bad[0]['motion']['expected_ref_valid'],
                                   known_motion_word=bad[0]['motion']['word']))
        report['vectors'][vector]=dict(differences=diffs,statistics=stats,
                                        window={c:rows[23:34] for c,rows in clients.items()})
    return report


def render(report):
    lines=['# Predicted request window (complete prior history processed)','',
           'Generated by `report.py`; buffer generations are inferred writers, not allocation IDs.',
           'Gate 0 means the source suppresses motion reads **if kernel lookup matches the expected writer**.',
           '`?` needs an unrecorded dependent-segment flag. No row is an observed firmware instruction.','']
    for v,data in report['vectors'].items():
        lines += [f'## RPS_{v}','',
                  '| Decode picture | POC | Type | VA target:generation | Gst target:generation | Collocated POC | Expected MV gate | Wrong VA/Gst output |',
                  '| --- | --- | --- | --- | --- | --- | --- | --- |']
        for a,b in zip(data['window']['va'],data['window']['gst']):
            col=a['motion']['collocated'];gate=a['motion']['expected_ref_valid']
            target=lambda r:f"{r['destination']['buffer']}:{r['destination']['generation']}"
            lines.append(f"| {a['picture']} | {a['poc']} | {a['slice_type']} | {target(a)} | {target(b)} | "
                         f"{col['poc'] if col else '—'} | {'?' if gate is None else int(gate)} | "
                         f"{int(a['wrong_output'])}/{int(b['wrong_output'])} |")
        lines.append('')
    return '\n'.join(lines).rstrip()+'\n'


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--verify',action='store_true',help='compare committed decision.json and window.md')
    p.add_argument('--write',action='store_true',help='regenerate this research output; never edits capture inputs')
    args=p.parse_args()
    m.require(not(args.verify and args.write),'choose verify or write')
    data=decision(); rendered=render(data)
    if args.write:
        (ROOT/'decision.json').write_text(json.dumps(data,indent=2)+'\n')
        (ROOT/'window.md').write_text(rendered)
    elif args.verify:
        m.require(data==parse(read(ROOT/'decision.json')),'published decision differs')
        m.require(rendered==(ROOT/'window.md').read_text(),'published window differs')
        print('PASS: 4 x 300 pictures mapped; source-derived decision and window reproduced; no hardware')
    else:print(json.dumps(data,indent=2))


if __name__=='__main__':
    try:main()
    except (m.Reject,KeyError,TypeError,IndexError,OSError,ValueError,subprocess.SubprocessError) as exc:
        print(f'AVD map unavailable: {exc}',file=sys.stderr);sys.exit(2)
