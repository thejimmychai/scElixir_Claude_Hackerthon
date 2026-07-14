"""Stage D — In-silico reversal -> TF recipe (async job).

GET  /stage/D?organ=lung&layer=epithelial&source=AT2&target=Tip%20(fetal)&species=human
  -> { recipe, modules, screen, artifact_uri }
POST /stage/D/run { organ, layer, source, target, species, ... } -> { job_id }

Backing: AT2_to_TiP_TF_recipe.csv, lung_AT2_to_progenitor_TF_scheme.csv,
insilico_TF_perturbation_screen.csv, alternative_stagewise_TF_scheme.csv.
Only the AT2 -> fetal distal-tip transition was actually run; other transitions
report not_computed (no fabricated recipe — guardrail 1).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .. import config, data_loader, registry, store
from ..jobs import ComputeUnavailable

# The screen ships as the fibroblast-OSKM KO/OE scan that demonstrates the
# projection method; return the strongest-magnitude rows for compactness.
SCREEN_TOP = 60


def get(
    organ: str = "lung",
    layer: str = "epithelial",
    source: Optional[str] = None,
    target: Optional[str] = None,
    species: str = "human",
) -> Dict[str, Any]:
    if registry.stage_status("D", organ, layer, source, target, species) != "cached":
        return {
            "status": "not_computed",
            "organ": organ, "layer": layer, "source": source, "target": target, "species": species,
            "note": (
                "In-silico reversal was executed for the lung epithelial "
                "AT2 -> fetal distal-tip transition. Select that combination for the "
                "real 11-TF recipe. For any other transition, run the CellOracle KO/OE "
                "screen projected onto the transition vector (no recipe is fabricated)."
            ),
        }

    ds = data_loader.get()
    screen = ds.tf_screen()
    top_screen = sorted(screen, key=lambda r: abs(r["projection"] or 0.0), reverse=True)[:SCREEN_TOP]
    return {
        "status": "cached",
        "organ": organ, "layer": layer, "source": source, "target": target, "species": species,
        "recipe": ds.tf_recipe(),
        "modules": ds.tf_modules(),
        "screen": top_screen,
        "screen_note": (
            "Raw KO/OE scan from the reprogramming-landscape session (fibroblast->pluripotent "
            "OSKM), demonstrating the transition-vector projection method Stage D applies."
        ),
        "alt_schemes": ds.alt_schemes(),
        "evidence": "in_silico",
        "artifact_uri": "external://artifact-store/AT2_to_TiP_reversal.json",
        "artifact_status": "external_not_in_bundle",
    }


def run(job) -> Dict[str, Any]:
    p = job.params
    organ = p.get("organ", "lung")
    layer = p.get("layer", "epithelial")
    source, target, species = p.get("source"), p.get("target"), p.get("species", "human")
    if registry.stage_status("D", organ, layer, source, target, species) == "cached":
        job.progress = "loading cached TF recipe"
        result = get(organ, layer, source, target, species)
        key = store.make_key("D", organ, layer, source, target, species, p.get("engine_params"))
        result["artifact_uri"] = store.put(key, result)
        return result
    raise ComputeUnavailable(
        f"No cached TF recipe for {organ}/{layer} {source} -> {target}. Producing one needs "
        "the layer's GRN (Stage C) + CellOracle simulate_shift projected onto the transition "
        f"vector. Only {config.REFERENCE_CASE['source']} -> {config.REFERENCE_CASE['target']} "
        "(lung epithelial) is cached."
    )
