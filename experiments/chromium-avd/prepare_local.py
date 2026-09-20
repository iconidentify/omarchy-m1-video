#!/usr/bin/env python3
"""Adapt the pinned recipe to this explicitly selected private native tool tree."""
import argparse
import json
from pathlib import Path
import shlex

from prepare_recipe import recipe


def replace_once(text, before, after):
    if text.count(before) != 1:
        raise ValueError('Missing or ambiguous local recipe anchor: ' + before)
    return text.replace(before, after)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--tools', type=Path, required=True)
    parser.add_argument('--rust-sysroot', type=Path, required=True)
    args = parser.parse_args()
    prefix = args.tools.resolve(strict=True)
    rust = args.rust_sysroot.resolve(strict=True)
    for name in ['gn', 'clang', 'clang++', 'ld.lld', 'gperf', 'bindgen', 'rustfmt', 'node', 'go', 'tsc']:
        if not (prefix / 'bin' / name).is_file():
            raise ValueError('Missing private tool: ' + name)
    if not (prefix / 'lib/libclang.so').is_file():
        raise ValueError('Missing matching libclang in private tool prefix')
    data = recipe(args.original.read_bytes())
    for name in ['node', 'go', 'gperf']:
        data = replace_once(data, '/usr/bin/' + name, shlex.quote(str(prefix / 'bin' / name)))
    for key, path in [('clang_base_path', prefix), ('rust_bindgen_root', prefix),
                      ('rust_sysroot_absolute', rust)]:
        data = replace_once(data, shlex.quote(key + '="/usr"'),
                            shlex.quote(key + '=' + json.dumps(str(path))))
    data = replace_once(data, "'is_component_build=false'", "'is_component_build=true'")
    data = replace_once(data, "'use_gold=false'", "'use_mold=false'\n    'use_lld=true'")
    data = replace_once(data, "'symbol_level=0'", "'symbol_level=0'\n    'blink_symbol_level=0'\n    'v8_symbol_level=0'\n    'use_thin_lto=false'")
    # Native test/browser targets remain available; build the browser first.
    data = replace_once(data,
                        'ninja -j1 -C out/Release chrome chrome_sandbox chromedriver.unstripped content_unittests',
                        'if [[ ${CHROMIUM_AVD_CONFIGURE_ONLY:-0} != 1 ]]; then\n'
                        '    ninja -j1 -C out/Release chrome chrome_sandbox\n'
                        '  fi')
    # The pinned distribution patch uses /usr/bin/tsc; redirect that one source
    # location into the private tool prefix, retaining the rest of its behavior.
    anchor = '  patch -Np1 -i ../chromium-153-typescript.patch'
    script = ('from pathlib import Path; p = Path("third_party/devtools-frontend/src/third_party/typescript/typescript.py"); '
              's = p.read_text(); old = "\\\"/usr/bin/tsc\\\""; '
              'assert s.count(old) == 1; p.write_text(s.replace(old, ' +
              repr(json.dumps(str(prefix / 'bin/tsc'))) + '))')
    data = replace_once(data, anchor, anchor + '\n  python3 -c ' + shlex.quote(script))
    with args.output.open('x') as output:
        output.write(data)
    print('Prepared private-tool component-build recipe; no build or install performed.')


if __name__ == '__main__':
    main()
