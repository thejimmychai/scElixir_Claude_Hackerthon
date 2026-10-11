"""Stage E — Small-molecule mirror (LINCS is a web call).

GET  /stage/E?organ=lung&layer=epithelial&source=AT2&target=Tip%20(fetal)[&engine=...]
  -> { compounds, curated, single_cell_confirm }
POST /stage/E/run { organ, layer, source, target, signature: {up, down}, lung_only } -> { job_id }

Backing: AT2_to_TiP_compounds.csv, lung_AT2_to_progenitor_small_molecules.csv,
AT2_to_TiP_tahoe_validation.csv. A custom signature runs a live query through
tf_to_drug_connectivity.py:

  * genes in ``up``   -> direction "mimic":  LINCS compounds whose UP signatures
                         reproduce the TF program
  * genes in ``down`` -> direction "reverse": compounds whose UP signatures oppose it

Each direction is queried separately and the hits are tagged with the direction
they came from. Results from live queries are saved as artifacts keyed by the
canonical signature, so the same signature is served again without re-querying.
"""

from __future__ import annotations

import importlib.util
import math
import os
import re
import sys
from typing import Any, Dict, List, Optional

from .. import artifacts, config, data_loader, registry
from ..jobs import ComputeUnavailable

GENE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-]{0,39}$")
MAX_GENES = 500
ENGINE_KEYS = ("signature", "lung_only")


# --------------------------------------------------------------------------- #
# request canonicalisation (shared by the POST validator and GET lookups)     #
# --------------------------------------------------------------------------- #
def canonical_signature(sig: Any) -> Dict[str, List[str]]:
    """Validate and canonicalise an ``{up, down}`` gene signature.

    Genes are upper-cased, de-duplicated and sorted, so the same signature always
    maps to the same artifact identity (guardrail 5). Raises ValueError otherwise.
    """
    if not isinstance(sig, dict):
        raise ValueError("signature must be an object with 'up' and/or 'down' gene lists")
    extra = set(sig) - {"up", "down"}
    if extra:
        raise ValueError(f"unknown signature keys: {', '.join(sorted(extra))}")
    out: Dict[str, List[str]] = {}
    for key in ("up", "down"):
        genes = sig.get(key, [])
        if not isinstance(genes, list) or any(not isinstance(g, str) for g in genes):
            raise ValueError(f"signature.{key} must be a list of gene symbols")
        clean = sorted({g.strip().upper() for g in genes if g.strip()})
        bad = [g for g in clean if not GENE_RE.match(g)]
        if bad:
            raise ValueError(f"invalid gene symbols in signature.{key}: {', '.join(bad[:5])}")
        if len(clean) > MAX_GENES:
            raise ValueError(f"signature.{key} has more than {MAX_GENES} genes")
        out[key] = clean
    if not out["up"] and not out["down"]:
        raise ValueError("signature needs at least one gene in 'up' or 'down'")
    return out


def canonical_engine(engine: Dict[str, Any]) -> Dict[str, Any]:
    """Canonical engine parameters for Stage E (raises ValueError on bad input)."""
    extra = set(engine) - set(ENGINE_KEYS)
    if extra:
        raise ValueError(f"unknown engine parameters for Stage E: {', '.join(sorted(extra))}")
    out: Dict[str, Any] = {}
    if engine.get("signature") is not None:
        out["signature"] = canonical_signature(engine["signature"])
    out["lung_only"] = bool(engine.get("lung_only", False))
    return out


# --------------------------------------------------------------------------- #
# reference (cached) nominations                                              #
# --------------------------------------------------------------------------- #
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
    if registry.reference_cached("E", organ, layer, source, target):
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
# live connectivity query                                                     #
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
            f"connectivity engine dependencies missing ({exc}); need requests, numpy, pandas and scipy"
        ) from exc
    return module


def _json_safe(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Replace NaN with None so the payload is strict JSON."""
    out = []
    for r in records:
        out.append({k: (None if isinstance(v, float) and math.isnan(v) else v) for k, v in r.items()})
    return out


def live_connectivity(up: List[str], down: List[str], lung_only: bool = False) -> Dict[str, Any]:
    """Live LINCS L1000 connectivity + Tahoe cross-reference for a {up, down} signature."""
    engine = _load_engine()
    records: List[Dict[str, Any]] = []
    try:
        tahoe = engine.load_tahoe_drugs()
        for genes, direction in ((up, "mimic"), (down, "reverse")):
            if not genes:
                continue
            conn = engine.connectivity_query(genes, direction=direction, lung_only=lung_only)
            conn = engine.cross_ref_tahoe(conn, tahoe)
            records.extend(conn.to_dict(orient="records"))
    except ComputeUnavailable:
        raise
    except Exception as exc:  # network / API failure
        raise ComputeUnavailable(f"live LINCS/Tahoe query failed: {exc}") from exc
    return {
        "status": "cached",
        "mode": "live",
        "signature": {"up": up, "down": down},
        "lung_only": lung_only,
        "directions": {
            "mimic": "hits whose UP signatures reproduce the 'up' genes",
            "reverse": "hits whose UP signatures oppose the 'up' genes (their overlap is the 'down' side)",
        },
        "compounds": _json_safe(records),
        "evidence": "in_silico",
    }


def run(job) -> Dict[str, Any]:
    p = job.params
    organ = p.get("organ", "lung")
    layer = p.get("layer", "epithelial")
    source, target = p.get("source"), p.get("target")
    signature = p.get("signature")

    if signature:
        # A stored artifact for this exact signature is answered by the app before a job
        # is ever created (app.route_post), so this path always computes.
        engine = canonical_engine({"signature": signature, "lung_only": p.get("lung_only", False)})
        ident = artifacts.identity_for("E", organ, layer, source, target, engine_params=engine)
        job.progress = "querying LINCS L1000 + Tahoe-100M"
        sig = engine["signature"]
        result = live_connectivity(sig["up"], sig["down"], engine["lung_only"])
        result["artifact_uri"] = artifacts.save(ident, result)
        return result

    if registry.reference_cached("E", organ, layer, source, target):
        job.progress = "loading cached compound nominations"
        return _cached(organ, layer, source, target)

    raise ComputeUnavailable(
        f"No cached compounds for {organ}/{layer} {source} -> {target}, and no signature was "
        "supplied. Provide {up, down} genes to run a live connectivity query, or select the "
        "cached lung epithelial AT2 -> fetal distal-tip case."
    )
