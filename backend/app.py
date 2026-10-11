"""Standard-library HTTP server exposing the Section-4 API + the frontend.

Run:  python3 -m backend.app          (serves API + UI on http://127.0.0.1:8765)

Reads are synchronous. Long stages (B/C/D/E/F) accept a POST that submits a job and
returns a handle to poll at /jobs/{id}. A stage result is served from, in order:
a durable artifact written by a real run under identical parameters, then the
shipped reference data. Anything else is ``not_computed`` with a ``requires`` list.

    GET  /organs
    GET  /organs/{organ}/layers
    GET  /organs/{organ}/layers/{layer}/states
    GET  /runs?organ=&layer=&source=&target=&species=&route=
    GET  /stages
    GET  /provenance
    GET  /meta
    GET  /compute/status[?probe=1]      engine + input availability (honest)
    GET  /results                       index of durable stage artifacts
    GET  /stage/A?organ=
    GET  /stage/B?organ=&layer=
    GET  /stage/C?organ=&layer=&route=&source=&target=
    GET  /stage/D?organ=&layer=&source=&target=&species=
    GET  /stage/E?organ=&layer=&source=&target=
    GET  /stage/F?organ=&layer=&source=&target=&species=
      (every /stage/* GET also accepts engine=<JSON> to address a parameterised result)
    POST /stage/{B|C|D|E|F}/run         (JSON body; invalid bodies get 400)
    GET  /jobs/{job_id}
    GET  /  and static assets under frontend/
"""

from __future__ import annotations

import errno
import json
import mimetypes
import os
import posixpath
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, unquote, urlparse

from . import artifacts, capabilities, config, data_loader, jobs, registry
from .stages import (
    stage_a_evidence,
    stage_b_atlas,
    stage_c_grn,
    stage_d_reversal,
    stage_e_drugs,
    stage_f_pertformer,
)

SPECIES = ("human", "mouse")
RUN_STAGES = {
    "B": stage_b_atlas.run,
    "C": stage_c_grn.run,
    "D": stage_d_reversal.run,
    "E": stage_e_drugs.run,
    "F": stage_f_pertformer.run,
}


class BadRequest(Exception):
    """A client error: the request is malformed. Answered with HTTP 400."""


# --------------------------------------------------------------------------- #
# helpers                                                                      #
# --------------------------------------------------------------------------- #
def _q1(qs: Dict[str, List[str]], key: str, default: Optional[str] = None) -> Optional[str]:
    vals = qs.get(key)
    return vals[0] if vals else default


def _json_default(obj: Any) -> Any:
    """Make numpy scalars and similar serialisable (live engine results)."""
    if hasattr(obj, "item"):
        return obj.item()
    return str(obj)


def _parse_engine(stage: str, raw: Optional[str]) -> Dict[str, Any]:
    if not raw:
        return {}
    try:
        engine = json.loads(raw)
    except ValueError:
        raise BadRequest("engine must be a JSON object")
    if not isinstance(engine, dict):
        raise BadRequest("engine must be a JSON object")
    if stage == "E":
        try:
            return stage_e_drugs.canonical_engine(engine)
        except ValueError as exc:
            raise BadRequest(str(exc))
    return engine


# --------------------------------------------------------------------------- #
# GET                                                                          #
# --------------------------------------------------------------------------- #
STAGE_HANDLERS = {
    "A": lambda o, l, s, t, sp, r: stage_a_evidence.get(o),
    "B": lambda o, l, s, t, sp, r: stage_b_atlas.get(o, l),
    "C": lambda o, l, s, t, sp, r: stage_c_grn.get(o, l, r, s, t),
    "D": lambda o, l, s, t, sp, r: stage_d_reversal.get(o, l, s, t, sp),
    "E": lambda o, l, s, t, sp, r: stage_e_drugs.get(o, l, s, t),
    "F": lambda o, l, s, t, sp, r: stage_f_pertformer.get(o, l, s, t, sp),
}


def route_get(path: str, qs: Dict[str, List[str]]):
    parts = [p for p in path.strip("/").split("/") if p != ""]

    if path == "/health":
        return 200, {"status": "ok"}

    if path == "/organs":
        return 200, registry.organs()

    if path == "/stages":
        return 200, data_loader.get().stages

    if path == "/meta":
        ds = data_loader.get()
        return 200, {
            "meta": ds.meta,
            "organs": registry.organs(),
            "stages": ds.stages,
            "layer_defaults": config.LAYER_DEFAULTS,
            "reference_case": config.REFERENCE_CASE,
            "grn_routes": list(config.GRN_ROUTES),
        }

    if path == "/provenance":
        return 200, _provenance()

    if path == "/compute/status":
        return 200, capabilities.report(probe=_q1(qs, "probe") == "1")

    if path == "/results":
        return 200, {"results": artifacts.list_all(), "results_dir": config.RESULTS_DIR}

    # /organs/{organ}/layers   and  /organs/{organ}/layers/{layer}/states
    if len(parts) >= 3 and parts[0] == "organs" and parts[2] == "layers":
        organ = unquote(parts[1])
        if len(parts) == 3:
            return 200, registry.layers(organ)
        if len(parts) == 5 and parts[4] == "states":
            layer = unquote(parts[3])
            return 200, registry.states(organ, layer)

    if path == "/runs":
        return 200, _runs(qs)

    if parts and parts[0] == "jobs" and len(parts) == 2:
        job = jobs.get(unquote(parts[1]))
        if not job:
            return 404, {"error": "unknown job_id"}
        return 200, job.to_dict()

    if len(parts) == 2 and parts[0] == "stage":
        return _stage_get(parts[1].upper(), qs)

    return None  # not an API route -> try static


def _stage_get(stage: str, qs: Dict[str, List[str]]):
    if stage not in STAGE_HANDLERS:
        return 404, {"error": f"unknown stage '{stage}'"}

    organ = _q1(qs, "organ", "lung")
    layer = _q1(qs, "layer", "epithelial")
    source = _q1(qs, "source")
    target = _q1(qs, "target")
    species = _q1(qs, "species", "human")
    route = _q1(qs, "route", "scenicplus")

    if species not in SPECIES:
        raise BadRequest(f"species must be one of {', '.join(SPECIES)}")
    if stage == "C" and route not in config.GRN_ROUTES:
        raise BadRequest(f"route must be one of {', '.join(config.GRN_ROUTES)}")
    engine = _parse_engine(stage, _q1(qs, "engine"))

    # A durable artifact for exactly these parameters wins over everything else.
    ident = artifacts.identity_for(stage, organ, layer, source, target, species, route, engine)
    stored = artifacts.load(ident)
    if stored is not None:
        return 200, {**stored, "served_from": "artifact"}

    payload = STAGE_HANDLERS[stage](organ, layer, source, target, species, route)
    if payload.get("status") == "cached":
        payload.setdefault("served_from", "reference")
    if payload.get("status") == "not_computed" and stage != "A":
        payload["requires"] = capabilities.requirements(stage, organ, layer, route)
    return 200, payload


def _runs(qs: Dict[str, List[str]]):
    organ = _q1(qs, "organ", "lung")
    layer = _q1(qs, "layer", "epithelial")
    source = _q1(qs, "source")
    target = _q1(qs, "target")
    species = _q1(qs, "species", "human")
    route = _q1(qs, "route", "scenicplus")
    idx = registry.run_index(organ, layer, source, target, species, route)

    # Overlay any in-flight jobs matching these params as "running".
    def matches(stage: str):
        def pred(p: Dict[str, Any]) -> bool:
            if p.get("organ", "lung") != organ or p.get("layer", "epithelial") != layer:
                return False
            if stage in ("D", "E", "F"):
                if source is not None and p.get("source") not in (None, source):
                    return False
                if target is not None and p.get("target") not in (None, target):
                    return False
            if stage == "F" and p.get("species", "human") != species:
                return False
            return True
        return pred

    for stage in ("B", "C", "D", "E", "F"):
        if jobs.find_running(stage, matches(stage)):
            idx["stages"][stage] = "running"
    return idx


def _provenance():
    ds = data_loader.get()
    artifact_map = {
        "A": ["perturbseq_datasets_catalog.csv", "tf_to_drug_connectivity.py"],
        "B": ["*_subatlas.h5ad (external)", "ALL_lineage_state_TFs.csv"],
        "C": ["GRN_network_scores_enhancer.csv", "epi_links.celloracle.links (external)"],
        "D": ["AT2_to_TiP_TF_recipe.csv", "lung_AT2_to_progenitor_TF_scheme.csv",
              "insilico_TF_perturbation_screen.csv", "alternative_stagewise_TF_scheme.csv"],
        "E": ["AT2_to_TiP_compounds.csv", "lung_AT2_to_progenitor_small_molecules.csv",
              "AT2_to_TiP_tahoe_validation.csv"],
        "F": ["distaltf_fate_proximity_readout.json", "fate_proximity_readout.json",
              "pertformer_io_contract.json"],
    }
    return {
        "statement": (
            "Every live table and number is extracted from real artifacts produced by four "
            "analysis sessions in this project. Nothing is synthetic. In-silico predictions "
            "are hypotheses requiring wet-lab validation."
        ),
        "stages": [
            {"stage": s["id"], "session": s["session"], "artifacts": artifact_map.get(s["id"], [])}
            for s in ds.stages
        ],
    }


# --------------------------------------------------------------------------- #
# POST                                                                         #
# --------------------------------------------------------------------------- #
def _validate_run(stage: str, body: Dict[str, Any]) -> Dict[str, Any]:
    p = dict(body)
    p.setdefault("organ", "lung")
    p.setdefault("layer", "epithelial")
    for key in ("organ", "layer"):
        if not isinstance(p[key], str) or not p[key]:
            raise BadRequest(f"'{key}' must be a non-empty string")
    for key in ("source", "target"):
        if p.get(key) is not None and not isinstance(p[key], str):
            raise BadRequest(f"'{key}' must be a string")

    species = p.get("species", "human")
    if species not in SPECIES:
        raise BadRequest(f"species must be one of {', '.join(SPECIES)}")
    p["species"] = species

    if "engine_params" in p and not isinstance(p["engine_params"], dict):
        raise BadRequest("engine_params must be a JSON object")

    if stage == "C":
        route = p.get("route", "scenicplus")
        if route not in config.GRN_ROUTES:
            raise BadRequest(f"route must be one of {', '.join(config.GRN_ROUTES)}")
        p["route"] = route

    if stage == "E":
        if p.get("signature") is not None:
            p["signature"] = stage_e_drugs.canonical_signature(p["signature"])  # ValueError -> 400
            p["lung_only"] = bool(p.get("lung_only", False))
        else:
            p.pop("signature", None)
    return p


def _run_identity(stage: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """The artifact identity a run request addresses (same rules as the GET path)."""
    if stage == "E" and params.get("signature"):
        engine = stage_e_drugs.canonical_engine(
            {"signature": params["signature"], "lung_only": params.get("lung_only", False)})
    else:
        engine = dict(params.get("engine_params") or {})
    return artifacts.identity_for(
        stage, params.get("organ"), params.get("layer"), params.get("source"), params.get("target"),
        params.get("species", "human"), params.get("route"), engine)


def route_post(path: str, body: Any):
    parts = [p for p in path.strip("/").split("/") if p != ""]
    # /stage/{X}/run
    if len(parts) == 3 and parts[0] == "stage" and parts[2] == "run":
        stage = parts[1].upper()
        runner = RUN_STAGES.get(stage)
        if not runner:
            return 404, {"error": f"stage '{stage}' has no async runner"}
        if not isinstance(body, dict):
            raise BadRequest("request body must be a JSON object")
        try:
            params = _validate_run(stage, body)
        except ValueError as exc:
            raise BadRequest(str(exc))
        # A stored artifact for exactly these parameters answers the request at once.
        ident = _run_identity(stage, params)
        stored = artifacts.load(ident)
        if stored is not None:
            result = {**stored, "artifact_uri": "file://" + artifacts.path_for(ident), "served_from": "artifact"}
            job = jobs.completed(stage, params, result)
        else:
            job = jobs.submit(stage, params, runner)
        return 202, {"job_id": job.job_id, "stage": stage, "status": job.status}
    return 404, {"error": "unknown route"}


# --------------------------------------------------------------------------- #
# HTTP plumbing                                                                #
# --------------------------------------------------------------------------- #
class Handler(BaseHTTPRequestHandler):
    server_version = "ReproPipeline/1.1"
    protocol_version = "HTTP/1.1"

    def _send_json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=_json_default).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)
        try:
            result = route_get(path, qs)
        except BadRequest as exc:
            self._send_json(400, {"error": str(exc)})
            return
        except Exception as exc:  # noqa: BLE001
            self._send_json(500, {"error": f"{type(exc).__name__}: {exc}"})
            return
        if result is not None:
            self._send_json(result[0], result[1])
            return
        self._serve_static(path)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            length = int(self.headers.get("Content-Length", "0") or "0")
        except ValueError:
            self._send_json(400, {"error": "invalid Content-Length header"})
            return
        raw = self.rfile.read(length) if length > 0 else b""
        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except ValueError:
            self._send_json(400, {"error": "invalid JSON body"})
            return
        try:
            result = route_post(parsed.path, body)
        except BadRequest as exc:
            self._send_json(400, {"error": str(exc)})
            return
        except Exception as exc:  # noqa: BLE001
            self._send_json(500, {"error": f"{type(exc).__name__}: {exc}"})
            return
        self._send_json(result[0], result[1])

    def _serve_static(self, path: str) -> None:
        rel = unquote(path)
        if rel in ("/", ""):
            rel = "/index.html"
        # Normalise and confine to FRONTEND_DIR (prevent path traversal).
        safe = posixpath.normpath(rel).lstrip("/")
        full = os.path.join(config.FRONTEND_DIR, *safe.split("/"))
        full = os.path.abspath(full)
        if not full.startswith(os.path.abspath(config.FRONTEND_DIR)):
            self._send_json(403, {"error": "forbidden"})
            return
        if not os.path.isfile(full):
            self._send_json(404, {"error": "not found", "path": path})
            return
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        with open(full, "rb") as fh:
            self._send_bytes(200, fh.read(), ctype)

    def log_message(self, fmt: str, *args: Any) -> None:  # quieter logging
        return


def _bind(host: str, port: int, strict: bool) -> ThreadingHTTPServer:
    """Bind the port, or — unless a port was requested explicitly — the next free one.

    Another program (on macOS the Claude desktop app's own service listens on 8765)
    can already own the default port. Binding with a clear message beats a silent
    failure, and the chosen URL is always printed.
    """
    attempts = 1 if strict else 20
    last: Optional[OSError] = None
    for candidate in range(port, port + attempts):
        try:
            return ThreadingHTTPServer((host, candidate), Handler)
        except OSError as exc:
            if exc.errno != errno.EADDRINUSE:
                raise
            last = exc
    raise SystemExit(f"port {port} is in use by another program ({last}); choose one with --port")


def serve(host: str = config.HOST_DEFAULT, port: int = config.PORT_DEFAULT, strict: bool = False) -> None:
    mimetypes.add_type("application/javascript", ".js")
    data_loader.get()  # fail fast if the seed/reference files are missing
    httpd = _bind(host, port, strict)
    actual = httpd.server_address[1]
    if actual != port:
        print(f"port {port} is busy (another program), using {actual} instead")
    print("Universal Developmental Reprogramming Pipeline")
    print(f"  API + UI:  http://{host}:{actual}/")
    print("  compute status: /compute/status    stop with Ctrl-C")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down")
        httpd.shutdown()


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Reprogramming pipeline backend")
    ap.add_argument("--host", default=config.HOST_DEFAULT)
    ap.add_argument("--port", type=int, default=None,
                    help=f"port to bind (default {config.PORT_DEFAULT}, falling back to the next free one)")
    args = ap.parse_args()
    serve(args.host, args.port or config.PORT_DEFAULT, strict=args.port is not None)
