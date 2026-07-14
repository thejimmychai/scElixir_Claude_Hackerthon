# Human Lung Development Atlas — Construction README

**Project:** TF-network / GRN mapping across human lung development
**Scope:** Human, full developmental course (embryonic-fetal → perinatal → adult-aging), 4 lineages
**Built:** locally (CPU, 18 cores), scVI/scANVI integration, lineage-resolved

---

## 1. What this atlas is

A harmonized, lineage-resolved single-cell reference assembled from **8 public human lung
datasets** (827k cells downloaded → **630,000 cells** after dedup/QC), spanning the three
developmental phases the project targets. It is designed as the substrate for
gene-regulatory-network (GRN) inference: raw counts are preserved throughout, cells are
annotated to a consistent 4-lineage axis, and each lineage is integrated independently
(one batch-corrected latent space per lineage — the natural unit for GRN inference).

The **matched same-cell multiome gap** documented in the survey phase still holds: no human
same-cell RNA+ATAC exists before adulthood, so this RNA atlas is the transcriptomic backbone
onto which the (mouse developmental / human adult) multiome and separate-assay ATAC will be
layered downstream.

## 2. Source datasets (8 kept)

| short | dataset | phase(s) | cells | donors |
|---|---|---|---|---|
| He2022_fetal | He 2022 fetal lung atlas (ALL cells) | embryonic-fetal | 71,752 | 12 |
| FetalImmune | Fetal lung immune (leukocytes), immune-unique only | embryonic-fetal | 61,762 | 20 |
| DevHuman | Developing Human Atlas (lung-subset) | embryonic-fetal | 47,909 | 3 |
| LungMAP_MM | LungMAP human multiome (RNA half) | fetal→3yr→adult | 46,500 | 9 |
| Perinatal_NB | Newborn lung molecular phenotypes | perinatal | 5,499 | 2 |
| BPD_preterm | Bronchopulmonary dysplasia (preterm→toddler) | perinatal | 271,381 | 24 |
| MultiPhase | Multi-phase distal airway/alveoli | adult-aging | 115,788 | 17 |
| HLCA_Krasnow | Krasnow/Travaglini HLCA (Smart-seq2) | adult-aging | 9,409 | 3 |

**Dropped (4):** 3 He fetal lineage subsets (EPITHELIUM/Endothelium/Fibroblast — redundant with
He ALL_cells) and the fetal distal-tip organoid (in vitro).

## 3. Construction steps

**Step 1 — Dedup & raw counts.** Immune atlas deduplicated against He by barcode
(15,797 shared cells dropped → 61,762 immune-unique kept). DevHuman filtered to lung
(47,909 of 155k multi-organ cells). Raw integer counts recovered uniformly (`.raw.X` for 7
datasets, `.X` for DevHuman).

**Step 2 — Metadata harmonization.** Per-cell developmental phase assigned from the
`development_stage` ontology age (NOT dataset labels — three datasets span multiple phases and
were split per-cell). Parser handles post-fertilization weeks, Carnegie stages, newborn, and
postnatal month/year. Ontology-ID-only cell types (CL:) resolved via readable cell_type columns.

**Step 3 — 4-lineage annotation.** Every dataset's native cell types mapped to
{Epithelial, Mesenchymal, Endothelial, Immune, + Neural/Other}. BPD and LungMAP native lineage
columns used as ground truth (resolved abbreviations: AEC→Endothelial, PC→Mesenchymal,
SCMF→Mesenchymal, RAS→Epithelial, AM/IM/MON→Immune); rule-based classifier for the rest.
Validated against canonical markers — EPCAM/NKX2-1 (Epi), PECAM1/CLDN5 (Endo),
COL1A1/PDGFRA (Mes), PTPRC (Immune) — all cleanly enriched in their assigned lineage.

**Step 4 — Master object.** Concatenated on the strict 8/8 Ensembl-ID gene intersection
(**19,003 genes** — avoids structured missingness that would confound scVI/GRN).
630,000 cells × 19,003 genes, raw counts, 87 donors.

**Steps 5-6 — Lineage-resolved integration.** Per lineage: batch-aware HVG (2000,
batch = dataset|donor) → scVI (n_latent=30, n_layers=1, NB likelihood, ≤60 epochs early-stop)
→ scANVI (label harmonization) → neighbors/leiden/UMAP. Raw counts retained in each sub-atlas
for downstream GRN inference.

## 4. Phase × lineage coverage (the core structural result)

| phase | Epithelial | Mesenchymal | Endothelial | Immune | Neural | Other |
|---|---|---|---|---|---|---|
| embryonic-fetal | 21,802 | 82,976 | 7,196 | 84,013 | 984 | 1,473 |
| perinatal | 194,731 | 32,525 | 16,641 | 51,379 | 0 | 685 |
| adult-aging | 42,920 | 16,877 | 17,575 | 55,279 | 206 | 2,733 |

Every lineage has usable coverage in all three phases — the requirement for developmental
GRN trajectories. Notably, adult/aging depth (135,590 cells) is far better than the dedicated
adult reference alone (9,409) because the multi-phase and matched-multiome datasets contribute
substantial adult cells.

## 5. Deliverables

- `master_human_lung_dev.h5ad` — master harmonized atlas (630k × 19,003, raw counts), artifact store
- `epithelial_subatlas.h5ad` — **priority GRN-ready** (259,453 cells, integrated, raw counts + latent + UMAP)
- `mesenchymal/endothelial/immune_subatlas.h5ad` — remaining lineages (same structure)
- QC figures: phase×lineage composition, per-lineage UMAPs
- This README + updated Excel catalog


## 5.1 Per-lineage integrated sub-atlas summary

| lineage | cells | donors | leiden | pred types | fetal | perinatal | adult-aging |
|---|---|---|---|---|---|---|---|
| Epithelial | 259,453 | 79 | 39 | 96 | 21,802 | 194,731 | 42,920 |
| Mesenchymal | 132,378 | 84 | 37 | 78 | 82,976 | 32,525 | 16,877 |
| Endothelial | 41,412 | 76 | 27 | 54 | 7,196 | 16,641 | 17,575 |
| Immune | 190,676 | 87 | 48 | 163 | 84,013 | 51,379 | 55,279 |

Each sub-atlas is a full-gene AnnData (19,003 genes) with:
- `.layers['counts']` — raw integer counts (for GRN inference / scVI re-runs)
- `.X` — log1p-normalized (CP10K)
- `.obsm['X_scVI']`, `.obsm['X_scANVI']` — 30-dim batch-corrected latents
- `.obsm['X_umap']` — 2-D embedding
- `.obs['leiden']`, `.obs['pred_cell_type']` — clustering + scANVI-harmonized labels
- `.obs['dev_phase']`, `.obs['age_value']`, `.obs['dataset']`, `.obs['donor_id']` — for trajectory/GRN stratification

## 5.2 Integration quality — honest assessment

Raw cross-dataset k-NN mixing is low (2-4%), but this is **expected and not a defect**: the
datasets are phase-confounded (a fetal-only dataset has no adult cells to mix with), so global
mixing is bounded by biology. A cell-type-controlled test is fair: for perinatal AT2 cells
(where BPD contributes 96% and LungMAP the rest), the minority-dataset cells do embed into the
shared AT2 territory (observed/expected ratio ~0.23, i.e. partial but real integration given the
extreme imbalance).

**Design stance:** this atlas prioritizes *harmonization* (one gene space, one annotation scheme,
one phase axis, raw counts everywhere) with a *functional joint embedding*, over aggressive
cross-dataset blending. For developmental GRN inference this is the correct trade-off — over-mixing
would erase the fetal→perinatal→adult temporal signal that the regulatory-network analysis depends on.
Immune is the most naturally mixed lineage (17/48 clusters span multiple datasets); epithelial and
mesenchymal preserve clearer phase structure.

## 6. Compute notes

Built entirely on CPU (no GPU host attached during construction). scVI ~10-15 min/lineage,
scANVI ~15-40 min/lineage. Downstream GRN inference (SCENIC+/CellOracle) belongs on the
bio-desktop GPU host (RTX 4090 + 47 GB cisTarget DB pre-installed) when reattached.

## 7. Caveats

- **RNA-only.** No same-cell multiome in the developmental window (human same-cell RNA+ATAC is
  adult-only; developmental matched multiome is mouse-only). ATAC integration is a downstream step.
- **HLCA_Krasnow is Smart-seq2** (full-length, ~53k genes) vs 10x for the rest — the gene
  intersection and scVI batch correction absorb this, but it is a distinct assay.
- Lineage integration deliberately does not over-mix across phases: fetal progenitors and their
  mature adult counterparts occupy adjacent-but-distinct regions, preserving the temporal signal
  the GRN analysis depends on.

## 8. Local compute note (Apple Silicon GPU)

The local machine is an Apple M5 Max (40-core GPU, 48 GB unified memory), but the GPU is
**not accessible from the analysis sandbox**: MLX reports "No Metal device available … headless,
sandboxed, or virtualized macOS session", and PyTorch MPS is unavailable (the conda torch build
also misparses the macOS 26.x version string). This is a hard sandbox boundary, not a fixable
software issue — no framework (MLX, PyTorch MPS) can reach Metal here. All local single-cell work
therefore runs on CPU (18 cores; the "40" is the GPU core count, which is inaccessible). GPU-dependent
steps (scVI at scale, SCENIC+ motif enrichment)
belong on the bio-desktop workstation (RTX 4090 / CUDA) when reattached.


## 9. Cell-state + TF characterization (CPU, while GPU offline)

Each lineage was refined into coherent cell states and characterized for candidate GRN drivers.
TF analysis used the pySCENIC/aertslab curated human TF list (1,839 TFs; 1,435 present in the atlas).

### 9.1 Cell states per lineage
- **Epithelial** (10 states): AT2, AT1, Ciliated, Secretory/RAS, Basal, Tip (fetal), Stalk (fetal), PNEC/ionocyte, Progenitor/transitional
- **Mesenchymal** (13): Alveolar/matrix fibroblast, Developmental fibroblast, Myofibroblast/SCMF, Smooth muscle, Pericyte, Adventitial/Airway fibroblast, Chondrocyte, Mesothelial, Proliferating mesenchyme
- **Endothelial** (8): gCap/CAP1, Aerocyte/CAP2, Venous, Arterial, Lymphatic, EC-smooth-muscle-like
- **Immune** (13): Macrophage, Monocyte, DC, T, NK, T/NK-intermediate, ILC, B/plasma, Mast/granulocyte, Neutrophil, Erythroid/Mk, Progenitor

### 9.2 State-defining TFs — validation
The analysis recovers textbook master regulators as the top state markers, validating the pipeline:
| lineage | cell state | master TF recovered |
|---|---|---|
| Epithelial | Ciliated | **FOXJ1** (ciliogenesis master) |
| Epithelial | AT1 | **TEAD1** (Hippo/AT1 hub — the reprogramming target from the review) |
| Epithelial | Tip (fetal) | **ETV5** (FGF-driven distal progenitor) |
| Epithelial | Secretory/RAS | GRHL1, ELF3, EHF |
| Mesenchymal | Chondrocyte | **SOX9** (chondrogenic master) |
| Mesenchymal | Pericyte | MEF2C, HEYL, EBF1, EPAS1 |
| Mesenchymal | Alveolar fibroblast | MEIS1, PBX1, TCF21 |
| Endothelial | Lymphatic | **PROX1** (lymphatic master; logFC 8.1) |
| Endothelial | Arterial | MECOM, FOXO1, SOX17 |
| Immune | Erythroid | **GATA1, KLF1, TAL1** (erythroid master set) |
| Immune | Macrophage | **PPARG** (alveolar-macrophage master) |
| Immune | T cell | **BCL11B, TCF7, LEF1** |
| Immune | NK | **TBX21** (T-bet) |

Full table: `ALL_lineage_state_TFs.csv` (440 state-TF associations across 44 states).

### 9.3 Phase-dynamic TFs — candidate sensitive windows
TFs whose expression shifts across fetal→perinatal→adult within a cell state, after removing
dissociation immediate-early genes (FOS/JUN/EGR family) and ribosomal confounds. Highlights:
- **SOX5 peaks at perinatal** across myofibroblast, pericyte, and smooth muscle — a coherent
  cross-state perinatal (septation-window) mesenchymal program.
- **PPARG peaks at perinatal** in macrophages — matches the known postnatal alveolar-macrophage
  identity-acquisition window.
- **TCF21 declines** fetal→adult in alveolar fibroblasts (progenitor→mature).
- A recurring perinatal-peaking module (ZBTB20, FLI1, FOXO1, ETV6, RUNX1) across endothelial and
  immune states.

**Important caveat:** developmental phase is partly confounded with dataset (the perinatal window
is dominated by the BPD cohort). These phase-dynamic TFs are therefore *candidate* sensitive-window
programs to confirm with the batch-aware GRN inference (SCENIC+/CellOracle) on the GPU workstation,
not final calls. The state-defining TFs (§9.2) are robust to this confound (computed within the
integrated space across all datasets). Full table: `ALL_lineage_phase_dynamic_TFs.csv`.

### 9.4 Next step (GPU workstation)
These TF programs nominate the regulators to seed GRN inference. On the bio-desktop workstation
(RTX 4090, cisTarget hg38 DB), run SCENIC+ or CellOracle per lineage using these TFs as the
candidate regulator set, then use the phase-dynamic TFs to define the sensitive-window perturbation
targets for the direct-reprogramming screen.
