#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Build n9.0.1 ffmpeg with and without VAAPI, apply the admission patch. No install."""
from __future__ import annotations

import argparse
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile
import urllib.request

HERE = Path(__file__).resolve().parent
PIN = 'bf1b838f2ab88b4f8fd83443325c782ea0e0f7fa'
ARCHIVE_SHA = 'fb1931fd4eb29297ee1c1017a24f800c4d8fbea35b4f2aaeb28308a48a9149b4'
ON = ['--disable-everything', '--disable-autodetect', '--disable-asm',
      '--disable-doc', '--enable-decoder=h264', '--enable-parser=h264',
      '--enable-vaapi', '--enable-hwaccel=h264_vaapi']
OFF = ['--disable-everything', '--disable-autodetect', '--disable-asm',
       '--disable-doc', '--enable-decoder=h264', '--enable-parser=h264']


def sha(data):
    return hashlib.sha256(data).hexdigest()


def run(cmd, cwd, log):
    result = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=240)
    log.write_bytes(result.stdout)
    return result.returncode, result.stdout.decode(errors='replace')


def extract_archive(root, archive_bytes):
    if sha(archive_bytes) != ARCHIVE_SHA:
        raise ValueError('source archive identity mismatch')
    tar = root / 'source.tar.gz'
    tar.write_bytes(archive_bytes)
    with tarfile.open(tar) as stream:
        stream.extractall(root, filter='data')
    return root / ('FFmpeg-' + PIN)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('destination', type=Path)
    p.add_argument('--archive', type=Path)
    args = p.parse_args()
    root = args.destination.resolve()
    root.mkdir(parents=True, exist_ok=False)
    archive = args.archive.read_bytes() if args.archive else urllib.request.urlopen(
        f'https://codeload.github.com/FFmpeg/FFmpeg/tar.gz/{PIN}', timeout=60).read()
    tree = extract_archive(root, archive)
    patch = HERE / 'ffmpeg-n9.0.1-h264-vaapi-admission.patch'
    rc, _ = run(['patch','-p0','--fuzz=0','-i',str(patch)],tree,root/'patch-off.log')
    if rc: raise RuntimeError('VAAPI-off patch application failed')
    jobs = ['make', '-j' + str(min(6, os.cpu_count() or 1)), 'ffmpeg']

    off = tree
    rc, _ = run(['./configure', *OFF], off, root / 'configure-off.log')
    if rc or '#define CONFIG_H264_VAAPI_HWACCEL 1' in (off / 'config_components.h').read_text():
        raise RuntimeError('VAAPI-off configuration failed')
    rc, _ = run(jobs, off, root / 'build-off.log')
    if rc:
        raise RuntimeError('VAAPI-off ffmpeg failed to link')
    off_sha = sha((off / 'ffmpeg').read_bytes())
    nm_off = subprocess.check_output(['nm', str(off / 'ffmpeg_g')], text=True, errors='replace')
    if 'ff_h264_vaapi_admit_end' in nm_off:
        raise RuntimeError('admit symbols present in VAAPI-off binary')

    # Second tree for VAAPI-on + patch
    on_root = root / 'vaapi-on'
    on_root.mkdir()
    on = extract_archive(on_root, archive)
    rc, _ = run(['./configure', *ON], on, root / 'configure-on.log')
    if rc or '#define CONFIG_H264_VAAPI_HWACCEL 1' not in (on / 'config_components.h').read_text():
        raise RuntimeError('VAAPI-on configuration failed')
    patch = HERE / 'ffmpeg-n9.0.1-h264-vaapi-admission.patch'
    rc, out = run(['patch', '-p0', '--fuzz=0', '-i', str(patch)], on, root / 'patch.log')
    if rc:
        raise RuntimeError('admission patch failed')
    if (on / 'libavcodec/h264_vaapi_admit.c').read_bytes() != (HERE / 'h264_vaapi_admit.c').read_bytes():
        raise ValueError('patched admit.c is not the experiment file')
    rc, _ = run(jobs, on, root / 'build-on.log')
    if rc:
        raise RuntimeError('VAAPI-on patched ffmpeg failed to link')
    on_sha = sha((on / 'ffmpeg').read_bytes())
    nm_on = subprocess.check_output(['nm', str(on / 'ffmpeg_g')], text=True, errors='replace')
    for sym in ('ff_h264_vaapi_admit_start', 'ff_h264_vaapi_admit_slice',
                'ff_h264_vaapi_admit_end', 'ff_h264_vaapi_admit_reject'):
        if sym not in nm_on:
            raise RuntimeError('missing ' + sym)
    spec=importlib.util.spec_from_file_location('glue_test',HERE/'end-gate-test.py')
    glue_test=importlib.util.module_from_spec(spec);spec.loader.exec_module(glue_test)
    glue_report=glue_test.test(on)
    spec=importlib.util.spec_from_file_location('parser_test',HERE/'parser-test.py')
    parser_test=importlib.util.module_from_spec(spec);spec.loader.exec_module(parser_test)
    parser_report=parser_test.test(on)
    report = {
        'glue_test':glue_report,
        'parser_test':parser_report,
        'compiler':subprocess.check_output(['cc','--version'],text=True).splitlines()[0],
        'libva_version':subprocess.check_output(['pkg-config','--modversion','libva'],text=True).strip(),
        'configure_off':OFF,'configure_on':ON,
        'architecture':os.uname().machine,
        'schema': 'omarchy-m1-video.h264-client-admission-build/1',
        'ffmpeg_commit': PIN,
        'source_archive_sha256': ARCHIVE_SHA,
        'patch_sha256': sha(patch.read_bytes()),
        'vaapi_off_ffmpeg_sha256': off_sha,
        'vaapi_on_ffmpeg_sha256': on_sha,
        'remap': 'disabled',
        'hardware': 'none',
        'installed_changes': 'none',
        'logs':{p.name:sha(p.read_bytes()) for p in sorted(root.glob('*.log'))},
    }
    (root / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
