#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Offline orchestration tests; no decoder, sudo, install or module operation."""
import dataclasses
import json
import os
from pathlib import Path
import shutil
import struct
import tempfile
import unittest
from unittest import mock

import prepare
import run


@dataclasses.dataclass
class State:
    module_loaded: bool = True
    video_node: str = '/fake/video'
    busy: bool = False
    wedged: bool = False
    faults: tuple = ()


class FakeCampaign(run.Campaign):
    def __init__(self, root, native, fail_at=None, fault=False):
        self.root = root
        self.state = State()
        self.backend = mock.Mock(state=lambda: self.state)
        self.changed = self.restored = self.approval_installed = False
        self.current = 'original'
        self.calls = []
        self.visited = []
        self.fail_at, self.fault = fail_at, fault
        source = root / 'native-source'
        source.write_text('fake reviewed approval\n')
        self.preparation = {'native_approval': {'path': str(source), 'sha256': run.manifest.digest(source)}}
        self.document = {'artifacts': {'recorder_module': {'path': '/fake/candidate'}}}
        self.admitted = {'workloads': [{'name': str(index)} for index in range(8)]}

    def record(self, event, **data):
        self.calls.append((event, data))

    def identity(self, original):
        run.need(self.current == ('original' if original else 'candidate'), 'identity mismatch')

    def healthy(self, present=True):
        run.need(not self.state.faults, 'STOP: unhealthy; no module recovery')
        run.need(not present or self.state.module_loaded, 'decoder missing')
        return self.state

    def privileged(self, *argv):
        self.calls.append(('command', argv))
        if argv[0].endswith('rmmod'):
            self.state.module_loaded = False; self.current = None
        elif argv[0].endswith('insmod'):
            self.state.module_loaded = True; self.current = 'candidate'
        elif argv[0].endswith('modprobe'):
            self.state.module_loaded = True; self.current = 'original'
        elif argv[0].endswith('install'):
            if '-d' in argv:
                Path(argv[-1]).mkdir()
            else:
                shutil.copyfile(argv[-2], argv[-1])
        elif argv[0].endswith('rmdir'):
            Path(argv[-1]).rmdir()
        elif argv[0].endswith('rm'):
            Path(argv[-1]).unlink()

    def live_check(self):
        self.identity(False); self.healthy()

    def workload(self, row, number):
        self.visited.append(number)
        if number == self.fail_at:
            if self.fault:
                self.state.faults = ('new decoder fault',)
            raise ValueError('injected workload failure')
        return {'frames': 300}


class Tests(unittest.TestCase):
    def test_note_parser_requires_one_bounded_id(self):
        note = struct.pack('<III', 4, 20, 3) + b'GNU\0' + b'\x17' * 20
        self.assertEqual(prepare.note_id(note), '17' * 20)
        for bad in (note[:-1], note + note, b''):
            with self.assertRaises(ValueError):
                prepare.note_id(bad)

    def test_expansion_preserves_private_report_and_sanitizes_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'fresh'
            row = {'argv': ['python', '--root', '@OMARCHY_RUN_ROOT@', '--run', '@OMARCHY_KERNEL_RUN@',
                            '@OMARCHY_OBSERVER_REPORT@'],
                   'environment': {'GST_REGISTRY': '@OMARCHY_RUN_ROOT@/registry', 'PATH': '/usr/bin'}}
            lease = {'LIBVA_HW_GUARD_LEASE': 'lease', 'LIBVA_HW_GUARD_IDENTITY': 'avd',
                     'LIBVA_HW_GUARD': '1', 'LD_PRELOAD': '/untrusted'}
            argv, env = run.expanded(row, root, 17, lease)
            self.assertIn(str(root), argv)
            self.assertIn('17', argv)
            self.assertIn('@OMARCHY_OBSERVER_REPORT@', argv)
            self.assertNotIn('LD_PRELOAD', env)
            self.assertEqual(env['GST_REGISTRY'], str(root / 'registry'))
            root.mkdir()
            with self.assertRaisesRegex(ValueError, 'already exists'):
                run.expanded(row, root, 18, lease)

    def test_frame_sequence_and_geometry_are_not_just_hash_counts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lines = [f'0, {i}, {i}, 1, 149760, ' + 'a' * 32 for i in range(300)]
            (root / 'frames.md5').write_text('# generated fixture\n' + '\n'.join(lines))
            self.assertEqual(run.frame_hashes(root, 'va'), ['a' * 32] * 300)
            lines[3] = lines[2]
            (root / 'frames.md5').write_text('\n'.join(lines))
            with self.assertRaisesRegex(ValueError, 'sequence/geometry'):
                run.frame_hashes(root, 'va')

    def test_gst_requires_complete_output_extent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'output.yuv').write_bytes(b'bad')
            with self.assertRaisesRegex(ValueError, 'extent'):
                run.frame_hashes(root, 'gst')

    def test_prior_and_pair_pixels_are_separate_gates(self):
        hashes = ['a'] * 300
        prior = list(enumerate(hashes))
        prior = [list(row) for row in prior]
        reference = ['a'] * 299 + ['b']
        self.assertEqual(run.compare_frames(hashes, prior, reference, hashes), [299])
        with self.assertRaisesRegex(ValueError, 'baseline'):
            run.compare_frames(['c'] + hashes[1:], prior, reference)
        with self.assertRaisesRegex(ValueError, 'perturbs'):
            run.compare_frames(hashes, prior, reference, ['c'] + hashes[1:])

    def test_logical_reference_projection_matches_accepted_cross_client_evidence(self):
        root = prepare.REPO / 'experiments/hevc-avd-command-capture/capture-2026-09-17'
        for vector in 'BE':
            va = json.loads((root / f'{vector}-va-on-reference.json').read_text())
            gst = json.loads((root / f'{vector}-gst-on-reference.json').read_text())
            self.assertEqual(run.reference_projection(va['records']), run.reference_projection(gst['records']))
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            run.reference_projection([])

    def campaign(self, fail_at=None, fault=False):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        native = root / 'approval' / 'approved-builds'
        campaign = FakeCampaign(root, native, fail_at, fault)
        with mock.patch.object(run, 'NATIVE', native), \
             mock.patch.object(os, 'geteuid', return_value=1001), \
             mock.patch.dict(os.environ, {'LIBVA_HW_GUARD_LEASE': 'fixture'}):
            if fail_at:
                with self.assertRaisesRegex(ValueError, 'injected workload failure'):
                    campaign.run()
            else:
                campaign.run()
            before = len(campaign.calls)
            with self.assertRaises(FileExistsError):
                campaign.run()
            self.assertEqual(len(campaign.calls), before, 'replay reached a transition')
        self.assertFalse(native.exists())
        return campaign

    def test_all_eight_and_healthy_restore(self):
        campaign = self.campaign()
        self.assertEqual(campaign.visited, list(range(1, 9)))
        self.assertTrue(campaign.restored)
        self.assertTrue((campaign.root / 'complete.json').exists())

    def test_software_failure_stops_without_replay_and_restores_healthy_module(self):
        campaign = self.campaign(fail_at=2)
        self.assertEqual(campaign.visited, [1, 2])
        self.assertTrue(campaign.restored)
        self.assertFalse((campaign.root / 'complete.json').exists())

    def test_decoder_fault_prevents_module_recovery(self):
        campaign = self.campaign(fail_at=1, fault=True)
        commands = [data for event, data in campaign.calls if event == 'command']
        self.assertEqual(sum(command[0].endswith('rmmod') for command in commands), 1)
        self.assertFalse(any(command[0].endswith('modprobe') for command in commands))
        self.assertFalse(campaign.restored)
        self.assertEqual(campaign.visited, [1])

    def test_config_digest_refusal_precedes_loading_any_tools(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            path.write_text('{}')
            with self.assertRaisesRegex(ValueError, 'digest drift'):
                run.checked_config(path, '0' * 64)


if __name__ == '__main__':
    unittest.main()
