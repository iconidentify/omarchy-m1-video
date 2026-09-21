"""Exercise the actual adapted wrapper and Clang diagnostic verifier on Linux."""
import shutil
import subprocess
import sys

from prepare_test_build import adapted, prepare, TARGET


def check(cache, work):
    compiler = shutil.which('clang++')
    if not compiler:
        raise RuntimeError('Clang is required for nocompile diagnostic checks')
    source = work / 'diagnostic-wrapper'
    wrapper = source / TARGET
    wrapper.parent.mkdir(parents=True)
    original = (cache / TARGET).read_bytes()
    wrapper.write_bytes(original)
    prepare(source)
    assert wrapper.read_bytes() == original
    prepare(source, True)
    for data in [original + b'\n', wrapper.read_bytes()]:
        try:
            adapted(data)
        except ValueError:
            pass
        else:
            raise AssertionError('Modified wrapper accepted')
    # Only the Windows --generate-depfile branch uses this import. Linux
    # verification below executes the real wrapper and compiler, with no
    # substitute for argument filtering, diagnostics or exit-status handling.
    (source / 'build').mkdir()
    (source / 'build/action_helpers.py').write_text(
        'def write_depfile(*args, **kwargs):\n'
        '    raise AssertionError("Windows depfile shim unexpectedly called")\n')
    input_path = source / 'diagnostic.nc'
    output = source / 'placeholder.o'
    command = [sys.executable, str(wrapper), compiler, str(input_path),
               str(output), str(source / 'placeholder.d'), '--',
               '-w', '-Wno-stringop-overread', '-Wno-unused-but-set-global',
               '-Xclang', '-fsyntax-only', '-Xclang', '-verify', '-Werror', '-x', 'c++']
    rows = [
        ('expected-warning', '#warning required_warning // expected-error {{required_warning}}\n', [], 0, ''),
        ('missing-warning', '// expected-error {{missing_warning_sentinel}}\n', [], 1,
         'diagnostics expected but not seen'),
        ('unexpected-warning', '// expected-no-diagnostics\n#warning unexpected_warning_sentinel\n', [], 1,
         'diagnostics seen but not expected'),
        ('unknown-option', '// expected-no-diagnostics\n', ['-Wunknown-sentinel-option'], 1,
         'unknown warning option'),
    ]
    for name, text, extra, expected, diagnostic in rows:
        input_path.write_text(text)
        result = subprocess.run(command + extra, text=True, capture_output=True, timeout=30)
        assert result.returncode == expected and diagnostic in result.stderr, (
            name, result.returncode, result.stdout, result.stderr)
        assert output.exists() == (expected == 0), name
        if output.exists():
            output.unlink()
        print('PASS: actual nocompile wrapper ' + name, flush=True)
