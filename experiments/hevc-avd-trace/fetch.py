#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Fetch only manifest-locked primary AVD sources; never executes fetched code."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import urllib.request

HERE=Path(__file__).resolve().parent


def fetch(destination):
    manifest=json.loads((HERE/'sources.json').read_text())
    destination.mkdir(parents=False,exist_ok=False)
    revision=manifest['kernel_revision']
    def one(item):
        name,sha=item
        url=f'https://raw.githubusercontent.com/AsahiLinux/linux/{revision}/drivers/media/platform/apple/avd/{name}'
        with urllib.request.urlopen(url,timeout=30) as response:content=response.read(1024*1024+1)
        if hashlib.sha256(content).hexdigest()!=sha:raise ValueError('source hash mismatch: '+name)
        (destination/name).write_bytes(content)
    with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(one,manifest['upstream_files'].items()))
    print(f'PASS: {len(manifest["upstream_files"])} exact pinned upstream source files')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('destination',type=Path)
    fetch(p.parse_args().destination)
