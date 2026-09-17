#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Load the curated source-control inventory; no generated duplicate of its prose."""
import json
from pathlib import Path
SCHEMA = "omarchy-m1-video.hevc-avd-controls-map/1"
CLASSES = ("already_measured", "statically_derivable", "missing_runtime_input", "outside_scope")
BINDINGS = {"sps", "pps", "decode", "sl", "base", "tile_info", "pred_weight_table", "scaling_matrix"}
def document():
    return json.loads((Path(__file__).resolve().parent / "inventory.json").read_text())
FIELDS = document()["fields"]
