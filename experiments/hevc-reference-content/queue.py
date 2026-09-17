#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Fake asynchronous decode queue for pause/drain/retention proofs. No device."""
from __future__ import annotations

class QueueError(Exception):
    pass


class FakeQueue:
    def __init__(self, run, context, client='self', exporter='verified-coherent-noncached'):
        self.run = run
        self.context = context
        self.client = client
        self.exporter = exporter
        self.paused = False
        self.closed = False
        self.submissions = 0
        self.inflight = []  # list of job ids still reading a retained allocation
        self.completed = []
        self.retained = {}  # alloc_id -> generation
        self.next_job = 1
        self.clock = 0

    def retain(self, allocation, generation):
        if self.closed:
            raise QueueError('closed')
        self.retained[allocation] = generation

    def release(self, allocation):
        self.retained.pop(allocation, None)

    def submit(self, allocation, generation, reader=True):
        if self.closed:
            raise QueueError('closed')
        if self.paused:
            raise QueueError('paused')
        if self.client != 'self':
            raise QueueError('foreign client')
        job = self.next_job
        self.next_job += 1
        self.submissions += 1
        item = {'job': job, 'allocation': allocation, 'generation': generation, 'reader': reader}
        self.inflight.append(item)
        return job

    def complete(self, job):
        for i, item in enumerate(self.inflight):
            if item['job'] == job:
                self.inflight.pop(i)
                self.completed.append(item)
                return
        raise QueueError('unknown job')

    def pause(self):
        if self.closed:
            raise QueueError('closed')
        self.paused = True

    def resume(self):
        self.paused = False

    def drain(self, deadline_ticks=20):
        """Finish in-flight jobs while paused. New submits remain forbidden."""
        if not self.paused:
            raise QueueError('drain without pause')
        ticks = 0
        while self.inflight:
            ticks += 1
            self.clock += 1
            if ticks > deadline_ticks:
                raise QueueError('drain deadline')
            self.complete(self.inflight[0]['job'])
        return ticks

    def readers_on(self, allocation, generation):
        return [j for j in self.inflight
                if j['reader'] and j['allocation'] == allocation and j['generation'] == generation]

    def retention_ok(self, allocation, generation):
        return self.retained.get(allocation) == generation
