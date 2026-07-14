"""Stage B — Developmental atlas (async job).

GET  /stage/B?organ=lung&layer=epithelial
  -> { atlas, states, source_datasets, artifact_uri }
POST /stage/B/run { organ, layer } -> { job_id }

Backing: the integrated *_subatlas.h5ad (external, multi-GB — not in the bundle)
summarised by the seed layer stats + ALL_lineage_state_TFs.csv. The read returns
the cached summary; a fresh recompute (scVI/scANVI) is a real GPU-scale job and
is refused honestly when no cached result exists.
"""

from __future__ import annotations

from typing import Any, Dict

from .. import data_loader, registry, store
from ..jobs import ComputeUnavailable


def _states_with_padj(layer_id: str) -> Dict[str, Any]:
    """Seed states (role + top master TFs), enriched with padj where available."""
    ds = data_loader.get()
    layer = ds.layers[layer_id]
    padj_table = ds.state_tfs_table().get(ds.layers[layer_id]["name"].lower(), {})
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
    if not registry.layer_exists(organ, layer):
        return {"status": "not_computed", "organ": organ, "layer": layer, "note": "Unknown cell layer."}

    ds = data_loader.get()
    l = ds.layers[layer]
    a = l["atlas"]
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
        "states": _states_with_padj(layer),
        "source_datasets": ds.dev_datasets,
        "artifact_uri": f"external://artifact-store/{layer}_subatlas.h5ad",
        "artifact_status": "external_not_in_bundle",
        "method_note": (
            "Per-lineage scVI/scANVI integration, raw counts retained; states via "
            "Leiden + DE master-TF calling (pySCENIC TF list). See CONSTRUCTION_README.md."
        ),
    }


def run(job) -> Dict[str, Any]:
    p = job.params
    organ, layer = p.get("organ", "lung"), p.get("layer", "epithelial")
    if registry.stage_status("B", organ, layer) == "cached":
        job.progress = "loading cached sub-atlas summary"
        result = get(organ, layer)
        key = store.make_key("B", organ, layer, engine_params=p.get("engine_params"))
        result["artifact_uri"] = store.put(key, result)
        return result
    raise ComputeUnavailable(
        f"No cached atlas for organ='{organ}', layer='{layer}'. Assembling it requires "
        "CELLxGENE/GEO retrieval + scVI/scANVI integration (CPU->GPU at scale), which is "
        "not available in this bundle. Only the lung reference atlas is cached."
    )
