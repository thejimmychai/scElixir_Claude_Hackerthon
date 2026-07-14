"""Load the seed payload and the ground-truth reference files into memory.

This is the single source of truth the backend serves from. Everything is read
once, lazily, and cached. The seed JSON (``frontend/seed/pipeline_seed_data.json``)
carries the curated payload the frontend also embeds; the CSV/JSON files under
``data/reference/`` are the richer ground-truth outputs each stage runner reads.

No third-party libraries: CSVs are parsed with the ``csv`` module, not pandas.
"""

from __future__ import annotations

import csv
import json
import os
from typing import Any, Dict, List, Optional

from . import config


# --------------------------------------------------------------------------- #
# small parsing helpers                                                        #
# --------------------------------------------------------------------------- #
def _num(value: str) -> Optional[float]:
    """Parse a numeric CSV cell to int/float, or None if blank/non-numeric."""
    if value is None:
        return None
    s = str(value).strip()
    if s == "" or s.lower() in ("na", "nan", "none"):
        return None
    try:
        f = float(s)
    except ValueError:
        return None
    return int(f) if f.is_integer() else f


def _read_csv(name: str) -> List[Dict[str, str]]:
    path = os.path.join(config.DATA_DIR, name)
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _read_json(name: str) -> Any:
    path = os.path.join(config.DATA_DIR, name)
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


# --------------------------------------------------------------------------- #
# the loaded dataset (lazy singleton)                                          #
# --------------------------------------------------------------------------- #
class Dataset:
    """Holds every reference artifact, parsed into API-ready structures."""

    def __init__(self) -> None:
        with open(config.SEED_PATH, encoding="utf-8") as fh:
            self.seed: Dict[str, Any] = json.load(fh)

        self.meta = self.seed["meta"]
        self.organs = self.seed["organs"]
        self.stages = self.seed["stages"]
        self.layers = self.seed["layers"]
        self.refcase = self.seed["refcase"]
        # seed's 14-row curated evidence subset (frontend fallback only)
        self.seed_evidence = self.seed["evidence"]
        self.dev_datasets = self.seed["dev_datasets"]

        # Reference files are parsed on demand and memoised here.
        self._cache: Dict[str, Any] = {}

    # -- Stage A -------------------------------------------------------------
    def evidence_catalog(self) -> List[Dict[str, Any]]:
        """Full 36-row perturbation-screen catalog (Stage A backing)."""
        if "evidence" not in self._cache:
            rows = _read_csv("perturbseq_datasets_catalog.csv")
            out = []
            for r in rows:
                out.append(
                    {
                        "study": r["study"],
                        "author": r["first_author"],
                        "year": r["year"],
                        "method": r["method"],
                        "pert": r["perturbation_type"],
                        "tf_focus": r["tf_focus"],
                        "line": r["cell_line"],
                        "organ": r["organ"],
                        "organism": r["organism"],
                        "cells": r["approx_n_cells"],
                        "accession": r["accession"],
                        "repository": r["repository"],
                        "matched_multiome": r["matched_multiome"],
                        "tier": r["priority_tier"],
                        "doi": r["doi"],
                        "verified": r["verify_status"],
                        "notes": r["relevance_notes"],
                    }
                )
            self._cache["evidence"] = out
        return self._cache["evidence"]

    # -- Stage B -------------------------------------------------------------
    def state_tfs_table(self) -> Dict[str, Dict[str, List[Dict[str, Any]]]]:
        """ALL_lineage_state_TFs.csv keyed by lineage -> state -> [{tf,logFC,padj}]."""
        if "state_tfs" not in self._cache:
            table: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
            for r in _read_csv("ALL_lineage_state_TFs.csv"):
                lin = r["lineage"].strip().lower()
                st = r["cell_state"]
                table.setdefault(lin, {}).setdefault(st, []).append(
                    {"tf": r["TF"], "logFC": _num(r["logFC"]), "padj": _num(r["padj"])}
                )
            self._cache["state_tfs"] = table
        return self._cache["state_tfs"]

    # -- Stage C -------------------------------------------------------------
    def grn_scores(self) -> List[Dict[str, Any]]:
        """GRN_network_scores_enhancer.csv -> list of hub score rows (TF first col)."""
        if "grn" not in self._cache:
            path = os.path.join(config.DATA_DIR, "GRN_network_scores_enhancer.csv")
            out = []
            with open(path, newline="", encoding="utf-8") as fh:
                reader = csv.reader(fh)
                header = next(reader)  # first col blank = TF index
                for row in reader:
                    if not row or not row[0]:
                        continue
                    d = {header[i]: row[i] for i in range(1, len(header))}
                    out.append(
                        {
                            "tf": row[0],
                            "degree_all": _num(d.get("degree_all")),
                            "degree_centrality_all": _num(d.get("degree_centrality_all")),
                            "degree_in": _num(d.get("degree_in")),
                            "degree_out": _num(d.get("degree_out")),
                            "betweenness_centrality": _num(d.get("betweenness_centrality")),
                            "eigenvector_centrality": _num(d.get("eigenvector_centrality")),
                            "cluster": d.get("cluster"),
                        }
                    )
            self._cache["grn"] = out
        return self._cache["grn"]

    # -- Stage D -------------------------------------------------------------
    def tf_recipe(self) -> List[Dict[str, Any]]:
        if "recipe" not in self._cache:
            out = []
            for r in _read_csv("AT2_to_TiP_TF_recipe.csv"):
                intervention = r["Intervention"]
                action = "ACTIVATE" if "ACTIVATE" in intervention.upper() else "KNOCK_OUT"
                conf_raw = r["Confidence"]
                conf = conf_raw.split("—")[0].strip().upper().split()[0] if conf_raw else ""
                out.append(
                    {
                        "tf": r["TF"],
                        "action": action,
                        "intervention": intervention,
                        "rationale": r["Rationale_expression"],
                        "grn_evidence": r["GRN_evidence"],
                        "note": r["Note"],
                        "confidence": conf,
                        "confidence_detail": conf_raw,
                    }
                )
            self._cache["recipe"] = out
        return self._cache["recipe"]

    def tf_modules(self) -> List[Dict[str, Any]]:
        if "modules" not in self._cache:
            out = []
            for r in _read_csv("lung_AT2_to_progenitor_TF_scheme.csv"):
                out.append(
                    {
                        "module": r["GRN_module"],
                        "source": r["measured_endoderm_source"],
                        "tf": r["lung_TF_nomination"],
                        "role": r["role"],
                        "evidence_class": r["evidence_class"],
                    }
                )
            self._cache["modules"] = out
        return self._cache["modules"]

    def tf_screen(self) -> List[Dict[str, Any]]:
        if "screen" not in self._cache:
            out = []
            for r in _read_csv("insilico_TF_perturbation_screen.csv"):
                out.append(
                    {
                        "dataset": r["dataset"],
                        "tf": r["TF"],
                        "mode": r["mode"],
                        "transition": r["transition"],
                        "projection": _num(r["projection"]),
                    }
                )
            self._cache["screen"] = out
        return self._cache["screen"]

    def alt_schemes(self) -> List[Dict[str, Any]]:
        if "alt" not in self._cache:
            out = []
            for r in _read_csv("alternative_stagewise_TF_scheme.csv"):
                out.append(
                    {
                        "dataset": r["dataset"],
                        "transition": r["transition"],
                        "combo": r["combo"],
                        "combo_size": _num(r["combo_size"]),
                        "combo_projection": _num(r["combo_projection"]),
                        "best_single": r["best_single"],
                        "best_single_projection": _num(r["best_single_projection"]),
                        "combo_gain_over_single": _num(r["combo_gain_over_single"]),
                        "contains_OSKM_factor": r["contains_OSKM_factor"],
                        "novel_TFs_vs_OSKM": r["novel_TFs_vs_OSKM"],
                    }
                )
            self._cache["alt"] = out
        return self._cache["alt"]

    # -- Stage E -------------------------------------------------------------
    def compounds(self) -> List[Dict[str, Any]]:
        if "compounds" not in self._cache:
            out = []
            for r in _read_csv("AT2_to_TiP_compounds.csv"):
                out.append(
                    {
                        "name": r["Compound"],
                        "moa": r["Tahoe_MoA"],
                        "targets": r["Tahoe_targets"],
                        "approved": r["Human_approved"],
                        "induce_target_score": _num(r["induce_TiP_score"]),
                        "suppress_source_score": _num(r["suppress_AT2_score"]),
                        "suppress_clubcili_score": _num(r["suppress_clubcili_score"]),
                        "n_objectives_hit": _num(r["n_objectives_hit"]),
                        "min_gene_overlap": _num(r["min_gene_overlap"]),
                        "pubchem_cid": _num(r["PubChem_CID"]),
                    }
                )
            self._cache["compounds"] = out
        return self._cache["compounds"]

    def curated_compounds(self) -> List[Dict[str, Any]]:
        if "curated" not in self._cache:
            out = []
            for r in _read_csv("lung_AT2_to_progenitor_small_molecules.csv"):
                out.append(
                    {
                        "name": r["compound"],
                        "pathway": r["target_pathway"],
                        "source": r["source"],
                        "rationale": r["rationale"],
                        "confidence": r["confidence"],
                    }
                )
            self._cache["curated"] = out
        return self._cache["curated"]

    def tahoe_validation(self) -> List[Dict[str, Any]]:
        if "tahoe" not in self._cache:
            out = []
            for r in _read_csv("AT2_to_TiP_tahoe_validation.csv"):
                out.append(
                    {
                        "intervention": r["intervention"],
                        "type": r["type"],
                        "source_dn": _num(r.get("AT2↓")),
                        "target_up": _num(r.get("tip↑")),
                        "cili_dn": _num(r.get("cili↓")),
                        "club_dn": _num(r.get("club↓")),
                        "reprog_score": _num(r["reprog_score"]),
                    }
                )
            self._cache["tahoe"] = out
        return self._cache["tahoe"]

    # -- Stage F -------------------------------------------------------------
    def fate_distal(self) -> Dict[str, Any]:
        if "fate_distal" not in self._cache:
            self._cache["fate_distal"] = _read_json("distaltf_fate_proximity_readout.json")
        return self._cache["fate_distal"]

    def fate_oskm(self) -> Dict[str, Any]:
        if "fate_oskm" not in self._cache:
            self._cache["fate_oskm"] = _read_json("fate_proximity_readout.json")
        return self._cache["fate_oskm"]

    def pertformer_contract(self) -> Dict[str, Any]:
        if "io" not in self._cache:
            self._cache["io"] = _read_json("pertformer_io_contract.json")
        return self._cache["io"]


_DATASET: Optional[Dataset] = None


def get() -> Dataset:
    """Return the process-wide loaded dataset (constructing it on first use)."""
    global _DATASET
    if _DATASET is None:
        _DATASET = Dataset()
    return _DATASET
