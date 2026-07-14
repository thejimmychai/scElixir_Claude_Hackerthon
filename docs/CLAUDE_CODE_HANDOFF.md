# Universal Developmental Reprogramming Pipeline — Build & Iteration Spec

**Purpose of this document.** A self-contained engineering brief for iterating the **backend** and the
**frontend interface** of the Universal Developmental Reprogramming Pipeline with Claude Code. It captures
the scientific workflow, the existing assets, the per-stage API contracts, the data schemas, and a phased
build plan. Everything here is grounded in four analysis sessions already run in this project — no invented
capabilities.

> **What already exists (starting point) — all exported to real files on disk:**
> Everything below has been written into the build bundle at
> **`~/Desktop/repro-pipeline-build/`** so Claude Code can read it directly (no sandbox / artifact-ID
> lookups needed). See **Section 0.5** for the full tree. Key items:
> - `frontend/reprogramming_pipeline.html` — a standalone single-file interactive blueprint (vanilla JS +
>   embedded JSON, no build step). This is the current frontend.
> - `frontend/seed/pipeline_seed_data.json` — the exact data payload the HTML embeds (organs, stages,
>   layers, reference case, evidence catalog). Seed for the backend's mock responses / integration fixtures.
> - `backend/engine/` — the three reusable engine scripts (+ helpers), ready to wrap.
> - `data/reference/` — the ground-truth CSV/JSON outputs (TF recipes, GRN scores, drug tables, fate
>   scores) any backend must reproduce.
> - `docs/` — this spec plus the science-facing `PIPELINE_README.md` and `CONSTRUCTION_README.md`.

## 0. TL;DR for Claude Code

You are turning a **static, data-embedded HTML blueprint** into a **frontend + backend application** that
runs a 6-stage computational-biology pipeline. The pipeline reverses an adult/mature cell state back toward
its embryonic progenitor and nominates (a) a transcription-factor combination and (b) small-molecule
treatments, validated in-silico.

- **Do not rip out the current HTML.** Refactor it: the embedded `DATA` object becomes an API response;
  each stage's render function becomes a component that fetches instead of reading a global.
- **The pipeline is a DAG of 6 stages (A→F).** Each stage has a defined input/output contract (Section 4).
  Build them as independent, cacheable jobs — most are minutes-to-hours and belong on a worker, not in a
  request handler.
- **One organ (lung) is fully worked; three (liver/pancreas/cornea) are planned.** The backend must treat
  "organ" and "cell layer" as first-class parameters and return a clear "not yet computed" state rather
  than fabricating results. **Never synthesize pipeline outputs** — a stage either has a real cached result
  or reports that it must be run.
- **Reuse the existing engine code** (Section 5) rather than reimplementing: the TF→drug connectivity
  toolkit, the CellOracle GRN wrapper, and the PertFormer runner all exist as tested scripts.

---

## 0.5. Where the files are (read this first)

The entire build kit is exported to disk at **`~/Desktop/repro-pipeline-build/`**. These are plain files —
open, copy, and edit them directly; you do **not** need the Claude Science sandbox or any artifact-ID
lookup to build. The layout already matches the target repo in Section 2, so you can build in place or copy
it out as a git repo root.

```
~/Desktop/repro-pipeline-build/
├── docs/
│   ├── CLAUDE_CODE_HANDOFF.md            # this spec
│   ├── PIPELINE_README.md                # science summary of the 6-stage workflow
│   └── CONSTRUCTION_README.md            # Stage-B atlas construction method (scVI/scANVI)
├── frontend/
│   ├── reprogramming_pipeline.html       # current standalone blueprint (refactor target)
│   └── seed/pipeline_seed_data.json      # the embedded DATA, standalone (fixtures + offline fallback)
├── backend/engine/                        # reusable, tested engine code — wrap, don't rewrite
│   ├── tf_to_drug_connectivity.py        # TF→drug connectivity toolkit (Stages A & E)
│   ├── celloracle_local.py               # CellOracle GRN + perturbation (Stages C & D)
│   ├── run_pertformer.py                 # PertFormer GPU inference (Stage F)
│   ├── oskm_ki_and_readout.py            # in-silico motif KI + fate readout (Stage F helper)
│   └── run_epi_grn.py                    # epithelial GRN driver (Stage C helper)
├── data/reference/                        # ground-truth outputs — regression fixtures for each stage
│   ├── perturbseq_datasets_catalog.csv           # Stage A evidence catalog (36 rows)
│   ├── ALL_lineage_state_TFs.csv                 # Stage B per-state master TFs (all 4 layers)
│   ├── GRN_network_scores_enhancer.csv           # Stage C hub scores
│   ├── AT2_to_TiP_TF_recipe.csv                  # Stage D reference TF recipe
│   ├── lung_AT2_to_progenitor_TF_scheme.csv      # Stage D stage-gated module scheme
│   ├── alternative_stagewise_TF_scheme.csv       # Stage D alternative scheme
│   ├── insilico_TF_perturbation_screen.csv       # Stage D raw KO/OE screen
│   ├── AT2_to_TiP_compounds.csv                  # Stage E compound nominations
│   ├── lung_AT2_to_progenitor_small_molecules.csv# Stage E curated cocktail
│   ├── AT2_to_TiP_tahoe_validation.csv           # Stage E single-cell confirmation
│   ├── distaltf_fate_proximity_readout.json      # Stage F fate scores (distal-TF cocktail)
│   ├── fate_proximity_readout.json               # Stage F fate scores (OSKM)
│   └── pertformer_io_contract.json               # Stage F model I/O contract (peaks, tokens, KI rules)
└── BUNDLE_MANIFEST.txt                    # every file with size + sha256 prefix
```

**Not in the bundle (too large / must be fetched or recomputed):** the integrated `*_subatlas.h5ad`
atlases (Stage B outputs, multi-GB), the CellOracle `.links` objects, PertFormer weights (~12.8 GB, on
Hugging Face), and the model repo source (`models.py`/`attention.py`/`data_processing.py`/`kmer_dict.pkl`,
cloned from the PertFormer repo). Section 4/5 note where each is obtained. The reference CSV/JSON in
`data/reference/` are the *summarized outputs* of those heavy artifacts — enough to seed fixtures and
regression-test every stage without the raw data.

Wherever this spec below names a bare filename (e.g. `AT2_to_TiP_TF_recipe.csv`), it lives under
`data/reference/`; engine scripts live under `backend/engine/`. Paths are given relative to the bundle root.

---

## 1. The scientific workflow (what the pipeline computes)

The pipeline collapses four project sessions into **one 6-stage spine**. Input: an organ + cell layer +
a source→target state transition + species. Output: a ranked TF combination and small-molecule cocktail
to drive the reversal, with an in-silico fate-proximity score.

| Stage | Name | Goal | Core method | Compute | Source session |
|---|---|---|---|---|---|
| **A** | Evidence base | Catalog large-scale Perturb-seq / TF-OE atlases; build TF→drug engine | GEO/OpenAlex survey; LINCS L1000; Tahoe-100M | CPU + web APIs | Perturb-seq Landscape |
| **B** | Developmental atlas | Assemble + harmonize + integrate embryonic→adult scRNA per lineage; resolve states + master TFs | CELLxGENE Census; scVI/scANVI; DE | CPU (scVI) → GPU at scale | Human Lung Dev Datasets |
| **C** | GRN inference | Per-lineage/stage regulatory network + regulons + hubs | CellOracle base-GRN; SCENIC+ enhancer-aware | GPU (SCENIC+) / CPU (CellOracle) | Lung Dev + Fibroblast |
| **D** | In-silico reversal | Define adult→progenitor transition; KO/OE screen → precision TF combo | CellOracle `simulate_shift` + transition-vector projection | CPU/GPU | Fibroblast + Epithelial |
| **E** | Small-molecule mirror | Map stage signatures to mimicking compounds; single-cell confirm | LINCS connectivity; Tahoe-100M; organ reagent overlay | CPU + web APIs | Perturb-seq + Fibroblast |
| **F** | Deep-learning fate validation | Score {adult, progenitor, TF-KI} with a sequence model; fate-proximity Δ | PertFormer (3B params) motif-KI | **GPU A100** (Modal) | PertFormer AT2 OSKM KI |

**Dependency DAG:** `A → (feeds drug engine into E)`; `B → C → D → {E, F}`. B is the atlas that everything
downstream reads. C needs B. D needs C. E needs D's stage signatures + A's drug engine. F needs D's TF
recipe + ATAC tracks. A is independent and can run first/in parallel.

**Worked reference case (all 6 stages executed):** Lung · Epithelial · adult **AT2 → fetal distal-tip
progenitor**. Headline result — the distal-TF cocktail (SOX9/NKX2-1/ETV5/ETV4) moves human AT2 fate-proximity
Δ **+0.107** toward the tip (cosine 0.656→0.763), ~93% larger than the OSKM cocktail's +0.055. This is the
integration test the backend must reproduce from cache.

---

## 2. Target architecture

Suggested shape (adapt as you see fit — the contracts in Section 4 matter more than the framework):

```
repro-pipeline/
├── frontend/                     # refactor of reprogramming_pipeline.html
│   ├── index.html
│   ├── src/
│   │   ├── state.js              # selection state (organ/layer/source/target/species/stage)
│   │   ├── api.js                # fetch wrappers for the backend
│   │   └── stages/               # one module per stage panel (A–F)
│   └── seed/pipeline_seed_data.json   # offline/mock fallback (== current embedded DATA)
├── backend/
│   ├── app.py                    # API surface (FastAPI recommended)
│   ├── registry.py               # organ/layer/state registry + "what's computed" index
│   ├── stages/                   # one runner module per stage
│   │   ├── stage_a_evidence.py
│   │   ├── stage_b_atlas.py
│   │   ├── stage_c_grn.py
│   │   ├── stage_d_reversal.py
│   │   ├── stage_e_drugs.py
│   │   └── stage_f_pertformer.py
│   ├── engine/                   # REUSED existing code (Section 5)
│   │   ├── tf_to_drug_connectivity.py   # TF→drug connectivity toolkit (exists)
│   │   ├── celloracle_local.py   # CellOracle GRN wrapper (exists)
│   │   └── run_pertformer.py     # PertFormer runner (exists)
│   ├── jobs.py                   # async job queue + status (stages are long-running)
│   └── store.py                  # artifact/result cache (keyed by run params)
└── data/                         # or object storage: atlases, GRNs, tracks, results
```

**Two hard architectural rules driven by the science:**

1. **Stages are jobs, not request handlers.** Stage B (scVI integration) is 10–40 min/lineage; Stage F
   needs an A100 for ~17 min. The API must submit a job, return a job id, and let the frontend poll. Only
   Stage A and cached reads are synchronous.
2. **Results are cached and keyed by parameters.** A run is identified by
   `(organ, layer, source_state, target_state, species, stage, engine_params_hash)`. If a result exists,
   serve it; otherwise report `status: "not_computed"` and offer to run it. This is what lets the frontend
   show real lung data instantly while planned organs honestly report "not yet run."

---

## 3. The seed data payload (`frontend/seed/pipeline_seed_data.json`)

This is the single source of truth the current HTML embeds. Use it verbatim as the backend's initial
fixture and the frontend's offline fallback. Top-level shape:

```jsonc
{
  "meta":   { "project", "subtitle", "reference_case", "generated" },
  "organs": {
    "lung":     { "name", "status": "implemented", "note", "atlas_cells": 623919, "atlas_datasets": 8 },
    "liver":    { "name", "status": "planned", "note" },
    "pancreas": { "status": "planned", ... },
    "cornea":   { "status": "planned", ... }
  },
  "stages": [   // 6 entries, the workflow spine (drives the ribbon + stage docs)
    { "id":"A", "title", "short", "goal", "inputs":[...], "methods":[...],
      "outputs":[...], "session", "compute", "status" }, ...
  ],
  "layers": {   // the 4 cell layers, each with real atlas stats + cell states
    "epithelial": {
      "name":"Epithelial",
      "atlas": { "cells":259453, "donors":79, "n_states":96,
                 "fetal":21802, "perinatal":194731, "adult_aging":42920 },
      "states": {
        "AT2":         { "role":"mature",      "master_tfs":[{"tf":"ETV5","logFC":2.77}, ...] },
        "Tip (fetal)": { "role":"progenitor",  "master_tfs":[...] }, ...
      }
    },
    "mesenchymal": {...}, "endothelial": {...}, "immune": {...}
  },
  "refcase": {  // the fully-worked lung AT2→Tip results (Stages D/E/F)
    "recipe":     [ {tf, action, rationale, grn, note, conf}, ...11 ],   // Stage D TF recipe
    "modules":    [ {module, source, tf, role, evidence}, ...4 ],        // Stage D stage-gated scheme
    "compounds":  [ {name, moa, targets, approved, tip, supAT2, nhit}, ...18 ], // Stage E LINCS/Tahoe
    "curated_sm": [ {name, pathway, source, rationale, conf}, ...7 ],    // Stage E curated cocktail
    "tahoe":      [ {intv, type, AT2dn, tipup, score}, ...17 ],          // Stage E single-cell confirm
    "fate": {                                                            // Stage F PertFormer
      "distalTF": { "human":{ref,ki,delta}, "mouse":{...} },
      "OSKM":     { "human":{ref,ki,delta}, "mouse":{...} },
      "panel":    [ "SOX9","ID2","ETV5", ... 21 genes ]
    }
  },
  "evidence":     [ {study, author, year, method, pert, tf, line, organ, org, cells, acc, tier}, ...14 ],
  "dev_datasets": [ {short, name, phase, cells, donors}, ...8 ]
}
```

**Role field on each state** is the axis the reversal uses: `"mature"` (valid source), `"progenitor"`
(valid target ◆), `"other"`. The four layers currently carry real state→master-TF data for lung; a new
organ populates the same structure from its own Stage B run.

---

## 4. API contracts (build the backend against these)

All routes are suggestions; the request/response *shapes* are the contract. Long-running stages (B, C, D, F)
return a job handle; poll `GET /jobs/{job_id}`. Reads are synchronous.

### Registry & selection

```
GET /organs
  → [ { id, name, status: "implemented"|"planned", note, atlas_cells?, atlas_datasets? } ]

GET /organs/{organ}/layers
  → [ { id, name, atlas: {cells, donors, n_states, fetal, perinatal, adult_aging}|null,
        status: "implemented"|"planned" } ]

GET /organs/{organ}/layers/{layer}/states
  → { states: { "<state name>": { role: "mature"|"progenitor"|"other",
                                   master_tfs: [{tf, logFC}] } } }
  # role drives which states are valid sources (mature) vs targets (progenitor ◆)

GET /runs?organ=&layer=&source=&target=&species=
  → { run_id, stages: { A:"cached"|"not_computed"|"running", B:..., ... F:... } }
  # the "what's computed" index that lets the UI gray out un-run stages
```

### Stage A — Evidence base (synchronous; independent)

```
GET /stage/A?organ=lung
  → { datasets: [ {study, author, year, method, pert, tf_focus, line, organ,
                   organism, cells, accession, tier, doi, verified} ],
      drug_engine: { libraries:["LINCS L1000"], confirm:"Tahoe-100M",
                     status:"ready" } }
```
Backing data: `perturbseq_datasets_catalog.csv` (36 rows, every row carries a recorded `verify_status`
beginning "Verified"; of these 31/36 have a resolved DOI and 29/36 cite a GEO accession or PMID, with the
remaining 7 verified via DOI + OpenAlex/GitHub/Zenodo — see the `verify_status` column for the per-row
basis). The drug engine is `tf_to_drug_connectivity.py` (Section 5.1).

### Stage B — Developmental atlas (async job)

```
POST /stage/B/run   { organ, layer }
  → { job_id }
GET  /stage/B?organ=lung&layer=epithelial
  → { atlas: {cells, donors, n_states, phase_coverage:{fetal,perinatal,adult_aging}},
      states: { "<state>": {role, master_tfs:[{tf,logFC}]} },
      source_datasets: [ {short, name, phase, cells, donors} ],
      artifact_uri }        # path to the integrated .h5ad
```
Backing: `*_subatlas.h5ad`, `ALL_lineage_state_TFs.csv`. Runner logic mirrors the atlas construction
(scVI/scANVI per lineage, raw counts retained). See `CONSTRUCTION_README.md` in the project.

### Stage C — GRN inference (async job)

```
POST /stage/C/run   { organ, layer, route: "celloracle"|"scenicplus" }
  → { job_id }
GET  /stage/C?organ=lung&layer=epithelial
  → { hubs: [ {tf, degree_centrality_all, betweenness_centrality,
               eigenvector_centrality, cluster} ],
      route, n_edges, artifact_uri }   # GRN edges parquet/links object
```
Backing: `GRN_network_scores_enhancer.csv` (columns: `degree_all, degree_centrality_all, degree_in,
degree_centrality_in, degree_out, degree_centrality_out, betweenness_centrality, eigenvector_centrality,
cluster`), `epi_links.celloracle.links`. Runner: `celloracle_local.py` (Section 5.2).

### Stage D — In-silico reversal → TF recipe (async job)

```
POST /stage/D/run   { organ, layer, source, target, species,
                      candidate_pool?: [tf], engine_params?: {alpha, bagging} }
  → { job_id }
GET  /stage/D?organ=lung&layer=epithelial&source=AT2&target=Tip%20(fetal)&species=human
  → { recipe: [ {tf, action:"ACTIVATE"|"KNOCK_OUT", rationale, grn_evidence,
                 confidence:"HIGH"|"MEDIUM"|"LOW"} ],
      modules: [ {module, tf, role, evidence_class} ],          # stage-gated scheme
      screen: [ {tf, mode:"OE"|"KO", transition, projection} ], # raw KO/OE scan
      artifact_uri }
```
Backing: `AT2_to_TiP_TF_recipe.csv`, `lung_AT2_to_progenitor_TF_scheme.csv`,
`insilico_TF_perturbation_screen.csv` (columns: `dataset, TF, mode, transition, projection`).
Method: CellOracle `simulate_shift` projected onto the transition vector.

### Stage E — Small-molecule mirror (async-ish; LINCS is a web call)

```
POST /stage/E/run   { organ, layer, source, target,
                      signature?: {up:[gene], down:[gene]},   # else derived from Stage D
                      lung_only?: bool }
  → { job_id }   # or synchronous if signature is provided and cached
GET  /stage/E?organ=lung&layer=epithelial&source=AT2&target=Tip%20(fetal)
  → { compounds: [ {name, moa, targets, approved, induce_target_score,
                    suppress_source_score, n_objectives_hit, pubchem_cid} ],
      curated: [ {name, pathway, source, rationale, confidence} ],
      single_cell_confirm: [ {intervention, type:"single"|"combo",
                              source_dn, target_up, reprog_score} ] }
```
Backing: `AT2_to_TiP_compounds.csv`, `lung_AT2_to_progenitor_small_molecules.csv`,
`AT2_to_TiP_tahoe_validation.csv`. Engine: `tf_to_drug_connectivity.py::connectivity_query()` +
`cross_ref_tahoe()`.

### Stage F — Deep-learning fate validation (async GPU job)

```
POST /stage/F/run   { organ, layer, source, target, species,
                      tf_set: [tf],                 # the KI cocktail (motif-bearing TFs)
                      readout_panel?: [gene],        # default 21-gene fate panel
                      ki_params?: {score_quantile: 0.90, ki_scale: 1.0} }
  → { job_id }   # dispatches to A100 (Modal); ~17 min
GET  /stage/F?organ=lung&layer=epithelial&source=AT2&target=Tip%20(fetal)&species=human
  → { fate: { ref_cos, ki_cos, delta_proximity, n_genes,
              panel:[gene], per_gene:[{gene, ref, ki, target}] },
      tf_set, species, compare?: { OSKM:{delta}, distalTF:{delta} } }
```
Backing: `distaltf_fate_proximity_readout.json`, `fate_proximity_readout.json`. Runner:
`run_pertformer.py`. **Requires GPU** — see the PertFormer I/O contract in the project
(`pertformer_io_contract.json`): 3B params, ~12.8 GB weights, DNA+ATAC→expression, ATAC-only in-silico KI.

### Jobs

```
GET /jobs/{job_id}
  → { job_id, stage, params, status: "queued"|"running"|"done"|"failed",
      progress?, result_uri?, error? }
```

---

## 5. Reusable engine code (already written & tested — do not reimplement)

These scripts exist as project artifacts. Pull them into `backend/engine/` and wrap them; don't rewrite.

### 5.1 `tf_to_drug_connectivity.py` — TF→drug connectivity toolkit (Stages A & E)

> **Two copies of this toolkit exist in the project** — same functions, either works:
> `tf_to_drug_connectivity.py` (standalone script, version `41320fbf`) and `tfdrug_kernel.py` (the
> `tf-drug-connectivity` skill's auto-loading kernel sidecar, version `3240ae77`). Pull in
> `tf_to_drug_connectivity.py` for `backend/engine/`.

```python
compute_signature_from_expr(Xn, gene_symbols, pert_mask, ctrl_mask, ...)
    -> (up_genes, down_genes, table)          # build a TF signature from Perturb-seq
connectivity_query(signature_genes, direction="mimic"|"reverse",
                   lung_only=False, library=None, top=None)
    -> DataFrame of LINCS L1000 compounds ranked by connectivity
load_tahoe_drugs()      -> DataFrame           # 379 annotated Tahoe-100M compounds
load_tahoe_cell_lines() -> DataFrame           # Tahoe-100M cell lines (incl. A549)
cross_ref_tahoe(conn_df, tahoe_drugs=None)
    -> conn_df + columns in_tahoe / tahoe_moa / tahoe_targets / tahoe_cid
```
Network: needs `maayanlab.cloud` (Enrichr/LINCS) and `datasets-server.huggingface.co` (Tahoe metadata)
reachable. Packages: `requests, numpy, pandas, scipy`. This is essentially the entire Stage E compute — the
backend route calls `connectivity_query()` then `cross_ref_tahoe()`.

### 5.2 `celloracle_local.py` — CellOracle GRN + perturbation (Stages C & D)

```python
prep_counts_adata(path, stage_col="stage", counts_layer="counts", n_hvg=3000, ...)
build_oracle(adata, base_grn, stage_col="stage")
infer_links(oracle, stage_col="stage", alpha=10, bagging=20)
```
CPU-only mode: uses CellOracle's built-in promoter/motif base-GRN (no cisTarget DB, no GPU). Trade-off
documented in the script's docstring — edges are motif-atlas-derived rather than sample-ATAC-specific, but
the perturbation biology (which TFs drive each transition) is preserved. The GPU/SCENIC+ enhancer-aware
route is the higher-fidelity alternative when matched ATAC + an A100 + the 47 GB cisTarget DB are available.
Environment: the `celloracle` conda env already exists in this project.

### 5.3 `run_pertformer.py` — PertFormer inference (Stage F)

Zero-shot DNA+ATAC→expression on GPU. Per-gene forward pass over peaks within ±300 kb of the TSS; emits
`predictions.json = {condition: {gene: expr}}`. Expects, staged flat in the job workdir: `models.py`,
`attention.py`, `data_processing.py`, `kmer_dict.pkl` (from the repo), a `manifest.json` listing
conditions, and the `info_*.txt` + `info_*.sidecar.json` input files; weights mounted at `/weights`.
Ran on Modal A100-40GB in ~17 min for 6 conditions. The in-silico KI edit (open motif∩accessible peaks,
ATAC-only) is in `oskm_ki_and_readout.py`; the fate readout is a cosine of the predicted-expression vector
to the target-state profile.

**Environments already provisioned in this project** (reuse, don't rebuild): `lung-atlas`, `scvi-cpu`
(Stage B), `celloracle` (C/D), `genomics` (F track-building), `compute-provider-modal` (F dispatch),
plus base `python`/`r`.

---

## 6. Frontend refactor (from the current HTML)

`reprogramming_pipeline.html` is vanilla JS with an embedded `const DATA = {...}`. Its structure maps
cleanly onto components:

- **State object** `S = { organ, layer, source, target, species, stage }` → keep as-is (a store).
- **Selectors** (`initSelectors`, `rebuildLayer`, `rebuildStates`) → a `<SelectionPanel>` that hydrates
  from `GET /organs`, `/layers`, `/states` instead of the embedded `DATA`.
- **Pipeline ribbon** (`renderRibbon`) → a `<StageRibbon>` reading the stage list + the per-run
  "what's computed" index (`GET /runs`), graying out `not_computed` stages.
- **Per-stage panels** (`renderA … renderF`) → one component each, fetching `GET /stage/{X}`. The current
  render functions are literally the response-to-DOM templates — reuse the markup, swap the data source.
- **Provenance modal** → keep; point it at a `GET /provenance` route.

**Keep an offline mode.** Bundle `pipeline_seed_data.json` so the UI works with the real lung data even
before the backend is up (`api.js` falls back to the seed when `fetch` fails). This is what makes the
blueprint useful during backend iteration.

**Design constraints already baked in (preserve them):** planned organs render a "planned" notice, not
fake data; Stages D/E/F show the *method* for any layer but only real *numbers* for combinations that were
actually run. Do not "fill in" the others with placeholder values.

---

## 7. Phased build plan (suggested order for Claude Code)

**Phase 0 — Scaffold & contracts.** Stand up the backend skeleton with all Section-4 routes returning the
seed data (read `pipeline_seed_data.json`, slice by params). Refactor the HTML frontend to fetch from these
routes with the seed as offline fallback. *Outcome: same UI, now client/server, no compute yet.*

**Phase 1 — Registry & the "what's computed" index.** Implement `store.py` + `registry.py`: a result cache
keyed by `(organ, layer, source, target, species, stage, params_hash)`, seeded with the cached lung
results. `GET /runs` reports per-stage status. *Outcome: UI correctly shows lung as computed, others as
not_computed.*

**Phase 2 — Wire the synchronous engines.** Stage A (catalog read + drug-engine health) and Stage E
(`tf_to_drug_connectivity.py` live LINCS/Tahoe query). These need no GPU and give immediate end-to-end value.
*Outcome: you can nominate compounds for a new signature live.*

**Phase 3 — Async job infra + CPU stages.** Add `jobs.py` (queue + status polling). Wire Stage B
(scVI/scANVI atlas build) and Stages C/D (`celloracle_local.py`). *Outcome: a new organ/layer can be taken
from raw atlas → GRN → TF recipe.*

**Phase 4 — GPU Stage F.** Integrate `run_pertformer.py` behind a Modal (or other A100) dispatch. Gate it
behind explicit user action (it's the most expensive step). *Outcome: fate-proximity validation for a
nominated TF cocktail.*

**Phase 5 — New-organ workflow.** Exercise the full spine on a second organ (liver hepatocyte→hepatoblast
is the natural first migration). Everything parameterized in Phases 1–4 should now "just run" with new
inputs. *Outcome: the pipeline is genuinely universal, not lung-only.*

At each phase, the lung AT2→Tip reference case (Section 1) is the regression test: the numbers in
`pipeline_seed_data.json` → `refcase` are what a correct backend must reproduce from cache and, eventually,
recompute.

---

## 8. Guardrails (scientific integrity — enforce in code)

1. **Never fabricate pipeline outputs.** A stage result is either a real cached artifact or
   `status:"not_computed"`. No placeholder TF recipes, drug scores, or fate deltas. This is the single most
   important rule — the whole value of the tool is that its outputs are real.
2. **In-silico ≠ validated.** Every TF recipe, compound, and fate score is a *hypothesis requiring wet-lab
   validation.* Surface that framing in the API (`"evidence":"in_silico"`) and UI, as the current blueprint
   does.
3. **Species is not cosmetic.** Mouse and human give different answers (the reference case: human AT2 has
   headroom to move toward the tip, mouse AT2 already sits adjacent to its E17.5 tip). Keep species a real
   parameter through Stages D/F, not a display toggle.
4. **Respect the modality gaps.** Human same-cell RNA+ATAC does not exist before adulthood; the atlas is an
   RNA backbone with ATAC layered from mouse-developmental / human-adult sources. Don't assume matched
   multiome exists for every organ/phase — Stage C's SCENIC+ route is conditional on it.
5. **Cache keys must include engine params.** Changing `score_quantile`, `alpha`, candidate pool, or
   readout panel produces a different result — don't serve a stale cache across param changes.

---

## 9. Ground-truth files (all in the local bundle)

All paths are relative to `~/Desktop/repro-pipeline-build/`. Read them directly — no artifact store needed.

| Purpose | Bundle path |
|---|---|
| Seed payload (this build) | `frontend/seed/pipeline_seed_data.json` |
| Current frontend | `frontend/reprogramming_pipeline.html` |
| Science summary | `docs/PIPELINE_README.md` |
| Atlas construction method | `docs/CONSTRUCTION_README.md` |
| Per-state master TFs (all 4 layers) | `data/reference/ALL_lineage_state_TFs.csv` |
| GRN hub scores | `data/reference/GRN_network_scores_enhancer.csv` |
| TF recipe (reference) | `data/reference/AT2_to_TiP_TF_recipe.csv` |
| TF module schemes | `data/reference/lung_AT2_to_progenitor_TF_scheme.csv`, `data/reference/alternative_stagewise_TF_scheme.csv` |
| KO/OE screen | `data/reference/insilico_TF_perturbation_screen.csv` |
| Compound nominations | `data/reference/AT2_to_TiP_compounds.csv` |
| Curated cocktail | `data/reference/lung_AT2_to_progenitor_small_molecules.csv` |
| Single-cell drug confirm | `data/reference/AT2_to_TiP_tahoe_validation.csv` |
| Fate-proximity scores | `data/reference/distaltf_fate_proximity_readout.json`, `data/reference/fate_proximity_readout.json` |
| PertFormer I/O contract | `data/reference/pertformer_io_contract.json` |
| Reusable engines | `backend/engine/tf_to_drug_connectivity.py`, `celloracle_local.py`, `run_pertformer.py` (+ `oskm_ki_and_readout.py`, `run_epi_grn.py`) |

`BUNDLE_MANIFEST.txt` at the bundle root lists every file with its size and sha256 prefix. Use these as
fixtures to seed the backend and as regression targets to verify each stage runner's output.

**What is *not* in the bundle** (fetch or recompute — see Sections 4/5): integrated `*_subatlas.h5ad`
atlases, CellOracle `.links` objects, PertFormer weights (~12.8 GB, Hugging Face
`GenomicIntelligenceDamoAcademy/pertformer`), and the PertFormer repo source
(`models.py`/`attention.py`/`data_processing.py`/`kmer_dict.pkl`, from `github.com/alibaba/damo-pertformer`).
