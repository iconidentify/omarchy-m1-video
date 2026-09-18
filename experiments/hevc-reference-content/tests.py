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
from source_audit import inspect_sources, reject_historical_identity
import client_source
from real_barrier import prove_no_real_barrier
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


class SourceAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cache = Path(tempfile.mkdtemp(prefix='hevc-ref-content-src-'))
        cls.addClassCleanup(shutil.rmtree, cls.cache)
        texts = client_source.fetch(cls.cache)
        cls.bodies, cls.hashes = client_source.extract(texts)

    def test_exact_extracted_identities(self):
        report = inspect_sources(self.bodies)
        self.assertEqual(report['functions'], self.hashes)
        self.assertFalse(report['c_functions_executed'])
        self.assertFalse(report['client_instrumentation'])
        self.assertFalse(report['real_adapter_implemented'])
        self.assertFalse(report['copy_authorized'])

    def test_file_hash_drift_rejected(self):
        path = self.cache / 'src/surface.c'
        old = path.read_bytes();path.write_bytes(old+b'\n/* drift */\n')
        try:
            with self.assertRaisesRegex(ValueError, 'source hash mismatch'):
                client_source.fetch(self.cache)
        finally: path.write_bytes(old)

    def test_function_mutation_rejected(self):
        bodies = dict(self.bodies)
        bodies['wait_on_capture_locked'] = bodies['wait_on_capture_locked'].replace('<< index','<< 0')
        with self.assertRaisesRegex(ValueError,'function identity'):
            inspect_sources(bodies)
        del bodies['ff_vaapi_decode_issue']
        with self.assertRaises(ValueError): inspect_sources(bodies)

    def test_source_scope_is_explicit(self):
        report = inspect_sources(self.bodies)
        self.assertIn('upstream base only', report['avd_completion_scope'])
        self.assertIn('direct V4L2', report['gstreamer_scope'])

    def test_boolean_and_association_identity_always_rejected(self):
        association = json.loads((CAPTURE / 'E-va-on-association.json').read_text())
        for records in (None, association, {'coherent':True,'paused':True,'retained':True}):
            with self.assertRaisesRegex(AdapterError,'not live ownership'):
                reject_historical_identity(records)

    def test_forged_generations_do_not_admit_historical_captures(self):
        records = json.loads((CAPTURE / 'E-va-on-reference.json').read_text())
        for row in records['records']:
            row.update(generation=7,writer_job=99)
        with self.assertRaisesRegex(AdapterError,'not live ownership'):
            reject_historical_identity(records)
        for client in ('VA','Gst','unknown'):
            with self.assertRaisesRegex(AdapterError,'blocked'):
                real_client_adapter(client, records, bodies=self.bodies)

    def test_passing_source_strings_never_enables_copy(self):
        for bodies in (self.bodies, {}, {'pause':'return token;'}):
            with self.assertRaisesRegex(AdapterError,'blocked'):
                real_client_adapter('VA',bodies=bodies)


class ExecutedBarrierTests(unittest.TestCase):
    def test_extracted_wait_cannot_pause_all_producers(self):
        out = prove_no_real_barrier()
        self.assertIn('no pause token', out)
        self.assertIn('no generation', out)

    def test_real_adapter_still_blocked_after_execution(self):
        with self.assertRaisesRegex(AdapterError, 'wait_on_capture_locked'):
            real_client_adapter('VA')


def mutations():
    variants = {
        'default-on': ('adapter.py', 'enabled=False', 'enabled=True', 1),
        'leaked-pin': ('adapter.py', 'self.queue.unpin(token)', 'pass # missing unpin', 1),
        'writer-unbound': ('synthetic_queue.py', "a['writer'] != identity", 'False', 2),
        'pause-bypassed': ('synthetic_queue.py', 'if self.paused:', 'if False:', 2),
    }
    copies = ('tests.py', 'adapter.py', 'synthetic_queue.py', 'source_audit.py',
              'client_source.py', 'source-map.json', 'function-hashes.json',
              'real_barrier.py', 'barrier_harness.c')
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
        suite.addTests(loader.loadTestsFromTestCase(SourceAuditTests))
        suite.addTests(loader.loadTestsFromTestCase(ExecutedBarrierTests))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful(): sys.exit(1)
    if not unit_only: mutations()
