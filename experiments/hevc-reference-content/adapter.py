#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Process-context observer adapter. Copy path runs only after pause/drain/retention."""
from __future__ import annotations

from queue import FakeQueue, QueueError

MAX_COPY = 184320
MAX_SNAPSHOTS = 8
ALLOWED_LENGTHS = (345600, 368128)
COMP = (161280, 177152)
MV = 7168


class AdapterError(Exception):
    pass


class Observer:
    def __init__(self, queue: FakeQueue, enabled=True):
        self.queue = queue
        self.enabled = enabled
        self.snapshots = []
        self.copied = 0

    def admit(self, layout, identity, mapping='verified-coherent-noncached'):
        if not self.enabled:
            raise AdapterError('disabled')
        if mapping != 'verified-coherent-noncached' or self.queue.exporter != mapping:
            raise AdapterError('unsupported exporter')
        if self.queue.client != 'self':
            raise AdapterError('foreign client')
        if layout.get('width', 448) != 448 or layout.get('height', 240) != 240:
            raise AdapterError('geometry')
        length = layout['length']
        if length not in ALLOWED_LENGTHS:
            raise AdapterError('length')
        if layout.get('comp_start') != COMP[0] or layout.get('comp_size') != COMP[1]:
            raise AdapterError('compressed extent')
        if layout.get('mv_size') != MV or layout.get('mv_offset') != length - MV:
            raise AdapterError('mv extent')
        if COMP[0] + COMP[1] > layout['mv_offset']:
            raise AdapterError('overlap')
        size = COMP[1] + MV
        if size > MAX_COPY:
            raise AdapterError('budget')
        if identity.get('run') != self.queue.run or identity.get('context') != self.queue.context:
            raise AdapterError('stale identity')
        return size

    def snapshot(self, layout, identity, plane, deadline_ticks=20):
        size = self.admit(layout, identity)
        alloc = identity['allocation']
        gen = identity['generation']
        if not self.queue.retention_ok(alloc, gen):
            raise AdapterError('missing retention')
        try:
            self.queue.pause()
            self.queue.drain(deadline_ticks=deadline_ticks)
        except QueueError as exc:
            self.queue.resume()
            raise AdapterError(str(exc)) from exc
        if self.queue.readers_on(alloc, gen):
            self.queue.resume()
            raise AdapterError('reader still active')
        if not self.queue.retention_ok(alloc, gen):
            self.queue.resume()
            raise AdapterError('lost retention')
        if identity.get('run') != self.queue.run:
            self.queue.resume()
            raise AdapterError('stale identity')
        if len(self.snapshots) >= MAX_SNAPSHOTS:
            self.queue.resume()
            raise AdapterError('overflow')
        if not isinstance(plane, (bytes, bytearray)) or len(plane) < layout['length']:
            self.queue.resume()
            raise AdapterError('malformed plane')
        start, csize = COMP
        mv_off = layout['mv_offset']
        copy = bytes(plane[start:start + csize] + plane[mv_off:mv_off + MV])
        if len(copy) != size:
            self.queue.resume()
            raise AdapterError('copy size')
        self.snapshots.append({
            'identity': dict(identity),
            'hash': _fnv(copy),
            'bytes': size,
        })
        self.copied += size
        self.queue.resume()
        return self.snapshots[-1]


def _fnv(data):
    h = 2166136261
    for b in data:
        h ^= b
        h = (h * 16777619) & 0xffffffff
    return h
