"""Tests for the Phase 2–5 features: live Stage E, route handling, the capability
report, durable artifacts with identity guardrails, organ bundles, and validation.

Everything that writes is redirected to a temporary directory, and the live
connectivity engine is replaced by a fake, so these tests need no network and
no optional packages. Fixtures named ``*_FIXTURE`` are synthetic test data and
are never served as results outside these tests.

Run:  python3 -m unittest discover -s tests -v     (from the bundle root)
"""

import json
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import artifacts, capabilities, config, organ_bundles  # noqa: E402
from backend.app import BadRequest, route_get, route_post  # noqa: E402
from backend.stages import stage_e_drugs  # noqa: E402


def get(path, **qs):
    q = {k: [str(v)] for k, v in qs.items()}
    return route_get(path, q)


def wait_for_job(job_id, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        _, job = route_get(f"/jobs/{job_id}", {})
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(0.03)
    raise AssertionError("job did not finish")


# --------------------------------------------------------------------------- #
# fakes                                                                        #
# --------------------------------------------------------------------------- #
class FakeFrame:
    """Stands in for the pandas DataFrame the engine returns."""

    def __init__(self, rows):
        self.rows = rows

    def to_dict(self, orient="records"):
        return [dict(r) for r in self.rows]


class FakeEngine:
    """Stands in for backend/engine/tf_to_drug_connectivity.py (records every call)."""

    def __init__(self):
        self.calls = []
        self.tahoe_loads = 0

    def load_tahoe_drugs(self):
        self.tahoe_loads += 1
        return "TAHOE_FIXTURE"

    def connectivity_query(self, genes, direction="mimic", lung_only=False, library=None, top=None):
        self.calls.append(("query", list(genes), direction, lung_only))
        return FakeFrame([{"drug": f"{direction}_FIXTURE", "cell_line": "A549",
                           "combined_score": 1.5, "direction": direction}])

    def cross_ref_tahoe(self, conn, tahoe_drugs=None):
        self.calls.append(("tahoe", tahoe_drugs))
        return FakeFrame([{**r, "in_tahoe": True} for r in conn.rows])


class Isolated(unittest.TestCase):
    """Redirect every writable location to a temporary directory."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = self._tmp.name
        self._saved = {k: getattr(config, k) for k in ("RESULTS_DIR", "ORGANS_DIR", "EXTERNAL_DIR")}
        config.RESULTS_DIR = os.path.join(base, "results")
        config.ORGANS_DIR = os.path.join(base, "organs")
        config.EXTERNAL_DIR = os.path.join(base, "external")

    def tearDown(self):
        for k, v in self._saved.items():
            setattr(config, k, v)
        self._tmp.cleanup()


# --------------------------------------------------------------------------- #
# Stage E — live connectivity (Phase 2)                                        #
# --------------------------------------------------------------------------- #
class StageELive(Isolated):
    def test_both_directions_are_queried_with_the_right_gene_lists(self):
        eng = FakeEngine()
        with patch.object(stage_e_drugs, "_load_engine", return_value=eng):
            res = stage_e_drugs.live_connectivity(["SOX9", "LEF1"], ["FOXJ1"], lung_only=True)
        queries = [c for c in eng.calls if c[0] == "query"]
        # The previous implementation passed a {up, down} dict here; the engine
        # needs a gene list, and the reverse direction was never queried.
        self.assertEqual(queries[0], ("query", ["SOX9", "LEF1"], "mimic", True))
        self.assertEqual(queries[1], ("query", ["FOXJ1"], "reverse", True))
        self.assertEqual(eng.tahoe_loads, 1)  # Tahoe metadata is fetched once, not per direction
        self.assertEqual({r["direction"] for r in res["compounds"]}, {"mimic", "reverse"})
        self.assertTrue(all(r["in_tahoe"] for r in res["compounds"]))

    def test_canonical_signature_sorts_dedupes_and_validates(self):
        sig = stage_e_drugs.canonical_signature({"up": ["lef1", "SOX9", "sox9 "], "down": []})
        self.assertEqual(sig, {"up": ["LEF1", "SOX9"], "down": []})
        for bad in ({"up": "SOX9"}, {"up": ["SOX9; DROP"]}, {}, {"up": ["A"], "sideways": ["B"]}):
            with self.assertRaises(ValueError, msg=str(bad)):
                stage_e_drugs.canonical_signature(bad)

    def test_post_rejects_invalid_signatures_with_400(self):
        for body in ({"signature": {"up": "SOX9"}}, {"signature": {"up": ["A B"]}}, {"signature": {}}):
            with self.assertRaises(BadRequest, msg=str(body)):
                route_post("/stage/E/run", body)

    def test_job_stores_its_live_result_and_get_serves_it_back(self):
        eng = FakeEngine()
        body = {"organ": "lung", "layer": "epithelial", "source": "AT2", "target": "Tip (fetal)",
                "signature": {"up": ["SOX9"], "down": ["FOXJ1"]}, "lung_only": True}
        with patch.object(stage_e_drugs, "_load_engine", return_value=eng):
            _, submitted = route_post("/stage/E/run", body)
            job = wait_for_job(submitted["job_id"])
        self.assertEqual(job["status"], "done")
        self.assertTrue(job["result_uri"].startswith("file://"))

        engine_param = json.dumps({"signature": {"up": ["SOX9"], "down": ["FOXJ1"]}, "lung_only": True})
        code, served = get("/stage/E", organ="lung", layer="epithelial", source="AT2",
                           target="Tip (fetal)", engine=engine_param)
        self.assertEqual(code, 200)
        self.assertEqual(served["served_from"], "artifact")
        self.assertEqual(len(served["compounds"]), 2)

        # A second identical request is answered from the artifact, without querying again.
        calls_before = len(eng.calls)
        with patch.object(stage_e_drugs, "_load_engine", return_value=eng):
            job2 = wait_for_job(route_post("/stage/E/run", body)[1]["job_id"])
        self.assertEqual(job2["status"], "done")
        self.assertEqual(len(eng.calls), calls_before)

    def test_engine_failure_is_reported_not_faked(self):
        class BrokenEngine(FakeEngine):
            def connectivity_query(self, *a, **k):
                raise RuntimeError("maayanlab.cloud unreachable")

        with patch.object(stage_e_drugs, "_load_engine", return_value=BrokenEngine()):
            job = wait_for_job(route_post("/stage/E/run", {
                "organ": "lung", "layer": "epithelial", "source": "AT2", "target": "Tip (fetal)",
                "signature": {"up": ["SOX9"]}})[1]["job_id"])
        self.assertEqual(job["status"], "failed")
        self.assertIn("live LINCS/Tahoe query failed", job["error"])
        self.assertFalse(os.path.exists(config.RESULTS_DIR))  # nothing is saved for a failed run


# --------------------------------------------------------------------------- #
# Stage C routes and request validation (Phase 3)                              #
# --------------------------------------------------------------------------- #
class RoutesAndValidation(Isolated):
    def test_celloracle_route_is_not_served_from_the_scenicplus_table(self):
        code, payload = get("/stage/C", organ="lung", layer="epithelial", route="celloracle")
        self.assertEqual(code, 200)
        self.assertEqual(payload["status"], "not_computed")
        self.assertEqual(payload["route"], "celloracle")
        self.assertNotIn("hubs", payload)
        self.assertTrue(payload["requires"])

    def test_scenicplus_route_still_serves_the_reference_table(self):
        _, payload = get("/stage/C", organ="lung", layer="epithelial", route="scenicplus")
        self.assertEqual(payload["status"], "cached")
        self.assertEqual(payload["route"], "scenicplus")
        self.assertEqual(len(payload["hubs"]), 40)

    def test_unknown_route_species_and_engine_are_400(self):
        with self.assertRaises(BadRequest):
            get("/stage/C", organ="lung", route="bogus")
        with self.assertRaises(BadRequest):
            get("/stage/F", organ="lung", species="cat")
        with self.assertRaises(BadRequest):
            get("/stage/D", organ="lung", engine="not json")
        with self.assertRaises(BadRequest):
            route_post("/stage/C/run", {"route": "bogus"})
        with self.assertRaises(BadRequest):
            route_post("/stage/F/run", {"species": "cat"})
        with self.assertRaises(BadRequest):
            route_post("/stage/B/run", ["not", "an", "object"])

    def test_failed_job_carries_the_requirements_list(self):
        _, submitted = route_post("/stage/F/run", {
            "organ": "lung", "layer": "mesenchymal", "source": "Pericyte",
            "target": "Developmental fibroblast", "species": "human"})
        job = wait_for_job(submitted["job_id"])
        self.assertEqual(job["status"], "failed")
        self.assertIn("A100", job["error"])
        self.assertTrue(job["requires"])


# --------------------------------------------------------------------------- #
# capability report (Phase 3–4)                                                #
# --------------------------------------------------------------------------- #
class Capabilities(Isolated):
    def test_report_lists_every_engine_and_paths(self):
        rep = capabilities.report()
        self.assertEqual(set(rep["engines"]), {"lincs_tahoe", "scvi_atlas", "celloracle", "scenicplus", "pertformer"})
        self.assertIn("external_inputs", rep["paths"])
        self.assertNotIn("network", rep)  # network is only probed on request

    def test_stage_a_needs_nothing(self):
        self.assertEqual(capabilities.requirements("A", "lung", "epithelial"), [])

    def test_missing_input_is_listed_then_disappears_when_present(self):
        before = capabilities.requirements("B", "lung", "epithelial")
        self.assertIn("Input not present: data/external/lung/epithelial_subatlas.h5ad", before)
        os.makedirs(os.path.join(config.EXTERNAL_DIR, "lung"), exist_ok=True)
        with open(os.path.join(config.EXTERNAL_DIR, "lung", "epithelial_subatlas.h5ad"), "w") as fh:
            fh.write("")
        after = capabilities.requirements("B", "lung", "epithelial")
        self.assertNotIn("Input not present: data/external/lung/epithelial_subatlas.h5ad", after)

    def test_route_specific_requirements(self):
        cell = capabilities.requirements("C", "lung", "epithelial", "celloracle")
        scen = capabilities.requirements("C", "lung", "epithelial", "scenicplus")
        self.assertTrue(any("celloracle" in r.lower() or "CellOracle" in r for r in cell))
        self.assertTrue(any("SCENIC+" in r for r in scen))
        self.assertFalse(any("SCENIC+" in r for r in cell))

    def test_compute_status_endpoint(self):
        code, payload = get("/compute/status")
        self.assertEqual(code, 200)
        self.assertIn("engines", payload)


# --------------------------------------------------------------------------- #
# durable artifacts and identity guardrails (Phase 1)                          #
# --------------------------------------------------------------------------- #
class ArtifactsGuardrails(Isolated):
    def setUp(self):
        super().setUp()
        self.ident = artifacts.identity_for(
            "D", "lung", "mesenchymal", "Pericyte", "Developmental fibroblast", "human")
        artifacts.save(self.ident, {"status": "cached", "fixture": "unit-test payload", "recipe": []})

    def test_artifact_is_served_and_indexed(self):
        code, payload = get("/stage/D", organ="lung", layer="mesenchymal",
                            source="Pericyte", target="Developmental fibroblast", species="human")
        self.assertEqual(payload["served_from"], "artifact")
        _, runs = get("/runs", organ="lung", layer="mesenchymal",
                      source="Pericyte", target="Developmental fibroblast", species="human")
        self.assertEqual(runs["stages"]["D"], "cached")
        _, index = get("/results")
        self.assertEqual(len(index["results"]), 1)

    def test_other_species_and_engine_parameters_never_receive_it(self):
        base = dict(organ="lung", layer="mesenchymal", source="Pericyte", target="Developmental fibroblast")
        _, mouse = get("/stage/D", species="mouse", **base)
        self.assertEqual(mouse["status"], "not_computed")  # guardrail 3: species is real
        _, tuned = get("/stage/D", species="human", engine=json.dumps({"alpha": 10}), **base)
        self.assertEqual(tuned["status"], "not_computed")  # guardrail 5: engine params fold in

    def test_identity_is_checked_on_read(self):
        path = artifacts.path_for(self.ident)
        with open(path) as fh:
            doc = json.load(fh)
        doc["identity"]["target"] = "Something else"
        with open(path, "w") as fh:
            json.dump(doc, fh)
        self.assertIsNone(artifacts.load(self.ident))

    def test_reference_results_are_not_copied_into_results(self):
        get("/stage/E", organ="lung", layer="epithelial", source="AT2", target="Tip (fetal)")
        route_post("/stage/E/run", {"organ": "lung", "layer": "epithelial", "source": "AT2", "target": "Tip (fetal)"})
        ref = artifacts.identity_for("E", "lung", "epithelial", "AT2", "Tip (fetal)")
        self.assertIsNone(artifacts.load(ref))


# --------------------------------------------------------------------------- #
# organ bundles (Phase 5)                                                      #
# --------------------------------------------------------------------------- #
def organ_fixture(organ_id="testorgan", status="implemented"):
    """Synthetic organ for these tests only — not data, never served outside them."""
    return {
        "id": organ_id,
        "name": "Test organ (fixture)",
        "status": status,
        "note": "unit-test fixture",
        "layers": {
            "hepatocyte": {
                "name": "Hepatocyte",
                "atlas": {"cells": 1000, "donors": 3, "n_states": 2,
                          "fetal": 100, "perinatal": 300, "adult_aging": 600},
                "states": {
                    "Mature cell": {"role": "mature", "master_tfs": [{"tf": "TF_A", "logFC": 2.0}]},
                    "Progenitor cell": {"role": "progenitor", "master_tfs": [{"tf": "TF_B", "logFC": 1.5}]},
                },
            }
        },
    }


class OrganBundles(Isolated):
    def _write(self, folder, doc):
        d = os.path.join(config.ORGANS_DIR, folder)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "organ.json"), "w") as fh:
            json.dump(doc, fh)

    def test_valid_bundle_is_registered_and_its_layer_is_served(self):
        self._write("testorgan", organ_fixture())
        _, organs = get("/organs")
        self.assertIn("testorgan", {o["id"] for o in organs})
        _, layers = get("/organs/testorgan/layers")
        self.assertIsNotNone(layers[0]["atlas"])
        _, states = get("/organs/testorgan/layers/hepatocyte/states")
        self.assertEqual(states["states"]["Mature cell"]["role"], "mature")
        _, stage_b = get("/stage/B", organ="testorgan", layer="hepatocyte")
        self.assertEqual(stage_b["status"], "cached")
        self.assertEqual(stage_b["atlas"]["cells"], 1000)

    def test_bundle_never_brings_stage_results_without_a_real_run(self):
        self._write("testorgan", organ_fixture())
        for stage in ("D", "E", "F"):
            _, payload = get(f"/stage/{stage}", organ="testorgan", layer="hepatocyte",
                             source="Mature cell", target="Progenitor cell", species="human")
            self.assertEqual(payload["status"], "not_computed", stage)
            self.assertTrue(payload["requires"], stage)

    def test_invalid_bundle_is_skipped_and_reported(self):
        bad = organ_fixture()
        bad["layers"]["hepatocyte"]["states"].pop("Progenitor cell")
        self._write("badorgan", dict(bad, id="badorgan"))
        self.assertFalse(organ_bundles.scan()["badorgan"]["valid"])
        _, organs = get("/organs")
        self.assertNotIn("badorgan", {o["id"] for o in organs})

    def test_validator_rules(self):
        good = organ_fixture()
        self.assertEqual(organ_bundles.validate(good, expected_id="testorgan"), [])
        self.assertTrue(organ_bundles.validate(good, expected_id="other"))              # id/folder mismatch
        self.assertTrue(organ_bundles.validate(dict(good, id="lung"), expected_id="lung"))  # lung is reserved
        bad_role = organ_fixture()
        bad_role["layers"]["hepatocyte"]["states"]["Mature cell"]["role"] = "adult"
        self.assertTrue(organ_bundles.validate(bad_role, expected_id="testorgan"))
        bad_atlas = organ_fixture()
        bad_atlas["layers"]["hepatocyte"]["atlas"]["cells"] = "many"
        self.assertTrue(organ_bundles.validate(bad_atlas, expected_id="testorgan"))
        bad_tf = organ_fixture()
        bad_tf["layers"]["hepatocyte"]["states"]["Mature cell"]["master_tfs"] = [{"tf": "X", "logFC": True}]
        self.assertTrue(organ_bundles.validate(bad_tf, expected_id="testorgan"))

    def test_underscore_and_dot_folders_are_ignored(self):
        self._write("_template", organ_fixture("_template"))
        self.assertNotIn("_template", organ_bundles.scan())


if __name__ == "__main__":
    unittest.main(verbosity=2)
