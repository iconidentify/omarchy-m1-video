#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Rehouse external inventory inputs; produce candidates, never approve or run."""
import argparse
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE.parent / 'deployment'))
import manifest
import admission

EXTRA_SOURCES = (
    'experiments/hevc-reference-content/deployment/manifest.py',
    'experiments/hevc-reference-content/deployment/admission.py',
    'experiments/hevc-reference-content/deployment/build.py',
    'experiments/hevc-reference-content/campaign/controller.py',
    'experiments/hevc-reference-content/live-campaign/run.py',
    'experiments/hevc-reference-content/live-campaign/prepare.py',
)


def note_id(raw):
    found = []
    offset = 0
    while offset < len(raw):
        manifest.need(offset + 12 <= len(raw), 'short ELF note')
        namesz, descsz, kind = struct.unpack_from('<III', raw, offset)
        name = offset + 12
        desc = name + ((namesz + 3) & ~3)
        end = desc + ((descsz + 3) & ~3)
        manifest.need(end <= len(raw), 'ELF note extent')
        if kind == 3 and raw[name:name + namesz] == b'GNU\0':
            manifest.need(descsz in (16, 20, 32), 'ELF build-ID extent')
            found.append(raw[desc:desc + descsz].hex())
        offset = end
    manifest.need(len(found) == 1, 'missing/ambiguous ELF build-ID')
    return found[0]


def copy_record(row, destination):
    source = Path(row['path'])
    manifest.need(manifest.digest(source) == row['sha256'], 'input drift before rehouse')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open('rb') as src, destination.open('xb') as dst:
        shutil.copyfileobj(src, dst)
    manifest.need(manifest.digest(destination) == row['sha256'], 'rehouse changed bytes')
    return row | {'path': str(destination)}


def rehouse_external_artifacts(document, destination, build_root):
    for name, row in document['artifacts'].items():
        path = Path(row['path'])
        if not path.is_relative_to(build_root) and not path.is_relative_to('/usr'):
            document['artifacts'][name] = copy_record(
                row, destination / 'artifacts' / (name + '-' + path.name))


def prepare(path):
    _, document = manifest.read_document(path)
    manifest.need(document['state'] == 'candidate', 'not a candidate')
    manifest.validate(document | {'state': 'reviewed'}, root_owned=False)
    need_clean = subprocess.check_output(['git', 'status', '--porcelain'], cwd=REPO)
    manifest.need(not need_clean.strip(), 'campaign sources must be committed and clean')
    stage = path.parent
    # Runtime search paths were linked at this final location. Do not relocate ELF files.
    manifest.need(stage.is_relative_to('/var/lib') and stage.name == 'stage',
                  'build at the final /var/lib stage first')
    destination = stage / 'campaign-inputs'
    destination.mkdir(mode=0o755, exist_ok=False)
    for index, row in enumerate(document['patches']):
        document['patches'][index] = copy_record(row, destination / 'patches' /
                                               f'{index:02d}-{Path(row["path"]).name}')
    for vector, row in document['corpus'].items():
        document['corpus'][vector] = copy_record(row, destination / f'{vector}.hevc')
    document['reference'] = copy_record(document['reference'], destination / 'reference-provenance.json')
    # hwguard's source provenance lookup requires its real Meson repository layout.
    # Keep the byte-identical pinned source, not a standalone copy with invented metadata.
    guard = stage.parent / ('va-source/libva-v4l2_request-' +
                            document['sources']['va_driver']['revision']) / 'tests/hwguard.py'
    manifest.need(manifest.digest(guard) == document['artifacts']['hwguard']['sha256'],
                  'guard source differs from staged guard')
    document['artifacts']['hwguard'] = manifest.file_record(guard)
    rehouse_external_artifacts(document, destination, stage.parent)
    artifacts = {name: Path(row['path']) for name, row in document['artifacts'].items()}
    document['commands'] = admission._builder_module().command_matrix(
        artifacts, document['corpus'], document['targets'])
    extra = {}
    tool_root = artifacts['same_run_supervisor'].parents[3]
    # This leaf permits immutable root-owned oracle/UAPI inputs in the reader;
    # private capture ownership remains unchanged. Record the exact staged delta.
    relative = 'experiments/hevc-reference-content/same-run/validator.py'
    shutil.copyfile(REPO / relative, tool_root / relative)
    document['runtime_sources'][relative] = manifest.file_record(tool_root / relative)
    document['repo'] = {'commit': subprocess.check_output(
        ['git', 'rev-parse', 'HEAD'], cwd=REPO, text=True).strip(), 'dirty': False}
    for relative in EXTRA_SOURCES:
        target = tool_root / relative
        extra[relative] = copy_record(manifest.file_record(REPO / relative), target)
    for vector in 'BE':
        for client in ('va', 'gst'):
            relative = f'experiments/hevc-avd-trace/captures/2026-09-17-schema2/frames/{vector}-{client}-off.json'
            extra[relative] = copy_record(manifest.file_record(REPO / relative), destination / f'{vector}-{client}-prior.json')
    native = {
        'kernel_source': document['sources']['kernel']['revision'],
        'avd_patchset': '029f57377a00f3584678f80a8011d8ba7a17c83f1708d9a429d3c91dbb2d0390',
        'kernel': note_id(Path('/sys/kernel/notes').read_bytes()),
        **{name: row['build_id'] for name, row in document['kernel']['modules'].items()},
        'va': document['artifacts']['va_driver']['build_id'],
        'gst': document['artifacts']['gst_plugin']['build_id'],
    }
    native_path = destination / 'native-approved-builds.candidate'
    native_path.write_text(''.join(f'{key} {value}\n' for key, value in native.items()))
    manifest.validate(document | {'state': 'reviewed'}, root_owned=False)
    output = destination / 'manifest.candidate.json'
    output.write_bytes(admission.canonical(document))
    inventory = {'source_candidate_sha256': manifest.digest(path),
                 'candidate': manifest.file_record(output),
                 'native_approval': manifest.file_record(native_path), 'extra_sources': extra,
                 'execution_authorized': False}
    inventory_path = destination / 'preparation.json'
    inventory_path.write_bytes(admission.canonical(inventory))
    print(json.dumps({'preparation': str(inventory_path), 'sha256': manifest.digest(inventory_path),
                      'candidate_sha256': manifest.digest(output), 'execution_authorized': False}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('candidate', type=Path)
    args = parser.parse_args()
    prepare(args.candidate.absolute())
