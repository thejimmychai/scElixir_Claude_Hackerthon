# Universal Developmental Reprogramming Pipeline — Interface & Workflow

**Deliverable:** `reprogramming_pipeline.html` — a standalone, single-file interactive blueprint
(no server, no dependencies; open in any browser). All data is embedded; nothing is fetched at runtime.

This interface synthesizes **four analysis sessions** in this project into one **6-stage universal
pipeline** for predicting adult→embryonic-progenitor reversal (rejuvenation) via transcription-factor
combinations and small-molecule treatments.

---

## The 6-stage workflow spine (organ-agnostic)

| Stage | Name | Goal | Core methods | Source session |
|---|---|---|---|---|
| **A** | Evidence base | Catalog large-scale Perturb-seq / TF-OE atlases; build TF→drug engine | GEO/OpenAlex survey, LINCS L1000, Tahoe-100M | Perturb-seq Landscape Review |
| **B** | Developmental atlas | Assemble + harmonize + integrate embryonic→adult scRNA per lineage; resolve states + master TFs | CELLxGENE Census, scVI/scANVI, DE TF calling | Human Lung Dev Datasets |
| **C** | GRN inference | Per-lineage/stage regulatory network, regulons, hubs | CellOracle base-GRN; SCENIC+ enhancer-aware | Lung Dev + Fibroblast Reprog |
| **D** | In-silico reversal | Define adult→progenitor transition; KO/OE screen → precision TF combo | CellOracle perturbation, transition-vector projection | Fibroblast Reprog + Epithelial |
| **E** | Small-molecule mirror | Map stage signatures to mimicking compounds; confirm single-cell | LINCS connectivity, Tahoe-100M, organ reagent overlay | Perturb-seq + Fibroblast Reprog |
| **F** | Deep-learning fate validation | Score {adult, progenitor, TF-KI} with a sequence model; fate-proximity Δ | PertFormer (3B, A100), motif-KI, mouse↔human | PertFormer AT2 OSKM Knock-in |

## Selection axes (the interface controls)

1. **Organ** — Lung (implemented, full reference case) · Liver / Pancreas / Cornea (planned migration targets)
2. **Cell layer** — Epithelial (10 states) · Mesenchymal (13) · Endothelial (8) · Immune (13). All four
   carry real cell-state + master-TF data from the 623k-cell lung atlas.
3. **Source state** (adult / mature) → **Target state** (embryonic progenitor ◆)
4. **Species** — Human · Mouse (cross-species robustness)

## The worked reference case (fully executed, all 6 stages)

**Lung · Epithelial · adult AT2 → fetal distal-tip progenitor**

- **TF recipe (Stage D):** ACTIVATE SOX9, LEF1, ETV5, FOXP2; KNOCK-OUT CEBPA, PPARG, FOXJ1, MYB, RFX2, RFX3, EHF
- **Small molecules (Stage E):** LINCS/Tahoe nominations (everolimus, belinostat, EGFR/MEK inhibitors…) +
  curated lung cocktail (CHIR99021, RepSox, Y-27632, DMH1, FGF10)
- **Fate validation (Stage F):** distal-TF cocktail (SOX9/NKX2-1/ETV5/ETV4) moves human AT2
  **Δ +0.107** toward tip (cos 0.656→0.763) — ~93% larger than OSKM's Δ +0.055; mouse is a specificity control.

## How to bring a new organ online

The spine is organ-agnostic. For liver/pancreas/cornea, run the same stages:
1. **B** — assemble that organ's developmental atlas (embryonic→adult, 4 lineages) from CELLxGENE/GEO.
2. **C** — infer per-lineage GRNs (CellOracle always; SCENIC+ if matched ATAC exists).
3. **D** — define the adult-mature → embryonic-progenitor transition; run the KO/OE screen.
4. **E** — mirror stage signatures to compounds; overlay organ-established reagents.
5. **F** — build DNA+ATAC for {adult, progenitor, TF-KI}; run PertFormer; report fate-proximity Δ.

To wire a live compute backend later, each stage's Inputs/Outputs (shown in the interface) define the
data contract; the embedded lung data becomes the mock response / integration test.

## Provenance

Every table and number in the interface is extracted from real project artifacts (see the in-app
**Data provenance** panel). No values are synthetic. In-silico predictions are hypotheses requiring
wet-lab validation.
