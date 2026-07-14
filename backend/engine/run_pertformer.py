#!/usr/bin/env python
"""
run_pertformer.py  — PertFormer zero-shot expression inference on GPU (Modal A100).

Replicates codes/example_gexp_compute.ipynb, generalized to:
  - multiple input files (conditions), each concatenating MANY genes,
  - per-gene forward pass using each gene's peak_index_range + tss_loc + strand from a sidecar json.

Emits out/predictions.json = {condition: {gene: predicted_expression_float}} for the readout.

Layout expected in the job workdir (staged by submit_job inputs=, flat):
  models.py, attention.py, data_processing.py, kmer_dict.pkl   (from the repo)
  manifest.json  = {conditions:[{name, txt, sidecar}]}
  info_*.txt, info_*.sidecar.json                              (the 6 input files)
Weights mounted at /weights (Modal Volume): the 11 .pkl files.
"""
import os, json, sys
import torch
from einops import rearrange

sys.path.insert(0, ".")   # models.py / attention.py / data_processing.py shipped flat
from data_processing import tokenizer, pre_pro, narrowPeak_Reader
import models, attention          # noqa: needed so torch.load can unpickle the module objects
from models import *              # noqa
from attention import *          # noqa
import torch.nn.functional as _F
models.F = _F                     # models.AttentionPool.forward references F.pad (dead branch here, but be safe)

WEIGHTS = os.environ.get("PF_WEIGHTS", "/weights")
DEVICE  = torch.device("cuda", 0)
_UNK = {"count": 0}


def safe_pre_processing(tok_str, genome_dict):
    """Map 6-mer tokens to ids; any k-mer not in the dict (e.g. contains 'N') -> [MASK]=3.
    DNA is state-independent, so this is identical across Ref/KI/tip and cannot bias the comparison."""
    toks = tok_str.split()
    out = []
    for t in toks:
        v = genome_dict.get(t)
        if v is None:
            v = 3; _UNK["count"] += 1   # [MASK]
        out.append(v)
    return out


def load_model():
    def L(name):
        return torch.load(os.path.join(WEIGHTS, name), map_location="cpu", weights_only=False).to(DEVICE).eval()
    return dict(
        dna_embed=L("dna_embed.pkl"), atac_embed=L("atac_embed.pkl"),
        pos1_embed=L("pos1_embed.pkl"), pos2_embed=L("pos2_embed.pkl"),
        tss_embed=L("tss_embed.pkl"), pad_embed=L("pad_embed.pkl"),
        encoder_1=L("transformer_1.pkl"), encoder_2=L("transformer_2.pkl"),
        encoder_3=L("transformer_3.pkl"), atten_pool=L("atten_pool.pkl"),
        ff_net=L("feedforward.pkl"),
    )


def parse_info(txt_path, genome_dict):
    """Return list of peaks (dna_tokens, atac_discretized) in file order."""
    raw = narrowPeak_Reader(txt_path)
    n = len(raw) // 3
    dna_in, atac_in = [], []
    for i in range(n):
        dna_seq = raw[i*3+1][0]
        dna_in.append(safe_pre_processing(tokenizer(dna_seq, 6), genome_dict))
        atac_vals = [float(v) for v in raw[i*3+2]]
        atac_in.append(pre_pro(atac_vals, 6))
    return dna_in, atac_in


def forward_gene(m, dna_g, atac_g, tss_loc, direction, verify=False):
    """One gene: dna_g/atac_g are lists of peaks. Returns scalar predicted expression."""
    dna_in = torch.tensor(dna_g).to(DEVICE)
    sig_in = torch.tensor(atac_g).to(DEVICE)
    npk = dna_in.shape[0]
    if npk == 0:
        return None
    pos1 = torch.arange(1, 130, dtype=torch.int, device=DEVICE)          # 129
    pos2 = torch.arange(1, 9, dtype=torch.int, device=DEVICE)            # 8
    pos3 = torch.zeros(150, dtype=torch.int, device=DEVICE)
    tl = int(tss_loc)
    tl = max(1, min(tl, npk-2)) if npk >= 3 else 0                        # keep neighbors in-range
    pos3[tl] = 0
    if npk >= 3:
        if direction == '+':
            pos3[tl-1] = 1; pos3[tl+1] = 2
            for k in range(tl-1): pos3[tl-1-k-1] = pos3[tl-1-k] + 2
            for k in range(npk-tl-2): pos3[tl+1+k+1] = pos3[tl+1+k] + 2
        else:
            pos3[tl-1] = 2; pos3[tl+1] = 1
            for k in range(tl-1): pos3[tl-1-k-1] = pos3[tl-1-k] + 2
            for k in range(npk-tl-2): pos3[tl+1+k+1] = pos3[tl+1+k] + 2
    with torch.no_grad():
        CLS     = m["dna_embed"](torch.ones(npk*8, 1, dtype=torch.int, device=DEVICE))
        x_POS_1 = m["pos1_embed"](pos1)
        x_mul   = m["dna_embed"](dna_in.int().reshape(npk*8, 128)) + m["atac_embed"](sig_in.int().reshape(npk*8, 128))
        x_embed = torch.cat((CLS, x_mul), dim=1)
        x_enc_1 = m["encoder_1"](x_embed + x_POS_1)[:, 0, :].reshape(npk, 8, 2048)
        x_POS_2 = m["pos2_embed"](pos2)
        x_enc_2 = m["encoder_2"](x_enc_1 + x_POS_2)
        x_enc_2 = rearrange(x_enc_2, 'b n d -> b d n')
        x_enc_2 = m["atten_pool"](x_enc_2)
        x_enc_2 = rearrange(x_enc_2, 'b d n -> b n d').squeeze(1)
        x_pad   = m["pad_embed"](torch.zeros(150-npk, dtype=torch.int, device=DEVICE))
        x_eb3   = torch.cat((x_enc_2, x_pad), dim=0)
        x_POS_3 = m["tss_embed"](pos3)
        x_enc_3 = m["encoder_3"](x_eb3 + x_POS_3)
        result  = m["ff_net"](x_enc_3).squeeze(1)
    # ff_net (ANN) flattens all 150x2048 features -> 1 scalar; result reshapes to (1,) = this gene's expression.
    r = result.reshape(-1)
    if verify:
        print(f"[verify] npk={npk} result.shape={tuple(result.shape)} -> scalar={float(r[0].item()):.5f}", flush=True)
    return float(r[0].item())


def main():
    os.makedirs("out", exist_ok=True)
    man = json.load(open("manifest.json"))
    genome_dict = torch.load("kmer_dict.pkl")
    m = load_model()
    print(f"[pertformer] weights loaded on {torch.cuda.get_device_name()}", flush=True)

    preds, first = {}, True
    for cond in man["conditions"]:
        name, txt, side = cond["name"], cond["txt"], cond["sidecar"]
        dna_in, atac_in = parse_info(txt, genome_dict)
        sidecar = json.load(open(side))
        gene_expr = {}
        for gene, meta in sidecar.items():
            if not meta or meta.get("n_peaks", 0) == 0:
                gene_expr[gene] = None; continue
            a, b = meta["peak_index_range"]
            dna_g, atac_g = dna_in[a:b+1], atac_in[a:b+1]
            tss_loc = meta.get("tss_loc", 0) or 0
            direction = meta.get("strand", "+")
            try:
                gene_expr[gene] = forward_gene(m, dna_g, atac_g, tss_loc, direction, verify=first)
                first = False
            except Exception as e:
                gene_expr[gene] = None
                print(f"[warn] {name}/{gene}: {e}", flush=True)
        preds[name] = gene_expr
        done = sum(1 for v in gene_expr.values() if v is not None)
        print(f"[pertformer] {name}: {done}/{len(gene_expr)} genes predicted", flush=True)
        json.dump(preds, open("out/predictions.json", "w"), indent=2)  # checkpoint after each condition

    json.dump(preds, open("out/predictions.json", "w"), indent=2)
    print(f"[pertformer] predictions DONE ({_UNK['count']} unknown k-mers -> [MASK])", flush=True)

    # ---- readout: cosine-similarity fate proximity (the paper's metric, on PREDICTED EXPRESSION) ----
    readout = {}
    for route in ["human", "mouse"]:
        ref = preds.get(f"{route}_AT2_ref", {})
        ki  = preds.get(f"{route}_AT2_OSKM_KI", {})
        tip = preds.get(f"{route}_distal_tip", {})
        genes = [g for g in ref if ref.get(g) is not None and ki.get(g) is not None and tip.get(g) is not None]
        if not genes:
            continue
        import math
        def vec(d): return [float(d[g]) for g in genes]
        def cos(a, b):
            dot = sum(x*y for x, y in zip(a, b))
            na = math.sqrt(sum(x*x for x in a)); nb = math.sqrt(sum(y*y for y in b))
            return dot/(na*nb) if na > 0 and nb > 0 else float("nan")
        a, k, t = vec(ref), vec(ki), vec(tip)
        cos_ref_tip = cos(a, t); cos_ki_tip = cos(k, t)
        readout[route] = {
            "n_genes": len(genes),
            "cos_AT2ref_to_tip": round(cos_ref_tip, 4),
            "cos_AT2_OSKM_KI_to_tip": round(cos_ki_tip, 4),
            "delta_proximity": round(cos_ki_tip - cos_ref_tip, 4),
            "genes": genes,
        }
        print(f"[readout] {route}: cos(AT2ref,tip)={cos_ref_tip:.4f}  "
              f"cos(AT2+OSKM,tip)={cos_ki_tip:.4f}  Δ={cos_ki_tip-cos_ref_tip:+.4f}", flush=True)
    json.dump(readout, open("out/fate_proximity_readout.json", "w"), indent=2)
    print("[pertformer] DONE ->", list(preds), flush=True)


if __name__ == "__main__":
    main()
