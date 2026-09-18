# Integration design/code review

AI disclosure: implementation, this record and the separate review were produced
by Codex agents. This is not independent human specialist approval.

On 2026-09-18, a separate reviewer examined the lifetime/allocation design before
copy implementation and the resulting actual adapter code. The shared workflow's
request for separate lifetime/reference review was the basis for that review.

Findings incorporated:

- Move executable identity out of the caller's writable pool into private per-object
  state initialized once before a lease. Avoid dynamic-loader locking while paused.
- Snapshot lock acquisition must not add another two-second window to the original
  begin deadline; use immediate trylocks and the retained absolute deadline.
- Preserve a failed mapping pointer/length in the native context. End retries unmap
  and refuses to release ownership while it fails; a new snapshot cannot overwrite it.
- Require HEVC on the VA codec and negotiated output format.
- Retain exact normalized identity, bounded pre/post-checked build/device provenance
  and absolute monotonic timestamps, rather than only a boolean attestation.
- Reject `builtin` module markers: absence of a sysfs build-ID note does not distinguish
  a built-in component from a loaded module compiled without notes.

The reviewer found no additional ordinary snapshot identity/range defect in the
revised copy/gate code. Final review of native cleanup and test design found no additional blocker for
the scoped offline draft: failed end preserves the lease/pins/cancellation state,
and successful end clears the mapping before release. The implementer executed
the suites recorded in [VALIDATION.md](VALIDATION.md); the separate reviewer read
the test source rather than independently reproducing those runs. External client/dependency/corpus identity and actual same-run kernel
command/reference integration remain outside the runtime verifier's coverage;
they are explicitly required before a live campaign. No hardware evidence or
coherence qualification is inferred from the model tests.
