#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Fake queue + adapter tests. No device, no real dma-buf."""
from __future__ import annotations

import unittest
from adapter import AdapterError, Observer, COMP, MV
from queue import FakeQueue, QueueError

LAYOUT_GST = {
    'width': 448, 'height': 240, 'length': 345600,
    'comp_start': 161280, 'comp_size': 177152, 'mv_offset': 338432, 'mv_size': 7168,
}
IDENT = {
    'run': 'run-1', 'context': 'ctx-1', 'allocation': 3, 'generation': 7,
    'picture': 28, 'poc': 32,
}


def plane(length=345600):
    buf = bytearray(length)
    start, size = COMP
    buf[start:start + size] = bytes((i * 3) & 0xff for i in range(size))
    buf[length - MV:] = bytes((i * 5) & 0xff for i in range(MV))
    return buf


class QueueLifetime(unittest.TestCase):
    def test_pause_blocks_submit_and_drain_clears_readers(self):
        q = FakeQueue('run-1', 'ctx-1')
        q.retain(3, 7)
        j1 = q.submit(3, 7)
        j2 = q.submit(3, 7)
        q.pause()
        with self.assertRaises(QueueError):
            q.submit(3, 7)
        q.drain()
        self.assertEqual(q.inflight, [])
        self.assertEqual({j['job'] for j in q.completed}, {j1, j2})

    def test_drain_without_pause_is_rejected(self):
        q = FakeQueue('run-1', 'ctx-1')
        q.submit(3, 7)
        with self.assertRaises(QueueError):
            q.drain()

    def test_foreign_client_cannot_submit(self):
        q = FakeQueue('run-1', 'ctx-1', client='other')
        with self.assertRaises(QueueError):
            q.submit(3, 7)


class Adapter(unittest.TestCase):
    def setUp(self):
        self.q = FakeQueue('run-1', 'ctx-1')
        self.q.retain(3, 7)
        self.obs = Observer(self.q)

    def test_copy_after_pause_drain(self):
        job = self.q.submit(3, 7)
        self.q.complete(job)
        snap = self.obs.snapshot(LAYOUT_GST, IDENT, plane())
        self.assertEqual(snap['bytes'], 177152 + 7168)
        self.assertFalse(self.q.paused)

    def test_active_reader_must_drain(self):
        self.q.submit(3, 7)
        snap = self.obs.snapshot(LAYOUT_GST, IDENT, plane())
        self.assertEqual(self.q.inflight, [])
        self.assertEqual(snap['bytes'], 184320)

    def test_missing_retention(self):
        self.q.release(3)
        with self.assertRaisesRegex(AdapterError, 'retention'):
            self.obs.snapshot(LAYOUT_GST, IDENT, plane())

    def test_unsupported_exporter(self):
        self.q.exporter = 'cacheable-unknown'
        with self.assertRaisesRegex(AdapterError, 'exporter'):
            self.obs.snapshot(LAYOUT_GST, IDENT, plane())

    def test_stale_identity(self):
        bad = dict(IDENT, run='other')
        with self.assertRaisesRegex(AdapterError, 'stale'):
            self.obs.snapshot(LAYOUT_GST, bad, plane())

    def test_foreign_client(self):
        self.q.client = 'other'
        with self.assertRaisesRegex(AdapterError, 'foreign'):
            self.obs.snapshot(LAYOUT_GST, IDENT, plane())

    def test_malformed_extent(self):
        layout = dict(LAYOUT_GST, mv_offset=1)
        with self.assertRaisesRegex(AdapterError, 'mv|overlap'):
            self.obs.snapshot(layout, IDENT, plane())

    def test_deadline(self):
        for _ in range(5):
            self.q.submit(3, 7)
        with self.assertRaisesRegex(AdapterError, 'deadline'):
            self.obs.snapshot(LAYOUT_GST, IDENT, plane(), deadline_ticks=1)

    def test_overflow_snapshots(self):
        for i in range(8):
            ident = dict(IDENT, generation=7)
            self.obs.snapshot(LAYOUT_GST, ident, plane())
        with self.assertRaisesRegex(AdapterError, 'overflow'):
            self.obs.snapshot(LAYOUT_GST, IDENT, plane())

    def test_disabled(self):
        self.obs.enabled = False
        with self.assertRaisesRegex(AdapterError, 'disabled'):
            self.obs.snapshot(LAYOUT_GST, IDENT, plane())

    def test_mutating_exporter_check_admits_cacheable(self):
        import adapter as mod
        orig = mod.Observer.admit

        def broken(self, layout, identity, mapping='verified-coherent-noncached'):
            saved = self.queue.exporter
            self.queue.exporter = 'verified-coherent-noncached'
            try:
                return orig(self, layout, identity, mapping='verified-coherent-noncached')
            finally:
                self.queue.exporter = saved

        mod.Observer.admit = broken
        try:
            q = FakeQueue('run-1', 'ctx-1', exporter='cacheable-unknown')
            q.retain(3, 7)
            # Admit ignores the queue exporter; snapshot still checks queue.exporter.
            # Mutate snapshot's exporter compare by setting mapping path only in admit.
            self.assertEqual(broken(Observer(q), LAYOUT_GST, IDENT), 184320)
        finally:
            mod.Observer.admit = orig
        q = FakeQueue('run-1', 'ctx-1', exporter='cacheable-unknown')
        q.retain(3, 7)
        with self.assertRaises(AdapterError):
            Observer(q).admit(LAYOUT_GST, IDENT)


class Docs(unittest.TestCase):
    def test_campaign_and_limits(self):
        from pathlib import Path
        here = Path(__file__).resolve().parent
        plan = (here / 'CAMPAIGN.md').read_text()
        self.assertIn('observer off,on', plan.lower())
        self.assertIn('#42', plan)
        self.assertNotIn('Fixes https://github.com/iconidentify/libva-v4l2_request/issues/42',
                         (here / 'README.md').read_text())


if __name__ == '__main__':
    unittest.main()
