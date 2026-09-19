# FFmpeg VA call-site review record

- Ticket/session: #114 / parent #82,
  `codex-114-va-callsite-20260919T210207Z`.
- Base: `adfb9e5ec894f32cbf830e3f82fd9cc7f43bb597`.
- Reviewed candidate: the complete worktree diff before its first commit; the PR
  records the final tested remote head.
- External sources: FFmpeg n9.0.1
  `bf1b838f2ab88b4f8fd83443325c782ea0e0f7fa` and driver
  `c77e7b566f7baf9c7a2aad797e62c9aa578d9687`, both archive-hash pinned in
  [VALIDATION.md](VALIDATION.md).
- Reviewer: implementation agent, AI self-review using the repository's local
  adversarial protocol. No independent specialist, provenance or hardware
  review is claimed.
- Scope: additive default-off FFmpeg HEVC/VA patch, paired private ABI token,
  complete-source offline fixture and hosted job. No install, device, module,
  reboot, shipped kernel patch, raw-byte publication or support-row change.

| Stage | Evidence / disposition |
| --- | --- |
| 1 Intent | The patch stays in an additive experiment and changes no packaged FFmpeg or public libva ABI. Private options default off. |
| 2 Claims | Traced `vaapi_hevc_start_frame()` before first submission and `hevc_receive_frame()` from real FIFO dequeue through observation before publication. Result export is normalized metadata/digest only. |
| 3 Execution | Read the complete arm, bind, select, begin, snapshot, end, finish, result, flush and uninit paths plus FFmpeg decode/thread callers. Invalid display, origin, ABI, late arm, threading, owner, identity and cleanup failures execute. |
| 4 Resources | State owns the loaded-driver handle, pool and held frame. Every successful begin reaches native end; failed end retains receipt/frame for same-owner retry. Output errors unref the caller frame. Persistent end failure at uninit quarantines rather than destroys retained state. |
| 5 Concurrency | FFmpeg frame threading transfers non-thread-safe VA state between workers, conflicting with the observer's owner-thread contract: R1. Armed mode now requires one decoder thread and one application owner; both guards have behavioral tests and mutations. |
| 6 Trust/bounds | Real `VADisplayContextP` magic/context/vtable is validated. `dladdr` identifies the loaded backend and every private symbol must resolve to that same DSO base with the paired ABI token. Parser limits selections to eight distinct ordinals. |
| 7 Hardware | Driver identity/range checks are inherited and rerun, but all syscalls/content here are synthetic. DMA visibility, firmware behavior, live manifest and same-run kernel association remain external gates. |
| 8 Consolidate | Three introduced findings were fixed; owner-thread, result-state and uninit concerns share the native lease contract. Dismissals/limits are recorded below. |
| 9 Resolve conflicts | The initial assumption that VA serialization made frame threading safe was rejected after reading `pthread_frame.c`: state serialization does not preserve `pthread_t` ownership. |
| 10 Verify | Complete pinned FFmpeg is built under ASan/UBSan and TSan. Nineteen cases and ten semantic mutations cover the final patch; the complete real-driver VA integration suite is rerun separately. |
| 11 Report | Ready for scoped PR review after final-head CI. #82 and driver #42 remain open; this is not a live-use or support decision. |

## Concerns and dispositions

- **R1, confirmed and fixed, P0/high confidence, introduced here:** FFmpeg's
  HEVC decoder supports frame threading and VAAPI is async-safe but not marked
  thread-safe. `pthread_frame.c` transfers the single VA private context across
  worker contexts, while the driver observer requires open/select/begin/end on
  the opening `pthread_t`. The original patch could open in one worker and fail
  or strand the session in another. Arm now rejects any active frame/slice
  threading or thread count other than one before symbol binding/session open.
  A foreign application thread also fails before surface selection. The
  `threaded-reject` and `foreign-owner` cases pass under both sanitizers, and
  mutations of both gates fail their named assertions.
- **R2, confirmed and fixed, P1/high confidence, introduced here:** once FIFO
  dequeue filled the caller's `AVFrame`, the first patch returned observer or
  non-VA errors without unrefing it. FFmpeg's receive wrapper does not unref a
  decoder-produced frame merely because the callback returned an error. Both
  failure branches now unref before returning. The structural call-site check
  requires dequeue → observer → failed-frame cleanup → publication ordering.
- **R3, confirmed and fixed, P1/high confidence, introduced here:** after a
  successful explicit finish, a later output correctly failed because the
  observer was closed, but `result()` and repeated `finish()` ignored the new
  sticky failure and could still report the earlier observation as successful.
  Both APIs now reject that state. The `post-finish-output` case proves the
  decode error invalidates result and uninit status; the `failed-result`
  mutation must fail the result assertion specifically.
- **T1, hosted-test integration fixed:** the first Ubuntu/x86 job stopped in
  FFmpeg configure because NASM was absent. The selected observer path does not
  require x86 assembly; the hermetic runner now passes `--disable-x86asm` instead
  of adding an unrelated assembler dependency. That stopped configure supplied
  no execution evidence; the rerun is required at the new head.
- **D1, dismissed:** symbol lookup could accidentally bind libva or another
  driver's global symbol. The handle is `RTLD_NOLOAD` on the DSO containing the
  real backend vtable entry, and each resolved symbol's `dli_fbase` must equal
  that origin. Wrong-origin and ABI cases execute before open.
- **D2, dismissed within the stated caller contract:** a failed native end could
  release or lose the selected allocation. Output retains its own exact-frame
  reference and receipt while active; finish/flush retry end on the same owner.
  Uninit refuses VA context destruction while the lease remains active. Because
  FFmpeg's generic close API cannot report hardware-uninit failure, the client
  must complete the explicit retry before `avcodec_free_context()`; a persistent
  failure reaching close is documented as fatal quarantine, not recovery.
- **D3, dismissed:** hashing before native release could race DMA. Snapshot copies
  while the lease is held, native end succeeds, and only then are the private
  copied bytes hashed. Copy-off returns no digest. Raw bytes, mappings and fds
  never enter the result structure.
- **U1, unresolved external gate:** no live client/dependency/corpus manifest,
  same-run command/reference join, DMA-coherence proof or guarded B/E campaign
  exists. The refusing controller also predates this client and must distinguish
  VA output ordinals from Gst frame numbers while enforcing the VA owner/thread
  contract. Those remain #82/#42 work and prevent a coverage-count change.

Exact commands, identities, results and exclusions are in
[VALIDATION.md](VALIDATION.md). Decision: no remaining confirmed blocker for the
offline leaf; separate final-head review and hosted CI are still required before
merge. No independent reviewer is invented.
