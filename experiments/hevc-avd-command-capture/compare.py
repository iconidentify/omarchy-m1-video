#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Bind same-run returned ioctl controls to all named kernel window fields."""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys

HERE=Path(__file__).resolve().parent
TRACE=HERE.parent/'hevc-avd-command-trace'
sys.path.insert(0,str(TRACE))
import parser

def flag_values(header):
    pins=json.loads((HERE.parent/'hevc-avd-controls-map/source-map.json').read_text())
    data=header.read_bytes()
    parser.need(hashlib.sha256(data).hexdigest()==pins['v4l2_controls_h']['sha256'],'UAPI source identity')
    values={name:1<<int(bit) for name,bit in re.findall(
        r'^#define\s+(V4L2_HEVC_\w+FLAG_\w+)\s+\(1(?:ULL|U|UL)?\s*<<\s*(\d+)\)',data.decode(),re.M)}
    values.update({name:int(value,16) for name,value in re.findall(
        r'^#define\s+(V4L2_HEVC_\w+FLAG_\w+)\s+(0x[0-9a-fA-F]+)\s*$',data.decode(),re.M)})
    return values

def copied_fields(row,flags):
    controls=row['controls'];sl=controls['SLICE_PARAMS']
    sources={'sps':controls['SPS'],'pps':controls['PPS'],'sc':controls['SCALING_MATRIX'],
             'sl':sl,'w':sl['v4l2_hevc_pred_weight_table']}
    result={}
    for line in (TRACE/'kernel/control-layout.inc').read_text().splitlines():
        m=re.fullmatch(r'FIELD\((\w+), (\w+), ([\w>\-]+), (\d+)\)',line)
        if not m:continue
        kind,name,expr,count=m.groups()
        if expr=='flags':value=controls['DECODE_PARAMS']['flags']
        else:
            base,member=expr.split('->');value=sources[base][member]
        if name.endswith('_flags'):
            parser.need(isinstance(value,list) and len(value)==len(set(value)) and all(v in flags for v in value),'unmapped flags')
            value=sum(flags[v] for v in value)
        elif kind=='BYTES':
            parser.need(isinstance(value,list) and len(value)==int(count),'array extent')
            signed=expr.startswith('w->')
            parser.need(all(type(v) is int and (-128<=v<=127 if signed else 0<=v<=255) for v in value),'array domain')
            value=[v&255 for v in value]
        result[name]=value
    parser.validate_controls(result)
    parser.pack_controls(result)
    return result

def compare(capture,rows,flags):
    parser.need(len(rows)==300 and [r['picture'] for r in rows]==list(range(1,301)),'ioctl picture extent')
    parser.need(len({r['run'] for r in rows})==1,'mixed ioctl runs')
    for history,row in zip(capture['pictures'],rows):
        parser.need((history['picture'],history['poc'],history['target'],history['type'])==
                    (row['picture'],row['poc'],row['target'],row['controls']['SLICE_PARAMS']['slice_type']),
                    'ioctl/kernel full history mismatch')
    differences=[]
    for window in capture['windows']:
        expected=copied_fields(rows[window['picture']-1],flags)
        actual=parser.unpack_controls(window['controls'])
        for name,value in expected.items():
            if actual[name]!=value:
                differences.append(dict(picture=window['picture'],poc=window['poc'],field=name,
                                        ioctl=value,kernel=actual[name]))
    return differences
