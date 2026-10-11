"""Stage B — Developmental atlas (async job).

GET  /stage/B?organ=lung&layer=epithelial
  -> { atlas, states, source_datasets, artifact_uri }
POST /stage/B/run { organ, layer } -> { job_id }

Backing: the lung reference atlas summary (seed layer stats + ALL_lineage_state_TFs.csv),
or an organ bundle's layers for any other organ (organ_bundles.py). The integrated
*_subatlas.h5ad files are external and multi-GB; a fresh scVI/scANVI recompute is
refused honestly with the list of what is missing.
"""

from __future__ import annotations

from typing import Any, Dict

from .. import config, data_loader, registry
from ..jobs import ComputeUnavailable


def _states_with_padj(organ: str, layer_id: str, layer: Dict[str, Any]) -> Dict[str, Any]:
    """States (role + top master TFs); lung states are enriched with padj from the full table."""
    padj_table = {}
    if organ == config.REFERENCE_CASE["organ"]:
        padj_table = data_loader.get().state_tfs_table().get(layer["name"].lower(), {})
    out: Dict[str, Any] = {}
    for state_name, state in layer["states"].items():
        padj_lookup = {r["tf"]: r["padj"] for r in padj_table.get(state_name, [])}
        tfs = []
        for t in state["master_tfs"]:
            entry = {"tf": t["tf"], "logFC": t["logFC"]}
            if t["tf"] in padj_lookup:
                entry["padj"] = padj_lookup[t["tf"]]
            tfs.append(entry)
        out[state_name] = {"role": state["role"], "master_tfs": tfs}
    return out


def get(organ: str = "lung", layer: str = "epithelial") -> Dict[str, Any]:
    if not registry.organ_implemented(organ):
        o = registry.organ(organ) or {}
        return {
            "status": "not_computed",
            "organ": organ,
            "layer": layer,
            "note": o.get("note", "Planned organ — developmental atlas not yet assembled."),
        }
    ld = registry.layer_data(organ, layer)
    if ld is None:
        return {"status": "not_computed", "organ": organ, "layer": layer, "note": "Unknown cell layer."}

    ds = data_loader.get()
    a = ld["atlas"]
    is_reference = organ == config.REFERENCE_CASE["organ"]
    return {
        "status": "cached",
        "organ": organ,
        "layer": layer,
        "atlas": {
            "cells": a["cells"],
            "donors": a["donors"],
            "n_states": a["n_states"],
            "phase_coverage": {
                "fetal": a["fetal"],
                "perinatal": a["perinatal"],
                "adult_aging": a["adult_aging"],
            },
        },
        "states": _states_with_padj(organ, layer, ld),
        "source_datasets": ds.dev_datasets if is_reference else ld.get("source_datasets", []),
        "artifact_uri": f"external://artifact-store/{organ}/{layer}_subatlas.h5ad",
        "artifact_status": "external_not_in_bundle",
        "method_note": (
            "Per-lineage scVI/scANVI integration, raw counts retained; states via "
            "Leiden + DE master-TF calling (pySCENIC TF list). See CONSTRUCTION_README.md."
        ),
    }


def run(job) -> Dict[str, Any]:
    p = job.params
    organ, layer = p.get("organ", "lung"), p.get("layer", "epithelial")
    if registry.reference_cached("B", organ, layer):
        job.progress = "loading cached sub-atlas summary"
        return get(organ, layer)
    raise ComputeUnavailable(
        f"No cached atlas for organ='{organ}', layer='{layer}'. Assembling it needs the source "
        "datasets and an scVI/scANVI integration; see the requirements listed for this stage."
    )
