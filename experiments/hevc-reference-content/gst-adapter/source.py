#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Fetch pinned GStreamer v4l2codecs files and extract/patch request_queue."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re
import urllib.request

HERE = Path(__file__).resolve().parent
PINS = json.loads((HERE / 'source-map.json').read_text())


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


QUEUE_HOOK = 'if (!gst_hevc_observer_admit_queue (request))\n    return FALSE;\n  '
FREE_HOOK = 'if (!gst_hevc_observer_admit_free (request))\n    return;\n  '
FLUSH_HOOK = 'if (!gst_hevc_observer_admit_flush (self))\n    return FALSE;\n  '


def patched_bodies(texts, mutate=None):
    dec = texts['subprojects/gst-plugins-bad/sys/v4l2codecs/gstv4l2decoder.c']
    queue = function(dec, 'gst_v4l2_request_queue')
    free = function(dec, 'gst_v4l2_request_free')
    flush = function(dec, 'gst_v4l2_decoder_flush')
    sink = function(dec, 'gst_v4l2_decoder_queue_sink_mem')
    src = function(dec, 'gst_v4l2_decoder_queue_src_buffer')
    marker = 'GST_TRACE_OBJECT (decoder, "Queuing request %i.", request->fd);'
    if queue.count(marker) != 1:
        raise ValueError('queue hook drift')
    if mutate != 'no-queue-hook':
        queue = queue.replace(marker, QUEUE_HOOK + marker, 1)
    free_marker = 'request->decoder = NULL;'
    if free.count(free_marker) != 1:
        raise ValueError('free hook drift')
    if mutate != 'no-free-hook':
        free = free.replace(free_marker, FREE_HOOK + free_marker, 1)
    flush_marker = 'gst_v4l2_decoder_streamoff (self, GST_PAD_SINK);'
    if flush.count(flush_marker) != 1:
        raise ValueError('flush hook drift')
    if mutate != 'no-flush-hook':
        flush = flush.replace(flush_marker, FLUSH_HOOK + flush_marker, 1)
    # Drop static so the harness can call queue/flush.
    queue = queue.replace('gboolean\ngst_v4l2_request_queue', 'gboolean gst_v4l2_request_queue', 1)
    flush = flush.replace('gboolean\ngst_v4l2_decoder_flush', 'gboolean gst_v4l2_decoder_flush', 1)
    free = free.replace('static void\ngst_v4l2_request_free', 'void gst_v4l2_request_free', 1)
    return '\n\n'.join((sink, src, queue, free, flush)) + '\n'
