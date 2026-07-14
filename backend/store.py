"""Parameter-keyed result cache.

A run is identified by ``(organ, layer, source, target, species, stage,
engine_params_hash)`` — handoff Section 2, rule 2 and Section 8, guardrail 5:
changing an engine parameter (``alpha``, ``score_quantile``, candidate pool,
readout panel …) must produce a different cache key so a stale result is never
served across a parameter change.

Results are memoised in-process and also written to ``data/cache/`` as JSON, so
each cached stage result is a real, inspectable artifact with a ``result_uri``.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from typing import Any, Dict, Optional

from . import config

CACHE_DIR = os.path.join(config.ROOT, "data", "cache")

_LOCK = threading.Lock()
_MEM: Dict[str, Any] = {}


def _canonical_params(engine_params: Optional[Dict[str, Any]]) -> str:
    if not engine_params:
        return "{}"
    return json.dumps(engine_params, sort_keys=True, separators=(",", ":"))


def make_key(
    stage: str,
    organ: str,
    layer: str,
    source: Optional[str] = None,
    target: Optional[str] = None,
    species: str = "human",
    engine_params: Optional[Dict[str, Any]] = None,
) -> str:
    """Deterministic cache key. Engine params fold into a short hash suffix."""
    base = "::".join(
        [stage, organ or "", layer or "", source or "", target or "", species or ""]
    )
    phash = hashlib.sha1(_canonical_params(engine_params).encode("utf-8")).hexdigest()[:8]
    return f"{base}::{phash}"


def _path_for(key: str) -> str:
    safe = key.replace("::", "__").replace("/", "-").replace(" ", "_").replace("|", "-")
    return os.path.join(CACHE_DIR, f"{safe}.json")


def get(key: str) -> Optional[Any]:
    with _LOCK:
        if key in _MEM:
            return _MEM[key]
    path = _path_for(key)
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                value = json.load(fh)
            with _LOCK:
                _MEM[key] = value
            return value
        except (OSError, ValueError):
            return None
    return None


def put(key: str, value: Any) -> str:
    """Cache ``value`` under ``key`` and return its on-disk ``result_uri``."""
    with _LOCK:
        _MEM[key] = value
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = _path_for(key)
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(value, fh, indent=2, ensure_ascii=False)
    except OSError:
        pass
    return uri_for(key)


def uri_for(key: str) -> str:
    return "file://" + _path_for(key)


def has(key: str) -> bool:
    return get(key) is not None
