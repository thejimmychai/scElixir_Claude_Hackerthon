"""Stage F — Deep-learning fate validation (async GPU job).

GET  /stage/F?organ=lung&layer=epithelial&source=AT2&target=Tip%20(fetal)&species=human
  -> { fate, tf_set, species, compare }
POST /stage/F/run { organ, layer, source, target, species, tf_set, ... } -> { job_id }

Backing: distaltf_fate_proximity_readout.json (recipe cocktail) +
fate_proximity_readout.json (OSKM baseline). Both species were run, and species
is a real parameter (guardrail 3): human AT2 has headroom toward the tip, mouse
AT2 already sits adjacent to its E17.5 tip. A fresh recompute needs an A100 +
the 3B-param PertFormer weights, so uncached combinations are refused honestly.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .. import config, data_loader, registry, store
from ..jobs import ComputeUnavailable

# The reference distal-TF knock-in cocktail (motif-bearing TFs).
DISTAL_TF_SET = ["SOX9", "NKX2-1", "ETV5", "ETV4"]
OSKM_TF_SET = ["POU5F1", "SOX2", "KLF4", "MYC"]


def _fate_for_species(species: str) -> Dict[str, Any]:
    ds = data_loader.get()
    distal = ds.fate_distal()[species]
    oskm = ds.fate_oskm()[species]
    return {
        "fate": {
            "ref_cos": distal["cos_AT2ref_to_tip"],
            "ki_cos": distal["cos_AT2_KI_to_tip"],
            "delta_proximity": distal["delta_proximity"],
            "n_genes": distal["n_genes"],
            "panel": distal["genes"],
            "per_gene": None,  # aggregate cosine only in cached readout; no per-gene fabrication
        },
        "cocktails": {
            "distalTF": {
                "tf_set": DISTAL_TF_SET,
                "ref_cos": distal["cos_AT2ref_to_tip"],
                "ki_cos": distal["cos_AT2_KI_to_tip"],
                "delta": distal["delta_proximity"],
            },
            "OSKM": {
                "tf_set": OSKM_TF_SET,
                "ref_cos": oskm["cos_AT2ref_to_tip"],
                "ki_cos": oskm["cos_AT2_OSKM_KI_to_tip"],
                "delta": oskm["delta_proximity"],
            },
        },
        "compare": {
            "OSKM": {"delta": oskm["delta_proximity"]},
            "distalTF": {"delta": distal["delta_proximity"]},
        },
    }


def get(
    organ: str = "lung",
    layer: str = "epithelial",
    source: Optional[str] = None,
    target: Optional[str] = None,
    species: str = "human",
    tf_set: Optional[List[str]] = None,
) -> Dict[str, Any]:
    if registry.stage_status("F", organ, layer, source, target, species) != "cached":
        return {
            "status": "not_computed",
            "organ": organ, "layer": layer, "source": source, "target": target, "species": species,
            "note": (
                "Fate validation was run for lung epithelial AT2 -> fetal distal-tip in both "
                "human and mouse. Select that combination for the real PertFormer cosine "
                "fate-proximity comparison. A new run dispatches the 3B-param model to an A100."
            ),
            "model": data_loader.get().pertformer_contract()["model"],
        }

    payload = _fate_for_species(species)
    return {
        "status": "cached",
        "organ": organ, "layer": layer, "source": source, "target": target, "species": species,
        "tf_set": tf_set or DISTAL_TF_SET,
        "evidence": "in_silico",
        "model": data_loader.get().pertformer_contract()["model"],
        **payload,
    }


def run(job) -> Dict[str, Any]:
    p = job.params
    organ = p.get("organ", "lung")
    layer = p.get("layer", "epithelial")
    source, target, species = p.get("source"), p.get("target"), p.get("species", "human")
    tf_set = p.get("tf_set")
    if registry.stage_status("F", organ, layer, source, target, species) == "cached":
        job.progress = "loading cached PertFormer fate readout"
        result = get(organ, layer, source, target, species, tf_set)
        key = store.make_key("F", organ, layer, source, target, species,
                             engine_params={"tf_set": tf_set, **(p.get("ki_params") or {})})
        result["artifact_uri"] = store.put(key, result)
        return result
    raise ComputeUnavailable(
        f"No cached fate readout for {organ}/{layer} {source} -> {target} ({species}). PertFormer "
        "inference needs an A100 + the ~12.8 GB 3B-param weights (HuggingFace "
        "GenomicIntelligenceDamoAcademy/pertformer) and DNA+ATAC tracks; only the lung "
        "epithelial AT2 -> fetal distal-tip case (human & mouse) is cached."
    )
