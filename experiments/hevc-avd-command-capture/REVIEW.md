# Maintainer adversarial self-review

AI-generated; this is not independent specialist approval.

## Confirmed defect and correction

The first attempted capture loaded the reviewed #70 module, but the reference
recorder was missing. No decoder was forked. Restoration hit a kernel Oops because
the generated initializer removed the reference debugfs tree unconditionally after
successful platform registration; unloading removed the same freed tree again.
The broad text replacement in prepare.py changed an unbraced conditional's meaning.
This review miss belongs to the maintainer as well as the original generator.

The correction matches the full conditional, adds braces around both cleanup
calls, and matches normal exit separately. Source drift fails preparation. Tests
extract and compile the actual generated module init/exit bodies, exercising
success, registration failure and eight repeated lifecycles. Reintroducing the
exact observed bad conditional fails. Existing tests still compare actual pinned
C packing, command hook interiors, poisoned native padding and reader lifetime.
The corrected matching ARM64 build is warning-free and has not been loaded.

## Supervisor and comparison

Twenty offline tests use real child processes with fake recorder backends. They
cover actual exit status, dual-arm-before-exec, partial arm, sticky/late errors,
deadline termination/reaping, cancellation, failed reads, disk-full persistence,
existing sealed evidence, paired identity mismatch, parent death, every named
copied-field mutation, missing/misbound history and unknown flags. Incident tests
reject false restored/success evidence; faulted/unloading state tests prohibit
another module operation. The complete source tests catch the original lifecycle
mutation, five actual command-source mutations and removal of the reader guard.
Required Bash syntax, rebuild and installer mocks also pass.

The same-run measurement path invokes accepted request/lifecycle validators and
the accepted reference-history checker with same-run ioctl refs. Packing comes
from a hash-verified primary C build. Historical controls only exercise the
conversion contract. Missing values are never filled from an earlier run.

## Limits and remaining work

The campaign completed zero decoder workloads. Hardware and output results for
the corrected candidate remain entirely unmeasured. The original installed module
is intact, but the failed unload left this boot without a usable video device.
No second unload/load, decoder replay, installation or reboot occurred within the
attempt. The fixed journal boundary remains unchanged, and the hardware guard
blocks future runs on the Oops. A clean boot, fresh machine/module checks and a
new bounded attempt are required before #71 can be completed. The recorded old
campaign config and single-use marker must not be reused.

The outer guard returned child-error; its fast final idle observation was not a
proof of health. The report retains the kernel Oops and incomplete restoration.
The corrected controller always records terminal state and rejects non-live
module state. No firmware-cause claim, codec gain, stability, boot, concurrency
or release qualification follows from this work.
