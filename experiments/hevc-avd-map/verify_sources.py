#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Verify locally downloaded pinned primary source bytes and macro extraction.

Downloads are an explicit separate step; this tool never fetches or executes
kernel source. Pass a flat directory containing the basenames in source-map.json.
"""
import argparse
import re
from pathlib import Path

import model as m
import report


def verify(directory):
    source=report.parse(report.read(report.ROOT/'source-map.json'))
    for row in source['kernel']:
        name=Path(row['path']).name
        m.require(report.digest(directory/name)==row['sha256'],'source hash mismatch: '+name)
    pattern=r'^#define (?:AVD_REF_|AVD_OP_REF(?:\s|_)|AVD_OP_SL_REF(?:\s|_)).*$'
    upstream=re.findall(pattern,(directory/'avd-inst.h').read_text(),re.M)
    excerpt=re.findall(pattern,(report.ROOT/'avd-bits.h').read_text(),re.M)
    m.require(excerpt==upstream,'instruction macro excerpt differs from pinned source')
    m.require((report.ROOT/'avd-bits.h').read_text().startswith('/* SPDX-License-Identifier: MIT'),
              'upstream macro license not retained')
    m.require((report.ROOT/'LICENSE.avd-bits').read_bytes()==(directory/'MIT').read_bytes(),
              'upstream license text differs')
    for row in source['mapped_functions']:
        m.require(re.search(r'\b'+re.escape(row['name'])+r'\s*\(',
                           (directory/row['file']).read_text()) is not None,'source function missing')
    print(f"PASS: {len(source['kernel'])} primary source/license files and {len(excerpt)} verbatim instruction macros")


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory',type=Path)
    args=parser.parse_args();verify(args.directory)
