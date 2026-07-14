"""Stage E — Small-molecule mirror (LINCS is a web call).

GET  /stage/E?organ=lung&layer=epithelial&source=AT2&target=Tip%20(fetal)
  -> { compounds, curated, single_cell_confirm }
POST /stage/E/run { organ, layer, source, target, signature?, lung_only? } -> { job_id }

Backing: AT2_to_TiP_compounds.csv, lung_AT2_to_progenitor_small_molecules.csv,
AT2_to_TiP_tahoe_validation.csv. Engine: tf_to_drug_connectivity.py
(connectivity_query + cross_ref_tahoe). When a custom signature is supplied and
the engine's deps + network are available, a live LINCS/Tahoe query runs;
otherwise the cached reference nominations are served.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from typing import Any, Dict, List, Optional

from .. import config, data_loader, registry, store
from ..jobs import ComputeUnavailable


def _cached(organ: str, layer: str, source: Optional[str], target: Optional[str]) -> Dict[str, Any]:
    ds = data_loader.get()
    return {
        "status": "cached",
        "organ": organ, "layer": layer, "source": source, "target": target,
        "compounds": ds.compounds(),
        "curated": ds.curated_compounds(),
        "single_cell_confirm": ds.tahoe_validation(),
        "evidence": "in_silico",
        "source_note": (
            "Compounds ranked by LINCS L1000 connectivity to the reprogramming objective "
            "(induce Tip, suppress AT2, suppress club/ciliated); confirmed in Tahoe-100M."
        ),
    }


def get(
    organ: str = "lung",
    layer: str = "epithelial",
    source: Optional[str] = None,
    target: Optional[str] = None,
) -> Dict[str, Any]:
    if registry.stage_status("E", organ, layer, source, target) == "cached":
        return _cached(organ, layer, source, target)
    return {
        "status": "not_computed",
        "organ": organ, "layer": layer, "source": source, "target": target,
        "note": (
            "Compound nomination was executed for lung epithelial AT2 -> fetal distal-tip. "
            "Select that combination for the ranked nominations + curated cocktail, or POST "
            "a custom {up, down} signature to run a live LINCS/Tahoe query."
        ),
    }


# --------------------------------------------------------------------------- #
# live connectivity query (best effort)                                       #
# --------------------------------------------------------------------------- #
def _load_engine():
    path = os.path.join(config.ENGINE_DIR, "tf_to_drug_connectivity.py")
    if not os.path.exists(path):
        raise ComputeUnavailable("connectivity engine module not found")
    if config.ENGINE_DIR not in sys.path:
        sys.path.insert(0, config.ENGINE_DIR)
    spec = importlib.util.spec_from_file_location("tf_to_drug_connectivity", path)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)  # type: ignore[union-attr]
    except ImportError as exc:
        raise ComputeUnavailable(
            f"connectivity engine dependencies missing ({exc}); need requests/numpy/pandas/scipy"
        ) from exc
    return module


def live_connectivity(up: List[str], down: List[str], lung_only: bool = False) -> Dict[str, Any]:
    """Run a live LINCS L1000 connectivity query + Tahoe cross-ref for a signature."""
    engine = _load_engine()
    signature = {"up": up, "down": down}
    try:
        conn = engine.connectivity_query(signature, direction="mimic", lung_only=lung_only)
        conn = engine.cross_ref_tahoe(conn)
    except Exception as exc:  # network / API failure
        raise ComputeUnavailable(f"live LINCS/Tahoe query failed: {exc}") from exc
    records = conn.to_dict(orient="records") if hasattr(conn, "to_dict") else list(conn)
    return {
        "status": "cached",
        "mode": "live",
        "signature": signature,
        "lung_only": lung_only,
        "compounds": records,
        "evidence": "in_silico",
    }


def run(job) -> Dict[str, Any]:
    p = job.params
    organ = p.get("organ", "lung")
    layer = p.get("layer", "epithelial")
    source, target = p.get("source"), p.get("target")
    signature = p.get("signature")

    if signature and (signature.get("up") or signature.get("down")):
        job.progress = "querying LINCS L1000 + Tahoe-100M"
        result = live_connectivity(
            signature.get("up", []), signature.get("down", []), bool(p.get("lung_only"))
        )
        key = store.make_key("E", organ, layer, source, target, engine_params={"signature": signature, "lung_only": bool(p.get("lung_only"))})
        result["artifact_uri"] = store.put(key, result)
        return result

    if registry.stage_status("E", organ, layer, source, target) == "cached":
        job.progress = "loading cached compound nominations"
        result = _cached(organ, layer, source, target)
        key = store.make_key("E", organ, layer, source, target, engine_params=p.get("engine_params"))
        result["artifact_uri"] = store.put(key, result)
        return result

    raise ComputeUnavailable(
        f"No cached compounds for {organ}/{layer} {source} -> {target}, and no signature "
        "supplied. Provide {up, down} genes to run a live connectivity query, or select the "
        "cached lung epithelial AT2 -> fetal distal-tip case."
    )
