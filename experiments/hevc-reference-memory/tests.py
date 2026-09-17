#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual-source layout checks and synthetic observation-contract rejections."""
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import observation
import source

HERE = Path(__file__).resolve().parent
CAPTURE = HERE.parent / 'hevc-avd-command-capture/capture-2026-09-17'


class Layout(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        # Optional source cache is still checked against every pin before use.
        cache = os.environ.get('HEVC_MEMORY_SOURCE_CACHE')
        cls.inputs = source.prepare(cls.root/'inputs', Path(cache) if cache else None)
        for mutation, name in ((False,'layout'), (True,'mutant')):
            inc=cls.root/'extracted.inc'
            source.extract(cls.inputs,inc,mutate=mutation)
            subprocess.run(['cc','-std=c11','-O0','-Wall','-Werror','-fsanitize=undefined',
                            '-I',str(cls.root),str(HERE/'layout-harness.c'),'-o',str(cls.root/name)],check=True,timeout=30)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def layout(self,w=448,h=240,depth=8,length=0,mutant=False,valid=True):
        result=subprocess.run([str(self.root/('mutant' if mutant else 'layout')),*map(str,(w,h,depth,length))],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0 if valid else 2,result.stderr)
        self.assertEqual(result.stderr,'')
        return json.loads(result.stdout) if valid else None

    def test_matches_all_selected_records(self):
        count=0
        for client in ('va','gst'):
            for vector in ('B','E'):
                records=json.loads((CAPTURE/f'{vector}-{client}-on-reference.json').read_text())['records']
                for r in records:
                    if r.get('kind')!=1 or not 24<=r['picture']<=34: continue
                    actual=self.layout(r['width'],r['height'],8,r['length'])
                    for a,b in (('start','comp_start'),('comp','comp_size'),('mv','mv_size'),('mv_offset','mv_offset')):
                        self.assertEqual(actual[a],r[b])
                    self.assertEqual(actual['offsets'],[114688,0,176128,118784])
                    count+=1
        self.assertEqual(count,44)

    def test_source_identity_drift(self):
        import shutil
        bad=self.root/"bad-cache"
        shutil.copytree(self.inputs,bad)
        path=bad/source.AVD/"avd-drv.c"
        path.write_text(path.read_text()+"\n/* drift */\n")
        with self.assertRaisesRegex(ValueError,"source hash mismatch"):
            source.prepare(self.root/"bad-output",bad)

    def test_real_source_offset_mutation(self):
        self.assertNotEqual(self.layout(mutant=True)['offsets'],[114688,0,176128,118784])
        self.assertEqual(self.layout()['offsets'],[114688,0,176128,118784])

    def test_ten_bit(self):
        p=self.layout(depth=10)
        self.assertEqual((p['start'],p['comp'],p['mv'],p['packed']),(322560,320512,7168,650240))
        self.assertEqual(p['offsets'],[229376,0,319488,233472])

    def test_extents_and_alignment(self):
        for depth in (8,10):
            for w,h in ((64,64),(128,80),(448,240),(512,256),(16384,16384)):
                p=self.layout(w,h,depth)
                self.assertLessEqual(p['start']+p['comp'],p['mv_offset'])
                self.assertEqual(p['mv_offset']+p['mv'],p['length'])
                self.assertTrue(0==p['offsets'][1]<p['offsets'][0]<p['offsets'][3]<p['offsets'][2]<p['comp'])

    def test_invalid_and_overflow_domain(self):
        for args in ((0,240,8,0),(448,0,8,0),(65,64,8,0),(64,65,8,0),
                     (448,240,9,0),(448,240,12,0),(2**32,240,8,0),
                     (448,2**32,8,0),(448,240,8,2**32),(448,240,8,1),
                     (-1,240,8,0),('x',240,8,0),(2**64,240,8,0)):
            self.layout(*args,valid=False)

    def test_actual_allocator_failed_resize(self):
        drv=(self.inputs/'patched/avd-drv.c').read_text()
        functions=source.function(drv,'avd_buf_free')+'\n'+source.function(drv,'avd_buf_alloc')
        stub = r"""
#include <stddef.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#define GFP_KERNEL 0
struct avd_dev { void *dev; };
struct avd_buf { void *cpu; size_t size, addr; };
static unsigned calls;
static void *dma_alloc_coherent(void *dev,size_t size,size_t *addr,int flags) {
    (void)dev; (void)flags; ++calls; *addr=1;
    return calls==1 ? NULL : malloc(size);
}
static void dma_free_coherent(void *dev,size_t size,void *cpu,size_t addr) {
    (void)dev; (void)size; (void)addr; free(cpu);
}
"""
        main = r"""
int main(void) {
    struct avd_dev dev={0}; struct avd_buf buf={0};
    if(avd_buf_alloc(&dev,&buf,4096)!=-ENOMEM || buf.cpu || buf.size!=4096) return 1;
    /* Actual helper reports success with no allocation after a smaller retry. */
    if(avd_buf_alloc(&dev,&buf,2048)!=0 || buf.cpu || calls!=1) { avd_buf_free(&dev,&buf); return 2; }
    avd_buf_free(&dev,&buf);
    return buf.cpu || buf.size || buf.addr ? 3 : 0;
}
"""
        path=self.root/'allocator.c'; binary=self.root/'allocator'
        command=['cc','-std=c11','-Wall','-Werror',str(path),'-o',str(binary)]
        path.write_text(stub+functions+main)
        subprocess.run(command,check=True,timeout=30)
        subprocess.run([str(binary)],check=True,timeout=10)
        corrected=functions.replace('if (!buf->cpu && size < buf->size)',
                                    'if (buf->cpu && size <= buf->size)')
        self.assertNotEqual(corrected,functions)
        path.write_text(stub+corrected+main)
        subprocess.run(command,check=True,timeout=30)
        self.assertEqual(subprocess.run([str(binary)],timeout=10).returncode,2)

    def test_resize_reuse_extent(self):
        old=self.layout()
        self.layout(512,256,8,old['length'],valid=False)
        larger=self.layout(512,256)
        p=self.layout(length=larger['length'])
        self.assertEqual(p['mv_offset'],larger['length']-p['mv'])
        self.assertGreater(p['mv_offset'],p['start']+p['comp'])


class Observation(unittest.TestCase):
    def fixture(self):
        identity={'run':'synthetic-run','context':'synthetic-context','allocation':2,'generation':3,'picture':28,'poc':32}
        return dict(enabled=True,identity_before=identity,identity_after=dict(identity),
                    width=448,height=240,depth=8,length=368128,comp_start=161280,comp_size=177152,
                    mv_offset=360960,mv_size=7168,completed=True,quiescent=True,inflight_readers=0,
                    retained=True,mapping_readable=True,allocation_policy='verified-coherent-noncached',
                    provenance_verified=True,copy_budget=184320,snapshot_count=1,elapsed_us=1000,
                    error=False,overflow=False,context_kind='process')

    def test_synthetic_coherent_only(self):
        self.assertEqual(observation.validate(self.fixture())['bytes'],184320)

    def test_rejection_matrix(self):
        mutations={'enabled':False,'completed':False,'quiescent':False,'inflight_readers':1,
                   'retained':False,'mapping_readable':False,'allocation_policy':'noncoherent-with-sync-ioctl',
                   'provenance_verified':False,'copy_budget':184319,'snapshot_count':9,'elapsed_us':20001,
                   'error':True,'overflow':True,'context_kind':'irq','length':338432,'mv_offset':338431,
                   'comp_size':177153,'depth':10,'width':416,'generation':0}
        for field,value in mutations.items():
            with self.subTest(field=field):
                record=self.fixture();record[field]=value
                with self.assertRaises(ValueError):observation.validate(record)

    def test_identity_changes_and_resize(self):
        for key in observation.IDENTITY:
            record=self.fixture()
            record['identity_after'][key] = 'other' if key in ('run','context') else record['identity_after'][key]+1
            with self.assertRaises(ValueError):observation.validate(record)

    def test_malformed(self):
        for field in observation.FIELDS:
            record=self.fixture();del record[field]
            with self.assertRaises(ValueError):observation.validate(record)
        for key,value in (('length',True),('elapsed_us',-1),('completed',1),('length',2**64)):
            record=self.fixture();record[key]=value
            with self.assertRaises(ValueError):observation.validate(record)
        record=self.fixture();record['identity_after']['generation']=False
        with self.assertRaises(ValueError):observation.validate(record)


if __name__=='__main__':unittest.main()
