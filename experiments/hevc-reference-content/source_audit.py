#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Static inspection of exact pinned function strings. No C execution or API hook."""
import hashlib
import json
from pathlib import Path
from adapter import AdapterError

HERE = Path(__file__).resolve().parent

def inspect_sources(bodies):
    expected = json.loads((HERE/'function-hashes.json').read_text())
    actual = {name:hashlib.sha256(body.encode()).hexdigest() for name,body in bodies.items()}
    if actual != expected:
        raise ValueError('extracted function identity mismatch')
    return {
        'kind':'static-source-inspection', 'functions':actual,
        'c_functions_executed':False, 'client_instrumentation':False,
        'real_adapter_implemented':False, 'copy_authorized':False,
        'avd_completion_scope':'upstream base only; not shipped-patched code',
        'gstreamer_scope':'not audited; accepted v4l2slh265dec uses direct V4L2',
        'observations':[
            'VA surface readiness waits for a selected capture; this observer has no retained all-producer barrier.',
            'Exported storage lifetime alone does not establish a stable client writer generation.',
            'Pinned vb2-dma-contig CPU-access callbacks return without cache maintenance.',
            'A source audit or historical capture cannot supply a live retained writer identity.',
        ],
    }

def reject_historical_identity(records):
    # Even plausible, complete labels are not a live retention/completion receipt.
    raise AdapterError('blocked: historical or asserted identity is not live ownership')
