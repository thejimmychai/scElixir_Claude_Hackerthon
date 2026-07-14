/* stages.js — per-stage render functions.
 *
 * Each takes the API payload for that stage and returns an HTML string. These
 * are the response-to-DOM templates from the original standalone blueprint,
 * re-pointed at the fetched payloads (whose field names match the backend's
 * Section-4 contract) instead of a global DATA object. Guardrails are honoured:
 * planned organs and un-run combinations render an honest "not run" notice,
 * never fabricated numbers.
 */
(function () {
  "use strict";
  var esc = window.esc;

  function dataMode() {
    return window.API && window.API.mode === "offline" ? "SEED DATA · offline" : "LIVE DATA · reference case";
  }
  function liveHead(title, tag) {
    return '<div class="dpanel"><div class="dh"><div class="livewrap"><span class="dot"></span>' + dataMode() + "</div>" +
      '<h3 style="margin-left:4px">' + esc(title) + '</h3><span class="tag">' + esc(tag || "") + "</span></div><div class=\"db\">";
  }
  function insilicoNote() {
    return '<div class="note">In-silico predictions are hypotheses requiring wet-lab validation.</div>';
  }
  function plannedNotice(organ) {
    var o = (window.STATE.organs || []).filter(function (x) { return x.id === organ; })[0] || { name: organ, note: "" };
    return '<div class="dpanel"><div class="dh"><div class="plandata"><span class="dot"></span>PLANNED ORGAN</div>' +
      '<h3 style="margin-left:4px">' + esc(o.name) + " — migration target</h3></div>" +
      '<div class="db"><p style="color:var(--mut);margin:0 0 12px">' + esc(o.note) + "</p>" +
      '<div class="note">The pipeline spine (Stages A–F) is organ-agnostic. To bring <b>' + esc(o.name) +
      "</b> online, run the same workflow: assemble its developmental atlas (Stage B), infer GRNs (C), define the " +
      "adult→progenitor reversal (D), mirror to small molecules (E), and validate with the sequence model (F). " +
      "The lung reference case demonstrates every step end-to-end.</div></div></div>";
  }
  function notComputed(title, note) {
    return liveHead(title, "method demonstrated · this combination not yet run") +
      '<p style="color:var(--mut);margin:0;font-size:13px">' + esc(note || "This stage has not been run for the selected combination.") +
      '</p><div class="note acc" style="margin-top:12px">Select <b>Lung · Epithelial · AT2 → Tip (fetal)</b> to see the fully-worked reference numbers. ' +
      "No placeholder values are shown for un-run combinations.</div></div></div>";
  }

  /* ---------- Stage A — evidence base ---------- */
  function renderA(p) {
    if (p.status !== "cached") return notComputed("Perturbation-screen evidence catalog", p.note);
    var de = p.drug_engine || {};
    var engineLine = de.live_query_available
      ? '<span style="color:var(--act)">● live query available</span>'
      : '<span style="color:var(--warn)">● cached engine (live LINCS/Tahoe query needs deps + network)</span>';
    var rows = (p.datasets || []).map(function (e) {
      return "<tr><td>" + esc(e.study) + (e.author ? '<div style="color:var(--dim);font-size:11px">' + esc(e.author) + " " + esc(e.year) + "</div>" : "") +
        "</td><td>" + esc(e.method) + "</td><td>" + esc(e.pert) + "</td>" +
        "<td>" + esc(e.line) + '<div style="color:var(--dim);font-size:11px">' + esc(e.organism || e.organ) + "</div></td>" +
        '<td class="mono" style="font-size:11px">' + esc(e.cells) + "</td>" +
        '<td class="mono" style="font-size:11px">' + esc(e.accession) + "</td></tr>";
    }).join("");
    return liveHead("Perturbation-screen evidence catalog", (p.datasets || []).length + " datasets · recorded verify_status") +
      '<p style="color:var(--mut);margin:0 0 8px;font-size:13px">Large-scale single-cell perturbation screens catalogued for the organ, prioritizing lung lines (A549) and TF-focused libraries. The TF→drug connectivity engine (LINCS L1000 + Tahoe-100M) is seeded from these signatures.</p>' +
      '<div style="font-size:12px;margin:0 0 12px">Drug engine: ' + engineLine + "</div>" +
      "<table><thead><tr><th>Study</th><th>Method</th><th>Perturbation</th><th>Line / organism</th><th>Cells</th><th>Accession</th></tr></thead><tbody>" +
      rows + "</tbody></table></div></div>";
  }

  /* ---------- Stage B — developmental atlas ---------- */
  function renderB(p) {
    if (p.status !== "cached") return notComputed("Developmental sub-atlas", p.note);
    var a = p.atlas, ph = a.phase_coverage;
    var tot = (ph.fetal || 0) + (ph.perinatal || 0) + (ph.adult_aging || 0);
    var pct = function (n) { return tot ? Math.max(4, Math.round(100 * n / tot)) : 0; };
    var ds = (p.source_datasets || []).map(function (x) {
      return '<tr><td class="mono" style="font-size:11px">' + esc(x.short) + "</td><td>" + esc(x.name) + "</td><td>" + esc(x.phase) +
        '</td><td class="mono" style="font-size:11px">' + (x.cells / 1000).toFixed(0) + 'k</td><td class="mono" style="font-size:11px">' + x.donors + "</td></tr>";
    }).join("");
    var stRows = Object.keys(p.states || {}).map(function (name) {
      var v = p.states[name];
      var tfs = v.master_tfs.slice(0, 6).map(function (t) {
        return '<span class="chip">' + esc(t.tf) + '<span style="color:var(--dim)"> ' + t.logFC + "</span></span>";
      }).join(" ");
      return "<tr><td>" + esc(name) + " " + (v.role === "progenitor" ? '<span class="pill p-hi">progenitor ◆</span>' : "") +
        '</td><td><div class="chips">' + tfs + "</div></td></tr>";
    }).join("");
    return liveHead(window.STATE.layers.filter(function (l) { return l.id === window.STATE.layer; })[0].name + " developmental sub-atlas",
      (a.cells / 1000).toFixed(0) + "k cells · " + a.donors + " donors · " + a.n_states + " annotated states") +
      '<div class="statgrid">' +
      '<div class="stat"><div class="v">' + (a.cells / 1000).toFixed(0) + '</div><div class="l">cells (k)</div></div>' +
      '<div class="stat"><div class="v">' + a.donors + '</div><div class="l">donors</div></div>' +
      '<div class="stat"><div class="v">' + a.n_states + '</div><div class="l">cell states</div></div>' +
      '<div class="stat"><div class="v">' + (p.source_datasets || []).length + '</div><div class="l">source datasets</div></div></div>' +
      '<h4 style="font-size:11px;text-transform:uppercase;letter-spacing:1px;color:var(--dim);margin:6px 0 4px">Developmental phase coverage</h4>' +
      '<div class="phasebars">' +
      '<div style="flex:' + pct(ph.fetal) + ';background:#7ee0c0">' + (ph.fetal ? (ph.fetal / 1000).toFixed(0) + "k" : "") + "</div>" +
      '<div style="flex:' + pct(ph.perinatal) + ';background:#4aa8ff">' + (ph.perinatal ? (ph.perinatal / 1000).toFixed(0) + "k" : "") + "</div>" +
      '<div style="flex:' + pct(ph.adult_aging) + ';background:#f0b866">' + (ph.adult_aging ? (ph.adult_aging / 1000).toFixed(0) + "k" : "") + "</div></div>" +
      '<div class="legend"><span><i style="background:#7ee0c0"></i>embryonic-fetal</span><span><i style="background:#4aa8ff"></i>perinatal</span><span><i style="background:#f0b866"></i>adult-aging</span></div>' +
      '<h4 style="font-size:11px;text-transform:uppercase;letter-spacing:1px;color:var(--dim);margin:20px 0 8px">Cell states & master TFs (DE, log-fold-change)</h4>' +
      '<table><thead><tr><th style="width:210px">Cell state</th><th>Top state-defining TFs</th></tr></thead><tbody>' + stRows + "</tbody></table>" +
      '<h4 style="font-size:11px;text-transform:uppercase;letter-spacing:1px;color:var(--dim);margin:20px 0 8px">Source datasets (harmonized to one gene/phase axis)</h4>' +
      "<table><thead><tr><th>ID</th><th>Dataset</th><th>Phase(s)</th><th>Cells</th><th>Donors</th></tr></thead><tbody>" + ds + "</tbody></table>" +
      '<div class="note">Human same-cell RNA+ATAC does not exist before adulthood — this RNA backbone is the substrate; matched multiome (mouse developmental / human adult) is layered in Stage C/F.</div></div></div>';
  }

  /* ---------- Stage C — GRN inference ---------- */
  function renderC(p) {
    var S = window.STATE;
    var cand = p.candidate_hubs || { source: [], target: [] };
    var chips = function (arr) { return (arr || []).map(function (t) { return '<span class="chip">' + esc(t) + "</span>"; }).join(" ") || "—"; };
    var head = liveHead("Gene-regulatory network — hub regulators",
      p.status === "cached" ? (p.route_detail || "CellOracle base-GRN + SCENIC+ enhancer-aware") : "candidate regulators (Stage-B master TFs)");
    var body = '<p style="color:var(--mut);margin:0 0 14px;font-size:13px">Per-state regulons anchor the transition whose direction Stage D perturbs along. The source and target candidate regulators are the state master TFs; the enhancer-aware SCENIC+ hub table (when available) ranks network centrality.</p>' +
      '<div class="cols">' +
      '<div class="dpanel" style="margin:0"><div class="dh"><h3 style="font-size:13px">Source hubs · ' + esc(S.source) + '</h3></div><div class="db"><div class="chips">' + chips(cand.source) + "</div></div></div>" +
      '<div class="dpanel" style="margin:0"><div class="dh"><h3 style="font-size:13px">Target hubs · ' + esc(S.target) + ' ◆</h3></div><div class="db"><div class="chips">' + chips(cand.target) + "</div></div></div></div>";
    if (p.status === "cached" && (p.hubs || []).length) {
      var hubRows = p.hubs.slice(0, 20).map(function (h) {
        return '<tr><td class="tf">' + esc(h.tf) + "</td><td>" + (h.degree_centrality_all != null ? h.degree_centrality_all.toFixed(3) : "—") +
          "</td><td>" + (h.betweenness_centrality != null ? h.betweenness_centrality.toFixed(4) : "—") +
          "</td><td>" + (h.eigenvector_centrality != null ? h.eigenvector_centrality.toFixed(3) : "—") +
          '</td><td class="mono" style="font-size:11px">' + esc(h.cluster) + "</td></tr>";
      }).join("");
      var clusterLabel = p.n_clusters
        ? p.n_clusters + " cell-state sub-networks · " + (p.n_edges != null ? p.n_edges.toLocaleString() : "—") + " edges total"
        : (p.n_edges != null ? p.n_edges.toLocaleString() + " edges" : "");
      body += '<h4 style="font-size:11px;text-transform:uppercase;letter-spacing:1px;color:var(--dim);margin:20px 0 8px">Network hubs — enhancer-aware GRN (' +
        clusterLabel + " · top 20 distinct-TF hubs by peak degree centrality)</h4>" +
        "<table><thead><tr><th>TF</th><th>Degree centrality</th><th>Betweenness</th><th>Eigenvector</th><th>Peak cluster</th></tr></thead><tbody>" + hubRows + "</tbody></table>";
    } else {
      body += '<div class="note" style="margin-top:14px">' + esc(p.note || "Enhancer-aware GRN centrality table was inferred only for the lung epithelial reference layer.") + "</div>";
    }
    body += '<div class="note acc" style="margin-top:12px"><b>GRN rewiring principle:</b> transitions are driven by a hub hand-off — an early network module rewires into the target-state module. Edge-turnover localizes where rewiring is sharpest; those are the perturbation-sensitive windows Stage D targets.</div>' +
      '<div class="note">Two routes: <b>CellOracle</b> (promoter/motif base-GRN, RNA-only — always available) and <b>SCENIC+</b> (enhancer-aware eRegulons — needs matched ATAC + GPU cisTarget DB).</div>';
    return head + body + "</div></div>";
  }

  /* ---------- Stage D — in-silico reversal → TF recipe ---------- */
  function renderD(p) {
    if (p.status !== "cached") return notComputed("In-silico reversal — TF recipe", p.note);
    var recipeRows = (p.recipe || []).map(function (r) {
      var act = r.action === "ACTIVATE";
      return '<tr><td class="tf">' + esc(r.tf) + '</td><td><span class="pill ' + (act ? "p-act" : "p-ko") + '">' + (act ? "ACTIVATE" : "KNOCK-OUT") + "</span></td>" +
        '<td style="font-size:11.5px">' + esc(r.rationale) + '</td><td style="font-size:11px;color:var(--dim)">' + esc(r.grn_evidence) + "</td>" +
        '<td><span class="pill ' + (/HIGH/i.test(r.confidence) ? "p-hi" : "p-med") + '">' + esc(r.confidence) + "</span></td></tr>";
    }).join("");
    var modRows = (p.modules || []).map(function (m) {
      return '<tr><td style="font-size:12px">' + esc(m.module) + '</td><td class="tf">' + esc(m.tf) +
        '</td><td style="font-size:11.5px;color:var(--mut)">' + esc(m.role) + '</td><td style="font-size:11px;color:var(--dim)">' + esc(m.evidence_class) + "</td></tr>";
    }).join("");
    var out = liveHead("In-silico reversal — precision TF recipe", "AT2 → fetal distal-tip · CellOracle KO/OE projection") +
      '<p style="color:var(--mut);margin:0 0 12px;font-size:13px">In-silico KO/OE screen projected onto the AT2→Tip transition vector, split into <b>activate</b> (re-open progenitor program) and <b>knock-out</b> (release mature/alternative identity) calls.</p>' +
      "<table><thead><tr><th>TF</th><th>Intervention</th><th>Rationale</th><th>GRN evidence</th><th>Conf.</th></tr></thead><tbody>" + recipeRows + "</tbody></table>" +
      '<h4 style="font-size:11px;text-transform:uppercase;letter-spacing:1px;color:var(--dim);margin:20px 0 8px">Stage-gated module scheme (measured GRN → lung nomination)</h4>' +
      "<table><thead><tr><th>GRN module</th><th>TF</th><th>Role</th><th>Evidence class</th></tr></thead><tbody>" + modRows + "</tbody></table>";
    if ((p.alt_schemes || []).length) {
      var altRows = p.alt_schemes.slice(0, 6).map(function (s) {
        return '<tr><td style="font-size:11.5px">' + esc(s.transition) + '</td><td class="tf" style="font-size:11px">' + esc(s.combo) +
          '</td><td class="mono" style="font-size:11px">' + (s.combo_projection != null ? s.combo_projection.toFixed(2) : "—") +
          '</td><td class="mono" style="font-size:11px">' + (s.combo_gain_over_single != null ? "+" + s.combo_gain_over_single.toFixed(2) : "—") + "</td></tr>";
      }).join("");
      out += '<h4 style="font-size:11px;text-transform:uppercase;letter-spacing:1px;color:var(--dim);margin:20px 0 8px">Combo vs single-TF gains (stage-wise scheme)</h4>' +
        "<table><thead><tr><th>Transition</th><th>Best combo</th><th>Projection</th><th>Gain over single</th></tr></thead><tbody>" + altRows + "</tbody></table>";
    }
    out += '<div class="note">The scheme replaces constitutive OSKM with stage-gated modules — the progenitor lock-in is a distributed network property, not strongly single-TF-drivable, hence combinations.</div>';
    return out + "</div></div>";
  }

  /* ---------- Stage E — small-molecule mirror ---------- */
  function renderE(p) {
    if (p.status !== "cached") return notComputed("Small-molecule mirror", p.note);
    var maxSup = Math.max.apply(null, (p.compounds || []).map(function (c) { return c.suppress_source_score || 0; }).concat([1]));
    var cRows = (p.compounds || []).slice(0, 14).map(function (c) {
      return '<tr><td class="tf" style="font-weight:600">' + esc(c.name) + '</td><td style="font-size:11.5px">' + esc(c.moa) +
        '</td><td style="font-size:11px;color:var(--dim)">' + esc(c.targets) + "</td>" +
        '<td><span class="bar"><i style="width:' + Math.round(100 * (c.suppress_source_score || 0) / maxSup) + '%"></i></span> <span class="mono" style="font-size:11px">' + (c.suppress_source_score != null ? c.suppress_source_score : "—") + "</span></td>" +
        '<td class="' + (c.approved === "yes" ? "p-yes" : "p-no") + '">' + (c.approved === "yes" ? "approved" : "—") + "</td></tr>";
    }).join("");
    var curRows = (p.curated || []).map(function (c) {
      return '<tr><td class="tf">' + esc(c.name) + '</td><td style="font-size:12px">' + esc(c.pathway) +
        '</td><td style="font-size:11px;color:var(--dim)">' + esc(c.source) +
        '</td><td><span class="pill ' + (/HIGH/i.test(c.confidence) ? "p-hi" : "p-med") + '">' + esc((c.confidence || "").split("(")[0].trim()) + "</span></td></tr>";
    }).join("");
    var out = liveHead("Small-molecule mirror — compound nomination", "LINCS L1000 → Tahoe-100M single-cell confirmation") +
      '<p style="color:var(--mut);margin:0 0 12px;font-size:13px">Compounds whose transcriptional signature mimics the reprogramming objective (induce Tip, suppress AT2, suppress club/ciliated). Ranked by AT2-suppression connectivity; approval status from Tahoe metadata.</p>' +
      "<table><thead><tr><th>Compound</th><th>MoA</th><th>Targets</th><th>Suppress-AT2 connectivity</th><th>Status</th></tr></thead><tbody>" + cRows + "</tbody></table>" +
      '<h4 style="font-size:11px;text-transform:uppercase;letter-spacing:1px;color:var(--dim);margin:20px 0 8px">Curated organ cocktail (measured prior + lung-established)</h4>' +
      "<table><thead><tr><th>Compound</th><th>Pathway</th><th>Source</th><th>Conf.</th></tr></thead><tbody>" + curRows + "</tbody></table>";
    if ((p.single_cell_confirm || []).length) {
      var scRows = p.single_cell_confirm.slice(0, 10).map(function (t) {
        var pos = (t.reprog_score || 0) >= 0;
        return "<tr><td>" + esc(t.intervention) + '</td><td><span class="pill ' + (t.type === "combo" ? "p-hi" : "p-med") + '">' + esc(t.type) + "</span></td>" +
          '<td class="mono" style="font-size:11px">' + (t.source_dn != null ? t.source_dn : "—") + '</td><td class="mono" style="font-size:11px">' + (t.target_up != null ? t.target_up : "—") + "</td>" +
          '<td class="delta ' + (pos ? "pos" : "neg") + '" style="font-size:12px">' + (pos ? "+" : "") + (t.reprog_score != null ? t.reprog_score : "—") + "</td></tr>";
      }).join("");
      out += '<h4 style="font-size:11px;text-transform:uppercase;letter-spacing:1px;color:var(--dim);margin:20px 0 8px">Tahoe-100M single-cell confirmation (A549)</h4>' +
        "<table><thead><tr><th>Intervention</th><th>Type</th><th>AT2 ↓</th><th>Tip ↑</th><th>Reprog score</th></tr></thead><tbody>" + scRows + "</tbody></table>";
    }
    out += '<div class="note">LINCS lacks canonical reprogramming reagents (CHIR99021, RepSox, forskolin), so connectivity recovers shared mechanisms (DNMT, RTK/EGFR, mTOR, HDAC) but the curated row adds organ-established stemness triggers absent from the library.</div>';
    return out + "</div></div>";
  }

  /* ---------- Stage F — PertFormer fate validation ---------- */
  function renderF(hu, mo) {
    var S = window.STATE;
    if (hu.status !== "cached" && mo.status !== "cached") {
      return notComputed("Deep-learning fate validation", hu.note || mo.note);
    }
    function fateCard(sp, payload) {
      if (!payload || payload.status !== "cached" || !payload.cocktails) {
        return '<div class="fatecard"><h4>' + (sp === "human" ? "Human" : "Mouse") +
          ' · AT2 → fetal distal-tip</h4><div style="color:var(--dim);font-size:12px">Not run for ' + esc(sp) + ".</div></div>";
      }
      var c = payload.cocktails, dt = c.distalTF, ok = c.OSKM;
      var sel = sp === S.species;
      var bar = function (label, val, col) {
        return '<div class="fatebar"><div class="lab"><span>' + esc(label) + '</span><span class="mono">' + val.toFixed(3) + "</span></div>" +
          '<div class="track"><div class="fill" style="width:' + Math.round(val * 100) + "%;background:" + col + '"></div></div></div>';
      };
      var dpos = dt.delta >= 0, opos = ok.delta >= 0;
      return '<div class="fatecard" style="' + (sel ? "border-color:var(--acc);box-shadow:0 0 0 1px var(--acc)" : "") + '"><h4>' +
        (sp === "human" ? "Human" : "Mouse") + " · AT2 → fetal distal-tip " + (sel ? '<span class="badge b-impl" style="margin-left:auto">selected</span>' : "") + "</h4>" +
        bar("Reference (unedited AT2)", dt.ref_cos, "#6b7684") +
        bar("OSKM knock-in", ok.ki_cos, "#4aa8ff") +
        bar("Distal-TF knock-in (SOX9/NKX2-1/ETV5/ETV4)", dt.ki_cos, "#7ee0c0") +
        '<div style="display:flex;justify-content:space-between;margin-top:12px;font-size:12px">' +
        '<span style="color:var(--mut)">OSKM Δ <span class="delta ' + (opos ? "pos" : "neg") + '">' + (opos ? "+" : "") + ok.delta.toFixed(3) + "</span></span>" +
        '<span style="color:var(--mut)">Distal-TF Δ <span class="delta ' + (dpos ? "pos" : "neg") + '">' + (dpos ? "+" : "") + dt.delta.toFixed(3) + "</span></span></div></div>";
    }
    var order = S.species === "mouse" ? [["mouse", mo], ["human", hu]] : [["human", hu], ["mouse", mo]];
    var cards = order.map(function (pair) { return fateCard(pair[0], pair[1]); }).join("");
    var panel = (hu.fate && hu.fate.panel ? hu.fate.panel : []).map(function (g) { return '<span class="chip">' + esc(g) + "</span>"; }).join(" ");
    return liveHead("Deep-learning fate validation — PertFormer", "cosine fate-proximity · 21-gene panel · Modal A100") +
      '<p style="color:var(--mut);margin:0 0 14px;font-size:13px">In-silico motif knock-in opens accessible peaks bearing each TF\'s motif (ATAC-only edit); the 3B-parameter DNA+ATAC→expression model predicts the resulting program; fate-proximity Δ measures the move toward the progenitor target.</p>' +
      '<div class="fate">' + cards + "</div>" +
      '<div class="note acc" style="margin-top:16px"><b>Result:</b> in human, the lung-specific distal-TF cocktail moves AT2 ~93% farther toward distal-progenitor fate than OSKM (Δ +0.107 vs +0.055) — the largest fate shift in the project, winning by <b>specificity</b>. Mouse AT2 already sits close to its E17.5 tip, so it reads as a specificity control.</div>' +
      '<h4 style="font-size:11px;text-transform:uppercase;letter-spacing:1px;color:var(--dim);margin:18px 0 8px">Fate-readout gene panel (9 distal + 8 AT2 + 4 OSKM)</h4>' +
      '<div class="chips">' + panel + "</div>" +
      '<div class="note">Neither cocktail reaches a full fate switch (the model\'s somatic→iPSC benchmark hit ~0.75 from ~0.23); distal-TF at 0.66→0.76 is strong partial reprogramming. All predictions are in-silico hypotheses requiring wet-lab validation.</div></div></div>';
  }

  window.STAGES = {
    plannedNotice: plannedNotice,
    A: renderA, B: renderB, C: renderC, D: renderD, E: renderE, F: renderF,
  };
})();
