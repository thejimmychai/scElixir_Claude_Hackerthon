"""Organ / layer / state registry and the per-run "what's computed" index.

This module is where the scientific-integrity guardrails (handoff Section 8) are
encoded as data-availability logic. A stage is reported ``cached`` only when a
real artifact exists for the requested parameters; otherwise ``not_computed``.
Nothing is ever fabricated here — the runners in ``stages/`` refuse to emit
numbers for a combination this index marks ``not_computed``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import config, data_loader

STAGE_IDS = ["A", "B", "C", "D", "E", "F"]


# --------------------------------------------------------------------------- #
# registry views                                                              #
# --------------------------------------------------------------------------- #
def organs() -> List[Dict[str, Any]]:
    ds = data_loader.get()
    out = []
    for oid, o in ds.organs.items():
        entry = {"id": oid, "name": o["name"], "status": o["status"], "note": o.get("note", "")}
        if "atlas_cells" in o:
            entry["atlas_cells"] = o["atlas_cells"]
        if "atlas_datasets" in o:
            entry["atlas_datasets"] = o["atlas_datasets"]
        out.append(entry)
    return out


def organ(organ_id: str) -> Optional[Dict[str, Any]]:
    return data_loader.get().organs.get(organ_id)


def organ_implemented(organ_id: str) -> bool:
    o = organ(organ_id)
    return bool(o) and o.get("status") == "implemented"


def layers(organ_id: str) -> List[Dict[str, Any]]:
    ds = data_loader.get()
    implemented = organ_implemented(organ_id)
    out = []
    for lid, l in ds.layers.items():
        out.append(
            {
                "id": lid,
                "name": l["name"],
                # Only an implemented organ exposes its real atlas stats.
                "atlas": l.get("atlas") if implemented else None,
                "status": "implemented" if implemented else "planned",
            }
        )
    return out


def layer_exists(organ_id: str, layer_id: str) -> bool:
    return layer_id in data_loader.get().layers


def states(organ_id: str, layer_id: str) -> Dict[str, Any]:
    ds = data_loader.get()
    layer = ds.layers.get(layer_id)
    if not layer or not organ_implemented(organ_id):
        # Planned organs have no resolved states yet — honest empty result.
        return {"states": {}}
    return {"states": layer["states"]}


def role_states(layer_id: str, role: str) -> List[str]:
    layer = data_loader.get().layers.get(layer_id)
    if not layer:
        return []
    return [k for k, v in layer["states"].items() if v.get("role") == role]


# --------------------------------------------------------------------------- #
# "what's computed" index                                                     #
# --------------------------------------------------------------------------- #
def _is_reference_transition(organ_id: str, layer_id: str, source: Optional[str], target: Optional[str]) -> bool:
    rc = config.REFERENCE_CASE
    return (
        organ_id == rc["organ"]
        and layer_id == rc["layer"]
        and source == rc["source"]
        and target == rc["target"]
    )


def grn_available(organ_id: str, layer_id: str) -> bool:
    return layer_id in config.GRN_COMPUTED_LAYERS.get(organ_id, set())


def run_id(organ_id: str, layer_id: str, source: Optional[str], target: Optional[str], species: str) -> str:
    return "|".join([organ_id or "", layer_id or "", source or "", target or "", species or ""])


def stage_status(
    stage: str,
    organ_id: str,
    layer_id: str,
    source: Optional[str] = None,
    target: Optional[str] = None,
    species: str = "human",
) -> str:
    """Return ``cached`` | ``not_computed`` for one stage under given params.

    (``running`` is a live value set by the job queue, not by this static index.)
    """
    if not organ_implemented(organ_id):
        return "not_computed"
    if stage == "A":
        return "cached"
    if stage == "B":
        return "cached" if layer_exists(organ_id, layer_id) else "not_computed"
    if stage == "C":
        return "cached" if grn_available(organ_id, layer_id) else "not_computed"
    if stage in ("D", "E"):
        return "cached" if _is_reference_transition(organ_id, layer_id, source, target) else "not_computed"
    if stage == "F":
        ok = _is_reference_transition(organ_id, layer_id, source, target) and species in config.REFERENCE_CASE["species"]
        return "cached" if ok else "not_computed"
    return "not_computed"


def run_index(
    organ_id: str,
    layer_id: str,
    source: Optional[str] = None,
    target: Optional[str] = None,
    species: str = "human",
) -> Dict[str, Any]:
    """The ``GET /runs`` payload: run id + per-stage cached/not_computed status.

    Live ``running`` states are overlaid by the job queue in ``app.py``.
    """
    stages = {
        s: stage_status(s, organ_id, layer_id, source, target, species) for s in STAGE_IDS
    }
    return {
        "run_id": run_id(organ_id, layer_id, source, target, species),
        "params": {
            "organ": organ_id,
            "layer": layer_id,
            "source": source,
            "target": target,
            "species": species,
        },
        "stages": stages,
    }
