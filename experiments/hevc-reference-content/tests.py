#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Synthetic queue tests plus source-linked real-client barrier rejections."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from adapter import AdapterError, Observer, real_client_adapter, MAX_COPY
from barrier import ClientBarrier, classify
import client_source
from synthetic_queue import FakeQueue, QueueError

HERE = Path(__file__).resolve().parent
CAPTURE = HERE.parent / 'hevc-avd-command-capture/capture-2026-09-17'

def fixture(length=345600, policy='coherent-model'):
    q = FakeQueue('run-1', 'context-generation-1')
    data = bytes(range(256)) * (length // 256) + bytes(range(length % 256))
    q.allocate(3, 7, data, policy=policy)
    q.complete(q.submit(3, 7, writer=(28, 32)))
    layout = dict(width=448, height=240, length=length, comp_start=161280,
                  comp_size=177152, mv_offset=length - 7168, mv_size=7168)
    return q, q.writer_record(3), layout, data

class ObserverTests(unittest.TestCase):
    def test_default_off(self):
        q, ident, layout, _ = fixture()
        with self.assertRaisesRegex(AdapterError, 'disabled'):
            Observer(q).snapshot(layout, ident)
        self.assertFalse(q.paused)
        self.assertEqual(q.pins, {})

    def test_real_adapters_always_blocked(self):
        for client in ('VA', 'Gst', 'unknown'):
            for records in (None, {'coherent': True, 'paused': True, 'retained': True}):
                with self.assertRaisesRegex(AdapterError, 'blocked'):
                    real_client_adapter(client, records)
        with self.assertRaises(AdapterError):
            Observer(object(), enabled=True)

    def test_exact_ranges_both_lengths_hash_after_resume(self):
        for length in (345600, 368128):
            q, ident, layout, data = fixture(length)
            real_hash = hashlib.sha256
            def checked_hash(blob):
                self.assertFalse(q.paused)
                self.assertEqual(q.pins, {})
                return real_hash(blob)
            with patch('adapter.hashlib.sha256', checked_hash):
                result = Observer(q, enabled=True).snapshot(layout, ident)
            self.assertEqual(result['sha256'], real_hash(data[161280:338432] + data[-7168:]).hexdigest())
            self.assertEqual(result['bytes'], MAX_COPY)
            self.assertTrue(result['synthetic'])

    def test_external_worker_completion_and_submission_barrier(self):
        q, ident, layout, _ = fixture()
        reader = q.submit(3, 7)
        errors = []
        def complete_after_pause():
            try:
                with q.condition:
                    self.assertTrue(q.condition.wait_for(lambda: q.paused, timeout=1))
                with self.assertRaisesRegex(QueueError, 'paused'):
                    q.submit(3, 7)
                with self.assertRaisesRegex(QueueError, 'retained'):
                    q.release(3)
                q.complete(reader)
            except BaseException as exc:
                errors.append(exc)
        worker = threading.Thread(target=complete_after_pause)
        worker.start()
        try:
            Observer(q, enabled=True).snapshot(layout, ident, drain_seconds=1)
        finally:
            worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(q.inflight, {})
        self.assertEqual(q.pins, {})

    def test_drain_does_not_complete_jobs(self):
        q, ident, layout, _ = fixture()
        reader = q.submit(3, 7)
        observer = Observer(q, enabled=True)
        with self.assertRaisesRegex(AdapterError, 'deadline'):
            observer.snapshot(layout, ident, drain_seconds=0.001)
        self.assertIn(reader, q.inflight)
        self.assertNotIn(reader, q.completed)
        self.assertTrue(q.closed)
        self.assertTrue(observer.stopped)
        self.assertFalse(q.paused)
        self.assertEqual(q.pins, {})
        with self.assertRaises(QueueError):
            q.submit(3, 7)
        with self.assertRaises(AdapterError):
            observer.snapshot(layout, ident)

    def test_drain_requires_pause(self):
        q, _, _, _ = fixture()
        with self.assertRaisesRegex(QueueError, 'without pause'):
            q.drain(0.001)

    def test_unknown_and_cacheable_policy_rejected(self):
        for policy in ('unknown', 'cacheable', 'verified-coherent-noncached'):
            q, ident, layout, _ = fixture(policy=policy)
            with self.assertRaisesRegex(AdapterError, 'exporter'):
                Observer(q, enabled=True).snapshot(layout, ident)

    def test_all_identity_fields_bound_to_completed_writer(self):
        for key in ('run', 'context', 'allocation', 'generation', 'writer_job', 'picture', 'poc'):
            q, ident, layout, _ = fixture()
            ident[key] = 'other' if isinstance(ident[key], str) else ident[key] + 1
            with self.assertRaises(AdapterError, msg=key):
                Observer(q, enabled=True).snapshot(layout, ident)
        q, ident, layout, _ = fixture()
        del ident['writer_job']
        with self.assertRaises(AdapterError):
            Observer(q, enabled=True).snapshot(layout, ident)

    def test_incomplete_or_new_writer_is_not_old_reference(self):
        q, ident, layout, _ = fixture()
        job = q.submit(3, 7, writer=(29, 32))  # reused POC still a different writer
        with self.assertRaises(AdapterError):
            Observer(q, enabled=True).snapshot(layout, ident)
        q, ident, layout, _ = fixture()
        q.complete(q.submit(3, 7, writer=(29, 32)))
        with self.assertRaises(AdapterError):
            Observer(q, enabled=True).snapshot(layout, ident)

    def test_foreign_missing_or_wrong_plane_rejected(self):
        for mode in ('foreign', 'released', 'length'):
            q, ident, layout, _ = fixture()
            if mode == 'foreign': q.client = 'foreign'
            if mode == 'released': q.release(3)
            if mode == 'length': layout.update(length=368128, mv_offset=360960)
            with self.assertRaises(AdapterError):
                Observer(q, enabled=True).snapshot(layout, ident)

    def test_extents_types_overflow_and_deadlines(self):
        for key in ('width', 'height', 'length', 'comp_start', 'comp_size', 'mv_offset', 'mv_size'):
            for value in (-1, 2**64, True, 0.5):
                q, ident, layout, _ = fixture()
                layout[key] = value
                with self.assertRaises(AdapterError):
                    Observer(q, enabled=True).snapshot(layout, ident)
        for seconds in (0, -1, 3, float('nan'), float('inf')):
            q, ident, layout, _ = fixture()
            with self.assertRaises(AdapterError):
                Observer(q, enabled=True).snapshot(layout, ident, drain_seconds=seconds)

    def test_post_drain_changes_rejected_and_cleaned(self):
        for mode in ('pin', 'writer', 'run', 'context', 'generation', 'policy', 'inflight', 'exception'):
            q, ident, layout, _ = fixture()
            def corrupt(_seconds):
                if mode == 'pin': q.pins.clear()
                if mode == 'writer': q.allocations[3]['writer']['picture'] += 1
                if mode == 'run': q.run = 'changed'
                if mode == 'context': q.context = 'changed'
                if mode == 'generation': q.allocations[3]['generation'] += 1
                if mode == 'policy': q.allocations[3]['policy'] = 'unknown'
                if mode == 'inflight': q.inflight[99] = dict(allocation=3, generation=7, writer=None)
                if mode == 'exception': raise RuntimeError('injected')
            q.drain = corrupt
            with self.assertRaises(AdapterError, msg=mode):
                Observer(q, enabled=True).snapshot(layout, ident)
            self.assertTrue(q.closed)
            self.assertFalse(q.paused)
            self.assertEqual(q.pins, {})

    def test_copy_deadline_and_post_copy_identity(self):
        for mode in ('deadline', 'identity', 'exception'):
            q, ident, layout, _ = fixture()
            calls = []
            def clock():
                calls.append(1)
                if len(calls) == 1: return 0
                if mode == 'exception': raise RuntimeError('copy clock')
                if mode == 'identity': q.allocations[3]['writer']['picture'] += 1
                return .021 if mode == 'deadline' else .001
            obs = Observer(q, enabled=True, clock=clock)
            with self.assertRaises(AdapterError): obs.snapshot(layout, ident)
            self.assertEqual(obs.snapshots, [])
            self.assertFalse(q.paused)
            self.assertEqual(q.pins, {})
            self.assertTrue(q.closed)

    def test_retention_prevents_release_and_rewrite(self):
        q, ident, layout, _ = fixture()
        token, _ = q.pin(ident, layout['length'])
        with self.assertRaises(QueueError): q.release(3)
        with self.assertRaises(QueueError): q.submit(3, 7, writer=(29, 33))
        q.unpin(token)
        q.release(3)
        self.assertEqual(q.allocations, {})

    def test_off_on_same_pause_and_cleanup(self):
        for copy in (False, True):
            q, ident, layout, _ = fixture()
            observer = Observer(q, enabled=True)
            events = []
            for method in ('pin', 'pause', 'drain', 'validate', 'resume', 'unpin'):
                original = getattr(q, method)
                def record(*args, _name=method, _original=original):
                    events.append(_name)
                    return _original(*args)
                setattr(q, method, record)
            result = observer.snapshot(layout, ident, copy=copy)
            self.assertEqual(events, ['pin','pause','drain','validate','validate','resume','unpin'])
            self.assertEqual(result['bytes'], MAX_COPY if copy else 0)
            self.assertEqual(len(observer.pool), 1474560)

    def test_snapshot_cap(self):
        q, ident, layout, _ = fixture()
        obs = Observer(q, enabled=True)
        for _ in range(8): obs.snapshot(layout, ident)
        with self.assertRaisesRegex(AdapterError, 'budget'): obs.snapshot(layout, ident)
        self.assertEqual(sum(s['bytes'] for s in obs.snapshots), 1474560)
        self.assertEqual(q.pins, {})


class ClientBarrierTests(unittest.TestCase):
    bodies = None
    hashes = None

    @classmethod
    def setUpClass(cls):
        cache = Path(tempfile.mkdtemp(prefix='hevc-ref-content-src-'))
        texts = client_source.fetch(cache)
        cls.bodies, cls.hashes = client_source.extract(texts)
        cls.cache = cache

    def test_extracted_function_hashes_are_stable(self):
        self.assertEqual(sorted(self.bodies), sorted(self.hashes))
        for name, body in self.bodies.items():
            self.assertGreater(len(body), 40, name)
            self.assertIn(name.split('(')[0], body)
        self.assertIn('<< index', self.bodies['wait_on_capture_locked'])
        self.assertIn('return 0;', self.bodies['vb2_dc_dmabuf_ops_begin_cpu_access'])
        self.assertIn('vaBeginPicture', self.bodies['ff_vaapi_decode_issue'])
        self.assertIn('v4l2_m2m_buf_done_and_job_finish', self.bodies['avd_job_finish_no_pm'])

    def test_source_hash_mismatch_rejected(self):
        bad = self.cache / 'src/surface.c'
        original = bad.read_bytes()
        bad.write_bytes(original + b'\n/* drift */\n')
        try:
            with self.assertRaisesRegex(ValueError, 'source hash mismatch'):
                client_source.fetch(self.cache)
        finally:
            bad.write_bytes(original)

    def test_classify_lists_every_required_capability(self):
        report = classify(self.bodies)
        joined = ' '.join(report['missing'])
        for cap in ('all_producer_pause_token', 'retain_surface_and_allocation',
                    'drain_existing_readers', 'exporter_cache_identity',
                    'same_run_writer_join'):
            self.assertIn(cap, joined)
        self.assertEqual(report['present'], [])

    def test_instrumented_apis_fail_closed(self):
        for client in ('VA', 'Gst'):
            barrier = ClientBarrier(client, self.bodies)
            with self.assertRaisesRegex(AdapterError, 'pause token'):
                barrier.pause()
            with self.assertRaisesRegex(AdapterError, 'generation'):
                barrier.retain()
            with self.assertRaisesRegex(AdapterError, 'POLLOUT|drain'):
                barrier.drain(1)
            with self.assertRaisesRegex(AdapterError, 'no-op|exporter'):
                barrier.exporter_identity()
            with self.assertRaisesRegex(AdapterError, 'blocked'):
                real_client_adapter(client, bodies=self.bodies)

    def test_wait_mutation_is_still_not_a_pause_token(self):
        bodies = dict(self.bodies)
        bodies['wait_on_capture_locked'] = bodies['wait_on_capture_locked'].replace(
            '<< index', '<< index /* pause_all */')
        with self.assertRaisesRegex(AdapterError, 'pause token'):
            ClientBarrier('VA', bodies).pause()

    def test_cpu_access_return_zero_is_not_coherence(self):
        bodies = dict(self.bodies)
        bodies['vb2_dc_dmabuf_ops_begin_cpu_access'] = (
            'static int vb2_dc_dmabuf_ops_begin_cpu_access(void) { return 0; /* coherent */ }')
        with self.assertRaisesRegex(AdapterError, 'no-op|exporter'):
            ClientBarrier('VA', bodies).exporter_identity()

    def test_boolean_and_association_records_rejected(self):
        barrier = ClientBarrier('VA', self.bodies)
        with self.assertRaisesRegex(AdapterError, 'fixture booleans'):
            barrier.join_writer({'coherent': True, 'paused': True, 'retained': True})
        association = json.loads((CAPTURE / 'E-va-on-association.json').read_text())
        with self.assertRaisesRegex(AdapterError, 'poc/index-only'):
            barrier.join_writer(association)

    def test_capture_records_lack_live_generation(self):
        records = json.loads((CAPTURE / 'E-va-on-reference.json').read_text())
        with self.assertRaisesRegex(AdapterError, 'missing generation'):
            ClientBarrier('VA', self.bodies).join_writer(records)
        records['records'][1]['generation'] = 7
        records['records'][1]['writer_job'] = 99
        ident = ClientBarrier('VA', self.bodies).join_writer(records)
        self.assertEqual(ident['run'], records['run'])
        self.assertEqual(ident['allocation'], records['records'][1]['allocation'])
        with self.assertRaisesRegex(AdapterError, 'pause token'):
            real_client_adapter('VA', records, bodies=self.bodies)

    def test_observer_still_rejects_non_fake_queue(self):
        with self.assertRaises(AdapterError):
            Observer(object(), enabled=True)


def mutations():
    variants = {
        'default-on': ('adapter.py', 'enabled=False', 'enabled=True', 1),
        'leaked-pin': ('adapter.py', 'self.queue.unpin(token)', 'pass # missing unpin', 1),
        'writer-unbound': ('synthetic_queue.py', "a['writer'] != identity", 'False', 2),
        'pause-bypassed': ('synthetic_queue.py', 'if self.paused:', 'if False:', 2),
    }
    copies = ('tests.py', 'adapter.py', 'synthetic_queue.py', 'barrier.py',
              'client_source.py', 'source-map.json')
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        for name, (file, old, new, count) in variants.items():
            dest = root / name
            dest.mkdir()
            for source in copies:
                shutil.copyfile(HERE/source, dest/source)
            p = dest/file
            text = p.read_text()
            if text.count(old) != count: raise AssertionError('mutation drift: ' + name)
            p.write_text(text.replace(old,new))
            result = subprocess.run([sys.executable, str(dest/'tests.py'), '--unit-only'],
                                    capture_output=True, text=True, timeout=20)
            if result.returncode != 1 or 'FAILED (' not in result.stderr:
                raise AssertionError('mutation not detected: ' + name + '\n' + result.stderr)
            print('PASS: rejected actual-source mutation', name)

if __name__ == '__main__':
    unit_only = '--unit-only' in sys.argv
    loader = unittest.defaultTestLoader
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(ObserverTests))
    if not unit_only:
        suite.addTests(loader.loadTestsFromTestCase(ClientBarrierTests))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful(): sys.exit(1)
    if not unit_only: mutations()
