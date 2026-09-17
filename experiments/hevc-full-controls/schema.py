#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Derive serialized field shapes from the pinned UAPI and tracer flag tables."""
import argparse
import json
from pathlib import Path
import re

NAMES = ['v4l2_ctrl_hevc_' + n for n in
         ('sps', 'pps', 'slice_params', 'decode_params', 'scaling_matrix')]
NAMES += ['v4l2_hevc_pred_weight_table', 'v4l2_hevc_dpb_entry']


def derive(header, info):
    schema = {}
    for name in NAMES:
        body = re.search(r'struct ' + name + r' \{(.*?)\n\};', header, re.S).group(1)
        body = re.sub(r'/\*.*?\*/', '', body, flags=re.S)
        fields = {}
        for declaration in body.split(';'):
            d = declaration.strip()
            if not d:
                continue
            m = re.fullmatch(r'(__[us]\d+|struct\s+\w+)\s+(\w+)((?:\[\w+\])*)', d)
            if not m:
                raise ValueError('unaccounted UAPI declaration')
            typ, field, arr = m.groups()
            typ = ' '.join(typ.split())
            if re.fullmatch(r'reserved\d*', field):  # Pinned tracer omits padding.
                continue
            dims = [16 if x == 'V4L2_HEVC_DPB_ENTRIES_NUM_MAX' else int(x)
                    for x in re.findall(r'\[(\w+)\]', arr)]
            spec = dict(type=typ, shape=dims)
            if field == 'flags':
                suffix = {'v4l2_ctrl_hevc_sps': 'sps', 'v4l2_ctrl_hevc_pps': 'pps',
                          'v4l2_ctrl_hevc_slice_params': 'slice_params',
                          'v4l2_ctrl_hevc_decode_params': 'decode_param',
                          'v4l2_hevc_dpb_entry': 'pps'}[name]
                block = re.search(r'v4l2_hevc_' + suffix + r'_flag_def\[\] = \{(.*?)\};', info, re.S).group(1)
                spec['flags'] = re.findall(r'"(V4L2_HEVC_[A-Z0-9_]+)"', block)
                if name == 'v4l2_hevc_dpb_entry':
                    # Known tracer bug: bit 0 uses PPS spelling instead of DPB LT.
                    spec['flags'] = ['V4L2_HEVC_PPS_FLAG_DEPENDENT_SLICE_SEGMENT_ENABLED']
            fields[field] = spec
        schema[name] = fields
    fields = schema['v4l2_ctrl_hevc_slice_params']
    fields['v4l2_hevc_pred_weight_table'] = fields.pop('pred_weight_table')
    return schema


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('source_dir', type=Path)
    ap.add_argument('--verify', action='store_true')
    args = ap.parse_args()
    result = derive((args.source_dir / 'v4l2-controls.h').read_text(),
                    (args.source_dir / 'v4l2-tracer-info-gen.h').read_text())
    if args.verify:
        assert result == json.loads(Path(__file__).with_name('payload-schema.json').read_text())
        print('PASS: serialized payload shapes match pinned UAPI/flag tables')
    else:
        print(json.dumps(result, indent=2))
