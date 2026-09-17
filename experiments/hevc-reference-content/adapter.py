#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Synthetic observer only. Real client adapters are explicitly blocked."""
from __future__ import annotations
import hashlib
import time
from synthetic_queue import FakeQueue

MAX_COPY = 184320
MAX_SNAPSHOTS = 8
COMP = (161280, 177152)
MV = 7168

class AdapterError(Exception):
    pass

def real_client_adapter(client, records=None, *, bodies=None):
    """Records or source strings cannot enforce a live producer barrier or lifetime pin."""
    raise AdapterError('blocked: no verified real-client pause/retention/exporter adapter')

class Observer:
    def __init__(self, queue, enabled=False, clock=time.monotonic):
        if type(queue) is not FakeQueue:
            raise AdapterError('synthetic queue required')
        self.queue = queue
        self.enabled = enabled
        self.clock = clock
        # Bounded payload storage and views allocated before any pause.
        self.pool = bytearray(MAX_COPY * MAX_SNAPSHOTS)
        view = memoryview(self.pool)
        self.slots = [view[i * MAX_COPY:(i + 1) * MAX_COPY] for i in range(MAX_SNAPSHOTS)]
        self.snapshots = []
        self.stopped = False

    def admit(self, layout):
        keys = {'width', 'height', 'length', 'comp_start', 'comp_size', 'mv_offset', 'mv_size'}
        if set(layout) != keys or any(type(v) is not int for v in layout.values()):
            raise AdapterError('malformed extent')
        length = layout['length']
        if (layout['width'], layout['height']) != (448, 240) or length not in (345600, 368128):
            raise AdapterError('geometry/length')
        if (layout['comp_start'], layout['comp_size']) != COMP:
            raise AdapterError('compressed extent')
        if layout['mv_size'] != MV or layout['mv_offset'] != length - MV:
            raise AdapterError('mv extent')
        if COMP[0] + COMP[1] > layout['mv_offset']:
            raise AdapterError('overlap')

    def snapshot(self, layout, identity, *, copy=True, drain_seconds=2.0):
        if not self.enabled or self.stopped:
            raise AdapterError('disabled/stopped')
        if type(copy) is not bool or not 0 < drain_seconds <= 2:
            raise AdapterError('invalid deadline/mode')
        self.admit(layout)
        if len(self.snapshots) >= MAX_SNAPSHOTS:
            self.stopped = True
            raise AdapterError('snapshot budget')
        # Metadata and selected views prepared before pausing too.
        token = None
        result = {'identity': dict(identity), 'synthetic': True, 'copy': copy}
        slot = self.slots[len(self.snapshots)]
        try:
            token, plane = self.queue.pin(identity, layout['length'])
            compressed = plane[COMP[0]:COMP[0] + COMP[1]]
            motion = plane[layout['mv_offset']:layout['length']]
            first, second = slot[:COMP[1]], slot[COMP[1]:]
            self.queue.pause()
            # An external fake worker completes jobs; drain never does so itself.
            self.queue.drain(drain_seconds)
            self.queue.validate(token, identity)
            started = self.clock()
            if copy:
                first[:] = compressed
                second[:] = motion
            elapsed = self.clock() - started
            if elapsed < 0 or elapsed > 0.020:
                raise AdapterError('copy deadline')
            self.queue.validate(token, identity)
            self.queue.resume()
        except Exception as exc:
            self.stopped = True
            self.queue.stop()
            raise AdapterError(str(exc)) from exc
        finally:
            if token is not None:
                self.queue.unpin(token)
        # Hash and serialization only after the pause; raw bytes not returned.
        result.update(bytes=MAX_COPY if copy else 0, elapsed=elapsed,
                      sha256=hashlib.sha256(slot).hexdigest() if copy else None)
        self.snapshots.append(result)
        return result
