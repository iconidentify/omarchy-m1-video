#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Instrument pinned client/driver APIs; fail closed when they cannot own a copy."""
from __future__ import annotations
from adapter import AdapterError

REQUIRED = (
    'all_producer_pause_token',
    'retain_surface_and_allocation',
    'drain_existing_readers',
    'exporter_cache_identity',
    'same_run_writer_join',
)
IDENTITY = ('run', 'context', 'allocation', 'generation', 'writer_job', 'picture', 'poc')


def _one_index_wait(body):
    return 'queued_capture' in body and '<< index' in body


def _noop_cpu_access(body):
    return 'return 0;' in body and 'dma_sync' not in body and 'dma_buf_end' not in body


def classify(bodies):
    missing = []
    wait = bodies.get('wait_on_capture_locked', '')
    sync = bodies.get('v4l2r_SyncSurface', '')
    issue = bodies.get('ff_vaapi_decode_issue', '')
    if _one_index_wait(wait) or 'v4l2r_surface_ready' in sync:
        missing.append('all_producer_pause_token: wait_on_capture_locked/v4l2r_SyncSurface wait one capture; '
                       'ff_vaapi_decode_issue submits Begin/EndPicture with no pause token')
    if 'vaBeginPicture' in issue and 'pause' not in issue:
        if not any(item.startswith('all_producer_pause_token') for item in missing):
            missing.append('all_producer_pause_token: ff_vaapi_decode_issue has no producer pause')
    preserve = bodies.get('preserve_capture', '')
    export = bodies.get('v4l2r_ExportSurfaceHandle', '')
    if 'dmabuf_fd' in preserve and 'generation' not in preserve:
        missing.append('retain_surface_and_allocation: preserve_capture keeps fds, not generation/writer identity')
    if 'v4l2r_surface_ready' in export and 'generation' not in export:
        missing.append('retain_surface_and_allocation: ExportSurfaceHandle waits then exports; dma-buf has no fence')
    readers = bodies.get('capture_wait_readers', '')
    finish = bodies.get('avd_job_finish_no_pm', '')
    if 'POLLOUT' in readers and 'inflight' not in readers:
        missing.append('drain_existing_readers: capture_wait_readers polls one buffer POLLOUT; '
                       'avd_job_finish_no_pm completes one job into vb2')
    if 'v4l2_m2m_buf_done_and_job_finish' in finish and 'pause' not in finish:
        if not any(item.startswith('drain_existing_readers') for item in missing):
            missing.append('drain_existing_readers: DQBUF/job_finish is not a freeze of later submissions')
    begin = bodies.get('vb2_dc_dmabuf_ops_begin_cpu_access', '')
    end = bodies.get('vb2_dc_dmabuf_ops_end_cpu_access', '')
    if _noop_cpu_access(begin) and _noop_cpu_access(end):
        missing.append('exporter_cache_identity: vb2-dma-contig begin/end CPU access are no-op; '
                       'SYNC ioctl is not assumed')
    missing.append('same_run_writer_join: live generation/writer_job is not present on historical capture records')
    return {'required': REQUIRED, 'missing': missing, 'present': []}


class ClientBarrier:
    def __init__(self, client, bodies):
        if client not in ('VA', 'Gst', 'unknown'):
            raise AdapterError('unknown client')
        if not bodies:
            raise AdapterError('blocked: no verified real-client pause/retention/exporter adapter')
        for name in ('wait_on_capture_locked', 'v4l2r_ExportSurfaceHandle',
                     'ff_vaapi_decode_issue', 'vb2_dc_dmabuf_ops_begin_cpu_access',
                     'avd_job_finish_no_pm', 'capture_wait_readers', 'preserve_capture'):
            if name not in bodies:
                raise AdapterError('missing extracted API ' + name)
        self.client = client
        self.bodies = bodies
        self.report = classify(bodies)
        # Gst uses the same VA driver APIs; no pinned Gst pause token exists.
        if client == 'unknown':
            raise AdapterError('blocked: unknown client has no producer barrier')

    def pause(self):
        body = self.bodies['wait_on_capture_locked']
        issue = self.bodies['ff_vaapi_decode_issue']
        if _one_index_wait(body) or 'vaBeginPicture' in issue:
            raise AdapterError('blocked: no all-producer pause token')
        raise AdapterError('blocked: pause token not returned by pinned APIs')

    def retain(self):
        if 'generation' not in self.bodies['preserve_capture']:
            raise AdapterError('blocked: no retained surface/allocation generation')
        raise AdapterError('blocked: retention identity incomplete')

    def drain(self, seconds=2.0):
        if type(seconds) is not float and type(seconds) is not int:
            raise AdapterError('invalid deadline')
        if not 0 < seconds <= 2:
            raise AdapterError('invalid deadline')
        readers = self.bodies['capture_wait_readers']
        if 'POLLOUT' in readers:
            raise AdapterError('blocked: reader wait is one-buffer POLLOUT, not drained inflight set')
        raise AdapterError('blocked: drain cannot invent completion')

    def exporter_identity(self):
        if _noop_cpu_access(self.bodies['vb2_dc_dmabuf_ops_begin_cpu_access']):
            raise AdapterError('blocked: exporter CPU access is no-op; cacheable/unknown rejected')
        raise AdapterError('blocked: unsupported exporter')

    def join_writer(self, records):
        if records is None:
            raise AdapterError('missing records')
        if isinstance(records, list):
            if records and set(records[0]) <= {'output_index', 'pic', 'poc'}:
                raise AdapterError('poc/index-only identity')
            raise AdapterError('malformed records')
        if not isinstance(records, dict):
            raise AdapterError('malformed records')
        if 'records' not in records and any(key in records for key in ('coherent', 'paused', 'retained')):
            raise AdapterError('fixture booleans are not live ownership')
        if 'records' not in records:
            raise AdapterError('malformed records')
        run, context = records.get('run'), records.get('context')
        if run is None or context is None:
            raise AdapterError('stale identity: missing run/context')
        completed = [row for row in records['records']
                     if row.get('completed') == 1 and row.get('writer') is not None]
        if not completed:
            raise AdapterError('writer incomplete')
        row = completed[0]
        command = next((item for item in records['records']
                        if item.get('kind') == 1 and item.get('writer') == row.get('writer')
                        and item.get('allocation') == row.get('allocation')), {})
        ident = {
            'run': run, 'context': context,
            'allocation': row.get('allocation'),
            'generation': row.get('generation', command.get('generation')),
            'writer_job': row.get('writer_job', command.get('writer_job')),
            'picture': row.get('picture', command.get('picture')),
            'poc': row.get('poc', command.get('poc')),
        }
        missing = [key for key in IDENTITY if ident.get(key) is None]
        if missing:
            raise AdapterError('stale identity: missing ' + ','.join(missing))
        if ident['run'] != run or ident['context'] != context:
            raise AdapterError('stale identity')
        return ident
