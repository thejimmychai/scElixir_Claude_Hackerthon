# Universal Developmental Reprogramming Pipeline — application

A frontend + backend application built from the static blueprint per
[`docs/CLAUDE_CODE_HANDOFF.md`](docs/CLAUDE_CODE_HANDOFF.md). It serves the
6-stage pipeline (Atlas → GRN → in-silico reversal → TF combo + small-molecule
rejuvenation → deep-learning fate validation) over the Section-4 API, with the
lung `AT2 → fetal distal-tip` case fully worked and three organs planned.

## Run it

Three ways to launch, in order of capability:

**1. Double-click (no terminal, no server).** Open `frontend/standalone.html` in any
browser. It's a single self-contained file — the whole UI works offline against the
embedded lung reference case, and automatically upgrades to live data if the backend
below is running. This is the "just show me the thing" path.

**2. Full app (server + UI).** Zero dependencies — only a Python 3.8+ interpreter is
required (no `pip install`, no Node). From this directory:

```bash
./run.sh                 # or:  python3 -m backend.app --port 8765
```

Then open **http://127.0.0.1:8765/** — the backend serves both the API and the UI
same-origin (36-row catalog, live GRN hub table, async jobs, optional live LINCS
query). Stop with Ctrl-C. Override the port with `REPRO_PORT=9000 ./run.sh`.

> If `./run.sh` reports "permission denied", run `chmod +x run.sh` once, or just use
> `python3 -m backend.app`. If `localhost:8765` shows nothing, the server isn't
> running — start it with the command above (it must stay running in its terminal).

**3. Original blueprint.** `frontend/reprogramming_pipeline.html` is the pre-refactor
fully-inline standalone, kept for reference; also double-click-able.

Run the regression suite:

```bash
python3 -m unittest discover -s tests -v
```

## Why standard-library, not FastAPI

The handoff *suggests* FastAPI. This build uses `http.server` instead so the app
boots anywhere a Python interpreter exists, with no install step — appropriate
because the pipeline's heavy compute (scVI, CellOracle, PertFormer) lives on
separate GPU hosts and this bundle is the portable reference. **The request /
response shapes are the contract, and they match Section 4 exactly**; swapping in
FastAPI later is a mechanical port of `backend/app.py`'s route table.

## Architecture

```
backend/
  app.py            # http.server routing + static file serving (Section-4 routes)
  config.py         # bundle paths, reference-case + GRN-availability constants
  data_loader.py    # loads the seed + all data/reference CSV/JSON (csv module, no pandas)
  registry.py       # organ/layer/state directory + the "what's computed" index (guardrails)
  store.py          # result cache keyed by (organ,layer,source,target,species,stage,params_hash)
  jobs.py           # in-process async job queue for long stages (B/C/D/E/F)
  stages/           # one runner per stage (A-F): real cached result, or honest not_computed
  engine/           # reused, pre-existing engine scripts (wrapped, not rewritten)
frontend/
  index.html        # shell (markup + styles) — no embedded data
  src/seed.js       # offline fallback bundle (== the seed payload), loaded as a classic script
  src/api.js        # fetch wrappers; falls back to window.__SEED__ when the backend is down
  src/state.js      # selection store
  src/stages.js     # per-stage render functions (consume the API payloads)
  src/app.js        # boot: hydrate selectors/ribbon from the API, render stages
  seed/pipeline_seed_data.json   # the seed payload (source of truth for offline mode)
tests/test_contracts.py          # reference-case + guardrail regression tests
```

## API (handoff Section 4)

Reads are synchronous. Long stages accept a POST that submits a job; poll
`GET /jobs/{id}`.

| Route | Purpose |
|---|---|
| `GET /organs` | organ list (implemented / planned) |
| `GET /organs/{organ}/layers` | cell layers + atlas stats |
| `GET /organs/{organ}/layers/{layer}/states` | states with role + master TFs |
| `GET /runs?organ=&layer=&source=&target=&species=` | per-stage cached / not_computed / running index |
| `GET /stage/A?organ=` | evidence catalog (36 rows) + drug-engine health |
| `GET /stage/B?organ=&layer=` | atlas summary + states + source datasets |
| `GET /stage/C?organ=&layer=` | GRN hubs (centrality) + candidate regulators |
| `GET /stage/D?organ=&layer=&source=&target=&species=` | TF recipe + modules + KO/OE screen |
| `GET /stage/E?organ=&layer=&source=&target=` | compound nominations + curated cocktail + single-cell confirm |
| `GET /stage/F?organ=&layer=&source=&target=&species=` | PertFormer fate-proximity Δ (per species) |
| `POST /stage/{B\|C\|D\|E\|F}/run` | submit an async job → `{job_id}` |
| `GET /jobs/{job_id}` | job status (queued/running/done/failed) |
| `GET /provenance` | per-stage source sessions + artifacts |
| `GET /meta` | meta + organs + stages + layer defaults |

## Scientific-integrity guardrails (handoff Section 8 — enforced in code)

1. **Never fabricate outputs.** A stage returns a real cached artifact or
   `status:"not_computed"`. `registry.py` decides availability; runners refuse to
   emit numbers otherwise. Un-run transitions and planned organs render an honest
   "not run" notice — verified by `tests/test_contracts.py`.
2. **In-silico ≠ validated.** Recipes / compounds / fate deltas carry
   `"evidence":"in_silico"` and the UI frames them as hypotheses.
3. **Species is a real parameter.** Stage F returns different numbers for human
   (Δ +0.107) vs mouse (Δ −0.090); it is not a display toggle.
4. **Modality gaps respected.** Only the lung epithelial enhancer-aware GRN was
   inferred; other layers report `not_computed` for the centrality table.
5. **Cache keys include engine params.** Changing `score_quantile`, `alpha`, the
   candidate pool, or the readout panel yields a different `store` key.

## What's real vs. what needs external compute

Every number served is extracted from the real artifacts in `data/reference/`
(see `GET /provenance`). Recomputing an *uncached* combination needs resources not
in this bundle — the integrated `*_subatlas.h5ad`, CellOracle `.links`, and the
~12.8 GB PertFormer weights + an A100. Those jobs fail honestly with a message
naming the missing compute rather than inventing a result. Stage E can run a
**live** LINCS/Tahoe query when `requests/numpy/pandas/scipy` + network are
available; otherwise it serves the cached nominations.

## Offline mode

`frontend/src/seed.js` embeds the seed payload, so the UI still shows the real lung
reference case with no backend. `api.js` prefers the live backend and falls back to
the seed automatically; the header badge shows which mode is active.

`frontend/standalone.html` bundles all of that into one double-click-able file
(rebuild it with `python3 scripts/build_standalone.py` after changing any frontend
source). Opening the modular `frontend/index.html` directly also works in most
browsers, but a few restrict `file://` subresource loading — `standalone.html` avoids
that by inlining everything.
