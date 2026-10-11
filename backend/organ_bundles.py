"""Organ bundles — how a new organ comes online (handoff Phase 5).

A bundle is a folder ``data/organs/<organ_id>/`` containing ``organ.json``. It
describes the organ, its cell layers (atlas statistics + states with roles and
master TFs) and, optionally, its source datasets.

Bundles never carry stage *results*. Results for Stages C–F appear only when a
real run writes an artifact (see ``artifacts.py``), so a new organ cannot show
numbers that were not computed.

Check bundles:   python3 -m backend.organ_bundles               (all bundles)
                 python3 -m backend.organ_bundles path/to/organ_dir
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter
from typing import Any, Dict, List, Optional

from . import config

ORGAN_FILE = "organ.json"
ROLES = ("mature", "progenitor", "other")
ATLAS_KEYS = ("cells", "donors", "n_states", "fetal", "perinatal", "adult_aging")
_SNAKE = re.compile(r"^[a-z][a-z0-9_]*$")


def _is_count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def validate(doc: Any, expected_id: Optional[str] = None) -> List[str]:
    """Return a list of human-readable problems; an empty list means valid."""
    if not isinstance(doc, dict):
        return ["organ.json must contain a JSON object"]
    errors: List[str] = []

    oid = doc.get("id")
    if not isinstance(oid, str) or not _SNAKE.match(oid):
        errors.append("'id' must be snake_case (e.g. 'liver')")
    elif expected_id is not None and oid != expected_id:
        errors.append(f"'id' ('{oid}') must match its folder name ('{expected_id}')")
    if oid == "lung":
        errors.append("'lung' is the reference organ defined by the seed data and cannot be overridden")

    name = doc.get("name")
    if not isinstance(name, str) or not name.strip():
        errors.append("'name' is required")

    status = doc.get("status")
    if status not in ("planned", "implemented"):
        errors.append("'status' must be 'planned' or 'implemented'")

    layers = doc.get("layers", {})
    if not isinstance(layers, dict):
        return errors + ["'layers' must be an object keyed by layer id"]
    if status == "implemented" and not layers:
        errors.append("an implemented organ needs at least one layer")

    for lid, layer in layers.items():
        where = f"layer '{lid}'"
        if not _SNAKE.match(lid):
            errors.append(f"{where}: id must be snake_case")
        if not isinstance(layer, dict):
            errors.append(f"{where}: must be an object")
            continue
        if not isinstance(layer.get("name"), str) or not layer.get("name"):
            errors.append(f"{where}: 'name' is required")

        atlas = layer.get("atlas")
        if not isinstance(atlas, dict) or any(not _is_count(atlas.get(k)) for k in ATLAS_KEYS):
            errors.append(f"{where}: 'atlas' needs non-negative integers for {', '.join(ATLAS_KEYS)}")

        states = layer.get("states")
        if not isinstance(states, dict) or not states:
            errors.append(f"{where}: 'states' must be a non-empty object")
            continue

        roles: Counter = Counter()
        for sname, st in states.items():
            sw = f"{where}, state '{sname}'"
            if not isinstance(st, dict):
                errors.append(f"{sw}: must be an object")
                continue
            if st.get("role") not in ROLES:
                errors.append(f"{sw}: 'role' must be one of {', '.join(ROLES)}")
            else:
                roles[st["role"]] += 1
            tfs = st.get("master_tfs", [])
            if not isinstance(tfs, list):
                errors.append(f"{sw}: 'master_tfs' must be a list")
                continue
            for t in tfs:
                if (
                    not isinstance(t, dict)
                    or not isinstance(t.get("tf"), str)
                    or isinstance(t.get("logFC"), bool)
                    or not isinstance(t.get("logFC"), (int, float))
                ):
                    errors.append(f"{sw}: each master TF needs a 'tf' string and numeric 'logFC'")
                    break

        if status == "implemented":
            if roles["mature"] == 0:
                errors.append(f"{where}: needs at least one 'mature' (source) state")
            if roles["progenitor"] == 0:
                errors.append(f"{where}: needs at least one 'progenitor' (target) state")
    return errors


def scan(root: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """Read every organ folder under ``root``; folders starting with '.' or '_' are skipped."""
    root = root or config.ORGANS_DIR
    report: Dict[str, Dict[str, Any]] = {}
    if not os.path.isdir(root):
        return report
    for name in sorted(os.listdir(root)):
        if name.startswith((".", "_")):
            continue
        folder = os.path.join(root, name)
        if not os.path.isdir(folder):
            continue
        path = os.path.join(folder, ORGAN_FILE)
        if not os.path.isfile(path):
            report[name] = {"valid": False, "errors": [f"missing {ORGAN_FILE}"], "bundle": None}
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                doc = json.load(fh)
        except ValueError as exc:
            report[name] = {"valid": False, "errors": [f"invalid JSON: {exc}"], "bundle": None}
            continue
        errors = validate(doc, expected_id=name)
        report[name] = {"valid": not errors, "errors": errors, "bundle": doc if not errors else None}
    return report


def load_valid(root: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """Only the bundles that pass validation, keyed by organ id."""
    return {oid: v["bundle"] for oid, v in scan(root).items() if v["valid"]}


def _main(argv: List[str]) -> int:
    targets: List[str] = []
    if argv:
        targets = argv
    else:
        root = config.ORGANS_DIR
        targets = [os.path.join(root, n) for n in sorted(os.listdir(root))] if os.path.isdir(root) else []
    failures = 0
    checked = 0
    for target in targets:
        if not os.path.isdir(target) or os.path.basename(target).startswith((".", "_")):
            continue
        checked += 1
        name = os.path.basename(os.path.normpath(target))
        path = os.path.join(target, ORGAN_FILE)
        try:
            with open(path, encoding="utf-8") as fh:
                doc = json.load(fh)
            errors = validate(doc, expected_id=name)
        except (OSError, ValueError) as exc:
            errors = [f"cannot read {ORGAN_FILE}: {exc}"]
        if errors:
            failures += 1
            print(f"FAIL  {name}")
            for e in errors:
                print(f"        - {e}")
        else:
            print(f"OK    {name}")
    if checked == 0:
        print("no organ bundles found")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
