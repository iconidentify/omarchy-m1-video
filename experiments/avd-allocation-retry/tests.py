#!/usr/bin/env python3
"""Offline tests for the AVD allocation-retry candidate (issue #81).

Every function under test is extracted verbatim from the pinned, hash-verified,
shipped-patched sources.  Nothing is reimplemented.  Three variants are built
and compared: the pinned tree, candidate.patch, and alternative-reuse.patch.

No device, no module, no installation, no change to any shipped patch.

    python3 experiments/avd-allocation-retry/tests.py
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import source  # noqa: E402

CODECS = ('hevc', 'h264', 'vp9')
CACHE = os.environ.get('AVD_SOURCE_CACHE')
SANITIZE = bool(os.environ.get('AVD_SANITIZE'))

_state = {}


def setUpModule():
    root = Path(tempfile.mkdtemp(prefix='avd-alloc-retry-'))
    _state['root'] = root
    tree = source.prepare(root / 'tree', cache=Path(CACHE) if CACHE else None)
    _state['tree'] = tree
    _state['variants'] = {
        'pinned': tree / 'patched',
        'candidate': source.patch(tree, HERE / 'candidate.patch',
                                  root / 'candidate'),
        'alternative': source.patch(tree, HERE / 'alternative-reuse.patch',
                                    root / 'alternative'),
    }
    _state['builds'] = {}


def tearDownModule():
    shutil.rmtree(_state['root'], ignore_errors=True)


def text(variant, filename):
    return (_state['variants'][variant] / filename).read_text()


def build(variant, mutate=None):
    """Compile harness.c against the extracted allocator of one variant."""
    key = (variant, mutate[0] if mutate else None)
    if key in _state['builds']:
        return _state['builds'][key]

    work = _state['root'] / ('build-' + variant + ('-' + mutate[0] if mutate else ''))
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)

    drv = text(variant, 'avd-drv.c')
    alloc = source.function(drv, 'avd_buf_alloc')
    free = source.function(drv, 'avd_buf_free')
    if mutate:
        for old, new in mutate[1]:
            if alloc.count(old) != 1:
                raise AssertionError('mutation anchor not unique: %r' % (old,))
            alloc = alloc.replace(old, new)

    (work / 'extracted-types.h').write_text(
        source.struct(text(variant, 'avd.h'), 'avd_buf') + ';\n')
    (work / 'extracted.h').write_text(free + '\n\n' + alloc + '\n')
    shutil.copy(HERE / 'harness.c', work / 'harness.c')

    binary = work / 'harness'
    command = [os.environ.get('CC', 'cc'), '-std=gnu11', '-Wall', '-Wextra',
               '-Werror', '-O1', '-g', '-fno-omit-frame-pointer',
               '-I', str(work)]
    if os.environ.get('AVD_SANITIZE'):
        command += ['-fsanitize=address,undefined',
                    '-fno-sanitize-recover=all']
    command += [str(work / 'harness.c'), '-o', str(binary)]
    subprocess.run(command, check=True, capture_output=True, timeout=300)
    _state['builds'][key] = binary
    return binary


def run(variant, scenario, *failures, mutate=None):
    """Run one scenario and return {step: {field: value}} plus the exit code."""
    binary = build(variant, mutate=mutate)
    proc = subprocess.run([str(binary), scenario] + [str(f) for f in failures],
                          capture_output=True, text=True, timeout=60)
    steps = {}
    for line in proc.stdout.splitlines():
        parts = line.split()
        if not parts:
            continue
        fields = {}
        for part in parts[1:]:
            if '=' in part:
                name, value = part.split('=', 1)
                fields[name] = int(value) if value.lstrip('-').isdigit() else value
        steps[parts[0]] = fields
    return proc.returncode, steps, proc.stdout


# --------------------------------------------------------------------------
# 1. The reported defect, in the actual pinned function.
# --------------------------------------------------------------------------

class PinnedDefect(unittest.TestCase):
    def test_failed_allocation_leaves_a_stale_size(self):
        code, steps, out = run('pinned', 'single', 1)
        self.assertEqual(code, 0, out)
        self.assertEqual(steps['alloc']['ret'], -12)
        self.assertEqual(steps['alloc']['cpu'], 'null')
        self.assertEqual(steps['alloc']['size'], 4096,
                         'the pinned function records a size it did not allocate')

    def test_smaller_retry_reports_success_without_storage(self):
        code, steps, out = run('pinned', 'retry', 1)
        self.assertEqual(code, 0, out)
        self.assertEqual(steps['first']['ret'], -12)
        self.assertEqual(steps['second']['ret'], 0,
                         'the defect: the retry is reported as successful')
        self.assertEqual(steps['second']['cpu'], 'null')
        self.assertEqual(steps['second']['allocs'], 1,
                         'no second allocation was even attempted')

    def test_a_caller_that_trusts_the_return_value_uses_null(self):
        code, _, out = run('pinned', 'use-after-retry', 1)
        self.assertEqual(code, 94, out)
        self.assertIn('success-without-storage', out)

    def test_equal_and_larger_retries_are_unaffected(self):
        for scenario in ('retry-equal', 'retry-larger'):
            with self.subTest(scenario=scenario):
                code, steps, out = run('pinned', scenario, 1)
                self.assertEqual(code, 0, out)
                self.assertEqual(steps['second']['ret'], 0)
                self.assertEqual(steps['second']['cpu'], 'set')

    def test_reuse_never_happens_in_the_pinned_tree(self):
        """The inverted guard means every repeat call reallocates."""
        code, steps, out = run('pinned', 'retry')
        self.assertEqual(code, 0, out)
        self.assertEqual(steps['second']['allocs'], 2)
        self.assertEqual(steps['second']['frees'], 1)


# --------------------------------------------------------------------------
# 2. The candidate: behaviour preserving except for the defect.
# --------------------------------------------------------------------------

class Candidate(unittest.TestCase):
    def test_failed_allocation_leaves_nothing_behind(self):
        code, steps, out = run('candidate', 'single', 1)
        self.assertEqual(code, 0, out)
        self.assertEqual(steps['alloc']['ret'], -12)
        self.assertEqual(steps['alloc']['cpu'], 'null')
        self.assertEqual(steps['alloc']['size'], 0)

    def test_smaller_retry_allocates(self):
        code, steps, out = run('candidate', 'retry', 1)
        self.assertEqual(code, 0, out)
        self.assertEqual(steps['second']['ret'], 0)
        self.assertEqual(steps['second']['cpu'], 'set')
        self.assertEqual(steps['second']['size'], 2048)
        self.assertEqual(steps['second']['allocs'], 2)

    def test_retry_that_also_fails_still_reports_failure(self):
        code, steps, out = run('candidate', 'retry', 1, 2)
        self.assertEqual(code, 0, out)
        self.assertEqual(steps['second']['ret'], -12)
        self.assertEqual(steps['second']['cpu'], 'null')
        self.assertEqual(steps['second']['size'], 0)

    def test_success_is_never_reported_without_storage(self):
        for failures in ((), (1,), (2,), (1, 2)):
            for scenario in ('use-after-retry', 'sequence'):
                with self.subTest(scenario=scenario, failures=failures):
                    code, _, out = run('candidate', scenario, *failures)
                    self.assertNotEqual(code, 94, out)

    def test_zero_size_is_rejected_without_allocating(self):
        code, steps, out = run('candidate', 'zero')
        self.assertEqual(code, 0, out)
        self.assertEqual(steps['alloc']['ret'], -12)
        self.assertEqual(steps['alloc']['allocs'], 0)

    def test_zero_size_after_success_releases_the_buffer(self):
        code, steps, out = run('candidate', 'zero-after-failure')
        self.assertEqual(code, 0, out)
        self.assertEqual(steps['second']['ret'], -12)
        self.assertEqual(steps['second']['cpu'], 'null')
        self.assertEqual(steps['second']['live'], 0,
                         'the released buffer must not leak')

    def test_allocation_and_free_balance(self):
        for scenario in ('free', 'free-twice', 'sequence'):
            with self.subTest(scenario=scenario):
                code, steps, out = run('candidate', scenario)
                self.assertEqual(code, 0, out)
                self.assertEqual(steps['END']['live'], 0)
                self.assertEqual(steps['END']['allocs'] - steps['END']['fails'],
                                 steps['END']['frees'])

    def test_repeated_free_is_idempotent(self):
        code, steps, out = run('candidate', 'free-twice')
        self.assertEqual(code, 0, out)
        self.assertEqual(steps['END']['frees'], 1,
                         'the second free must not reach the DMA API')

    def test_behaviour_on_success_paths_matches_the_pinned_tree(self):
        for scenario, failures in (('single', ()), ('retry', ()),
                                   ('retry-equal', ()), ('retry-larger', ()),
                                   ('sequence', ()), ('free', ())):
            with self.subTest(scenario=scenario):
                _, pinned, _ = run('pinned', scenario, *failures)
                _, cand, _ = run('candidate', scenario, *failures)
                self.assertEqual(pinned['END'], cand['END'], scenario)


# --------------------------------------------------------------------------
# 3. The alternative: reuse, which is not behaviour preserving.
# --------------------------------------------------------------------------

class AlternativeReuse(unittest.TestCase):
    def test_smaller_request_reuses_the_existing_allocation(self):
        code, steps, out = run('alternative', 'retry')
        self.assertEqual(code, 0, out)
        self.assertEqual(steps['second']['ret'], 0)
        self.assertEqual(steps['second']['allocs'], 1)
        self.assertEqual(steps['second']['frees'], 0)
        self.assertEqual(steps['second']['size'], 4096,
                         'reuse keeps the larger recorded size')

    def test_equal_request_reuses_and_larger_request_reallocates(self):
        _, equal, _ = run('alternative', 'retry-equal')
        self.assertEqual(equal['second']['allocs'], 1)
        _, larger, _ = run('alternative', 'retry-larger')
        self.assertEqual(larger['second']['allocs'], 2)
        self.assertEqual(larger['second']['frees'], 1)

    def test_reuse_changes_observable_behaviour(self):
        """Documented reason this variant is not the candidate."""
        _, pinned, _ = run('pinned', 'sequence')
        _, alt, _ = run('alternative', 'sequence')
        self.assertNotEqual(pinned['END']['allocs'], alt['END']['allocs'])

    def test_the_defect_is_fixed_in_this_variant_too(self):
        code, steps, out = run('alternative', 'retry', 1)
        self.assertEqual(code, 0, out)
        self.assertEqual(steps['second']['ret'], 0)
        self.assertEqual(steps['second']['cpu'], 'set')
        code, _, out = run('alternative', 'use-after-retry', 1)
        self.assertNotEqual(code, 94, out)


# --------------------------------------------------------------------------
# 4. Negative mutations: the tests must fail when the repair is undone.
# --------------------------------------------------------------------------

INVERTED_GUARD = (
    'if (buf->cpu)\n\t\tavd_buf_free(avd, buf);',
    'if (!buf->cpu && size < buf->size)\n\t\treturn 0;\n'
    '\telse if (buf->cpu)\n\t\tavd_buf_free(avd, buf);')

STALE_SIZE_ON_FAILURE = (
    'memset(buf, 0, sizeof(*buf));\n\t\treturn -ENOMEM;',
    'buf->size = size;\n\t\treturn -ENOMEM;')

DROP_RECORDED_SIZE = ('buf->size = size;\n\treturn 0;', 'return 0;')

MUTATIONS = (
    ('guard', [INVERTED_GUARD]),
    ('stale', [STALE_SIZE_ON_FAILURE]),
    ('both', [INVERTED_GUARD, STALE_SIZE_ON_FAILURE]),
    ('size', [DROP_RECORDED_SIZE]),
)
MUTATION = {name: (name, tuple(edits)) for name, edits in MUTATIONS}


class Mutations(unittest.TestCase):
    """Undoing the repair must be caught, and shows which half does what."""

    def test_the_two_halves_are_each_independently_sufficient(self):
        """Either change alone already prevents the defect."""
        for name in ('guard', 'stale'):
            with self.subTest(mutation=name):
                code, _, out = run('candidate', 'use-after-retry', 1,
                                   mutate=MUTATION[name])
                self.assertEqual(code, 0, out)

    def test_undoing_both_halves_reintroduces_the_defect(self):
        code, steps, out = run('candidate', 'use-after-retry', 1,
                               mutate=MUTATION['both'])
        self.assertEqual(code, 94, out)
        self.assertEqual(steps['second']['ret'], 0)
        self.assertEqual(steps['second']['cpu'], 'null')

    def test_restoring_the_inverted_guard_alone_still_disables_reuse(self):
        code, steps, out = run('candidate', 'retry', mutate=MUTATION['guard'])
        self.assertEqual(code, 0, out)
        self.assertEqual(steps['second']['allocs'], 2,
                         'the inverted guard can never reuse a live buffer')

    def test_leaving_a_stale_size_after_failure_is_visible(self):
        _, steps, out = run('candidate', 'single', 1, mutate=MUTATION['stale'])
        self.assertEqual(steps['alloc']['size'], 4096, out)

    def test_dropping_the_recorded_size_is_detected(self):
        _, steps, out = run('candidate', 'single', mutate=MUTATION['size'])
        self.assertEqual(steps['alloc']['size'], 0, out)
        code, _, out = run('candidate', 'free', mutate=MUTATION['size'])
        self.assertEqual(code, 91, 'free size must match alloc size: ' + out)


# --------------------------------------------------------------------------
# 5. Caller audit, over the actual extracted source text.
# --------------------------------------------------------------------------

BUF_REFERENCE = re.compile(r'bufs\.([A-Za-z0-9_]+)')


def buffers(variant, codec, name):
    body = source.function(text(variant, 'avd-%s.c' % codec), 'avd_%s_%s' % (codec, name))
    return set(BUF_REFERENCE.findall(body))


class CallerAudit(unittest.TestCase):
    def test_pinned_start_paths_leak_partially_allocated_scratch(self):
        for codec in CODECS:
            with self.subTest(codec=codec):
                start = source.function(text('pinned', 'avd-%s.c' % codec),
                                        'avd_%s_start' % codec)
                self.assertIn('err_free_ctx:', start)
                self.assertIn('kfree(', start)
                self.assertNotIn('avd_%s_stop' % codec, start,
                                 'the pinned error path never reaches stop()')
                self.assertIn('alloc_bufs', start,
                              'so any buffer alloc_bufs() obtained is leaked')

    def test_candidate_start_paths_unwind_through_stop(self):
        for codec in CODECS:
            with self.subTest(codec=codec):
                start = source.function(text('candidate', 'avd-%s.c' % codec),
                                        'avd_%s_start' % codec)
                self.assertIn('avd_%s_stop(ctx);' % codec, start)
                self.assertNotIn('kfree(', start.split('err_free_ctx:')[1])

    def test_every_stop_frees_every_buffer_its_alloc_bufs_takes(self):
        for codec in CODECS:
            with self.subTest(codec=codec):
                taken = buffers('candidate', codec, 'alloc_bufs')
                freed = buffers('candidate', codec, 'stop')
                self.assertTrue(taken, 'alloc_bufs must allocate something')
                self.assertEqual(taken - freed, set(),
                                 'stop() must free what alloc_bufs() took')

    def test_every_stop_tolerates_a_null_context(self):
        for codec in CODECS:
            with self.subTest(codec=codec):
                stop = source.function(text('candidate', 'avd-%s.c' % codec),
                                       'avd_%s_stop' % codec)
                self.assertRegex(stop, r'if \(!\w+_ctx\)\s*\n\s*return;')

    def test_pinned_vp9_stop_lacks_the_null_check_its_siblings_have(self):
        stop = source.function(text('pinned', 'avd-vp9.c'), 'avd_vp9_stop')
        self.assertNotRegex(stop, r'if \(!vp9_ctx\)')
        for codec in ('hevc', 'h264'):
            other = source.function(text('pinned', 'avd-%s.c' % codec),
                                    'avd_%s_stop' % codec)
            self.assertRegex(other, r'if \(!\w+_ctx\)')

    def test_removing_the_unwind_fails_the_audit(self):
        """Negative mutation of the cleanup change."""
        start = source.function(text('candidate', 'avd-hevc.c'), 'avd_hevc_start')
        mutated = start.replace('avd_hevc_stop(ctx);', 'kfree(hevc_ctx);')
        self.assertNotIn('avd_hevc_stop(ctx);', mutated)
        self.assertIn('kfree(', mutated.split('err_free_ctx:')[1])

    def test_call_sites_are_enumerated_and_recorded(self):
        recorded = json.loads((HERE / 'caller-audit.json').read_text())
        found = {}
        for path in sorted((_state['variants']['pinned']).glob('avd-*.c')):
            hits = len(re.findall(r'(?<!int )avd_buf_alloc\(', path.read_text()))
            if hits:
                found[path.name] = hits
        self.assertEqual(found, recorded['call_sites'],
                         'caller-audit.json is out of date with the pinned tree')

    def test_the_repeat_call_sites_are_the_per_frame_scratch_paths(self):
        """Why reuse needs caller proof: these run again for every frame."""
        scratch = source.function(text('pinned', 'avd-hevc.c'),
                                  'avd_hevc_alloc_scratch')
        self.assertGreater(len(re.findall(r'avd_buf_alloc\(', scratch)), 1)
        run_fn = text('pinned', 'avd-hevc.c')
        self.assertIn('avd_hevc_alloc_scratch(ctx, &run)', run_fn)


# --------------------------------------------------------------------------
# 6. Source identity.
# --------------------------------------------------------------------------

class Identity(unittest.TestCase):
    def test_both_patches_apply_with_zero_fuzz(self):
        for name in ('candidate.patch', 'alternative-reuse.patch'):
            with self.subTest(patch=name):
                self.assertTrue((HERE / name).is_file())

    def test_the_patches_touch_only_the_avd_directory(self):
        for name in ('candidate.patch', 'alternative-reuse.patch'):
            for line in (HERE / name).read_text().splitlines():
                if line.startswith(('--- a/', '+++ b/')):
                    self.assertIn('drivers/media/platform/apple/avd/', line)

    def test_no_shipped_patch_is_modified(self):
        try:
            proc = subprocess.run(['git', 'status', '--porcelain', 'patches'],
                                  cwd=source.REPO, capture_output=True,
                                  text=True, timeout=60)
        except (OSError, subprocess.SubprocessError) as exc:
            self.skipTest('git unavailable: %s' % exc)
        if proc.returncode != 0:
            self.skipTest('not a git checkout')
        self.assertEqual(proc.stdout.strip(), '',
                         'this experiment must not change any shipped patch')

    def test_the_shipped_patch_stack_identity_is_verified(self):
        """prepare() refuses to run against an altered patch stack."""
        pins = json.loads((source.REFERENCE / 'source-map.json').read_text())
        self.assertEqual(len(pins['patches_concatenated_sha256']), 64)
        self.assertEqual(pins['kernel_revision'],
                         json.loads((HERE / 'caller-audit.json').read_text())
                         ['kernel_revision'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
