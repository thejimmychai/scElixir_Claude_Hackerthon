#!/usr/bin/env python
"""Epithelial GRN + in-silico perturbation (CellOracle 0.20.0, local CPU).
Resumable; single-writer log. Forces joblib THREADING backend: the sandbox
denies os.sysconf('SC_SEM_NSEMS_MAX'), which loky (default process backend)
calls uncaught -> PermissionError. Threading avoids semaphores; ridge/LAPACK
releases the GIL so we still get real parallelism."""
import os, sys, time, json
os.environ.setdefault('HOME','/tmp/co_home'); os.makedirs('/tmp/co_home',exist_ok=True)
os.environ.setdefault('NUMBA_CACHE_DIR','/tmp/numba_celloracle')
NJ=12
os.environ['OMP_NUM_THREADS']=os.environ['MKL_NUM_THREADS']=os.environ['OPENBLAS_NUM_THREADS']=str(NJ)
import numpy as np, pandas as pd, scanpy as sc, anndata as ad, celloracle as co
import joblib
def log(m): print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)

IN="build/epi_celloracle_input.h5ad"; ORACLE="build/epi_oracle.celloracle.oracle"
LINKS="build/epi_links.celloracle.links"; DONE="build/EPI_GRN_DONE"
CANDS=["TEAD1","ETV5","SOX9","FOXJ1","GATA6","NKX2-1","SOX2","TP63","MYRF","ETV4"]

def main():
    log(f"CellOracle {co.__version__} | joblib backend=threading n_jobs={NJ}")
    # ---- Stage 1: Oracle + preprocessing ----
    if not os.path.exists(ORACLE):
        A=ad.read_h5ad(IN); log(f"loaded {A.shape}")
        A.layers['raw_count']=A.X.copy()
        sc.pp.normalize_total(A, target_sum=1e4); sc.pp.log1p(A)
        A.obs['cell_state']=A.obs['cell_state'].astype('category')
        oracle=co.Oracle(); A.X=A.layers['raw_count'].copy()
        oracle.import_anndata_as_raw_count(adata=A, cluster_column_name='cell_state', embedding_name='X_umap')
        oracle.import_TF_data(TF_info_matrix=co.data.load_human_promoter_base_GRN())
        log("PCA"); oracle.perform_PCA(n_components=50)
        ev=np.cumsum(oracle.pca.explained_variance_ratio_)
        n_comps=int(min(50, max(20, (np.where(ev>0.85)[0][0]+1) if (ev>0.85).any() else 50)))
        k=int(0.025*oracle.adata.shape[0])
        log(f"kNN imputation n_pca={n_comps} k={k}")
        oracle.knn_imputation(n_pca_dims=n_comps, k=k, balanced=True, b_sight=k*8, b_maxl=k*4, n_jobs=NJ)
        oracle.to_hdf5(ORACLE); log("saved Oracle")
    else:
        oracle=co.load_hdf5(ORACLE); log("loaded Oracle checkpoint")

    # ---- Stage 2: per-cell-state GRN links ----
    if not os.path.exists(LINKS):
        log("get_links (per-state bagging ridge)")
        links=oracle.get_links(cluster_name_for_GRN_unit='cell_state', alpha=10, n_jobs=NJ, verbose_level=0)
        links.filter_links(p=0.001, weight="coef_abs", threshold_number=2000)
        links.to_hdf5(LINKS); log(f"saved links ({len(links.links_dict)} states)")
    else:
        links=co.load_hdf5(LINKS); log("loaded links checkpoint")

    # ---- Stage 3: network scores + simulation fit ----
    log("network scores"); links.get_network_score()
    links.merged_score.to_csv("build/epi_grn_network_scores.csv")
    oracle.get_cluster_specific_TFdict_from_Links(links_object=links)
    oracle.fit_GRN_for_simulation(alpha=10, use_cluster_specific_TFdict=True)
    log("GRN fit for simulation done")

    # ---- Stage 4: in-silico KO ----
    present=[g for g in CANDS if g in oracle.adata.var_names]
    log(f"in-silico KO: {present}")
    ko={}
    for tf in present:
        try:
            oracle.simulate_shift(perturb_condition={tf:0.0}, n_propagation=3)
            oracle.estimate_transition_prob(n_neighbors=200, knn_random=True, sampled_fraction=1, n_jobs=NJ)
            oracle.calculate_embedding_shift(sigma_corr=0.05)
            de=getattr(oracle,'delta_embedding',None)
            mag=float(np.linalg.norm(de,axis=1).mean()) if de is not None else None
            per={}
            if de is not None:
                cs=oracle.adata.obs['cell_state'].values
                for st in np.unique(cs): per[str(st)]=float(np.linalg.norm(de[cs==st],axis=1).mean())
            ko[tf]={'mean_shift_magnitude':mag,'per_state_shift':per}
            log(f"  {tf}: mean shift {mag:.4f}")
        except Exception as e:
            ko[tf]={'error':str(e)[:150]}; log(f"  {tf} FAILED: {str(e)[:150]}")
    json.dump(ko, open("build/epi_insilico_KO_summary.json","w"), indent=2)
    oracle.to_hdf5(ORACLE)
    open(DONE,"w").write(f"EPI_GRN_DONE {oracle.adata.shape[0]} cells\n")
    log("EPI_GRN_DONE")

with joblib.parallel_backend('threading', n_jobs=NJ):
    main()
