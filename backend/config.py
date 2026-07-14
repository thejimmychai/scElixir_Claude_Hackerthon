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

# Layers whose Stage-C enhancer-aware GRN centrality table actually exists.
# (The reference GRN_network_scores_enhancer.csv is the epithelial run.)
GRN_COMPUTED_LAYERS = {"lung": {"epithelial"}}

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
