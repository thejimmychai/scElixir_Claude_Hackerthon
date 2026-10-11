#!/usr/bin/env python3
"""Build frontend/standalone.html — a single self-contained file.

Inlines the classic scripts (src/seed.js, api.js, state.js, stages.js, app.js)
into frontend/index.html so the app runs on a plain double-click (file://) with
no server and no build tooling, while still upgrading to the live backend when
one is reachable.

It also embeds ``window.__SNAPSHOT__``: the exact responses the backend's own route
functions produce for every path the UI requests — organs, layers, states, the run
index and each stage for every cell layer (its default transition, both species).
Offline use therefore shows the same numbers as the live backend for those paths.
Re-run this after changing the frontend or the backend:

    python3 scripts/build_standalone.py
"""

from __future__ import annotations

import datetime
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
FE = ROOT / "frontend"
SCRIPTS = ["src/seed.js", "src/api.js", "src/state.js", "src/stages.js", "src/app.js"]

sys.path.insert(0, str(ROOT))
from backend import config, registry  # noqa: E402
from backend.app import route_get  # noqa: E402

# Which request parameters each path actually depends on. The browser matches a
# request to a snapshot entry on these keys only (the backend ignores the rest).
SNAPSHOT_KEYS = {
    "/stage/A": ["organ"],
    "/stage/B": ["organ", "layer"],
    "/stage/C": ["organ", "layer", "source", "target"],
    "/stage/D": ["organ", "layer", "source", "target", "species"],
    "/stage/E": ["organ", "layer", "source", "target"],
    "/stage/F": ["organ", "layer", "source", "target", "species"],
    "/runs": ["organ", "layer", "source", "target", "species"],
}
SPECIES = ("human", "mouse")


def default_transition(organ: str, layer: str):
    """The source/target the UI pre-selects for this organ and layer."""
    if organ == config.REFERENCE_CASE["organ"]:
        d = config.LAYER_DEFAULTS.get(layer, {})
        return d.get("source"), d.get("target")
    states = registry.states(organ, layer)["states"]
    mature = [k for k, v in states.items() if v.get("role") == "mature"]
    prog = [k for k, v in states.items() if v.get("role") == "progenitor"]
    return (mature[0] if mature else None), (prog[0] if prog else None)


def build_snapshot() -> dict:
    payloads: list = []
    index: dict = {}
    entries: list = []

    def payload_id(obj) -> int:
        blob = json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)
        if blob not in index:
            index[blob] = len(payloads)
            payloads.append(obj)
        return index[blob]

    def add(path: str, query: dict, stored_q: dict) -> None:
        code, payload = route_get(path, {k: [str(v)] for k, v in query.items()})
        if code != 200:
            raise RuntimeError(f"{path} returned HTTP {code} while building the snapshot")
        entries.append({"p": path, "q": stored_q, "i": payload_id(payload)})

    add("/meta", {}, {})
    add("/organs", {}, {})
    add("/provenance", {}, {})
    add("/stages", {}, {})

    organ_ids = [o["id"] for o in registry.organs()]
    for organ in organ_ids:
        add(f"/organs/{organ}/layers", {}, {})
        for layer in [l["id"] for l in registry.layers(organ)]:
            add(f"/organs/{organ}/layers/{layer}/states", {}, {})

    for organ in organ_ids:
        for layer in [l["id"] for l in registry.layers(organ)]:
            source, target = default_transition(organ, layer)
            for species in SPECIES:
                # Same five keys, in the same way, as the browser sends them.
                p = {"organ": organ, "layer": layer, "source": source, "target": target, "species": species}
                p = {k: v for k, v in p.items() if v is not None}
                add("/runs", p, p)
                for stage in ("A", "B", "C", "D", "E", "F"):
                    add(f"/stage/{stage}", p, p)

    return {
        "built": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "keys": SNAPSHOT_KEYS,
        "entries": entries,
        "payloads": payloads,
    }


def snapshot_script(snapshot: dict) -> str:
    blob = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
    blob = blob.replace("</", "<\\/")  # never let the JSON close the script tag
    return "<script>\n/* build snapshot: exact backend responses for the UI paths */\nwindow.__SNAPSHOT__ = " + blob + ";\n</script>"


def main() -> int:
    html = (FE / "index.html").read_text(encoding="utf-8")
    snapshot = build_snapshot()
    for src in SCRIPTS:
        code = (FE / src).read_text(encoding="utf-8")
        tag = '<script src="%s"></script>' % src
        if tag not in html:
            print(f"warning: expected script tag not found: {tag}", file=sys.stderr)
        inlined = "<script>\n/* inlined from %s */\n%s\n</script>" % (src, code)
        if src == "src/seed.js":
            inlined = snapshot_script(snapshot) + "\n" + inlined
        html = html.replace(tag, inlined)
    if 'script src="src/' in html:
        print("error: some external scripts were not inlined", file=sys.stderr)
        return 1
    html = html.replace(
        "<title>Universal Developmental Reprogramming Pipeline</title>",
        "<title>Universal Developmental Reprogramming Pipeline (standalone)</title>",
    )
    out = FE / "standalone.html"
    out.write_text(html, encoding="utf-8")
    print(f"wrote {out} ({len(html):,} bytes)")
    print(f"snapshot: {len(snapshot['entries'])} requests, {len(snapshot['payloads'])} distinct responses")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
