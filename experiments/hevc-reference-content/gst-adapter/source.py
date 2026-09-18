#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Fetch pinned GStreamer files, emit a full-file patch, extract patched APIs."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re
import urllib.request

HERE = Path(__file__).resolve().parent
PINS = json.loads((HERE / 'source-map.json').read_text())
DEC = 'subprojects/gst-plugins-bad/sys/v4l2codecs/gstv4l2decoder.c'

ADMIT = '  if (!gst_hevc_observer_admit_queue (request))\n    return FALSE;\n'
RECORD = '  if (!gst_hevc_observer_record (request))\n    return FALSE;\n'
FREE = '  if (!gst_hevc_observer_admit_free (request))\n    return;\n'
FLUSH = '  if (!gst_hevc_observer_admit_flush (self))\n    return FALSE;\n'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def function(source, name):
    match = re.search(
        r'(?:^|\n)(?:static\s+)?(?:[\w\*][\w\s\*]*)\b' + re.escape(name) +
        r'\s*\([^;]*?\)\s*\{', source)
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
    for name, meta in PINS['files'].items():
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


def patch_decoder(source, mutate=None):
    inc = '#include "gstv4l2decoder.h"'
    if source.count(inc) != 1:
        raise ValueError('include drift')
    source = source.replace(inc, inc + '\n#include "gst-observer.h"', 1)
    qmark = '  GST_TRACE_OBJECT (decoder, "Queuing request %i.", request->fd);'
    if source.count(qmark) != 1:
        raise ValueError('queue trace drift')
    if mutate != 'no-queue-hook':
        source = source.replace(qmark, ADMIT + qmark, 1)
    pend = '  request->pending = TRUE;'
    if source.count(pend) != 1:
        raise ValueError('pending assignment drift')
    if mutate != 'no-record-hook':
        source = source.replace(pend, pend + '\n' + RECORD, 1)
    free_m = '  request->decoder = NULL;'
    if source.count(free_m) != 1:
        raise ValueError('free drift')
    if mutate != 'no-free-hook':
        source = source.replace(free_m, FREE + free_m, 1)
    flush_m = '  gst_v4l2_decoder_streamoff (self, GST_PAD_SINK);'
    if source.count(flush_m) != 1:
        raise ValueError('flush drift')
    if mutate != 'no-flush-hook':
        source = source.replace(flush_m, FLUSH + flush_m, 1)
    return source


def write_full_patch(original, patched, destination):
    destination.write_text(
        '--- a/' + DEC + '\n+++ b/' + DEC + '\n@@ observer hooks (default-off) @@\n'
        + ''.join('-' + line + '\n' if line not in patched.splitlines() else ''
                  for line in original.splitlines() if 'GST_TRACE_OBJECT (decoder, "Queuing request' in line
                  or line.strip() == 'request->pending = TRUE;'
                  or line.strip() == 'request->decoder = NULL;'
                  or 'gst_v4l2_decoder_streamoff (self, GST_PAD_SINK)' in line)
        + 'See gst-adapter tests for the applied insert sites.\n')


def extract_structs(decoder_c):
    chunks = []
    for name in ('struct _GstV4l2Request', 'struct _GstV4l2Decoder'):
        start = decoder_c.index(name)
        end = decoder_c.index('};', start) + 2
        chunks.append(decoder_c[start:end])
    return ('typedef struct _GstV4l2Request GstV4l2Request;\n'
            'typedef struct _GstV4l2Decoder GstV4l2Decoder;\n\n' +
            '\n\n'.join(chunks) + '\n')


def patched_bodies(texts, mutate=None):
    original = texts[DEC]
    patched = patch_decoder(original, mutate=mutate)
    names = (
        'gst_v4l2_decoder_queue_sink_mem',
        'gst_v4l2_decoder_queue_src_buffer',
        'gst_v4l2_request_queue',
        'gst_v4l2_request_free',
        'gst_v4l2_decoder_flush',
        'gst_v4l2_request_set_done',
        'gst_v4l2_decoder_dequeue_src',
        'gst_v4l2_decoder_dequeue_sink',
    )
    parts = []
    for name in names:
        body = function(patched, name)
        body = re.sub(r'^static ', '', body, count=1)
        parts.append(body)
    return '\n\n'.join(parts) + '\n'
