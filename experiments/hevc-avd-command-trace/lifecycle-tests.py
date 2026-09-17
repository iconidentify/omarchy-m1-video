#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Execute exact generated module lifecycle bodies, including failure unwinding."""
from pathlib import Path
import subprocess
import packing

HERE=Path(__file__).resolve().parent

def verify(candidate,out,negative=False):
    out.mkdir()
    text=(candidate/'avd-drv.c').read_text().replace('int __init avd_module_init(', 'int avd_module_init(').replace('void __exit avd_module_exit(', 'void avd_module_exit(')
    bodies='\n'.join(packing.extract(text,name) for name in ('avd_module_init','avd_module_exit'))
    (out/'module-functions.h').write_text(bodies+'\n')
    (out/'test.c').write_text(r'''
#include <assert.h>
#include <string.h>
static int avd_driver, registered, result, ref_live, cmd_live;
static char sequence[32];
static void event(char c) { size_t n=strlen(sequence); assert(n+1<sizeof(sequence)); sequence[n]=c; sequence[n+1]=0; }
static void avd_trace_init(void) { assert(!ref_live);ref_live=1;event('R'); }
static void avd_cmdtrace_init(void) { assert(!cmd_live);cmd_live=1;event('C'); }
static void avd_trace_exit(void) { assert(ref_live && !registered);ref_live=0;event('r'); }
static void avd_cmdtrace_exit(void) { assert(cmd_live && !registered);cmd_live=0;event('c'); }
static int platform_driver_register(int *driver) { assert(driver==&avd_driver && ref_live && cmd_live);event('P');registered=!result;return result; }
static void platform_driver_unregister(int *driver) { assert(driver==&avd_driver && registered && ref_live && cmd_live);registered=0;event('p'); }
#include "module-functions.h"
int main(void) {
 for (int i=0;i<8;i++) {
  sequence[0]=0;result=0;
  assert(avd_module_init()==0);assert(ref_live && cmd_live && registered);assert(!strcmp(sequence,"RCP"));
  avd_module_exit();assert(!ref_live && !cmd_live && !registered);assert(!strcmp(sequence,"RCPpcr"));
  sequence[0]=0;result=-5;
  assert(avd_module_init()==-5);assert(!ref_live && !cmd_live && !registered);assert(!strcmp(sequence,"RCPcr"));
 }
 return 0;
}
''')
    subprocess.run(['cc','-std=gnu11','-Wall','-Werror','-fsanitize=address,undefined','-fno-sanitize-recover=all',str(out/'test.c'),'-o',str(out/'test')],check=True,timeout=30)
    r=subprocess.run([str(out/'test')],capture_output=True,text=True,timeout=10)
    (out/'run.log').write_text(r.stdout+r.stderr)
    if negative:
        assert r.returncode!=0,'unconditional teardown mutation escaped'
        print('PASS: original unbraced cleanup mutation rejected')
    else:
        assert r.returncode==0,r.stderr
        print('PASS: exact generated module init/exit success, registration failure and repeated lifecycle')
