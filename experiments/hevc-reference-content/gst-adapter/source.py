#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Retrieve and verify the complete pinned GStreamer source, never install it."""
import hashlib
import json
from pathlib import Path
import tarfile
import urllib.request

HERE = Path(__file__).resolve().parent
PINS = json.loads((HERE / 'source-map.json').read_text())
BASE = Path('subprojects/gst-plugins-bad/sys/v4l2codecs')


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def fetch(destination, archive=None):
    if archive is None:
        archive = destination / 'source.tar.gz'
        with urllib.request.urlopen(PINS['archive']['url'], timeout=120) as response:
            with archive.open('wb') as out:
                while chunk := response.read(1024 * 1024):
                    out.write(chunk)
    if digest(archive) != PINS['archive']['sha256']:
        raise ValueError('archive SHA256 mismatch')
    with tarfile.open(archive) as bundle:
        bundle.extractall(destination, filter='data')
    root = destination / ('gstreamer-' + PINS['gstreamer_revision'])
    for name, meta in PINS['files'].items():
        if digest(root / name) != meta['sha256']:
            raise ValueError('source SHA256 mismatch: ' + name)
    print('PASS pinned archive and original client source hashes', flush=True)
    return root
