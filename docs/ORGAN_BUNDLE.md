# Organ bundles — bringing a new organ online

An organ bundle is a folder `data/organs/<organ_id>/` containing `organ.json`. It is how
Phase 5 (a second organ) enters the registry. The bundle describes the organ and its cell
layers. It never carries stage results: results for Stages C–F appear only when a real
run writes an artifact under `data/results/`, so a new organ cannot show numbers that
were not computed.

## Check a bundle

```bash
python3 -m backend.organ_bundles                     # every bundle under data/organs/
python3 -m backend.organ_bundles data/organs/liver   # one bundle
```

The server skips invalid bundles and reports the reasons at `GET /compute/status`.

## Schema

```json
{
  "id": "liver",
  "name": "Liver",
  "status": "implemented",
  "note": "Hepatocyte → hepatoblast reversal.",
  "atlas_datasets": 6,
  "source_datasets": [
    {"short": "ExampleAtlas", "name": "Example atlas", "phase": "embryonic-fetal", "cells": 1000, "donors": 2}
  ],
  "layers": {
    "hepatocyte": {
      "name": "Hepatocyte",
      "atlas": {"cells": 0, "donors": 0, "n_states": 0,
                "fetal": 0, "perinatal": 0, "adult_aging": 0},
      "states": {
        "Mature hepatocyte": {"role": "mature",
                              "master_tfs": [{"tf": "HNF4A", "logFC": 2.1}]},
        "Hepatoblast": {"role": "progenitor",
                        "master_tfs": [{"tf": "PROX1", "logFC": 1.4}]}
      }
    }
  }
}
```

The numbers above are placeholders that show the shape. Replace every value with the
output of a real atlas run.

| Field | Rule |
|---|---|
| `id` | snake_case; must equal the folder name; `lung` is reserved for the seed reference |
| `status` | `planned` or `implemented`. Planned organs show their layers but no stage data |
| `layers` | required and non-empty for an implemented organ |
| `layer.atlas` | non-negative integers: `cells, donors, n_states, fetal, perinatal, adult_aging` |
| `layer.states[*].role` | `mature`, `progenitor` or `other`. An implemented layer needs at least one of each of the first two, because the UI selects a source and a target from them |
| `master_tfs` | list of `{tf: string, logFC: number}` |

Folders beginning with `.` or `_` are ignored.

## After a bundle is valid

- `GET /organs` lists the organ; `GET /organs/<id>/layers` and `…/states` serve its layers.
- `GET /stage/B` serves its atlas summary (a real, stored bundle, not a computed result).
- Stages C–F stay `not_computed`, with a `requires` list, until a real run writes an
  artifact for that exact combination. A stored artifact is then served with
  `served_from: "artifact"` and counted as `cached` in `GET /runs`.

## Where real results go

`data/results/<stage>/<name>__<digest>.json`, containing `{identity, payload}`. The
identity is the full parameter set, so a result for one species or one engine setting
is never served for another. The index is at `GET /results`. Results are kept out of
git by default (`data/results/` is ignored). Commit one deliberately with `git add -f`.
