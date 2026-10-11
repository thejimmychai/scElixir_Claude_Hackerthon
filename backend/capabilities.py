"""Compute capability report — what this machine can actually run.

Three jobs:
  1. ``GET /compute/status`` shows the honest state of every engine.
  2. Every not_computed stage carries a concrete ``requires`` list.
  3. Jobs that cannot run fail with the same list instead of a vague message.

Checks use ``importlib.util.find_spec`` and ``os.path`` only, so nothing heavy is
imported and the report is cheap enough to build on every request.
"""

from __future__ import annotations

import importlib.util
import os
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from . import config, organ_bundles

# pertformer_io_contract.json: "weights_hf ... (~12.8 GB, 11 .pkl files ...)"
PERTFORMER_WEIGHT_FILES = 11

ENGINES: Dict[str, Dict[str, Any]] = {
    "lincs_tahoe": {
        "label": "LINCS L1000 + Tahoe-100M connectivity (live)",
        "stages": ["A", "E"],
        "modules": ["requests", "numpy", "pandas", "scipy"],
        "files": ["backend/engine/tf_to_drug_connectivity.py"],
        "network": ["maayanlab.cloud", "datasets-server.huggingface.co"],
    },
    "scvi_atlas": {
        "label": "scVI / scANVI per-lineage atlas integration",
        "stages": ["B"],
        "modules": ["scvi", "scanpy", "anndata"],
        "inputs": ["{organ}/{layer}_subatlas.h5ad"],
        "notes": ["Source datasets from CELLxGENE Census / GEO (see docs/CONSTRUCTION_README.md)"],
        "hardware": "CPU (10–40 min per lineage); GPU at scale",
    },
    "celloracle": {
        "label": "CellOracle base-GRN + simulate_shift (CPU)",
        "stages": ["C", "D"],
        "modules": ["celloracle", "scanpy", "anndata"],
        "files": ["backend/engine/celloracle_local.py"],
        "inputs": ["{organ}/{layer}_subatlas.h5ad"],
        "notes": ["Stage D projects KO/OE shifts onto the transition vector of this layer's GRN"],
    },
    "scenicplus": {
        "label": "SCENIC+ enhancer-aware eRegulons (GPU)",
        "stages": ["C"],
        "modules": ["scenicplus"],
        "inputs": ["{organ}/{layer}_multiome.h5mu"],
        "notes": ["cisTarget hg38 database (~47 GB)", "matched scATAC for the layer"],
        "hardware": "GPU host (RTX 4090 class) with the cisTarget database",
    },
    "pertformer": {
        "label": "PertFormer DNA+ATAC fate inference (GPU)",
        "stages": ["F"],
        "modules": ["torch", "einops"],
        "files": ["backend/engine/run_pertformer.py"],
        "weights": True,
        "notes": ["DNA+ATAC tracks (bigWig + peak set) for the adult, progenitor and TF-KI states"],
        "hardware": "CUDA GPU; A100 80 GB recommended",
    },
}

STAGE_NOTES: Dict[str, List[str]] = {
    "E": ["A gene signature {up, down} for a live query, or the cached lung AT2 -> fetal distal-tip case"],
}

NETWORK_HOSTS = sorted({h for spec in ENGINES.values() for h in spec.get("network", [])})


def _missing_modules(names: List[str]) -> List[str]:
    return [n for n in names if importlib.util.find_spec(n) is None]


def weights_dir() -> str:
    return os.environ.get("PF_WEIGHTS", "/weights")


def _weights_status() -> Dict[str, Any]:
    d = weights_dir()
    if not os.path.isdir(d):
        return {"ok": False, "detail": f"{d} not found (set PF_WEIGHTS to the weights folder)"}
    n = sum(1 for f in os.listdir(d) if f.endswith(".pkl"))
    ok = n >= PERTFORMER_WEIGHT_FILES
    return {"ok": ok, "detail": f"{n} .pkl files at {d} (expected {PERTFORMER_WEIGHT_FILES})"}


def engine_report() -> Dict[str, Dict[str, Any]]:
    """Local availability of every engine: modules, files and weights (no network)."""
    out: Dict[str, Dict[str, Any]] = {}
    for name, spec in ENGINES.items():
        missing_mod = _missing_modules(spec.get("modules", []))
        missing_files = [
            f for f in spec.get("files", []) if not os.path.exists(os.path.join(config.ROOT, f))
        ]
        weights = _weights_status() if spec.get("weights") else None
        available = not missing_mod and not missing_files and (weights is None or weights["ok"])
        out[name] = {
            "label": spec["label"],
            "stages": spec["stages"],
            "available": available,
            "missing_modules": missing_mod,
            "missing_files": missing_files,
            "weights": weights,
            "hardware": spec.get("hardware"),
            "network": spec.get("network", []),
            "notes": spec.get("notes", []),
        }
    return out


def probe_network(timeout: float = 4.0) -> Dict[str, Dict[str, Any]]:
    """Check whether the external hosts answer. Any HTTP reply counts as reachable."""
    result: Dict[str, Dict[str, Any]] = {}
    for host in NETWORK_HOSTS:
        try:
            req = urllib.request.Request(f"https://{host}/", method="HEAD")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                result[host] = {"reachable": True, "status": resp.status}
        except urllib.error.HTTPError as exc:  # the server answered
            result[host] = {"reachable": True, "status": exc.code}
        except Exception as exc:  # noqa: BLE001 — DNS, TLS, timeout, offline
            result[host] = {"reachable": False, "error": type(exc).__name__}
    return result


def report(probe: bool = False) -> Dict[str, Any]:
    rep: Dict[str, Any] = {
        "engines": engine_report(),
        "organ_bundles": {
            oid: {"valid": v["valid"], "errors": v["errors"]}
            for oid, v in organ_bundles.scan().items()
        },
        "paths": {
            "external_inputs": config.EXTERNAL_DIR,
            "results": config.RESULTS_DIR,
            "organ_bundles": config.ORGANS_DIR,
        },
        "note": (
            "Availability is checked locally (modules, files, weights). Network "
            "reachability is only probed when requested with ?probe=1."
        ),
    }
    if probe:
        rep["network"] = probe_network()
    return rep


def requirements(
    stage: str,
    organ: Optional[str],
    layer: Optional[str],
    route: Optional[str] = None,
) -> List[str]:
    """Concrete, human-readable list of what is missing for one stage."""
    if stage == "A":
        return []
    rep = engine_report()
    engines = [name for name, spec in ENGINES.items() if stage in spec["stages"]]
    if stage == "C" and route in ("scenicplus", "celloracle"):
        engines = [route]

    items: List[str] = []
    for name in engines:
        spec, eng = ENGINES[name], rep[name]
        label = spec["label"]
        if eng["missing_modules"]:
            items.append(f"{label}: Python packages not installed ({', '.join(eng['missing_modules'])})")
        for f in eng["missing_files"]:
            items.append(f"{label}: engine file missing ({f})")
        if eng["weights"] is not None and not eng["weights"]["ok"]:
            items.append(f"{label}: PertFormer weights not found — {eng['weights']['detail']}")
        if organ and layer:
            for template in spec.get("inputs", []):
                rel = template.format(organ=organ, layer=layer)
                if not os.path.exists(os.path.join(config.EXTERNAL_DIR, rel)):
                    items.append(f"Input not present: data/external/{rel}")
        for note in spec.get("notes", []):
            items.append(f"{label}: {note}")
    items.extend(STAGE_NOTES.get(stage, []))

    seen, unique = set(), []
    for item in items:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique
