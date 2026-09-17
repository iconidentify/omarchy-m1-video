#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Synthetic observation-contract checker. Never maps/copies a real buffer."""
MAX_COPY = 184320
MAX_SNAPSHOTS = 8
IDENTITY = ('run', 'context', 'allocation', 'generation', 'picture', 'poc')
FIELDS = {'enabled', 'identity_before', 'identity_after', 'width', 'height', 'depth',
          'length', 'comp_start', 'comp_size', 'mv_offset', 'mv_size', 'completed',
          'quiescent', 'inflight_readers', 'retained', 'mapping_readable',
          'allocation_policy', 'provenance_verified', 'copy_budget', 'snapshot_count',
          'elapsed_us', 'error', 'overflow', 'context_kind'}


def validate(record):
    if not isinstance(record, dict) or set(record) != FIELDS:
        raise ValueError('missing/unknown contract fields')
    for key in ('enabled', 'completed', 'quiescent', 'retained', 'mapping_readable',
                'provenance_verified', 'error', 'overflow'):
        if type(record[key]) is not bool:
            raise ValueError('non-boolean contract field: ' + key)
    for key in ('width', 'height', 'depth', 'length', 'comp_start', 'comp_size',
                'mv_offset', 'mv_size', 'inflight_readers', 'copy_budget',
                'snapshot_count', 'elapsed_us'):
        if type(record[key]) is not int or not 0 <= record[key] <= 0xffffffff:
            raise ValueError('invalid integer: ' + key)
    if not record['enabled'] or record['error'] or record['overflow']:
        raise ValueError('disabled/error/overflow')
    if record['context_kind'] != 'process' or not all(record[k] for k in
            ('completed', 'quiescent', 'retained', 'mapping_readable', 'provenance_verified')):
        raise ValueError('unproved CPU/lifetime/quiescence contract')
    if record['inflight_readers']:
        raise ValueError('reference reader still in flight')
    # Current pinned exporter has no-op CPU sync hooks. Merely issuing SYNC is insufficient.
    if record['allocation_policy'] != 'verified-coherent-noncached':
        raise ValueError('cacheable/unknown exporter is blocked at current pin')
    for name in ('identity_before', 'identity_after'):
        identity = record[name]
        if not isinstance(identity, dict) or set(identity) != set(IDENTITY):
            raise ValueError('incomplete identity')
        for key in ('run', 'context'):
            if type(identity[key]) is not str or not 1 <= len(identity[key]) <= 64:
                raise ValueError('invalid run/context identity')
        for key in ('allocation', 'generation', 'picture'):
            if type(identity[key]) is not int or not 0 <= identity[key] <= 0xffffffff:
                raise ValueError('invalid allocation/writer identity')
        if type(identity['poc']) is not int or not -(2**31) <= identity['poc'] < 2**31:
            raise ValueError('invalid POC')
    if record['identity_before'] != record['identity_after']:
        raise ValueError('writer/run identity changed across observation')
    if (record['width'], record['height'], record['depth']) != (448, 240, 8):
        raise ValueError('outside bounded initial observation geometry')
    if (record['comp_start'], record['comp_size'], record['mv_size']) != (161280, 177152, 7168):
        raise ValueError('layout differs from pinned C and accepted window')
    if record['length'] not in (345600, 368128) or record['mv_offset'] != record['length'] - record['mv_size']:
        raise ValueError('wrong MV/plane extent')
    if record['comp_start'] + record['comp_size'] > record['mv_offset']:
        raise ValueError('overlapping ranges')
    size = record['comp_size'] + record['mv_size']
    if not size <= record['copy_budget'] <= MAX_COPY or not 1 <= record['snapshot_count'] <= MAX_SNAPSHOTS:
        raise ValueError('observation budget exceeded')
    if record['elapsed_us'] > 20000:
        raise ValueError('copy deadline exceeded')
    return {'design_fixture_only': True, 'bytes': size,
            'ranges': [(record['comp_start'], record['comp_start'] + record['comp_size']),
                       (record['mv_offset'], record['length'])]}
