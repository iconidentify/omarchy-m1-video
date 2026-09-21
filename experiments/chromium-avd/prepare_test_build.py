#!/usr/bin/env python3
"""Restore diagnostic verification for the pinned private Clang test build."""
import argparse
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
TARGET = 'tools/nocompile/wrapper.py'


def adapted(original):
    pin = next(row for row in json.loads((HERE / 'sources.json').read_text())
               if row['path'] == TARGET)
    if hashlib.sha256(original).hexdigest() != pin['sha256']:
        raise ValueError('Not the pinned nocompile wrapper')
    before = '  compiler_args += args.compiler_options\n'
    after = '''  # The Arch recipe suppresses all warnings and carries two warning
  # switches unknown to its Clang 22. Diagnostic tests must see real warnings.
  # Keep -verify, -Werror and every expected diagnostic unchanged.
  compiler_args += [
    flag for flag in args.compiler_options
    if flag not in ('-w', '-Wno-stringop-overread', '-Wno-unused-but-set-global')
  ]
'''
    text = original.decode()
    if text.count(before) != 1:
        raise ValueError('Missing or ambiguous compiler-options anchor')
    return text.replace(before, after)


def prepare(source, apply=False):
    source = source.resolve(strict=True)
    target = source / TARGET
    if target.resolve() != target:
        raise ValueError('Symlinked nocompile wrapper')
    result = adapted(target.read_bytes())
    if apply:
        target.write_text(result)
    print('Prepared test-only compiler flags; browser compilation is unchanged.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    prepare(args.source, args.apply)
