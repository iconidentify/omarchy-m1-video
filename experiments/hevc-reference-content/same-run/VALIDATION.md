# Offline validation — 2026-09-19

AI-assisted maintainer execution and adversarial self-review; no independent
review or hardware qualification is claimed. Implementation
`f9d3d85ebc4686cf928b0dae67b524d361ed6de3` was tested from base
`b60be8ad8b966ed3fc44d8edc62ff88f80d74fb4`.

The focused same-run boundary and semantic mutations passed:

```sh
python3 experiments/hevc-reference-content/same-run/tests.py
# 28 tests passed
python3 experiments/hevc-reference-content/same-run/mutations.py
# 10 named semantic mutations passed
```

Those cases cover real fork/exec/wait behavior with fake recorders; exact-PID
arm; environment/cwd/private-log binding; nonzero-child preservation; exact
client/queue/raw-V4L2/kernel identity chains for both clients; ambiguous,
foreign, stale and incomplete evidence; every existing validator/oracle call;
private stable reads; normalized-only results; and exclusive atomic publication.
No device or sudo command is used.

All directly affected and parent offline suites also exited zero:

```sh
python3 experiments/hevc-avd-command-capture/tests.py
# 22 tests passed
python3 experiments/hevc-reference-content/campaign/tests.py
# 51 tests passed
python3 experiments/hevc-reference-content/campaign/mutations.py
# 10 named semantic mutations passed
python3 experiments/hevc-reference-content/tests.py
# 25 tests plus 4 actual-source mutations passed
python3 experiments/hevc-reference-content/va-callsite/tests.py \
  --keep /tmp/omarchy-122-va-callsite
# complete pinned FFmpeg call-site/result/collector and 14 semantic mutations passed
```

The FFmpeg suite applied the shipped patches with zero fuzz, built and executed
the actual pinned HEVC VA output/result path against its fake driver, and covered
default-off, copy off/on, owner/thread/surface/ABI refusal, retry/quarantine,
report collision/write/close failure, process-exit collection and normalized
collector rejection. Its reported identities were:

| FFmpeg evidence | SHA-256 |
| --- | --- |
| Pinned source archive | `fb193f0a25f5f67da827632f64749520b36f9ebea1e5956bfc120d1364bdd88f` |
| Patched `ffmpeg-vaapi.o` | `89d50268afd5e214ed9f20e6a035fda01b16ee1db196064d1832d3c46d691574` |
| Patched FFmpeg program | `ae969fed3a7638186a34dadb97ca1e885cf23929815ca2c2ecaa90f2fc49a1b8` |
| Call-site fixture | `47339b7ed1b363b2b68e8ec31714a2fbd57f58c269df35ca703b9012d5d63682` |
| FFmpeg observer patch | `58b7c2b8b009f128011cc4ac858a2a3e59748765e7571ad9521b4069750f9013` |
| Driver ABI patch | `21ce2b1df7fcea8001cf0de6496a69ed1da6159e814cc2f42b58c4dd44ab766b` |

Additional checks passed: Python bytecode compilation of every changed Python
entry point, workflow YAML parsing, relevant shell syntax checks and
`git diff --check`.

## Tracer behavior probe

A no-device probe established the required process and status semantics:

```sh
bash -c 'echo wrapper_pid=$$; exec v4l2-tracer -u trace \
  python3 -c "import os; print(os.getpid(), os.getppid())"'
# wrapper PID 389783; tracee PID 389784; tracee parent 389783

v4l2-tracer -u trace python3 -c 'raise SystemExit(23)'
# tracer printed raw wait status 5888 but itself exited 0
```

The PIDs are ephemeral evidence only. The first result proves the wrapper and
tracee are different processes; the second proves the durable supervisor's
actual decoder wait record must remain authoritative.

## Environment and implementation identities

Host: Linux 7.1.13-3-1-ARCH aarch64; Python 3.14.7; GCC 16.1.1
(20260430); v4l2-tracer 1.32.0.

| Artifact | SHA-256 |
| --- | --- |
| `join.py` | `2aa1bb54e5ff1a76375f159a16e78fe1166e63becbdec8052c496cd185f54bd8` |
| `validator.py` | `9c81323b5c9760e598d3a4fb03c6d64eae3818247748170e860f5ef5ffa3c1c0` |
| `supervisor.py` | `fd65d2720f38e45b4e960856769bc3c56173fdc58fe2f37c8938c065eea16797` |
| `tests.py` | `77dc65ffe1b829d206f760dedd8a3404b924998c80e97351bb235883bc6e9e3a` |
| `mutations.py` | `3f0cca0c39ffe9b54acd203e3de23f41c9013c72ccddd2a044242424009f1c03` |
| paired `capture.py` | `45cf1cbaff305db5a66d8c2599e9b6645f0d90264b701bcfeb870d8a20cd8c30` |
| VA `collector.py` | `caa1199ca01ac7e98282d7bb07e20208fa53380e10edb567c382d22ca584038e` |
| hosted workflow | `5fedf607fbc6c4665b3c6d064ffaf7f01275d9f9560b3e9e4a3dd1d08e41cf97` |

These are offline process/schema/control-flow checks, not decoded-device output,
DMA visibility, cache coherence, pixel equality, performance, installation or a
support-count increase. The same-run command in `README.md` remains a
non-authorizing shape reference. A later device run still requires
`tests/hwguard.py`, healthy idle/fault gates, a reviewed live manifest, proven
selected-target eligibility, controller admission and explicit campaign
authorization.
