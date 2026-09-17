#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Exact-C packing, source mutations, serialization and wrapper lifetime checks."""
import copy
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import fixtures
import oracle
import parser
import prepare

HERE=Path(__file__).resolve().parent

def reject(call,reason):
    try:call()
    except (ValueError,AssertionError):return
    raise AssertionError('negative accepted: '+reason)

def verify(source):
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp);candidate=root/'candidate'
        prepare.prepare(source,candidate)
        spec=importlib.util.spec_from_file_location('lifecycle_tests',HERE/'lifecycle-tests.py')
        lifecycle=importlib.util.module_from_spec(spec);spec.loader.exec_module(lifecycle)
        lifecycle.verify(candidate,root/'module-lifecycle')
        bad=root/'module-lifecycle-mutant';shutil.copytree(candidate,bad)
        drv=bad/'avd-drv.c';code=drv.read_text()
        old="\tif (ret) {\n\t\tavd_cmdtrace_exit();\n\t\tavd_trace_exit();\n\t}\n"
        assert old in code
        drv.write_text(code.replace(old,"\tif (ret)\n\t\tavd_cmdtrace_exit();\n\tavd_trace_exit();\n",1))
        lifecycle.verify(bad,root/'module-lifecycle-mutation-check',negative=True)
        base=oracle.source_base(source,root/'baseline')
        compiled=oracle.build(base,candidate,root/'compiled')
        for seed in range(32):oracle.predict(compiled,fixtures.row(seed),check_hooks=True)
        rows=[]
        for pic in range(24,35):
            row=fixtures.row(pic,pic);pairs,inactive=oracle.predict(compiled,row)
            row.update(sites=[s for s,w in pairs],words=[w for s,w in pairs],nwords=len(pairs),nbytes=1392,inactive=inactive)
            rows.append(row)
        text=fixtures.snapshot(rows)
        parsed=parser.parse_snapshot(text,7)
        assert all(oracle.verify_window(compiled,row) for row in parsed['windows'])
        for label,bad in [
            ('missing windows',text.split('W ')[0]),('trailing garbage',text+'JUNK\n'),
            ('wrong run',text.replace('H 2 7 ','H 2 8 ',1)),
            ('active capture',text.replace('7 3 4 0','7 3 2 0',1)),
            ('kernel error',text.replace('7 3 4 0','7 3 4 1',1)),
            ('duplicate picture',text.replace('P 2 2 ','P 1 2 ',1)),
            ('bad version',text.replace('H 2 ','H 1 ',1)),
            ('noncanonical integer',text.replace('H 2 7 ','H 2 07 ',1))]:
            reject(lambda:parser.parse_snapshot(bad,7),label)
        for site in (oracle.SITES['SCL_8'],oracle.SITES['WT_CHR'],oracle.SITES['HDR_ZERO'],oracle.SITES['SLICE_META']):
            original=next(row for row in rows if row['sites'].count(site)>2)
            changed=copy.deepcopy(original)
            indices=[i for i,s in enumerate(changed['sites']) if s==site]
            changed['words'][indices[len(indices)//2]]^=1
            assert not oracle.verify_window(compiled,changed),site
        for mode in ('missing-word','missing-site','wrong-site','wrong-inactive'):
            changed=copy.deepcopy(rows[0])
            if mode=='missing-word':changed['words'].pop()
            if mode=='missing-site':changed['sites'].pop()
            if mode=='wrong-site':changed['sites'][0]=99
            if mode=='wrong-inactive':changed['inactive']^=1<<27
            assert not oracle.verify_window(compiled,changed),mode
        # Mutate actual instrumented C, not an unrelated model. Each must fail.
        original=(candidate/'avd-hevc.c').read_text()
        variants={
            'missing-scaling':('avd_cmdtrace_word(ctx, CMD_SITE_SCL_8);','if (!(i==3 && j==0 && k==4)) avd_cmdtrace_word(ctx, CMD_SITE_SCL_8);',1),
            'missing-weight':('avd_cmdtrace_word(ctx, CMD_SITE_WT_CHR);','if (i!=7) avd_cmdtrace_word(ctx, CMD_SITE_WT_CHR);',3),
            'changed-push':('sc_8x8[i][j][0][k]','(sc_8x8[i][j][0][k]+1)',1),
            'missing-I-state':('avd_cmdtrace_inactive(ctx, CMD_SITE_WT_SKIP);','(void)ctx;',2),
            'truncated-size':('avd_cmdtrace_slice_meta(ctx, size, offset, flags, sl->data_byte_offset);','avd_cmdtrace_slice_meta(ctx, size & 65535, offset, flags, sl->data_byte_offset);',1),
        }
        for name,(old,new,seed) in variants.items():
            assert old in original
            mutant=root/name;shutil.copytree(candidate,mutant)
            (mutant/'avd-hevc.c').write_text(original.replace(old,new))
            built=oracle.build(base,mutant,root/(name+'-build'),compiled/'v4l2-controls.h')
            reject(lambda:oracle.predict(built,fixtures.row(seed),check_hooks=True),name)
        spec=importlib.util.spec_from_file_location('wrapper_tests',HERE/'wrapper-tests.py')
        wrapper=importlib.util.module_from_spec(spec);spec.loader.exec_module(wrapper)
        wrapper.verify(candidate,root/'wrappers',compiled/'v4l2-controls.h')
        mutation=root/'lifetime-mutant';shutil.copytree(candidate,mutation)
        path=mutation/'avd-cmdtrace.c';code=path.read_text()
        assert 'snapshot_busy || (arm && capture)' in code
        path.write_text(code.replace('snapshot_busy || (arm && capture)','(arm && capture)',1))
        wrapper.verify(mutation,root/'lifetime-mutant-test',compiled/'v4l2-controls.h',negative=True)
        print('PASS: 32 exact-C cases, full 11-window snapshot, malformed/sequence negatives, five actual-source mutations, named packing/reserved poison and exact wrapper lifetime')

if __name__=='__main__':verify(Path(sys.argv[1]).resolve())
