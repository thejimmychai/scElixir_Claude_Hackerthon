/* api.js — backend fetch wrappers with an offline (window.__SEED__) fallback.
 *
 * Every call first tries the live backend (same-origin). If the fetch fails
 * (backend down, or the file was opened directly via file://), it falls back to
 * deriving the identical response shape from the embedded seed bundle. This is
 * what the handoff calls "keep an offline mode": the real lung reference case
 * works before the backend is up, and light up richer data (36-row catalog,
 * GRN hub table, live LINCS query) once it is.
 */
(function () {
  "use strict";

  var REF = { organ: "lung", layer: "epithelial", source: "AT2", target: "Tip (fetal)" };

  function seed() {
    return window.__SEED__ || {};
  }
  function isRefTransition(p) {
    return p.organ === REF.organ && p.layer === REF.layer &&
           p.source === REF.source && p.target === REF.target;
  }
  function organImplemented(organ) {
    var o = seed().organs && seed().organs[organ];
    return !!o && o.status === "implemented";
  }

  // ---- offline adapters: build backend-shaped payloads from the seed --------
  var SEED = {
    meta: function () {
      var s = seed();
      return {
        meta: s.meta,
        organs: SEED.organs(),
        stages: s.stages,
        layer_defaults: window.__DEFAULTS__ || {},
        reference_case: REF,
      };
    },
    organs: function () {
      var s = seed(), out = [];
      Object.keys(s.organs || {}).forEach(function (id) {
        var o = s.organs[id];
        var e = { id: id, name: o.name, status: o.status, note: o.note || "" };
        if (o.atlas_cells != null) e.atlas_cells = o.atlas_cells;
        if (o.atlas_datasets != null) e.atlas_datasets = o.atlas_datasets;
        out.push(e);
      });
      return out;
    },
    layers: function (organ) {
      var s = seed(), impl = organImplemented(organ), out = [];
      Object.keys(s.layers || {}).forEach(function (id) {
        var l = s.layers[id];
        out.push({ id: id, name: l.name, atlas: impl ? l.atlas : null,
                   status: impl ? "implemented" : "planned" });
      });
      return out;
    },
    states: function (organ, layer) {
      var l = seed().layers && seed().layers[layer];
      if (!l || !organImplemented(organ)) return { states: {} };
      return { states: l.states };
    },
    runs: function (p) {
      var st = {};
      ["A", "B", "C", "D", "E", "F"].forEach(function (s) { st[s] = SEED._status(s, p); });
      return { run_id: [p.organ, p.layer, p.source, p.target, p.species].join("|"),
               params: p, stages: st };
    },
    _status: function (stage, p) {
      if (!organImplemented(p.organ)) return "not_computed";
      if (stage === "A") return "cached";
      if (stage === "B") return seed().layers[p.layer] ? "cached" : "not_computed";
      if (stage === "C") return (p.organ === "lung" && p.layer === "epithelial") ? "cached" : "not_computed";
      if (stage === "D" || stage === "E") return isRefTransition(p) ? "cached" : "not_computed";
      if (stage === "F") return (isRefTransition(p) && (p.species === "human" || p.species === "mouse")) ? "cached" : "not_computed";
      return "not_computed";
    },
    provenance: function () {
      var s = seed();
      var art = {
        A: ["perturbseq_datasets_catalog.csv", "tf_to_drug_connectivity.py"],
        B: ["*_subatlas.h5ad (external)", "ALL_lineage_state_TFs.csv"],
        C: ["GRN_network_scores_enhancer.csv", "epi_links.celloracle.links (external)"],
        D: ["AT2_to_TiP_TF_recipe.csv", "lung_AT2_to_progenitor_TF_scheme.csv", "insilico_TF_perturbation_screen.csv"],
        E: ["AT2_to_TiP_compounds.csv", "lung_AT2_to_progenitor_small_molecules.csv", "AT2_to_TiP_tahoe_validation.csv"],
        F: ["distaltf_fate_proximity_readout.json", "fate_proximity_readout.json"],
      };
      return {
        statement: "Every live table and number is extracted from real artifacts produced by four analysis sessions in this project. Nothing is synthetic. In-silico predictions are hypotheses requiring wet-lab validation.",
        stages: (s.stages || []).map(function (st) {
          return { stage: st.id, session: st.session, artifacts: art[st.id] || [] };
        }),
      };
    },
    stage: function (id, p) {
      var status = SEED._status(id, p), s = seed(), rc = s.refcase || {};
      if (id === "A") {
        var datasets = organImplemented(p.organ) ? (s.evidence || []).map(function (e) {
          return { study: e.study, author: e.author, year: e.year, method: e.method,
                   pert: e.pert, line: e.line, organ: e.organ, organism: e.org,
                   cells: e.cells, accession: e.acc, tier: e.tier, doi: "", verified: "" };
        }) : [];
        return { status: status, organ: p.organ, datasets: datasets,
                 drug_engine: { libraries: ["LINCS L1000 (via Enrichr)"], confirm: "Tahoe-100M",
                                status: "ready", live_query_available: false,
                                note: "Offline fallback — live LINCS/Tahoe query needs the backend." } };
      }
      if (id === "B") {
        if (status !== "cached") return { status: status, organ: p.organ, layer: p.layer, note: (s.organs[p.organ] || {}).note || "" };
        var l = s.layers[p.layer], a = l.atlas;
        return { status: "cached", organ: p.organ, layer: p.layer,
                 atlas: { cells: a.cells, donors: a.donors, n_states: a.n_states,
                          phase_coverage: { fetal: a.fetal, perinatal: a.perinatal, adult_aging: a.adult_aging } },
                 states: l.states, source_datasets: s.dev_datasets,
                 artifact_uri: "external://artifact-store/" + p.layer + "_subatlas.h5ad" };
      }
      if (id === "C") {
        var l2 = s.layers[p.layer] || { states: {} };
        function tfs(name) { var st = l2.states[name]; return st ? st.master_tfs.slice(0, 8).map(function (t) { return t.tf; }) : []; }
        var cand = { source: tfs(p.source), target: tfs(p.target) };
        if (status !== "cached") return { status: status, organ: p.organ, layer: p.layer, candidate_hubs: cand,
                                          note: "Enhancer-aware GRN was inferred only for lung epithelial in the reference run." };
        return { status: "cached", organ: p.organ, layer: p.layer, route: "scenicplus",
                 route_detail: "SCENIC+ enhancer-aware eRegulons (13/16 canonical epithelial TFs recovered)",
                 hubs: [], n_edges: null, candidate_hubs: cand,
                 note: "Hub centrality table available from the backend." };
      }
      if (id === "D") {
        if (status !== "cached") return { status: status, organ: p.organ, layer: p.layer, source: p.source, target: p.target,
                                          note: "In-silico reversal was executed for lung epithelial AT2 -> fetal distal-tip." };
        return { status: "cached", organ: p.organ, layer: p.layer, source: p.source, target: p.target, species: p.species,
                 recipe: (rc.recipe || []).map(function (r) {
                   return { tf: r.tf, action: /ACTIVATE/i.test(r.action) ? "ACTIVATE" : "KNOCK_OUT",
                            intervention: r.action, rationale: r.rationale, grn_evidence: r.grn,
                            note: r.note, confidence: (r.conf || "").split("—")[0].trim().split(" ")[0].toUpperCase(),
                            confidence_detail: r.conf };
                 }),
                 modules: (rc.modules || []).map(function (m) {
                   return { module: m.module, source: m.source, tf: m.tf, role: m.role, evidence_class: m.evidence };
                 }),
                 screen: [], alt_schemes: [], evidence: "in_silico" };
      }
      if (id === "E") {
        if (status !== "cached") return { status: status, organ: p.organ, layer: p.layer, source: p.source, target: p.target,
                                          note: "Compound nomination was executed for lung epithelial AT2 -> fetal distal-tip." };
        return { status: "cached", organ: p.organ, layer: p.layer, source: p.source, target: p.target,
                 compounds: (rc.compounds || []).map(function (c) {
                   return { name: c.name, moa: c.moa, targets: c.targets, approved: c.approved,
                            induce_target_score: c.tip, suppress_source_score: c.supAT2,
                            n_objectives_hit: c.nhit, pubchem_cid: null };
                 }),
                 curated: (rc.curated_sm || []).map(function (c) {
                   return { name: c.name, pathway: c.pathway, source: c.source, rationale: c.rationale, confidence: c.conf };
                 }),
                 single_cell_confirm: (rc.tahoe || []).map(function (t) {
                   return { intervention: t.intv, type: t.type, source_dn: t.AT2dn, target_up: t.tipup, reprog_score: t.score };
                 }),
                 evidence: "in_silico" };
      }
      if (id === "F") {
        if (status !== "cached") return { status: status, organ: p.organ, layer: p.layer, source: p.source, target: p.target, species: p.species,
                                          note: "Fate validation was run for lung epithelial AT2 -> fetal distal-tip (human & mouse)." };
        var fate = rc.fate, sp = p.species, dt = fate.distalTF[sp], ok = fate.OSKM[sp];
        return { status: "cached", organ: p.organ, layer: p.layer, source: p.source, target: p.target, species: sp,
                 tf_set: ["SOX9", "NKX2-1", "ETV5", "ETV4"], evidence: "in_silico",
                 fate: { ref_cos: dt.ref, ki_cos: dt.ki, delta_proximity: dt.delta, n_genes: fate.panel.length, panel: fate.panel, per_gene: null },
                 cocktails: { distalTF: { tf_set: ["SOX9", "NKX2-1", "ETV5", "ETV4"], ref_cos: dt.ref, ki_cos: dt.ki, delta: dt.delta },
                              OSKM: { tf_set: ["POU5F1", "SOX2", "KLF4", "MYC"], ref_cos: ok.ref, ki_cos: ok.ki, delta: ok.delta } },
                 compare: { OSKM: { delta: ok.delta }, distalTF: { delta: dt.delta } } };
      }
      return { status: "not_computed" };
    },
  };

  // ---- live fetch with fallback ---------------------------------------------
  var API = {
    base: "",
    mode: null, // "live" | "offline", set on first call
    onmodechange: null,

    _setMode: function (m) {
      if (this.mode !== m) {
        this.mode = m;
        if (typeof this.onmodechange === "function") this.onmodechange(m);
      }
    },
    _qs: function (params) {
      var parts = [];
      Object.keys(params || {}).forEach(function (k) {
        if (params[k] != null) parts.push(encodeURIComponent(k) + "=" + encodeURIComponent(params[k]));
      });
      return parts.length ? "?" + parts.join("&") : "";
    },
    _get: function (path, fallback) {
      var self = this;
      return fetch(this.base + path, { headers: { "Accept": "application/json" } })
        .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
        .then(function (j) { self._setMode("live"); return j; })
        .catch(function () { self._setMode("offline"); return fallback(); });
    },
    _post: function (path, body) {
      return fetch(this.base + path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body || {}),
      }).then(function (r) { return r.json(); });
    },

    getMeta: function () { return this._get("/meta", function () { return SEED.meta(); }); },
    getOrgans: function () { return this._get("/organs", function () { return SEED.organs(); }); },
    getLayers: function (organ) { return this._get("/organs/" + encodeURIComponent(organ) + "/layers", function () { return SEED.layers(organ); }); },
    getStates: function (organ, layer) {
      return this._get("/organs/" + encodeURIComponent(organ) + "/layers/" + encodeURIComponent(layer) + "/states",
                       function () { return SEED.states(organ, layer); });
    },
    getRuns: function (p) { return this._get("/runs" + this._qs(p), function () { return SEED.runs(p); }); },
    getStage: function (id, p) {
      var params = { organ: p.organ, layer: p.layer, source: p.source, target: p.target, species: p.species };
      return this._get("/stage/" + id + this._qs(params), function () { return SEED.stage(id, p); });
    },
    getProvenance: function () { return this._get("/provenance", function () { return SEED.provenance(); }); },
    runStage: function (id, body) { return this._post("/stage/" + id + "/run", body); },
    getJob: function (jobId) { return this._get("/jobs/" + encodeURIComponent(jobId), function () { return { status: "unknown", error: "offline" }; }); },
  };

  window.API = API;
})();
