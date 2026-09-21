#!/usr/bin/env python3
"""Add a default-off BT.709 EGL import experiment to the pinned Chromium tree."""
import argparse
import hashlib
import json
from pathlib import Path

from prepare_source import VERSION

HERE = Path(__file__).resolve().parent
TARGET = 'ui/ozone/common/native_pixmap_egl_binding.cc'


def adapted(original):
    pin = next(row for row in json.loads((HERE / 'sources.json').read_text())
               if row['path'] == TARGET)
    if hashlib.sha256(original).hexdigest() != pin['sha256']:
        raise ValueError('Not the pinned original EGL import source')
    text = original.decode()
    replacements = [
        ('#include "base/logging.h"',
         '#include "base/feature_list.h"\n#include "base/logging.h"'),
        ('namespace {\n', '''namespace {

// Opt-in experiment for the measured Wayland NV12 path. Other overlay,
// format and range combinations require separate runtime qualification.
BASE_FEATURE(kVaapiBt709EglImport, base::FEATURE_DISABLED_BY_DEFAULT);
'''),
        ('''    switch (color_space.GetMatrixID()) {
      case gfx::ColorSpace::MatrixID::BT2020_NCL:''',
         '''    switch (color_space.GetMatrixID()) {
      case gfx::ColorSpace::MatrixID::BT709:
        attrs.push_back(base::FeatureList::IsEnabled(kVaapiBt709EglImport)
                            ? EGL_ITU_REC709_EXT
                            : EGL_ITU_REC601_EXT);
        break;
      case gfx::ColorSpace::MatrixID::BT2020_NCL:'''),
        ('    // TODO(b/233667677): Since https://crrev.com/c/3855381, the only NV12',
         '''    // The following describes the historical default. The opt-in BT.709
    // branch below corrects the sampled Wayland compositing matrix without
    // changing the range, plane layout or the direct-overlay implementation.
    // TODO(b/233667677): Since https://crrev.com/c/3855381, the only NV12'''),
    ]
    for before, after in replacements:
        if text.count(before) != 1:
            raise ValueError('Missing or ambiguous color-import source anchor')
        text = text.replace(before, after)
    return text


def prepare(source, apply=False):
    source = source.resolve(strict=True)
    if (source / 'chrome/VERSION').read_text() != VERSION:
        raise ValueError('Expected exactly Chromium 153.0.8010.36')
    target = source / TARGET
    if target.resolve() != target:
        raise ValueError('Symlinked EGL import source')
    result = adapted(target.read_bytes())
    if apply:
        target.write_text(result)
    print('Validated opt-in BT.709 EGL import; no build, install or browser launch.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    prepare(args.source, args.apply)
