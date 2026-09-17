#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Hash-check pinned sources, apply existing patches to a private copy, extract C."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import urllib.request

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
AVD = 'drivers/media/platform/apple/avd/'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def function(source, name):
    match = re.search(r'^(?:static )?(?:inline )?(?:void|int|u32|unsigned int)\s+' +
                      re.escape(name) + r'\([^;]*?\)\s*\{', source, re.M)
    if not match:
        raise ValueError('function not found: ' + name)
    end = match.end()
    depth = 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[match.start():end]


def prepare(root, cache=None):
    root.mkdir(exist_ok=False)
    pins = json.loads((HERE / 'source-map.json').read_text())
    def fetch(item):
        name, expected = item
        data = (cache / name).read_bytes() if cache else urllib.request.urlopen(
            f'https://raw.githubusercontent.com/AsahiLinux/linux/{pins["kernel_revision"]}/{name}',
            timeout=30).read(2 * 1024 * 1024)
        if digest(data) != expected:
            raise ValueError('source hash mismatch: ' + name)
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(fetch, pins['files'].items()))
    patches = json.loads((REPO / 'experiments/hevc-avd-trace/sources.json').read_text())['patches']
    contents = []
    for item in patches['files']:
        path = REPO / item['path']
        data = path.read_bytes()
        if digest(data) != item['sha256']:
            raise ValueError('patch changed: ' + str(path))
        contents.append(data)
    if digest(b''.join(contents)) != pins['patches_concatenated_sha256']:
        raise ValueError('patch stack identity mismatch')
    patched = root / 'patched'
    shutil.copytree(root / AVD, patched)
    for item in patches['files']:
        subprocess.run(['patch', '--batch', '--fuzz=0', '-p6', '-i', str(REPO / item['path'])],
                       cwd=patched, check=True, stdout=subprocess.PIPE, timeout=30)
    return root


def extract(root, destination, mutate=False):
    drv = (root / 'patched/avd-drv.c').read_text()
    hevc = (root / 'patched/avd-hevc.c').read_text()
    v4l2 = (root / 'patched/avd-v4l2.c').read_text()
    common = (root / 'drivers/media/v4l2-core/v4l2-common.c').read_text()
    if mutate:
        old = 'comp->offsets[2] = y + y_meta + uv;'
        if drv.count(old) != 1:
            raise ValueError('mutation target drift')
        drv = drv.replace(old, 'comp->offsets[2] = y + y_meta + uv + 16;')
    chunks = []
    for name in ('v4l2_format_block_width', 'v4l2_format_block_height',
                 'v4l2_format_plane_stride', 'v4l2_format_plane_height',
                 'v4l2_format_plane_size', 'v4l2_fill_pixfmt_mp'):
        chunks.append(function(common, name))
    for text, names in ((drv, ('calc_tile_meta', 'fill_comp')),
                        (hevc, ('mv_color_size', 'avd_hevc_adjust_decoded_fmt')),
                        (v4l2, ('avd_fill_decoded_pixfmt',))):
        chunks.extend(function(text, name) for name in names)
    rows = []
    for fmt in ('NV12', 'P010'):
        rows.append(next(line.strip() for line in common.splitlines()
                         if '.format = V4L2_PIX_FMT_' + fmt + ',' in line))
    tables = 'static const struct v4l2_format_info formats[] = {\n' + '\n'.join(rows) + '\n};\n'
    tables += '''static const struct v4l2_format_info *v4l2_format_info(u32 format) {
    for (unsigned i = 0; i < 2; ++i) if (formats[i].format == format) return &formats[i];
    return NULL;
}
'''
    placement = re.search(r'run->addresses\.mv_color = [^;]+;', hevc).group(0)
    tail = '''static uint64_t place_mv(u32 dst_len, u32 mv_color_len) {
    struct { struct { uint64_t y_out; } base; struct { uint64_t mv_color; } addresses; } storage = {0}, *run = &storage;
    ''' + placement + '\n    return run->addresses.mv_color;\n}\n'
    output = '/* Actual pinned kernel function bodies; see source-map.json and extraction.json. */\n'
    output += drv[:drv.index('#include')] + common[:common.index('#include')]
    output += tables + '\n\n'.join(chunks) + '\n' + tail
    destination.write_text(output)
    report = {'generated_sha256': digest(output.encode()), 'mutation': mutate,
              'functions_sha256': [digest(c.encode()) for c in chunks],
              'mv_expression': placement,
              'patched_avd': {p.name: digest(p.read_bytes()) for p in sorted((root/'patched').glob('*')) if p.is_file()}}
    destination.with_suffix('.json').write_text(json.dumps(report, indent=2)+'\n')
    return report
