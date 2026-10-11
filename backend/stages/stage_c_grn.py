"""Stage C — GRN inference (async job).

GET  /stage/C?organ=lung&layer=epithelial&route=scenicplus
  -> { hubs, n_clusters, n_edges, route, candidate_hubs, ... }
POST /stage/C/run { organ, layer, route } -> { job_id }

Backing: GRN_network_scores_enhancer.csv (the SCENIC+ enhancer-aware run for lung
epithelial). The CellOracle route has no cached GRN, so it reports not_computed
for every layer. Other layers surface only their candidate regulators (Stage-B
master TFs) rather than fabricated centrality scores.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .. import config, data_loader, registry
from ..jobs import ComputeUnavailable

TOP_HUBS = 40


def _hub_table() -> Dict[str, Any]:
    """Rank hubs across the enhancer GRN.

    GRN_network_scores_enhancer.csv is not one flat node list — it is 8 stacked
    per-cell-state centrality tables (clusters APr/AT1l/AT2l/Cili/EpiC/Meso/PNEC/TiP),
    each an independent ~2000-edge sub-network in which every TF appears once. So we
    (a) count edges per cluster (not summed into one inflated total), and (b) build a
    diverse hub list by keeping, for each TF, the cluster where its degree centrality
    peaks — otherwise the top rows collapse to the same few TFs repeated 8x.
    """
    ds = data_loader.get()
    rows = ds.grn_scores()

    edges_per_cluster: Dict[str, int] = {}
    best_by_tf: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        cluster = r["cluster"]
        edges_per_cluster[cluster] = edges_per_cluster.get(cluster, 0) + int(r["degree_out"] or 0)
        cur = best_by_tf.get(r["tf"])
        if cur is None or (r["degree_centrality_all"] or 0.0) > (cur["degree_centrality_all"] or 0.0):
            best_by_tf[r["tf"]] = r

    ranked = sorted(
        best_by_tf.values(),
        key=lambda r: (r["degree_centrality_all"] or 0.0),
        reverse=True,
    )[:TOP_HUBS]
    hubs = [
        {
            "tf": r["tf"],
            "degree_centrality_all": r["degree_centrality_all"],
            "betweenness_centrality": r["betweenness_centrality"],
            "eigenvector_centrality": r["eigenvector_centrality"],
            "cluster": r["cluster"],
        }
        for r in ranked
    ]
    clusters = sorted(edges_per_cluster)
    return {
        "hubs": hubs,
        "clusters": clusters,
        "n_clusters": len(clusters),
        "edges_per_cluster": edges_per_cluster,
        "n_edges_total": sum(edges_per_cluster.values()),
    }


def _candidate_hubs(organ: str, layer: str, source: Optional[str], target: Optional[str]) -> Dict[str, Any]:
    ld = registry.layer_data(organ, layer) or {}
    states = ld.get("states", {})

    def tfs(name: Optional[str]) -> List[str]:
        st = states.get(name)
        return [t["tf"] for t in st["master_tfs"][:8]] if st else []

    return {"source": tfs(source), "target": tfs(target)}


def get(
    organ: str = "lung",
    layer: str = "epithelial",
    route: str = "scenicplus",
    source: Optional[str] = None,
    target: Optional[str] = None,
) -> Dict[str, Any]:
    if not registry.organ_implemented(organ):
        o = registry.organ(organ) or {}
        return {"status": "not_computed", "organ": organ, "layer": layer, "route": route,
                "note": o.get("note", "Planned organ — GRN not yet inferred.")}

    cand = _candidate_hubs(organ, layer, source, target)
    if not registry.grn_available(organ, layer, route):
        if route == "scenicplus":
            note = ("The enhancer-aware (SCENIC+) GRN was inferred only for lung epithelial in the "
                    "reference run. Candidate regulators (Stage-B master TFs) are shown.")
        else:
            note = ("No CellOracle base-GRN has been computed for this layer. Candidate regulators "
                    "(Stage-B master TFs) are shown; the CellOracle route needs the layer's sub-atlas.")
        return {
            "status": "not_computed",
            "organ": organ,
            "layer": layer,
            "route": route,
            "note": note,
            "candidate_hubs": cand,
        }

    table = _hub_table()
    return {
        "status": "cached",
        "organ": organ,
        "layer": layer,
        "route": route,
        "route_detail": "SCENIC+ enhancer-aware eRegulons (13/16 canonical epithelial TFs recovered)",
        "n_clusters": table["n_clusters"],
        "clusters": table["clusters"],
        "edges_per_cluster": table["edges_per_cluster"],
        "n_edges": table["n_edges_total"],
        "hubs": table["hubs"],
        "candidate_hubs": cand,
        "artifact_uri": "external://artifact-store/epi_links.celloracle.links",
        "artifact_status": "external_not_in_bundle",
    }


def run(job) -> Dict[str, Any]:
    p = job.params
    organ, layer = p.get("organ", "lung"), p.get("layer", "epithelial")
    route = p.get("route", "scenicplus")
    if registry.reference_cached("C", organ, layer, route=route):
        job.progress = "loading cached GRN network scores"
        return get(organ, layer, route, p.get("source"), p.get("target"))
    raise ComputeUnavailable(
        f"No cached GRN for organ='{organ}', layer='{layer}' via route '{route}'. Inference needs "
        "the layer's sub-atlas (CellOracle, CPU) or matched multiome + cisTarget (SCENIC+, GPU); "
        "see the requirements listed for this stage."
    )
