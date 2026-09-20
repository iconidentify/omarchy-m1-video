# Adversarial review record

- Acceptance ticket/session: #126 / `codex-126-hevc-deployment-20260920`
- Base: `987c8f91a980878c82d5506dce2bb78e01b4119e`
- Reviewer: Codex maintainer self-review with AI assistance; not independent
- Scope: offline staging, identity/target/command admission and unconditional
  execution refusal. No installer, module or decoder operation.

| Stage | Evidence | Disposition |
| --- | --- | --- |
| 1 Intent | New code is isolated under the experimental deployment directory; existing shipped patches and defaults are unchanged. | Fits the owning offline leaf. |
| 2 Claims | Complete source/patch/artifact/dependency/corpus/target/plan inventory and real production builds are required before candidate emission. | Exact-head build evidence and the candidate digest are release evidence posted during closeout. |
| 3 Execution | Builder ends at a candidate. Verifier requires an exact externally reviewed digest. Admission reconstructs plan and commands, then returns false authorization. | Default and all error paths remain non-executing. |
| 4 Resources | Builder creates only a caller-selected empty directory and subprocess build trees; it does not install. Supervisor argv is data and is never invoked here. | Partial build trees remain inspectable; no device resource exists. |
| 5 Concurrency | Offline subprocesses share no mutable decoder state. Manifest publication/approval is outside the builder. | Inapplicable to hardware; later campaign owns process/device concurrency. |
| 6 Trust/bounds | Strict JSON keys, SHA-256/build IDs, direct regular paths, permissions, exact dependency closure, bounded selections and exact plan/command reconstruction. | Named tests/mutations cover every acceptance gate. |
| 7 Hardware | Host/module/config identities are attested, but candidate generation does not claim loaded-artifact equality or DMA visibility. | Live endpoint/build-ID checks run only for a reviewed manifest; no hardware used. |
| 8 Consolidate | The pre-#125 controller incorrectly bounded frame numbers by pool size. | Confirmed and fixed: per-vector ordinary-plus-reserve capacity replaces the stale boundary. |
| 9 Conflicts | Late Gst selectors 28/31/32 exceed pool slot counts but do not name slots; reserve allocation is selected by sticky publication state. | Source invariant and eligibility tests resolve the apparent conflict. |
| 10 Verify | Late-selector positive test, insufficient-capacity negative test, target parser and gate mutations all exercise the changed paths. | No unresolved offline correctness finding at current head. |
| 11 Report | Exact-head local build, hosted CI and merge disposition are recorded in the PR rather than editing this manifest-bound commit afterward. | Merge remains conditional on that evidence. |

## Findings

- D1, confirmed, introduced before this leaf: campaign admission treated
  `system_frame_number` as a pool index and rejected legitimate late targets.
  The merged finite reserve makes selection independent of ordinal pool slots.
  Fixed by per-vector negotiated capacity with at least one ordinary allocation
  plus exactly one reserve per selector; regression and mutation tests pass.
- D2, confirmed during self-review: manifest commands originally named direct
  clients and admission compared names only. That did not bind the executable
  same-run evidence path. Fixed by emitting full supervisor argv/environment
  records and reconstructing both the plan and every command at admission.
- D3, confirmed during self-review: target evidence originally carried only an
  unbound digest. Fixed by staging it as an ordinary hashed artifact and
  requiring every target row to name that exact artifact digest.
- D4, confirmed by the clean production build: Arch's `glib-2.0.pc` advertised
  absent generator programs. Fixed without host installation by reproducing
  the two programs from hash-locked upstream 2.88.3 templates and binding the
  exact local pkg-config/native-file route into the candidate manifest.
- D5, confirmed in a copied unmutated test tree: two missing helper files made
  the old mutation harness report an unrelated error as mutation detection.
  Each mutation now requires a clean positive baseline and exactly its owning
  assertion failure, with no unrelated errors.
- D6, confirmed against both kernel recorder sources: live admission expected
  textual key/value status instead of the versioned numeric `S 1` wire format.
  Fixed with exact extent/version/zero-field validation and active-field
  negatives. Loaded GNU note parsing now honors its header and digest size.
- D7, confirmed across the real supervisor's callees: the command oracle takes
  a directory with two builds plus identity data; the initial argv named one
  executable. The initial guard path also named the wrong repository. Fixed
  by staging the complete oracle and using the guard from the pinned VA tree.
- D8, confirmed by loader/import analysis: copying the Gst binaries alone could
  select system libraries, and hashing only supervisor.py left its imports and
  data unbound. Stage and verify the built library closure plus all repository
  runtime inputs, Python, tracer and preload dependencies; probe the actual
  supervisor/oracle import before emitting a candidate.
- D9, confirmed by admissible counterexamples: evidence digest equality did
  not compare target contents, and plan validity did not imply the same target
  selection. Admission now compares both relationships explicitly.
- D10, confirmed in the pinned FFmpeg source: output POC logs require debug
  level and include the codec prefix and trailing period. The command enables
  debug output and keeps VAAPI output for hwdownload; the same-run reader
  accepts that exact log form with an unrelated-codec negative regression.

The strongest remaining limitation is intentionally outside #126: a valid
manifest cannot prove observation noninterference or HEVC correctness. Only the
guarded paired hardware campaign can do that, and driver #42 still owns the
actual correction and qualification.
