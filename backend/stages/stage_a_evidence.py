"""Stage A — Evidence base (synchronous; organ-independent).

GET /stage/A?organ=lung
  -> { datasets: [...], drug_engine: {...} }

Backing: perturbseq_datasets_catalog.csv (36 rows) + the TF->drug connectivity
engine (tf_to_drug_connectivity.py). Every catalog row carries a recorded
verify_status; the response exposes it verbatim rather than asserting a blanket
"verified". The engine health comes from the shared capability report.
"""

from __future__ import annotations

from typing import Any, Dict

from .. import capabilities, data_loader, registry


def _drug_engine_health() -> Dict[str, Any]:
    eng = capabilities.engine_report()["lincs_tahoe"]
    return {
        "libraries": ["LINCS L1000 (via Enrichr)"],
        "confirm": "Tahoe-100M",
        "engine_module": "backend/engine/tf_to_drug_connectivity.py",
        "status": "ready" if eng["available"] else "unavailable",
        "live_query_available": eng["available"],
        "missing_dependencies": eng["missing_modules"],
        "network": eng["network"],
        "note": (
            "Live LINCS/Tahoe queries need the listed Python packages and network access "
            "to the hosts above. The reference nominations are always served from the cache."
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
