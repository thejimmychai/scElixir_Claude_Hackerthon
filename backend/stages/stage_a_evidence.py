"""Stage A — Evidence base (synchronous; organ-independent).

GET /stage/A?organ=lung
  -> { datasets: [...], drug_engine: {...} }

Backing: perturbseq_datasets_catalog.csv (36 rows) + the TF->drug connectivity
engine (tf_to_drug_connectivity.py). Every catalog row carries a recorded
verify_status; the response exposes it verbatim rather than asserting a blanket
"verified".
"""

from __future__ import annotations

import importlib
import os
from typing import Any, Dict

from .. import config, data_loader, registry


def _drug_engine_health() -> Dict[str, Any]:
    """Report whether the connectivity engine can run a live query here.

    The engine needs requests/numpy/pandas/scipy plus network reachability to
    maayanlab.cloud (Enrichr/LINCS) and datasets-server.huggingface.co (Tahoe).
    We report the true local state instead of hard-coding "ready".
    """
    engine_present = os.path.exists(os.path.join(config.ENGINE_DIR, "tf_to_drug_connectivity.py"))
    missing = []
    for mod in ("requests", "numpy", "pandas", "scipy"):
        try:
            importlib.import_module(mod)
        except ImportError:
            missing.append(mod)
    live = engine_present and not missing
    return {
        "libraries": ["LINCS L1000 (via Enrichr)"],
        "confirm": "Tahoe-100M",
        "engine_module": "backend/engine/tf_to_drug_connectivity.py",
        "status": "ready" if engine_present else "missing",
        "live_query_available": live,
        "missing_dependencies": missing,
        "note": (
            "Connectivity engine wired for Stage E. Live LINCS/Tahoe query "
            "requires the listed packages + network access; when unavailable the "
            "cached reference nominations are served."
        ),
    }


def get(organ: str = "lung") -> Dict[str, Any]:
    if not registry.organ_implemented(organ):
        o = registry.organ(organ) or {}
        return {
            "status": "not_computed",
            "organ": organ,
            "note": o.get("note", "Planned organ — evidence catalog not yet assembled."),
            "datasets": [],
            "drug_engine": _drug_engine_health(),
        }
    ds = data_loader.get()
    return {
        "status": "cached",
        "organ": organ,
        "datasets": ds.evidence_catalog(),
        "drug_engine": _drug_engine_health(),
    }
