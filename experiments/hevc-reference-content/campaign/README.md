# Campaign controller

Plans and reviews the eight guarded workloads in [CAMPAIGN.md](../CAMPAIGN.md)
and **refuses to execute any of them**. Planning is offline and side-effect free:
no device is opened, no lease acquired, no module loaded and no client started.

The arguments below are synthetic shape examples, not approved campaign
selections:

```sh
python3 experiments/hevc-reference-content/campaign/controller.py \
    --gst-e-pool-size 16 --gst-b-pool-size 14 \
    --va-e-output-count 20 --va-b-output-count 20 \
    --gst-e-frames 2 5 9 --gst-b-frames 3 \
    --va-e-outputs 1 4 7 --va-b-outputs 2 \
    --gst-e-last-input 9 --gst-b-last-input 4 \
    --va-e-last-input 12 --va-b-last-input 6 --json
python3 experiments/hevc-reference-content/campaign/tests.py
python3 experiments/hevc-reference-content/campaign/mutations.py
```

## Distinct client coordinates

Gst selections are `system_frame_number`s. VA selections are zero-based decoded
output ordinals. They have separate CLI arguments, JSON domains and bounds:
Gst selected frame numbers are not pool indices. Its per-vector capacity check
instead proves that the negotiated source pool preserves at least one ordinary
allocation after reserving exactly one never-published allocation per selected
frame. VA alone uses the declared decoded-output count. A plan carrying either
domain or limit into the other client rejects.

Parameter-set safety uses a third coordinate: input/submission order. Each
client/vector row supplies the last input needed to produce its last selected
output. The controller compares in-band parameter-set-change input indices only
to that input window. It never compares a VA output ordinal as though it were an
input position.

Copy-off and copy-on select the same outputs. Both run the same observer open,
select, retain, drain, provenance, map/unmap, end and close path; only the two
bounded memcpy operations differ. The old controller selected nothing for the
copy-off rows, contradicting CAMPAIGN.md and making them invalid controls. The
eight-snapshot/byte budget counts the eight copy-on targets; the paired copy-off
observations spend no copied-byte budget.

## Checked contracts

| Check | Owning contract |
| --- | --- |
| Exact `{B,E} × {VA,Gst} × {copy-off,copy-on}` matrix | CAMPAIGN.md |
| Paired off/on selectors and input windows are identical | CAMPAIGN.md |
| Three E and one B target per client; eight copied targets total | CAMPAIGN.md |
| Gst `system_frame_number` domain and ordinary-plus-reserve pool capacity | Gst allocation eligibility path |
| Gst fresh element, streaming owner, flow-error failure and finish-before-lifecycle | Gst known controller limits |
| VA output-ordinal domain and decoded-output bound | FFmpeg/VA call site |
| VA fresh decoder, `threads=1`, `active_thread_type=0` | FFmpeg/VA call site |
| One VA owner for send/receive/flush/result/finish/close | FFmpeg/VA call site |
| VA finish before free/close; persistent end failure is fatal quarantine | FFmpeg/VA call site |
| Any sticky VA output failure invalidates result and repeated finish | PR #115 final-head fix |
| VA worker publishes one bounded normalized record to an exclusive path before free; collector also requires process exit zero | #118 FFmpeg result path |
| Parameter-set changes stay outside the explicit input window | Both client call sites |
| Healthy idle, no foreign client, journal boundary, module loaded, refcount 0 | CAMPAIGN.md |

`Plan.to_json()` includes a deterministic `client_contract` for every workload.
For VA it emits the private `threads`, `va_observer_outputs` and
`va_observer_copy` option values, the required runner-supplied
`va_observer_report` destination contract, required owner operations and
fatal-quarantine policy. For Gst it emits the internal arm API, selector values,
copy mode and negotiated ordinary/reserve capacity. These are inputs for a later runner, not
evidence that one ran. The top level always includes `valid`, every rejection
reason and
`execution_authorized: false`; an invalid document cannot look like an authorized
runner input merely because a consumer ignored the CLI exit status.

## Why execution still refuses

`Controller.execute()` checks the authorization record, plan and preconditions,
then raises `AuthorizationError` unconditionally. The executable
[same-run supervisor](../same-run/README.md) now supplies the per-workload
client/kernel join, but the campaign still lacks a reviewed live deployment
manifest, full client/dependency/corpus attestation, proven live target
eligibility and controller-level workload admission. Keeping refusal in code
prevents a valid-looking JSON document from becoming accidental hardware
authorization.

`Authorization` merely names an operator, guard lease, manifest digest, issue
authorization and hardware window supplied elsewhere. The controller cannot
mint or verify those external facts.

## Evidence and limits

The offline suite has 52 tests. Ten semantic source mutations remove the
selector-domain, Gst reserve-capacity, parameter-input-window, paired-control,
VA thread, VA owner, finish-before-close, fatal-cleanup, JSON no-authorization or
execution-refusal gate; each must fail its named assertion. A compiler error,
timeout or unrelated failure is not accepted as mutation detection.

This leaf does not drive a decoder, choose real campaign targets, verify the
declared output counts/input windows, collect evidence, compare off/on outputs or
restore a machine. Those values must come from the locked corpus and later
same-run evidence, not assumed POC/index mappings. A plan passing review says
only that it is internally consistent with the accepted client contracts.

See [REVIEW.md](REVIEW.md) for the adversarial dispositions and
[VALIDATION.md](VALIDATION.md) for exact offline evidence and limitations.
