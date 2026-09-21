"""Compile the applied matrix/range switches; no EGL calls or devices."""
import os
import re
import subprocess

from prepare_color import adapted, prepare, TARGET
from prepare_source import VERSION


def check(cache, work):
    source = work / 'color-import'
    target = source / TARGET
    target.parent.mkdir(parents=True)
    (source / 'chrome').mkdir()
    version = source / 'chrome/VERSION'
    version.write_text(VERSION)
    original = (cache / TARGET).read_bytes()
    target.write_bytes(original)
    prepare(source)
    assert target.read_bytes() == original
    version.write_text(VERSION + '# wrong version\n')
    try:
        prepare(source, True)
    except ValueError:
        assert target.read_bytes() == original
    else:
        raise AssertionError('Wrong Chromium version accepted')
    version.write_text(VERSION)
    target.unlink()
    target.symlink_to(cache / TARGET)
    try:
        prepare(source, True)
    except ValueError:
        assert (cache / TARGET).read_bytes() == original
    else:
        raise AssertionError('Symlinked import source accepted')
    target.unlink()
    target.write_bytes(original)
    prepare(source, True)
    applied = target.read_text()
    for data in (original + b'\n', target.read_bytes()):
        try:
            adapted(data)
        except ValueError:
            pass
        else:
            raise AssertionError('Modified or reapplied import source accepted')
    assert applied.count('BASE_FEATURE(kVaapiBt709EglImport, base::FEATURE_DISABLED_BY_DEFAULT);') == 1
    start = applied.index('    attrs.push_back(EGL_YUV_COLOR_SPACE_HINT_EXT);')
    end = applied.index('\n  }\n\n  if (!plane_index_.has_value())', start)
    switches = applied[start:end]
    # The switch body, enum declarations and EGL numeric definitions come
    # from pinned sources. Only FeatureList state and ColorSpace accessors
    # are adapters. This does not test real EGL/FeatureList or GPU dispatch.
    colors = (cache / 'ui/gfx/color_space.h').read_text()
    enums = '\n'.join(re.search(r'enum class ' + name + r' : uint8_t \{.*?\n  \};',
                                colors, re.S).group() for name in ('MatrixID', 'RangeID'))
    egl = (cache / 'third_party/angle/include/EGL/eglext.h').read_text()
    constants = sorted(set(re.findall(r'\bEGL_[A-Z0-9_]+\b', switches)))
    definitions = '\n'.join(re.search(r'^#define ' + key + r'\s+0x[0-9A-Fa-f]+$',
                                       egl, re.M).group() for key in constants)
    preamble = '''#include <cstdint>
#include <vector>
#include <gtest/gtest.h>
using EGLint = int;
namespace base { inline bool enabled; struct FeatureList {
  static bool IsEnabled(int) { return enabled; }
}; }
[[maybe_unused]] constexpr int kVaapiBt709EglImport = 1;
namespace gfx { struct ColorSpace {
''' + enums + '''
  MatrixID matrix; RangeID range;
  MatrixID GetMatrixID() const { return matrix; }
  RangeID GetRangeID() const { return range; }
}; }
''' + definitions + '''
using M = gfx::ColorSpace::MatrixID;
using R = gfx::ColorSpace::RangeID;
std::vector<EGLint> Attributes(M matrix, R range, bool enabled) {
  base::enabled = enabled;
  gfx::ColorSpace color_space{matrix, range};
  std::vector<EGLint> attrs;
'''
    cases = '''
 return attrs;
}
TEST(EglBt709Import, DefaultRetainsBt601) {
 EXPECT_EQ(Attributes(M::BT709, R::LIMITED, false),
   (std::vector<int>{EGL_YUV_COLOR_SPACE_HINT_EXT, EGL_ITU_REC601_EXT,
                    EGL_SAMPLE_RANGE_HINT_EXT, EGL_YUV_NARROW_RANGE_EXT}));
}
TEST(EglBt709Import, OptInHonorsBt709) {
 EXPECT_EQ(Attributes(M::BT709, R::LIMITED, true),
   (std::vector<int>{EGL_YUV_COLOR_SPACE_HINT_EXT, EGL_ITU_REC709_EXT,
                    EGL_SAMPLE_RANGE_HINT_EXT, EGL_YUV_NARROW_RANGE_EXT}));
}
TEST(EglBt709Import, Bt2020Unchanged) {
 for (bool enabled : {false, true})
  EXPECT_EQ(Attributes(M::BT2020_NCL, R::LIMITED, enabled),
   (std::vector<int>{EGL_YUV_COLOR_SPACE_HINT_EXT, EGL_ITU_REC2020_EXT,
                    EGL_SAMPLE_RANGE_HINT_EXT, EGL_YUV_NARROW_RANGE_EXT}));
}
TEST(EglBt709Import, OtherMatricesUnchanged) {
 for (M matrix : {M::INVALID, M::RGB, M::FCC, M::BT470BG, M::SMPTE170M,
                  M::SMPTE240M, M::YCOCG, M::YDZDX, M::GBR})
  for (bool enabled : {false, true})
   EXPECT_EQ(Attributes(matrix, R::LIMITED, enabled)[1], EGL_ITU_REC601_EXT);
}
TEST(EglBt709Import, AllRangeDecisionsUnchanged) {
 for (M matrix : {M::BT709, M::BT2020_NCL, M::INVALID, M::SMPTE170M})
  for (bool enabled : {false, true}) {
   EXPECT_EQ(Attributes(matrix, R::FULL, enabled)[3], EGL_YUV_FULL_RANGE_EXT);
   for (R range : {R::INVALID, R::LIMITED, R::DERIVED})
    EXPECT_EQ(Attributes(matrix, range, enabled)[3], EGL_YUV_NARROW_RANGE_EXT);
  }
}
'''
    cpp = source / 'color-test.cc'
    binary = source / 'color-test'
    flags = [os.environ.get('CXX', 'c++'), '-std=c++20', '-O1', '-g',
             '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
             '-fno-sanitize-recover=undefined', '-fno-omit-frame-pointer',
             str(cpp), '-lgtest_main', '-lgtest', '-pthread', '-o', str(binary)]
    cpp.write_text(preamble + switches + cases)
    subprocess.run(flags, check=True, timeout=120)
    subprocess.run([str(binary)], check=True, timeout=30)
    mutations = [
        ('ignore709', '? EGL_ITU_REC709_EXT', '? EGL_ITU_REC601_EXT', 'OptInHonorsBt709'),
        ('always-on', 'base::FeatureList::IsEnabled(kVaapiBt709EglImport)', 'true', 'DefaultRetainsBt601'),
    ]
    for name, before, after, case in mutations:
        assert switches.count(before) == 1
        cpp.write_text(preamble + switches.replace(before, after) + cases)
        subprocess.run(flags, check=True, timeout=120)
        result = subprocess.run([str(binary), '--gtest_filter=EglBt709Import.' + case],
                                text=True, capture_output=True, timeout=30)
        assert result.returncode == 1 and '[  FAILED  ] EglBt709Import.' + case in result.stdout
        assert 'runtime error:' not in result.stderr and 'AddressSanitizer' not in result.stderr
        print('PASS: compiled import assertion detects ' + name, flush=True)
    print('PASS: pinned import adaptation/refusals, five color/range cases and two mutations.')
