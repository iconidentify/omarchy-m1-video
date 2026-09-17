# Failed pre-decoder attempt — 2026-09-17 21:02:35 UTC

AI-generated measured incident report. This preserves a failure, not a successful
capture or qualification. The candidate module SHA-256 was
`3f17561f44fdf578c14c79e0d0dd55190aa63b70f6ad07908536807e030e8bb4`.
**Do not load that candidate.**

One outer guard owned temporary load and the first B/VA/off attempt. The reference
recorder status file was missing. The supervisor rejected preflight before fork:
`child_pid=null`, `child_released=false`, `child_exit=null`. Zero decoder workloads
executed; the seven remaining workloads were not attempted. The outer tracer
printed raw wait status 32000; its exit alone was not treated as success.

A fresh state check was idle with no fault before attempted restoration. The
non-forced candidate unload then produced a kernel NULL-pointer Oops in
`avd_trace_exit → debugfs_remove → simple_recursive_removal → down_write`.
The unloading command ended with signal 11. The kernel left apple_avd in
`Unloading` / `initstate=going`, reference count -1, with no video node.
Original loaded-module restoration failed. The installed original file was
unchanged (SHA-256 `e50540e1d0fc48c7e0bf9b21ff028758bdb35f94aa7070af00de88e61e5c70e9`).
No forced unload, decoder retry, second load, installation or reboot was attempted
in this campaign. The fixed fault boundary was not advanced past the Oops.

The guard reported child-error, not success. Because the failure completed between
polls, its final event alone does not establish a fault-free kernel; the terminal
journal and module-state observation are required. The controller now persists a
terminal state even after rapid failures and rejects a module outside `live`.

Root cause is a source-generation control-flow error. In the generated module
initializer, adding the second recorder exit to an unbraced conditional left
`avd_trace_exit()` unconditional. Successful registration therefore removed the
reference debugfs tree, and module exit attempted a second removal. The correction
replaces the complete conditional with a braced block and matches the exit path
separately, rejecting source drift. A regression executes the actual generated
init/exit bodies for registration success/failure and repeated lifecycles; putting
the original bad conditional back must fail. This was missed by maintainer
self-review; previous tests exercised recorder wrappers and packing, not the
combined generated module lifecycle. No firmware or HEVC corruption conclusion
can be drawn from this pre-decoder failure.

Raw kernel journal remains private; the excerpt redacts addresses, PID and host.
Private digests bind local originals but do not independently authenticate them.
A clean boot and fresh, explicitly recorded attempt are prerequisites for any
hardware follow-up. #71 and driver #42 remain open; codec counts are unchanged.
