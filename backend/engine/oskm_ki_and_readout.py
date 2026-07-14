#!/usr/bin/env python
"""
oskm_ki_and_readout.py
======================
Phase-3 scaffold for the OSKM-KI-on-AT2 -> distal-progenitor proximity experiment.

This file has TWO jobs, both of which run on the PertFormer per-gene input files produced
in Phase 2 (info_<state>.txt + info_<state>.sidecar.json):

  (1) make_oskm_ki_file()   — take the AT2 reference input and write the OSKM-KI-perturbed
                              input, editing ONLY the ATAC signal lines (DNA + peak set unchanged),
                              exactly as the paper describes:
                              "inducing the highest ATAC peak flanking the 300,000-bp of the TSS
                               of targeted gene to the loci with OSKM motifs".
  (2) fate_proximity()      — after PertFormer has predicted expression for each state/condition,
                              compute the cosine-similarity fate score (AT2, OSKM-KI-AT2, target).

PertFormer itself (the 3B-param DNA+ATAC->expression model) is NOT run here — it is GPU-gated
(A100 recommended) and must run on the online app (pertformer.ibreed.cn) or a provisioned GPU.
The runbook (RUNBOOK.md) explains where these functions plug into that run.

Input file format (shipped + our Phase-2 output), 3 lines per peak:
    >chrom_start_end
    <1029 bp DNA>
    <1029 whitespace-separated ATAC floats>
Genes are concatenated; the sidecar json maps each gene -> {tss_loc, strand, n_peaks, peak_index_range}.
"""
import json, argparse, math
import numpy as np


# ----------------------------------------------------------------------------- I/O
def read_info(path):
    """Return list of peaks: [{id, dna, atac(np.array len1029)}], in file order."""
    peaks, buf = [], []
    with open(path) as f:
        lines = [ln.rstrip("\n") for ln in f if ln.strip() != ""]
    assert len(lines) % 3 == 0, f"{path}: line count {len(lines)} not a multiple of 3"
    for i in range(0, len(lines), 3):
        pid, dna, atac = lines[i], lines[i+1], lines[i+2]
        assert pid.startswith(">"), f"peak id line malformed at {i}: {pid[:40]}"
        assert len(dna) == 1029, f"DNA len {len(dna)} != 1029 at peak {i//3}"
        vals = np.array([float(x) for x in atac.split()], dtype=float)
        assert vals.size == 1029, f"ATAC len {vals.size} != 1029 at peak {i//3}"
        peaks.append({"id": pid, "dna": dna, "atac": vals})
    return peaks


def write_info(peaks, path):
    with open(path, "w") as f:
        for p in peaks:
            f.write(p["id"] + "\n")
            f.write(p["dna"] + "\n")
            f.write(" ".join(f"{x:.4f}" for x in p["atac"]) + "\n")


def peak_coords(pid):
    """'>chr8_127735000_127736028' -> ('chr8', 127735000, 127736028)."""
    s = pid[1:]
    chrom, a, b = s.rsplit("_", 2)
    return chrom, int(a), int(b)


# ------------------------------------------------------------------- OSKM-KI edit
def make_oskm_ki_file(ref_txt, ref_sidecar, motif_hits_csv, out_txt,
                      score_quantile=0.90, ki_scale=1.0):
    """
    Write the OSKM-KI-perturbed input from the AT2 reference input.

    Mechanism (paper p.9): within each gene's +/-300 kb window, find the loci that carry an
    OSKM motif (POU5F1/SOX2/KLF4/MYC), and RAISE their ATAC signal to the level of the window's
    highest existing peak. We only edit peaks that (a) overlap a strong OSKM motif hit and
    (b) are not already at/above that max.

    Args:
      ref_txt, ref_sidecar : the AT2 reference PertFormer input + its sidecar json.
      motif_hits_csv       : oskm_motif_hits_<species>_<genome>.csv (cols: gene,factor,chrom,
                             motif_pos,strand,score,...). Motif coords MUST be in the same genome
                             as the peaks in ref_txt.
      out_txt              : path for the OSKM-KI input.
      score_quantile       : keep only motif hits at/above this per-factor score quantile
                             (0.90 = strongest 10% of motif matches) to avoid editing weak sites.
      ki_scale             : multiply the induced level by this (1.0 = exactly the window max).

    Returns a summary dict (n peaks edited per gene, etc.).
    """
    import pandas as pd
    peaks = read_info(ref_txt)
    sidecar = json.load(open(ref_sidecar))
    motifs = pd.read_csv(motif_hits_csv)

    # per-factor score threshold
    thr = motifs.groupby("factor")["score"].quantile(score_quantile).to_dict()
    strong = motifs[motifs.apply(lambda r: r["score"] >= thr.get(r["factor"], 1e9), axis=1)].copy()

    edited_summary = {}
    for gene, meta in sidecar.items():
        if not meta or meta.get("n_peaks", 0) == 0:
            continue
        a, b = meta["peak_index_range"]
        gpeaks = peaks[a:b+1]
        # window max profile level = the single highest ATAC value across this gene's peaks
        win_max = max(float(p["atac"].max()) for p in gpeaks)
        target_level = win_max * ki_scale
        gmot = strong[strong["gene"] == gene]
        if gmot.empty:
            edited_summary[gene] = {"edited": 0, "win_max": round(win_max, 3)}
            continue
        mpos = gmot[["chrom", "motif_pos"]].values.tolist()
        n_ed = 0
        for p in gpeaks:
            chrom, s, e = peak_coords(p["id"])
            # does any strong OSKM motif fall inside this peak's 1029-bp span?
            hit = any((str(mc) == chrom or ("chr"+str(mc)) == chrom or str(mc) == chrom.replace("chr",""))
                      and s <= int(mp) <= e for mc, mp in mpos)
            if not hit:
                continue
            cur_max = float(p["atac"].max())
            if cur_max >= target_level:      # already open; nothing to induce
                continue
            # raise this peak's profile to the window-max level, preserving its shape where present.
            # If the peak is essentially closed (flat/low), impose a summit-centered bump at target_level.
            if cur_max <= 1e-6:
                prof = np.zeros(1029)
                center = 514
                width = 150
                idx = np.arange(1029)
                prof = target_level * np.exp(-0.5 * ((idx - center) / width) ** 2)
                p["atac"] = prof
            else:
                p["atac"] = p["atac"] * (target_level / cur_max)
            n_ed += 1
        edited_summary[gene] = {"edited": n_ed, "win_max": round(win_max, 3),
                                "n_strong_motifs": int(len(gmot))}
    write_info(peaks, out_txt)
    total = sum(v["edited"] for v in edited_summary.values())
    return {"out": out_txt, "total_peaks_edited": total, "per_gene": edited_summary}


# --------------------------------------------------------------- fate proximity
def _cosine(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return float("nan")
    return float(np.dot(a, b) / (na * nb))


def fate_proximity(pred_json, gene_order=None, target_state="distal_tip"):
    """
    Compute the fate-proximity scores once PertFormer has produced per-gene predicted expression
    for each condition.

    pred_json : {condition: {gene: predicted_expression_float}}, with conditions at least:
                "AT2_ref", "AT2_OSKM_KI", and the target (e.g. "distal_tip").
    Returns cosine similarity of each condition's predicted-expression vector to the target's,
    plus the KEY readout: does OSKM-KI move AT2 toward the distal-tip profile?
    """
    preds = json.load(open(pred_json)) if isinstance(pred_json, str) else pred_json
    conds = list(preds.keys())
    genes = gene_order or sorted(set().union(*[set(preds[c]) for c in conds]))
    def vec(c): return np.array([preds[c].get(g, 0.0) for g in genes], float)

    tgt_key = next((c for c in conds if target_state in c), None)
    out = {"genes": genes, "cosine_to_target": {}, "target_condition": tgt_key}
    if tgt_key:
        tv = vec(tgt_key)
        for c in conds:
            out["cosine_to_target"][c] = _cosine(vec(c), tv)
        if "AT2_ref" in preds and "AT2_OSKM_KI" in preds:
            base = out["cosine_to_target"]["AT2_ref"]
            after = out["cosine_to_target"]["AT2_OSKM_KI"]
            out["headline"] = {
                "AT2_ref_to_target": base,
                "AT2_OSKM_KI_to_target": after,
                "delta": (after - base) if (base==base and after==after) else float("nan"),
                "interpretation": "positive delta = OSKM-KI moves AT2 toward distal-progenitor fate"
            }
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="OSKM-KI edit + fate-proximity readout for PertFormer inputs")
    sub = ap.add_subparsers(dest="cmd", required=True)
    k = sub.add_parser("ki", help="write OSKM-KI-perturbed input from AT2 reference")
    k.add_argument("--ref-txt", required=True); k.add_argument("--ref-sidecar", required=True)
    k.add_argument("--motif-hits", required=True); k.add_argument("--out", required=True)
    k.add_argument("--score-quantile", type=float, default=0.90); k.add_argument("--ki-scale", type=float, default=1.0)
    r = sub.add_parser("readout", help="cosine-similarity fate proximity from PertFormer predictions")
    r.add_argument("--pred-json", required=True); r.add_argument("--target-state", default="distal_tip")
    a = ap.parse_args()
    if a.cmd == "ki":
        print(json.dumps(make_oskm_ki_file(a.ref_txt, a.ref_sidecar, a.motif_hits, a.out,
                                            a.score_quantile, a.ki_scale)["per_gene"], indent=2))
    else:
        print(json.dumps(fate_proximity(a.pred_json, target_state=a.target_state), indent=2))
