#!/usr/bin/env python3
"""
tf_to_drug_connectivity.py
==========================
Connect a transcription-factor (TF) perturbation signature to small-molecule
interventions: given the genes a TF program turns UP and DOWN, rank compounds
whose transcriptional signatures MIMIC (or REVERSE) that program, then check
which of those compounds are available at single-cell resolution in Tahoe-100M
(including in the lung line A549).

This is the "small-molecule mirroring" layer for the lung TF-network /
direct-reprogramming program. It operationalises the Connectivity-Map paradigm
(Lamb 2006; Subramanian 2017) with two free, no-auth data services:

  1. Enrichr / LINCS L1000  (maayanlab.cloud)  -> signature -> ranked compounds
  2. Tahoe-100M  (HuggingFace datasets-server) -> single-cell drug atlas, 50
     cancer cell lines incl. A549, 379 compounds / 1,100 perturbations

Conceptual logic
----------------
- A compound that MIMICS a TF program produces a transcriptional change in the
  SAME direction: its up-genes overlap the TF up-genes. Query the TF UP list
  against `LINCS_L1000_Chem_Pert_up`.
- A compound that REVERSES a TF program (antidote) produces the OPPOSITE change:
  its up-genes overlap the TF DOWN list. Query the TF DOWN list against
  `LINCS_L1000_Chem_Pert_up` (or the TF UP list against `..._down`).

Typical use
-----------
    from tf_to_drug_connectivity import (
        compute_signature_from_perturbseq, connectivity_query, cross_ref_tahoe)

    # 1. TF signature (up/down gene symbols) — from your Perturb-seq / CellOracle
    up, down = [...], [...]

    # 2. rank compounds that mimic / reverse it (optionally restrict to lung lines)
    mimic  = connectivity_query(up,   direction="mimic",   lung_only=True)
    revert = connectivity_query(down, direction="reverse", lung_only=True)

    # 3. which hits are in Tahoe-100M (single-cell A549 available)?
    hits = cross_ref_tahoe(mimic)

Requires: requests, pandas, numpy, scipy (scanpy/anndata optional).
Network: needs allowlist access to maayanlab.cloud and
datasets-server.huggingface.co.
"""
from __future__ import annotations
import re, time, json
import requests
import numpy as np
import pandas as pd

ENRICHR = "https://maayanlab.cloud/Enrichr"
HF = "https://datasets-server.huggingface.co"
TAHOE_DS = "tahoebio/Tahoe-100M"

# LINCS L1000 chemical-perturbation libraries exposed by Enrichr
LIB_CHEM_UP = "LINCS_L1000_Chem_Pert_up"
LIB_CHEM_DN = "LINCS_L1000_Chem_Pert_down"
LIB_CRISPR  = "LINCS_L1000_CRISPR_KO_Consensus_Sigs"

LUNG_LINE_RE = re.compile(r"A549|HCC515|HCC827|H1299|H460|H358|H1975|CALU|NCIH|HOP-?92|LUNG", re.I)


# --------------------------------------------------------------------------- #
# 1. Build a TF signature from a Perturb-seq matrix (CRISPRa / CRISPRi / KO)   #
# --------------------------------------------------------------------------- #
def compute_signature_from_expr(Xn, gene_symbols, pert_mask, ctrl_mask,
                                n_top=100, min_mean=0.05):
    """Rank genes by a t-like statistic (perturbed vs control) on a
    log-normalised cells x genes matrix `Xn` (scipy.sparse CSR or ndarray).

    Returns (up_genes, down_genes, full_table). `gene_symbols` aligns to columns.
    """
    import scipy.sparse as sp
    def _mean(mask):
        return np.asarray(Xn[mask].mean(0)).ravel()
    def _var(mask, mean):
        Xg = Xn[mask]
        sq = np.asarray(Xg.multiply(Xg).mean(0)).ravel() if sp.issparse(Xg) \
             else (Xg**2).mean(0)
        return np.maximum(sq - mean**2, 1e-8)
    m1, m0 = _mean(pert_mask), _mean(ctrl_mask)
    n1, n0 = int(pert_mask.sum()), int(ctrl_mask.sum())
    se = np.sqrt(_var(pert_mask, m1) / n1 + _var(ctrl_mask, m0) / n0)
    se[se == 0] = 1e-6
    lfc = m1 - m0
    t = lfc / se
    tab = (pd.DataFrame({"symbol": gene_symbols, "lfc": lfc, "t": t,
                         "mean_pert": m1, "mean_ctrl": m0})
             .dropna(subset=["symbol"])
             .groupby("symbol", as_index=False)
             .agg({"lfc": "mean", "t": "mean", "mean_pert": "max", "mean_ctrl": "max"}))
    tab = tab[(tab["mean_pert"] > min_mean) | (tab["mean_ctrl"] > min_mean)]
    up = tab.sort_values("t", ascending=False)["symbol"].head(n_top).tolist()
    dn = tab.sort_values("t", ascending=True)["symbol"].head(n_top).tolist()
    return up, dn, tab


# --------------------------------------------------------------------------- #
# 2. Connectivity query against LINCS L1000 via Enrichr                        #
# --------------------------------------------------------------------------- #
def _enrichr_addlist(genes, description="sig"):
    r = requests.post(f"{ENRICHR}/addList",
                      files={"list": (None, "\n".join(genes)),
                             "description": (None, description)}, timeout=30)
    r.raise_for_status()
    return r.json()["userListId"]


def _enrichr_enrich(uid, library):
    r = requests.get(f"{ENRICHR}/enrich",
                     params={"userListId": uid, "backgroundType": library}, timeout=60)
    r.raise_for_status()
    return r.json().get(library, [])


def _parse_lincs_term(term):
    # e.g. "LJP006 A549 24H-mitoxantrone-0.37"
    parts = term.split(" ")
    cell = parts[1] if len(parts) > 1 else ""
    tail = " ".join(parts[2:]) if len(parts) > 2 else term
    m = re.match(r"(\d+H)-(.+)-([\d\.]+)$", tail)
    if m:
        return cell, m.group(1), m.group(2).strip(), m.group(3)
    return cell, "", tail, ""


def connectivity_query(signature_genes, direction="mimic", lung_only=False,
                       library=None, top=None):
    """Rank LINCS compounds by connectivity to a TF signature.

    direction="mimic"   : pass the TF UP list; hits reproduce the TF program.
    direction="reverse" : pass the TF DOWN list; hits oppose the TF program.
    Set lung_only=True to keep only lung cell lines (A549, HCC515, ...).
    """
    lib = library or LIB_CHEM_UP
    uid = _enrichr_addlist(signature_genes, f"tf_{direction}")
    time.sleep(0.3)
    rows = _enrichr_enrich(uid, lib)
    recs = []
    for r in rows:
        cell, dur, drug, dose = _parse_lincs_term(r[1])
        recs.append({"cell_line": cell, "drug": drug, "dose": dose, "duration": dur,
                     "pval": r[2], "combined_score": r[4],
                     "n_overlap": len(r[5]), "overlap_genes": ";".join(r[5]),
                     "direction": direction, "term": r[1]})
    df = pd.DataFrame(recs)
    if lung_only and len(df):
        df = df[df["cell_line"].str.contains(LUNG_LINE_RE, na=False)]
    df = df.sort_values("combined_score", ascending=False).reset_index(drop=True)
    return df.head(top) if top else df


# --------------------------------------------------------------------------- #
# 3. Cross-reference against Tahoe-100M (single-cell drug atlas w/ A549)        #
# --------------------------------------------------------------------------- #
def load_tahoe_drugs():
    """Return the Tahoe-100M drug_metadata table (379 compounds, annotated)."""
    out, off = [], 0
    while True:
        j = requests.get(f"{HF}/rows",
                         params={"dataset": TAHOE_DS, "config": "drug_metadata",
                                 "split": "train", "offset": off, "length": 100},
                         timeout=60).json()
        rows = [r["row"] for r in j["rows"]]
        out += rows
        off += len(rows)
        if off >= j.get("num_rows_total", 0) or not rows:
            break
    return pd.DataFrame(out)


def load_tahoe_cell_lines():
    """Return Tahoe-100M cell_line_metadata (one row per driver mutation)."""
    out, off = [], 0
    while True:
        j = requests.get(f"{HF}/rows",
                         params={"dataset": TAHOE_DS, "config": "cell_line_metadata",
                                 "split": "train", "offset": off, "length": 100},
                         timeout=60).json()
        rows = [r["row"] for r in j["rows"]]
        out += rows
        off += len(rows)
        if off >= j.get("num_rows_total", 0) or not rows:
            break
    return pd.DataFrame(out)


def cross_ref_tahoe(conn_df, tahoe_drugs=None):
    """Annotate connectivity hits with whether the compound is in Tahoe-100M
    (i.e. single-cell response data — including A549 — is available)."""
    if tahoe_drugs is None:
        tahoe_drugs = load_tahoe_drugs()
    tmap = {str(n).lower(): n for n in tahoe_drugs["drug"].dropna().unique()}
    def norm(s):
        return re.sub(r"\s*\(.*?\)", "", str(s)).strip().lower()
    df = conn_df.copy()
    df["in_tahoe"] = df["drug"].map(lambda d: norm(d) in tmap or str(d).lower() in tmap)
    ann = tahoe_drugs.set_index(tahoe_drugs["drug"].str.lower())
    def annotate(d):
        key = norm(d)
        row = ann.loc[key] if key in ann.index else (
              ann.loc[str(d).lower()] if str(d).lower() in ann.index else None)
        if row is None:
            return pd.Series({"tahoe_moa": "", "tahoe_targets": "", "tahoe_cid": ""})
        if isinstance(row, pd.DataFrame):
            row = row.iloc[0]
        return pd.Series({"tahoe_moa": row.get("moa-fine", ""),
                          "tahoe_targets": row.get("targets", ""),
                          "tahoe_cid": row.get("pubchem_cid", "")})
    df = pd.concat([df, df["drug"].apply(annotate)], axis=1)
    return df


if __name__ == "__main__":
    # Minimal smoke test with a p53-activation signature.
    up = ["CDKN1A", "MDM2", "BAX", "GADD45A", "BBC3", "SESN1", "FAS", "TP53I3"]
    res = connectivity_query(up, direction="mimic", lung_only=True, top=10)
    print(res[["cell_line", "drug", "dose", "combined_score", "pval"]].to_string(index=False))
