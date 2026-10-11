"""Filesystem layout for the backend.

Everything is resolved relative to the bundle root (the directory that contains
``backend/``, ``frontend/`` and ``data/``) so the app is position-independent:
copy the bundle anywhere, or run it in place.
"""

from __future__ import annotations

import os

# <root>/backend/config.py  ->  <root>
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BACKEND_DIR = os.path.join(ROOT, "backend")
ENGINE_DIR = os.path.join(BACKEND_DIR, "engine")
DATA_DIR = os.path.join(ROOT, "data", "reference")
FRONTEND_DIR = os.path.join(ROOT, "frontend")
SEED_PATH = os.path.join(FRONTEND_DIR, "seed", "pipeline_seed_data.json")

# Large inputs that are not in the bundle (integrated sub-atlases, multiome files)
# are dropped here by the user; capabilities.py checks for them by path.
EXTERNAL_DIR = os.path.join(ROOT, "data", "external")
# Durable results written by runs that actually computed something (artifacts.py).
RESULTS_DIR = os.path.join(ROOT, "data", "results")
# Organ bundles for organs beyond the lung reference (organ_bundles.py).
ORGANS_DIR = os.path.join(ROOT, "data", "organs")

# The one worked reference case (all six stages executed). Used by the store /
# registry to decide which (organ, layer, source, target) combinations have a
# real cached result vs. must report ``not_computed``.
REFERENCE_CASE = {
    "organ": "lung",
    "layer": "epithelial",
    "source": "AT2",
    "target": "Tip (fetal)",
    "species": ("human", "mouse"),  # both species were run in Stage F
}

# Stage-C routes the API accepts, and the (organ, layer, route) combinations whose
# GRN actually exists. The reference GRN_network_scores_enhancer.csv is the
# SCENIC+ (enhancer-aware) run for lung epithelial; no CellOracle GRN is cached.
GRN_ROUTES = ("scenicplus", "celloracle")
GRN_COMPUTED = {("lung", "epithelial", "scenicplus")}

HOST_DEFAULT = "127.0.0.1"
PORT_DEFAULT = int(os.environ.get("REPRO_PORT", "8765"))

# Default source/target state per layer for the reversal selectors. These are
# the sensible starting transitions the UI pre-selects; they were part of the
# original standalone blueprint and are not derivable from the atlas stats.
LAYER_DEFAULTS = {
    "epithelial": {"source": "AT2", "target": "Tip (fetal)"},
    "mesenchymal": {"source": "Myofibroblast/SCMF", "target": "Developmental fibroblast"},
    "endothelial": {"source": "gCap/CAP1", "target": "EC (developmental/general)"},
    "immune": {"source": "Macrophage", "target": "Progenitor"},
}
