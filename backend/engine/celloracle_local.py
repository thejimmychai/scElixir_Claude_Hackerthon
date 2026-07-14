"""
Local CellOracle GRN pipeline for reprogramming landscape (no GPU, no cisTarget DB).

Replaces the GPU-host Phase-2 plan with a CPU-only local pipeline:
  - Base GRN: CellOracle built-in promoter/motif atlas (species-matched), NOT per-sample scATAC.
  - GRN inference: bagging-ridge regression per stage (cluster unit = 'stage').
  - Rewiring: differential edge strength between consecutive stages.
  - In-silico perturbation: simulate_shift for TF KO/OE per transition.

Scientific note on the base-GRN substitution:
  The approved plan used SCENIC+ eRegulons from paired scATAC + a 47 GB cisTarget DB on a GPU host.
  Running locally, we use CellOracle's promoter-based base GRN (published motif->promoter atlas) as the
  prior on possible TF->gene edges, then prune/weight it per stage with the dataset's own scRNA via
  bagging ridge. Trade-off: edges come from a motif atlas rather than each sample's own accessibility,
  so they are slightly less sample-specific; but the *perturbation biology* (which TFs drive each
  transition, and the effect of KO/OE) is preserved and this is CellOracle's standard documented mode.
"""
import os
os.environ.setdefault("NUMBA_CACHE_DIR","/tmp/numba_cache")
os.environ.setdefault("HOME","/tmp/ch_home")
os.makedirs(os.path.join(os.environ["HOME"],"Library/Application Support"),exist_ok=True)
import numpy as np, pandas as pd, scanpy as sc, anndata as ad, celloracle as co
import scipy.sparse as sp

def prep_counts_adata(path, stage_col="stage", counts_layer="counts", n_hvg=3000, n_top_stage_cells=None):
    """Load staged h5ad, restore raw counts to X, HVG-select, PCA/neighbors/UMAP for CellOracle."""
    adata = sc.read_h5ad(path)
    # restore raw counts to X
    if counts_layer in adata.layers:
        adata.X = adata.layers[counts_layer].copy()
    else:
        # mouse case: only lognorm available -> caller must handle; here assume counts present
        raise ValueError(f"no '{counts_layer}' layer in {path}; raw counts required for CellOracle")
    adata.layers["raw_count"] = adata.X.copy()
    # standard scanpy prep on a fresh normalized copy for embedding
    sc.pp.normalize_total(adata, target_sum=1e4); sc.pp.log1p(adata)
    sc.pp.highly_variable_genes(adata, n_top_genes=n_hvg)
    adata = adata[:, adata.var.highly_variable].copy()
    sc.pp.scale(adata, max_value=10)
    sc.tl.pca(adata, n_comps=50)
    sc.pp.neighbors(adata, n_neighbors=15, n_pcs=50)
    if "X_umap" not in adata.obsm: sc.tl.umap(adata)
    # restore counts into X for CellOracle raw-count import
    adata.X = adata.layers["raw_count"][:, :].copy() if False else adata.layers["raw_count"]
    return adata

def build_oracle(adata, base_grn, stage_col="stage"):
    oracle = co.Oracle()
    adata.X = adata.layers["raw_count"].copy()
    oracle.import_anndata_as_raw_count(adata=adata, cluster_column_name=stage_col, embedding_name="X_umap")
    oracle.import_TF_data(TF_info_matrix=base_grn)
    oracle.perform_PCA()
    n_comps = min(50, oracle.pca.explained_variance_ratio_.shape[0])
    k = int(0.025*oracle.adata.shape[0]); k=max(25,min(k,200))
    oracle.knn_imputation(n_pca_dims=n_comps, k=k, balanced=True, b_sight=min(k*8, oracle.adata.shape[0]-1),
                          b_maxl=min(k*4, oracle.adata.shape[0]-1), n_jobs=8)
    return oracle

def infer_links(oracle, stage_col="stage", alpha=10, bagging=20):
    links = oracle.get_links(cluster_name_for_GRN_unit=stage_col, alpha=alpha, bagging_number=bagging,
                             model_method="bagging_ridge", n_jobs=-1, verbose_level=0)
    links.filter_links(p=0.001, weight="coef_abs", threshold_number=2000)
    return links
