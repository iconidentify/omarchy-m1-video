# Validation record

AI-executed implementation and self-review for issue #126. The exact final
candidate, build output identities, hosted checks and PR are recorded during
closeout; this file must be updated from the final clean head before merge.

Offline commands:

```sh
python3 experiments/hevc-reference-content/campaign/tests.py
python3 experiments/hevc-reference-content/campaign/mutations.py
python3 experiments/hevc-reference-content/deployment/target_tests.py
python3 experiments/hevc-reference-content/deployment/tests.py
python3 experiments/hevc-reference-content/deployment/mutations.py
python3 -m py_compile experiments/hevc-reference-content/campaign/*.py \
  experiments/hevc-reference-content/deployment/*.py
git diff --check
```

Current results:

- 52/52 campaign-controller tests passed; ten named semantic mutations were
  distinguished by their owning tests.
- 4/4 target-derivation tests passed against the four hash-locked public
  association tables, synthetic contiguous/noncontiguous pool traces and
  accepted/refused Annex-B parameter-set placement.
- 15/15 deployment tests passed. They cover candidate refusal, exact approved
  digest, clean source, source/patch/artifact/dependency/module/corpus/target/
  capacity/plan/command binding, fresh run placeholders, trust modes, strict
  JSON and deterministic controller/builder reconstruction.
- Eight deployment mutations removing the manifest-digest, source, dependency,
  corpus, capacity, target, plan or execution-refusal gate each failed their
  named test.
- The private B and E Gst traces were parsed without decoder access. Their raw
  SHA-256 values are pinned in `target-evidence-20260920.json`; both expose one
  contiguous 19-allocation ordinary capture pool.

No decoder device, module operation, installation or reboot was used. The full
pinned production build is recorded separately below after it completes.
