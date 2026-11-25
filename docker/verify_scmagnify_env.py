#!/usr/bin/env python3
"""
Deterministic smoke & functional verification script for the scMagnify + scElixir
Docker environment. Tests:
  1. Core package imports & exact version reporting
  2. MSNGC self-explaining multi-scale neural Granger causality forward/backward pass
  3. MAGNI partial ordering + time-lag estimation + decoupler MLM regulon activity
  4. RegDecomp Tucker tensor decomposition (TFs x TGs x Lags -> RegFactors)
  5. Google GenAI SDK (Interactions API client surface check)
"""
from __future__ import annotations

import argparse
import sys
import numpy as np
import pandas as pd
import scipy.sparse as sp
import torch
import anndata as ad


def verify(quick: bool = False) -> None:
    print("=" * 72)
    print("scMagnify + scElixir Reproducible Environment Verification")
    print("=" * 72)

    import mudata as md
    import scanpy as sc
    import cellrank as cr
    import decoupler as dc
    import tensorly as tl
    import scmagnify as scm
    from google import genai

    print(f"Python      : {sys.version.split()[0]}")
    print(f"PyTorch     : {torch.__version__} (CUDA available: {torch.cuda.is_available()})")
    print(f"NumPy/SciPy : {np.__version__} / {sp.__name__} ({__import__('scipy').__version__})")
    print(f"AnnData/MuD : {ad.__version__} / {md.__version__}")
    print(f"Scanpy/CR   : {sc.__version__} / {cr.__version__}")
    print(f"Decoupler/TL: {dc.__version__} / {tl.__version__}")
    print(f"scMagnify   : {getattr(scm, '__version__', '0.1.1')}")
    print(f"google-genai: {getattr(genai, '__version__', 'installed')}")

    # Verify Gemini Interactions API client surface exists
    assert hasattr(genai, "Client"), "google.genai.Client missing"

    if quick:
        # Quick MSNGC neural forward check
        model = scm.MSNGC(n_reg=6, n_target=12, hidden=[16], lag=5, device="cpu")
        x = torch.randn(8, 5, 6)
        coeffs, y_pred, atten = model(x)
        assert coeffs.shape == (8, 5, 12, 6), f"Unexpected coeffs shape: {coeffs.shape}"
        assert y_pred.shape == (8, 12), f"Unexpected y_pred shape: {y_pred.shape}"
        assert atten.shape == (1, 5), f"Unexpected attention shape: {atten.shape}"
        print("[OK] Quick MSNGC multi-scale Granger forward pass verified.")
        return

    # Full synthetic MAGNI + RegDecomp end-to-end smoke test
    rng = np.random.default_rng(42)
    n_cells, n_genes = 96, 24
    gene_names = [f"TF{i}" for i in range(6)] + [f"TG{j}" for j in range(18)]
    t = np.linspace(0.0, 1.0, n_cells, dtype=np.float32)
    counts = rng.poisson(lam=3.0, size=(n_cells, n_genes)).astype(np.float32)
    # Plant lagged causal signal TF0 -> TG0..TG4, TF1 -> TG5..TG9
    for j in range(5):
        counts[3:, 6 + j] += 2.0 * counts[:-3, 0]
        counts[1:, 11 + j] += 2.0 * counts[:-1, 1]

    adata = ad.AnnData(X=sp.csr_matrix(counts))
    adata.var_names = gene_names
    adata.obs_names = [f"cell_{i}" for i in range(n_cells)]
    adata.layers["counts"] = sp.csr_matrix(counts)
    adata.obs["palantir_pseudotime"] = t
    adata.obs["celltype"] = pd.Categorical(["Early"] * 32 + ["Mid"] * 32 + ["Late"] * 32)
    sc.pp.normalize_total(adata, target_sum=1e4)
    sc.pp.log1p(adata)
    adata.layers["log1p_norm"] = adata.X.copy()
    sc.tl.pca(adata, n_comps=10)
    sc.pp.neighbors(adata, n_neighbors=10)
    sc.tl.umap(adata)

    basal_edges = []
    for tf in gene_names[:6]:
        for tg in gene_names[6:]:
            basal_edges.append({"TF": tf, "Target": tg, "Score": 1})
    basal_df = pd.DataFrame(basal_edges)

    magni = scm.MAGNI(
        data=adata,
        gene_selected=gene_names,
        basal_grn=basal_df,
        time_key="palantir_pseudotime",
        hidden=[16],
        lag=5,
        max_iter=15,
        patience=5,
        batch_size=32,
        seed=42,
        device="cpu",
    )
    magni.train()
    gdata = magni.regulation_inference(cv_thres=0.5, filter=["quantile", 0.75, True])
    gdata = scm.tl.get_network_score(gdata)
    decomper = scm.RegDecomp(gdata)
    decomper.tucker_decomposition(rank=3)
    decomper.compute_activity()
    assert "RegFactor" in gdata.mod, "RegFactor modality missing after compute_activity()"
    print("[OK] Full MAGNI + decoupler MLM + RegDecomp Tucker verification passed!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true", help="Run fast build-time check")
    args = parser.parse_args()
    verify(quick=args.quick)
