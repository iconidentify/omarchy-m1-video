# Offline validation

AI-executed implementation and self-review for issue #116. Base
`6b768d8deef9c3d60af0d65d4d2aadd4c1162a83`; exact final candidate and hosted
links are recorded in PR #117.

Commands:

```sh
python3 experiments/hevc-reference-content/campaign/tests.py
python3 experiments/hevc-reference-content/campaign/mutations.py
python3 -m py_compile experiments/hevc-reference-content/campaign/controller.py \
  experiments/hevc-reference-content/campaign/tests.py \
  experiments/hevc-reference-content/campaign/mutations.py
bash tests/rebuild.sh
bash -n install.sh uninstall.sh bin/apple-avd-rebuild tests/rebuild.sh \
  libva/PKGBUILD libva/libva-v4l2_request-avd.install
git diff --check
```

Results:

- 51/51 controller tests passed.
- Ten semantic mutations were detected by their named test: selector domain,
  Gst publication boundary, parameter input window, paired off/on selectors,
  VA thread count, VA application owner, finish-before-close, fatal cleanup,
  JSON no-authorization and execution refusal.
- Python compilation, repository rebuild/shell syntax and whitespace checks
  passed.

No hardware, decoder device, guard lease, module, installation, reboot, client,
raw content or campaign was used. No real output count, selector, input-window,
manifest, same-run kernel association or support result is claimed.
