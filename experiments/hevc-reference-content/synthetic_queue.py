#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Bounded fake queue; synthetic byte storage and records, never a dma-buf.

Original fake queue proposal: z23. Maintainer correction adds external completion
and pinned allocation/writer identities. No hardware proof.
"""
from __future__ import annotations
import threading
import time

class QueueError(Exception):
    pass

class FakeQueue:
    def __init__(self, run, context, *, client='self'):
        self.run, self.context, self.client = run, context, client
        self.condition = threading.Condition()
        self.paused = False
        self.closed = False
        self.allocations = {}
        self.inflight = {}
        self.completed = {}
        self.pins = {}
        self.next_job = 1
        self.next_pin = 1

    def _live(self):
        if self.closed or self.client != 'self':
            raise QueueError('closed/foreign client')

    def allocate(self, allocation, generation, data, *, policy='coherent-model'):
        with self.condition:
            self._live()
            if (self.paused or allocation in self.allocations or len(self.allocations) >= 8 or
                    type(allocation) is not int or type(generation) is not int or
                    allocation < 0 or generation < 0 or type(data) is not bytes or
                    len(data) not in (345600, 368128)):
                raise QueueError('allocation bounds/identity')
            self.allocations[allocation] = dict(generation=generation, data=bytearray(data),
                                                policy=policy, writer=None)

    def release(self, allocation):
        with self.condition:
            if (any(p['allocation'] == allocation for p in self.pins.values()) or
                    any(j['allocation'] == allocation for j in self.inflight.values())):
                raise QueueError('retained/inflight allocation')
            self.allocations.pop(allocation)

    def submit(self, allocation, generation, *, writer=None):
        """writer=(picture, POC); None means a reference reader."""
        with self.condition:
            self._live()
            if self.paused:
                raise QueueError('paused')
            a = self.allocations.get(allocation)
            if not a or a['generation'] != generation:
                raise QueueError('stale allocation')
            if writer is not None and any(p['allocation'] == allocation for p in self.pins.values()):
                raise QueueError('retained writer')
            if len(self.inflight) + len(self.completed) >= 128:
                raise QueueError('job budget')
            job = self.next_job
            self.next_job += 1
            self.inflight[job] = dict(allocation=allocation, generation=generation, writer=writer)
            return job

    def complete(self, job):
        with self.condition:
            self._live()
            item = self.inflight.pop(job)
            a = self.allocations[item['allocation']]
            if item['writer'] is not None:
                if any(p['allocation'] == item['allocation'] for p in self.pins.values()):
                    raise QueueError('writer changed while retained')
                picture, poc = item['writer']
                a['writer'] = dict(run=self.run, context=self.context,
                    allocation=item['allocation'], generation=item['generation'],
                    writer_job=job, picture=picture, poc=poc)
            self.completed[job] = item
            self.condition.notify_all()

    def writer_record(self, allocation):
        with self.condition:
            writer = self.allocations[allocation]['writer']
            if writer is None:
                raise QueueError('writer incomplete')
            return dict(writer)

    def pin(self, identity, length):
        with self.condition:
            self._live()
            a = self.allocations.get(identity.get('allocation'))
            if (not a or a['writer'] != identity or identity.get('run') != self.run or
                    identity.get('context') != self.context or
                    identity.get('writer_job') not in self.completed or
                    any(j['allocation'] == identity.get('allocation') and j['writer'] is not None
                        for j in self.inflight.values())):
                raise QueueError('stale/incomplete writer identity')
            if (a['policy'] != 'coherent-model' or len(a['data']) != length or
                    len(self.pins) >= 8):
                raise QueueError('unsupported exporter/plane/pin budget')
            token = self.next_pin
            self.next_pin += 1
            self.pins[token] = dict(identity)
            return token, memoryview(a['data']).toreadonly()

    def unpin(self, token):
        with self.condition:
            self.pins.pop(token, None)

    def pause(self):
        with self.condition:
            self._live()
            if self.paused:
                raise QueueError('already paused')
            self.paused = True
            self.condition.notify_all()

    def drain(self, seconds):
        with self.condition:
            self._live()
            if not self.paused:
                raise QueueError('drain without pause')
            deadline = time.monotonic() + seconds
            while self.inflight:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise QueueError('drain deadline/active job')
                self.condition.wait(remaining)
                self._live()

    def validate(self, token, identity):
        with self.condition:
            self._live()
            a = self.allocations.get(identity['allocation'])
            if (not self.paused or self.inflight or self.pins.get(token) != identity or
                    not a or a['writer'] != identity or a['generation'] != identity['generation'] or
                    identity['run'] != self.run or identity['context'] != self.context or
                    a['policy'] != 'coherent-model' or identity['writer_job'] not in self.completed):
                raise QueueError('lost retention/quiescence/identity')

    def resume(self):
        with self.condition:
            self._live()
            self.paused = False

    def stop(self):
        with self.condition:
            self.closed = True
            self.paused = False
            self.condition.notify_all()
