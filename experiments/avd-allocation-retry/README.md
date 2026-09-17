# AVD allocation failure followed by a smaller retry

**AI disclosure:** produced by Claude (Anthropic) acting as an agent for
@tankbottoms under the shared workflow in
[libva-v4l2_request#8](https://github.com/iconidentify/libva-v4l2_request/issues/8).
Independent work, not maintainer approval.

Offline candidate for [#81](https://github.com/iconidentify/omarchy-m1-video/issues/81),
building on the allocator finding in
[#77](https://github.com/iconidentify/omarchy-m1-video/issues/77) / PR78.

No device, no module load, no installation, no reboot, no shipped-patch change.
Counts and evidence files elsewhere in the repository are unchanged.

## What is wrong

`avd_buf_alloc()` in `avd-drv.c` can return success with `buf->cpu == NULL`.
The reuse fast path tests `!buf->cpu`, so it is taken only when there is no
allocation, and `buf->size` is assigned before `dma_alloc_coherent()` is
attempted. A request that fails at 4096 leaves `size = 4096, cpu = NULL`; a
following request for 2048 then satisfies `(!buf->cpu && size < buf->size)` and
returns 0 having allocated nothing.

Because the same inverted condition means reuse never occurs, the pinned tree
also reallocates on every repeat call — so the fix must not quietly turn reuse
on for the first time.

A second defect falls out of the audit: `avd_{hevc,h264,vp9}_start()` release
the private context with a bare `kfree()` on failure, so any buffer
`avd_*_alloc_bufs()` already obtained is leaked. See [AUDIT.md](AUDIT.md).

## Reproduce

Linux or macOS, Python 3, a C compiler, `patch`, and network access to the
public pinned kernel sources:

```
python3 experiments/avd-allocation-retry/tests.py
```

Optionally `AVD_SANITIZE=1` to build the harness with ASan and UBSan, and
`AVD_SOURCE_CACHE=<dir>` to supply the pinned sources from a local mirror
instead of fetching them.

The runner reuses `experiments/hevc-reference-memory/source.py` unchanged: the
same pinned revision, the same per-file hashes, and the same shipped-patch
identity check. It then builds three variants — pinned, `candidate.patch`,
`alternative-reuse.patch` — extracts `avd_buf_alloc()`, `avd_buf_free()` and
`struct avd_buf` **verbatim** from each, and compiles them against
`harness.c`. Allocator bodies under test are mechanically extracted; their DMA environment is synthetic.

`harness.c` is a userspace program, not a kernel module. It supplies a coherent
DMA stand-in with deterministic fault injection by call index, full
allocation/free accounting, and size/address checks on every free. Allocations
are poisoned with `0xA5` rather than zeroed, so no test can silently rely on
fresh memory being blank.

The additive `avd-allocation-retry.yml` hosted workflow runs the sanitizer suite.
It fetches public hash-pinned source files, without a device or privileged execution.
Existing `hevc-reference-memory.yml` already uses the same source-fetch approach.

## What the tests cover

36 test groups, including executed caller lifecycles:

- **PinnedDefect** (5) — the defect in the actual pinned function: stale size
  after failure, a smaller retry reported as success with no allocation, a
  caller that trusts the return value reaching NULL, equal/larger retries
  unaffected, and the proof that reuse never happens in the pinned tree.
- **Candidate** (9) — failure leaves nothing behind, the retry really
  allocates, a retry that also fails still reports failure, success is never
  reported without storage across every failure pattern, zero size is rejected
  without allocating, zero size after success still releases, alloc/free
  balance, idempotent free, and byte-for-byte identical accounting to the
  pinned tree on every success path.
- **AlternativeReuse** (4) — the reuse variant reuses on smaller and equal,
  reallocates on larger, fixes the same defect, and measurably changes
  behaviour, which is why it is not the candidate.
- **Mutations** (5) — undoing the repair must be caught. Each half of the fix is
  independently sufficient, so only undoing **both** reintroduces the defect;
  dropping the recorded size is caught by the free-size check.
- **CallerAudit** (8) — over the extracted text: the pinned start paths never
  reach `stop()`, the candidate ones do, every `stop()` frees every buffer its
  `alloc_bufs()` can take, every `stop()` tolerates a NULL context, the pinned
  `avd_vp9_stop()` alone lacks that check, removing the unwind fails the audit,
  the 47 call sites match `caller-audit.json`, and the repeat-call sites are the
  per-frame scratch paths.
- **Identity** (4) — the patches touch only the AVD directory and no shipped
  patch is modified.

## Results and limits

Both patches apply to the shipped-patched pinned tree with `-p6 --fuzz=0`.

| | pinned | candidate | alternative |
| --- | --- | --- | --- |
| failed 4096, then 2048 | **returns 0, `cpu` NULL** | returns 0, allocated | returns 0, allocated |
| size left after failure | 4096 | 0 | 0 |
| 4096 ok, then 2048 | free + realloc | free + realloc | reuse, 1 allocation |
| start-path failure | scratch leaked | unwound via `stop()` | unwound via `stop()` |

Not established: whether either failure has been observed on hardware; whether
the firmware faults on a zero DMA address; anything about `avd-av1.c`. Both
paths are reached only under allocation failure, which this experiment injects.
The maintainer subsequently completed a warning-free native ARM64 module build
against existing matching 7.1.13-3-1-ARCH headers with `KCFLAGS=-Werror`.
[Build evidence](build-evidence.json) records all source/patch/header/compiler/log
and output identities. Nothing was loaded or installed. This qualifies compilation,
not runtime behavior or the RPS_E corruption cause.

```sh
python3 experiments/avd-allocation-retry/build.py /tmp/avd-allocation-build \
  --headers /path/to/matching/arm64/kernel/build
```

The destination must be new; `--source-cache` is optional. `patch-identities.json`
locks both candidate/alternative files. Only the behavior-preserving candidate is
built. Keep the resulting module isolated: loading requires a separately reviewed
finite guarded plan, fresh health checks, exact build identity and restoration.
Do not replace a shipped patch or combine it with withdrawn recorder candidates.

## Executed caller cleanup regression

`lifecycle.py` additionally extracts actual `alloc_bufs`, `start`, `stop` and allocator
bodies for HEVC/H.264/VP9. It executes every allocation-failure index (2/7/12), context
allocation failure and success/stop under ASan/UBSan. Original start paths leak after
partial allocation; candidate paths balance all allocations. Replacing each actual
start cleanup with its old bare `kfree` makes the same no-leak oracle fail.
Mock allocations are reclaimed only after recording the expected baseline/mutant
leak, so those negative fixtures do not intentionally leak the test process.

The codec context layout, dimensions, SPS validation and VP9 table initialization
are explicit synthetic stand-ins. This tests actual unwind control flow, not those
codec algorithms or kernel ABI; the complete module build covers compilation.
The 35 original contributor tests remain, with success checks strengthened to require
exit zero rather than merely excluding the special NULL-storage exit code.
