"""Durable result artifacts — the "serve a real cached result" half of Phase 1.

A result is written to ``data/results/<stage>/<name>__<digest>.json`` together
with its full identity. Reads verify that identity before serving anything, so a
result produced for one parameter set (including engine parameters — guardrail 5)
can never be served for a different one.

Only runs that actually computed something write an artifact. Reference data
that ships in ``data/reference/`` is served directly and is never copied here.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from typing import Any, Dict, List, Optional

from . import config

_LOCK = threading.Lock()


def identity_for(
    stage: str,
    organ: Optional[str],
    layer: Optional[str],
    source: Optional[str] = None,
    target: Optional[str] = None,
    species: Optional[str] = "human",
    route: Optional[str] = None,
    engine_params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """The full parameter identity of one stage result.

    Only the parameters a stage actually depends on are kept, so the same result
    is found from every request that legitimately asks for it.
    """
    return {
        "stage": stage,
        "organ": organ or "",
        "layer": "" if stage == "A" else (layer or ""),
        "source": "" if stage in ("A", "B") else (source or ""),
        "target": "" if stage in ("A", "B") else (target or ""),
        "species": (species or "") if stage in ("D", "F") else "",
        "route": (route or "") if stage == "C" else "",
        "engine": dict(engine_params or {}),
    }


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def key_for(ident: Dict[str, Any]) -> str:
    """Stable digest of an identity (used in file names and for comparisons)."""
    return hashlib.sha256(_canonical(ident).encode("utf-8")).hexdigest()[:16]


def path_for(ident: Dict[str, Any]) -> str:
    readable = "_".join(
        part for part in (ident["organ"], ident["layer"], ident["source"], ident["target"], ident["species"], ident["route"])
        if part
    )
    readable = re.sub(r"[^A-Za-z0-9]+", "_", readable).strip("_")[:80] or "result"
    return os.path.join(config.RESULTS_DIR, ident["stage"], f"{readable}__{key_for(ident)}.json")


def load(ident: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return the stored payload for exactly this identity, or None."""
    path = path_for(ident)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        return None
    if doc.get("identity") != ident:  # guardrail 5: never serve across parameters
        return None
    return doc.get("payload")


def exists(ident: Dict[str, Any]) -> bool:
    return load(ident) is not None


def save(ident: Dict[str, Any], payload: Dict[str, Any]) -> str:
    """Persist a computed payload and return its ``file://`` URI."""
    path = path_for(ident)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    doc = {"identity": ident, "payload": payload}
    tmp = path + ".tmp"
    with _LOCK:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=2, ensure_ascii=False, default=str)
        os.replace(tmp, path)
    return "file://" + path


def list_all() -> List[Dict[str, Any]]:
    """Every stored result's identity, for the ``GET /results`` index."""
    out: List[Dict[str, Any]] = []
    if not os.path.isdir(config.RESULTS_DIR):
        return out
    for stage in sorted(os.listdir(config.RESULTS_DIR)):
        sdir = os.path.join(config.RESULTS_DIR, stage)
        if not os.path.isdir(sdir):
            continue
        for name in sorted(os.listdir(sdir)):
            if not name.endswith(".json"):
                continue
            try:
                with open(os.path.join(sdir, name), encoding="utf-8") as fh:
                    out.append({"identity": json.load(fh).get("identity"), "file": name})
            except (OSError, ValueError):
                continue
    return out
