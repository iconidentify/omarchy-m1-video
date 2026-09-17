"""Pinned-source access for the AVD allocation-retry candidate.

Reuses the verified preparation from experiments/hevc-reference-memory without
copying or modifying it: the same pinned revision, the same source hashes and
the same shipped-patch identity check.  Nothing here re-implements extraction.
"""

import importlib.util
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent.parent
REFERENCE = REPO / 'experiments/hevc-reference-memory'


def _load_reference():
    """Load the #77 module by path under its own name.

    It is also called source.py, so a plain import would find this file.
    """
    spec = importlib.util.spec_from_file_location(
        'hevc_reference_memory_source', REFERENCE / 'source.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


pinned = _load_reference()

AVD = pinned.AVD
digest = pinned.digest
function = pinned.function


def prepare(root, cache=None):
    """Fetch, hash-verify and shipped-patch the pinned AVD sources."""
    return pinned.prepare(root, cache=cache)


def patch(tree, patch_path, destination):
    """Copy the shipped-patched sources and apply one candidate patch."""
    import shutil
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(tree / 'patched', destination)
    subprocess.run(['patch', '--batch', '--fuzz=0', '-p6', '-i', str(patch_path)],
                   cwd=destination, check=True, stdout=subprocess.PIPE, timeout=30)
    return destination


def struct(source, name):
    """Extract an actual struct definition verbatim."""
    opening = 'struct %s {' % name
    start = source.index(opening)
    end = source.index('\n};', start) + len('\n};')
    return source[start:end]
