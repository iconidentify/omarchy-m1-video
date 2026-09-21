#!/usr/bin/env python3
"""Write a pinned, non-installing experimental PKGBUILD; execute no recipe code."""
import argparse
import hashlib
import json
from pathlib import Path
import shlex

HERE = Path(__file__).resolve().parent


def recipe(original):
    pin = next(row for row in json.loads((HERE / 'sources.json').read_text())
               if row['path'] == 'arch-PKGBUILD')
    if hashlib.sha256(original).hexdigest() != pin['sha256']:
        raise ValueError('Not the pinned Arch Linux ARM PKGBUILD')
    data = original.decode()
    substitutions = [
        ('pkgname=chromium\n', 'pkgname=chromium-m1-avd-experiment\n'),
        ('#  - disable vaapi, enable v4l2', '#  - experimental M1: VA-API instead of native V4L2'),
        ('export MAKEFLAGS="-j16"', 'export MAKEFLAGS="-j1"'),
        ('export ALARM_NINJA_JOBS="16"', 'export ALARM_NINJA_JOBS="1"'),
        ("'use_vaapi=false'", "'use_vaapi=true'"),
        ("'use_v4l2_codec=true'", "'use_v4l2_codec=false'"),
        ("'is_official_build=true' # implies is_cfi=true on x86_64",
         "'is_official_build=false'\n    'is_debug=false'\n    'is_component_build=false'\n    'target_cpu=\"arm64\"'"),
        ('ninja -C out/Release chrome chrome_sandbox chromedriver.unstripped',
         'ninja -j1 -C out/Release chrome chrome_sandbox chromedriver.unstripped content_unittests'),
        ('build() {\n', 'build() {\n  export MAKEFLAGS="-j1"\n  export ALARM_NINJA_JOBS="1"\n'),
        ('\n}\n\nbuild() {',
         '\n  python3 ' + shlex.quote(str(HERE / 'prepare_source.py')) + ' "$PWD" --apply\n}\n\nbuild() {'),
    ]
    for old, new in substitutions:
        if data.count(old) != 1:
            raise ValueError('Recipe anchor is missing or ambiguous: ' + old)
        data = data.replace(old, new)
    # Do not copy the distribution's Google API key into this private test build.
    lines = data.splitlines(keepends=True)
    keys = [i for i, line in enumerate(lines) if line.startswith('_google_api_key=')]
    if len(keys) != 1:
        raise ValueError('Expected one API-key assignment')
    lines[keys[0]] = "_google_api_key=''\n"
    return ''.join(lines)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('original', type=Path)
    parser.add_argument('output', type=Path, help='new file; never overwrite an existing recipe')
    args = parser.parse_args()
    result = recipe(args.original.read_bytes())
    with args.output.open('x') as output:
        output.write(result)
    print('Prepared recipe only. No source download, build, package install or launch.')
