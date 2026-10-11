"""Organ / layer / state registry and the per-run "what's computed" index.

This module is where the scientific-integrity guardrails (handoff Section 8) are
encoded as data-availability logic. A stage is reported ``cached`` only when a
real result exists for the requested parameters — either the shipped reference
data (lung AT2 -> fetal distal-tip) or a durable artifact written by a real run
under identical parameters. Otherwise it is ``not_computed``. Nothing is ever
fabricated here.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import artifacts, config, data_loader, organ_bundles

STAGE_IDS = ["A", "B", "C", "D", "E", "F"]


# --------------------------------------------------------------------------- #
# organs and layers                                                           #
# --------------------------------------------------------------------------- #
def _all_organs() -> Dict[str, Dict[str, Any]]:
    """Seed organs (lung + planned placeholders) merged with valid organ bundles."""
    merged: Dict[str, Dict[str, Any]] = {k: dict(v) for k, v in data_loader.get().organs.items()}
    for oid, bundle in organ_bundles.load_valid().items():
        layers = bundle.get("layers", {})
        entry: Dict[str, Any] = {"name": bundle["name"], "status": bundle["status"], "note": bundle.get("note", "")}
        if bundle["status"] == "implemented":
            entry["atlas_cells"] = sum(l["atlas"]["cells"] for l in layers.values())
            entry["atlas_datasets"] = bundle.get("atlas_datasets", len(bundle.get("source_datasets", [])))
        merged[oid] = entry
    return merged


def organs() -> List[Dict[str, Any]]:
    out = []
    for oid, o in _all_organs().items():
        entry = {"id": oid, "name": o["name"], "status": o["status"], "note": o.get("note", "")}
        if "atlas_cells" in o:
            entry["atlas_cells"] = o["atlas_cells"]
        if "atlas_datasets" in o:
            entry["atlas_datasets"] = o["atlas_datasets"]
        out.append(entry)
    return out


def organ(organ_id: str) -> Optional[Dict[str, Any]]:
    return _all_organs().get(organ_id)


def organ_implemented(organ_id: str) -> bool:
    o = organ(organ_id)
    return bool(o) and o.get("status") == "implemented"


def _layers_for(organ_id: str) -> Dict[str, Any]:
    bundles = organ_bundles.load_valid()
    if organ_id in bundles:
        return bundles[organ_id].get("layers", {})
    # The seed layers describe the lung reference; planned organs show them as placeholders.
    return data_loader.get().layers


def layer_data(organ_id: str, layer_id: str) -> Optional[Dict[str, Any]]:
    return _layers_for(organ_id).get(layer_id)


def layers(organ_id: str) -> List[Dict[str, Any]]:
    implemented = organ_implemented(organ_id)
    out = []
    for lid, l in _layers_for(organ_id).items():
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
    return layer_data(organ_id, layer_id) is not None


def states(organ_id: str, layer_id: str) -> Dict[str, Any]:
    layer = layer_data(organ_id, layer_id)
    if not layer or not organ_implemented(organ_id):
        # Planned organs have no resolved states yet — honest empty result.
        return {"states": {}}
    return {"states": layer["states"]}


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


def grn_available(organ_id: str, layer_id: str, route: str = "scenicplus") -> bool:
    return (organ_id, layer_id, route) in config.GRN_COMPUTED


def reference_cached(
    stage: str,
    organ_id: str,
    layer_id: str,
    source: Optional[str] = None,
    target: Optional[str] = None,
    species: str = "human",
    route: str = "scenicplus",
) -> bool:
    """True only when the shipped reference data answers this stage.

    The stage handlers use this (never the artifact-aware ``stage_status``) to decide
    whether they may return reference numbers, so a stored artifact can never cause
    lung reference content to be attached to some other combination.
    """
    if stage == "B":
        return layer_exists(organ_id, layer_id)
    if stage == "C":
        return grn_available(organ_id, layer_id, route)
    if stage in ("D", "E"):
        return _is_reference_transition(organ_id, layer_id, source, target)
    if stage == "F":
        return _is_reference_transition(organ_id, layer_id, source, target) and species in config.REFERENCE_CASE["species"]
    return False


def stage_status(
    stage: str,
    organ_id: str,
    layer_id: str,
    source: Optional[str] = None,
    target: Optional[str] = None,
    species: str = "human",
    route: str = "scenicplus",
    engine_params: Optional[Dict[str, Any]] = None,
) -> str:
    """Return ``cached`` | ``not_computed`` for one stage under the given parameters.

    (``running`` is a live value set by the job queue, not by this static index.)
    """
    if not organ_implemented(organ_id):
        return "not_computed"
    if stage == "A":
        return "cached"
    if reference_cached(stage, organ_id, layer_id, source, target, species, route):
        return "cached"
    ident = artifacts.identity_for(stage, organ_id, layer_id, source, target, species, route, engine_params)
    return "cached" if artifacts.exists(ident) else "not_computed"


def run_id(organ_id: str, layer_id: str, source: Optional[str], target: Optional[str], species: str) -> str:
    return "|".join([organ_id or "", layer_id or "", source or "", target or "", species or ""])


def run_index(
    organ_id: str,
    layer_id: str,
    source: Optional[str] = None,
    target: Optional[str] = None,
    species: str = "human",
    route: str = "scenicplus",
) -> Dict[str, Any]:
    """The ``GET /runs`` payload: run id + per-stage cached/not_computed status.

    Live ``running`` states are overlaid by the job queue in ``app.py``.
    """
    stages = {
        s: stage_status(s, organ_id, layer_id, source, target, species, route) for s in STAGE_IDS
    }
    return {
        "run_id": run_id(organ_id, layer_id, source, target, species),
        "params": {
            "organ": organ_id,
            "layer": layer_id,
            "source": source,
            "target": target,
            "species": species,
            "route": route,
        },
        "stages": stages,
    }
