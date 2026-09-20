#!/usr/bin/env python3
"""Fetch explicit pinned source inputs; not a Chromium checkout or build."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import urllib.request

HERE = Path(__file__).resolve().parent


def verified(cache):
    for row in json.loads((HERE / 'sources.json').read_text()):
        path = cache / row['path']
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != row['sha256']:
            raise ValueError('Source mismatch: ' + str(path))
    return cache


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('cache', type=Path)
    args = parser.parse_args()
    args.cache.mkdir(parents=True, exist_ok=True)
    for row in json.loads((HERE / 'sources.json').read_text()):
        path = args.cache / row['path']
        if path.exists():
            continue  # verified below; never repair/overwrite mismatching input
        with urllib.request.urlopen(row['url'], timeout=30) as response:
            data = response.read(2 * 1024 * 1024 + 1)
        if len(data) > 2 * 1024 * 1024:
            raise ValueError('Oversized source response')
        if row['url'].endswith('?format=TEXT'):
            data = base64.b64decode(data, validate=True)
        if hashlib.sha256(data).hexdigest() != row['sha256']:
            raise ValueError('Downloaded source mismatch: ' + row['path'])
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as output:
            output.write(data)
    verified(args.cache)
    print('Verified all pinned source inputs; no build or device use.')


if __name__ == '__main__':
    main()
