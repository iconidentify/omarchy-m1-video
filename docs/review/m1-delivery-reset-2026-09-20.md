# M1 delivery reset review

AI-assisted maintainer self-review, session `codex-m1-delivery-reset-20260920`.
Video PR130 from `c836cedc3361892dc4f40542821ee170e3a8ca0d`; companion driver
documentation PR101 at `9ec1e95d39df9bd2145cdceb92f3f4965d98b693`, based on
`5b5046cbda6892f4a63df0015857a80bd42c17cf`. Final PR heads and CI are recorded
in their descriptions. No independent review is claimed.

| Stage | Evidence / conclusion |
| --- | --- |
| 1 Intent | Owner-approved retrospective and delivery reset; priorities, bounded local build wrapper and existing-harness evidence. No production decoder or package change. |
| 2 Claims | Current pages distinguish installed/candidate/experimental; resource, player smoke and unrun client/boot gates are separate. Existing claims preserved. |
| 3 Execution | Wrapper passes argv directly to systemd, validates disk/RAM headroom and disk-backed temporary storage, preserves child exit status 7 in a real run; errors return nonzero. |
| 4 Resources | Actual cgroup reads show one CPU, 1 GiB high / 1.5 GiB max memory and 64 tasks. Service covers the child tree and has a deadline. Candidate build peak 224.6 MiB. |
| 5 Concurrency | A simultaneous second wrapper invocation was refused by the fixed user-service name. Scope is cooperating jobs for this user, not every desktop process or other users. Hardware retains its independent exclusive guard. |
| 6 Trust/bounds | Source/artifact/input hashes and normalized/original log hashes retained. Archive verifier never extracts paths; exact member set and raw sequence assertions reject altered data. |
| 7 Hardware | Six finite guards used whole-current-boot preflight and ended idle/healthy. Loaded build-ID versus disk hash limitations explicit. No module/install/reboot action. |
| 8 Consolidate | Guard source metadata names the harness checkout, not necessarily selected driver. Clarified alongside selected-driver metadata and actual candidate mapping observation; no historical record changed. |
| 9 Resolve | mpv helper can scale unequal images or tolerate a missing wait predicate. These smoke results additionally require equal dimensions, byte-identical captures, actual VA selection, play progress and zero drops. This does not certify all future helper inputs. |
| 10 Verify | Offline archive replay confirms 56 members, 80,640 ordered frames, 1,680 retained images, four player rows and six final guards. Rehashed mutations test missing frames, bad guard state, software fallback and wrong driver identity. Documentation links/diffs and applicable hosted checks are recorded with the final PR heads. |
| 11 Report | Ready for maintainer review at the documented scope. Current roadmap updated in place; old body archived. Driver docs should land after the companion delivery page. No release qualification or parent closure follows. |

The wrapper controls cooperating build jobs; it does not prove the previous
desktop freeze's cause or promise the desktop cannot freeze again. Memory
pressure was observed; driver involvement remains unproven.

[Evidence and limits](../evidence/m1-delivery-2026-09-20/README.md),
[semantic negative results](../evidence/m1-delivery-2026-09-20/verification-negatives.json).
Full strict suites, Chrome, sustained player/recovery, boot/platform and packaging
were not run in this bounded reset. Public-report and private-security routes
were inspected and remain unchanged; no synthetic public report was sent.
