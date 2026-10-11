"""Regression tests: the lung AT2 -> fetal distal-tip reference case is the
contract the backend must reproduce from cache (handoff Section 7), plus the
scientific-integrity guardrails (Section 8).

Run:  python3 -m unittest discover -s tests -v     (from the bundle root)
"""

import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import artifacts  # noqa: E402
from backend.app import route_get, route_post  # noqa: E402


def get(path, **qs):
    q = {k: [str(v)] for k, v in qs.items()}
    code, payload = route_get(path, q)
    return code, payload


REF = dict(organ="lung", layer="epithelial", source="AT2", target="Tip (fetal)", species="human")


class Registry(unittest.TestCase):
    def test_organs(self):
        _, organs = get("/organs")
        by_id = {o["id"]: o for o in organs}
        self.assertEqual(by_id["lung"]["status"], "implemented")
        self.assertEqual(by_id["lung"]["atlas_cells"], 623919)
        self.assertEqual(by_id["liver"]["status"], "planned")

    def test_planned_layers_have_no_atlas(self):
        _, layers = get("/organs/liver/layers")
        self.assertTrue(all(l["atlas"] is None and l["status"] == "planned" for l in layers))

    def test_states_roles(self):
        _, res = get("/organs/lung/layers/epithelial/states")
        self.assertEqual(res["states"]["AT2"]["role"], "mature")
        self.assertEqual(res["states"]["Tip (fetal)"]["role"], "progenitor")


class RunIndex(unittest.TestCase):
    def test_reference_all_cached(self):
        _, r = get("/runs", **REF)
        self.assertEqual(set(r["stages"].values()), {"cached"})

    def test_nonref_transition_gates_DEF(self):
        _, r = get("/runs", organ="lung", layer="epithelial", source="AT1", target="Tip (fetal)", species="human")
        self.assertEqual(r["stages"]["A"], "cached")
        self.assertEqual(r["stages"]["B"], "cached")
        self.assertEqual(r["stages"]["C"], "cached")
        for s in ("D", "E", "F"):
            self.assertEqual(r["stages"][s], "not_computed", s)

    def test_nonepithelial_gates_C(self):
        _, r = get("/runs", organ="lung", layer="mesenchymal", source="Pericyte",
                   target="Developmental fibroblast", species="human")
        self.assertEqual(r["stages"]["C"], "not_computed")

    def test_planned_organ_all_not_computed(self):
        _, r = get("/runs", organ="liver", layer="epithelial", species="human")
        self.assertEqual(set(r["stages"].values()), {"not_computed"})


class StageA(unittest.TestCase):
    def test_catalog_36_rows(self):
        _, a = get("/stage/A", organ="lung")
        self.assertEqual(a["status"], "cached")
        self.assertEqual(len(a["datasets"]), 36)
        self.assertTrue(all(d.get("verified") for d in a["datasets"]) is not None)

    def test_planned_organ_no_datasets(self):
        _, a = get("/stage/A", organ="liver")
        self.assertEqual(a["status"], "not_computed")
        self.assertEqual(a["datasets"], [])


class StageC(unittest.TestCase):
    def test_hubs_are_distinct_tfs_not_stacked_clusters(self):
        _, c = get("/stage/C", organ="lung", layer="epithelial")
        self.assertEqual(c["status"], "cached")
        tfs = [h["tf"] for h in c["hubs"]]
        # The CSV is 8 stacked per-cell-state tables; hubs must be de-duplicated,
        # not the same TF repeated 8x (WT1, WT1, WT1, ...).
        self.assertEqual(len(tfs), len(set(tfs)))
        self.assertEqual(c["n_clusters"], 8)
        # Each cell-state sub-network is ~2000 edges; total across 8 is ~16000.
        self.assertTrue(all(1500 < v < 2500 for v in c["edges_per_cluster"].values()))
        self.assertEqual(c["n_edges"], sum(c["edges_per_cluster"].values()))

    def test_non_epithelial_no_hub_table(self):
        _, c = get("/stage/C", organ="lung", layer="mesenchymal")
        self.assertEqual(c["status"], "not_computed")
        self.assertNotIn("hubs", c)  # guardrail 4: no GRN table for un-inferred layers


class StageD(unittest.TestCase):
    def test_recipe_reference(self):
        _, d = get("/stage/D", **REF)
        self.assertEqual(d["status"], "cached")
        self.assertEqual(len(d["recipe"]), 11)
        by_tf = {r["tf"]: r for r in d["recipe"]}
        self.assertEqual(by_tf["SOX9"]["action"], "ACTIVATE")
        self.assertEqual(by_tf["CEBPA"]["action"], "KNOCK_OUT")
        self.assertEqual(by_tf["FOXJ1"]["action"], "KNOCK_OUT")
        self.assertEqual(len(d["modules"]), 4)

    def test_no_recipe_for_unrun_transition(self):
        _, d = get("/stage/D", organ="lung", layer="epithelial", source="AT1", target="Tip (fetal)", species="human")
        self.assertEqual(d["status"], "not_computed")
        self.assertNotIn("recipe", d)  # guardrail 1: never fabricate a recipe


class StageE(unittest.TestCase):
    def test_compounds_reference(self):
        _, e = get("/stage/E", organ="lung", layer="epithelial", source="AT2", target="Tip (fetal)")
        self.assertEqual(e["status"], "cached")
        self.assertEqual(len(e["compounds"]), 55)
        ev = [c for c in e["compounds"] if c["name"] == "everolimus"][0]
        self.assertAlmostEqual(ev["suppress_source_score"], 226.1)
        self.assertEqual(len(e["single_cell_confirm"]), 17)


class StageF(unittest.TestCase):
    def test_fate_human(self):
        _, f = get("/stage/F", **REF)
        self.assertEqual(f["status"], "cached")
        self.assertAlmostEqual(f["fate"]["ref_cos"], 0.6564)
        self.assertAlmostEqual(f["fate"]["ki_cos"], 0.7631)
        self.assertAlmostEqual(f["fate"]["delta_proximity"], 0.1067)
        self.assertAlmostEqual(f["compare"]["OSKM"]["delta"], 0.0553)

    def test_fate_mouse_is_different(self):
        _, f = get("/stage/F", organ="lung", layer="epithelial", source="AT2", target="Tip (fetal)", species="mouse")
        self.assertAlmostEqual(f["fate"]["delta_proximity"], -0.0905)  # species is not cosmetic (guardrail 3)


class Jobs(unittest.TestCase):
    def _poll(self, job_id, timeout=5.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            _, j = get("/jobs/" + job_id)
            if j["status"] in ("done", "failed"):
                return j
            time.sleep(0.03)
        self.fail("job did not finish")

    def test_cached_job_done(self):
        code, r = route_post("/stage/B/run", {"organ": "lung", "layer": "epithelial"})
        self.assertEqual(code, 202)
        j = self._poll(r["job_id"])
        self.assertEqual(j["status"], "done")
        self.assertTrue(j["result_uri"])

    def test_uncached_job_fails_honestly(self):
        code, r = route_post("/stage/F/run", {"organ": "lung", "layer": "mesenchymal",
                                              "source": "Pericyte", "target": "Developmental fibroblast",
                                              "species": "human"})
        j = self._poll(r["job_id"])
        self.assertEqual(j["status"], "failed")
        self.assertIn("A100", j["error"])  # honest "requires GPU" message, not a fake result


class Store(unittest.TestCase):
    def test_engine_params_change_key(self):
        i1 = artifacts.identity_for("F", "lung", "epithelial", "AT2", "Tip (fetal)", "human",
                                    engine_params={"score_quantile": 0.90})
        i2 = artifacts.identity_for("F", "lung", "epithelial", "AT2", "Tip (fetal)", "human",
                                    engine_params={"score_quantile": 0.95})
        self.assertNotEqual(artifacts.key_for(i1), artifacts.key_for(i2))  # guardrail 5


if __name__ == "__main__":
    unittest.main(verbosity=2)
