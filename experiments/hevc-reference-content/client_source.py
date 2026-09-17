#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Fetch hash-pinned driver/kernel/FFmpeg files and extract named C functions."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re
import urllib.request

HERE = Path(__file__).resolve().parent
PINS = json.loads((HERE / 'source-map.json').read_text())['client_files']


def digest(data):
    return hashlib.sha256(data).hexdigest()


def function(source, name):
    match = re.search(
        r'(?:^|\n)(?:static\s+)?(?:[\w\*][\w\s\*]*)\b' + re.escape(name) +
        r'\s*\([^;]*?\)\s*\{',
        source)
    if not match:
        raise ValueError('function not found: ' + name)
    start = match.start()
    if source[start] == '\n':
        start += 1
    end = match.end()
    depth = 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


def fetch(cache=None):
    texts = {}
    for name, meta in PINS.items():
        if cache and (cache / name).is_file():
            data = (cache / name).read_bytes()
        else:
            data = urllib.request.urlopen(meta['url'], timeout=30).read(2 * 1024 * 1024)
        if digest(data) != meta['sha256']:
            raise ValueError('source hash mismatch: ' + name)
        if cache:
            target = cache / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        texts[name] = data.decode()
    return texts


def extract(texts):
    bodies = {}
    hashes = {}
    for name, meta in PINS.items():
        source = texts[name]
        for func in meta['functions']:
            body = function(source, func)
            bodies[func] = body
            hashes[func] = digest(body.encode())
    return bodies, hashes
