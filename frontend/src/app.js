/* app.js — boot + wiring. Hydrates the selection panel and ribbon from the API
 * (GET /organs, /layers, /states, /runs, /stages), renders the per-stage panel
 * from GET /stage/{X}, and offers an explicit "Request computation" action for
 * stages that are not computed. The action submits a background job and polls
 * GET /jobs/{id}; nothing is displayed until a real result exists.
 */
(function () {
  "use strict";
  var S = window.STATE, el = window.el, esc = window.esc, API = window.API;

  /* ---------- selection panel ---------- */
  function initOrganSelect() {
    var os = el("selOrgan"); os.innerHTML = "";
    S.organs.forEach(function (o) {
      var opt = document.createElement("option");
      opt.value = o.id;
      opt.textContent = o.name + (o.status !== "implemented" ? "  (planned)" : "");
      os.appendChild(opt);
    });
    os.value = S.organ;
  }

  function rebuildLayer() {
    return API.getLayers(S.organ).then(function (layers) {
      S.layers = layers;
      var ls = el("selLayer"); ls.innerHTML = "";
      var implemented = isImplemented(S.organ);
      layers.forEach(function (l) {
        var opt = document.createElement("option");
        opt.value = l.id;
        var n = l.atlas && l.atlas.cells ? " (" + Math.floor(l.atlas.cells / 1000) + "k cells)" : "";
        opt.textContent = l.name + (implemented ? n : "");
        ls.appendChild(opt);
      });
      if (!layers.some(function (l) { return l.id === S.layer; })) S.layer = layers[0] ? layers[0].id : S.layer;
      ls.value = S.layer;
      ls.disabled = !implemented;
    });
  }

  function rebuildStates() {
    return API.getStates(S.organ, S.layer).then(function (res) {
      S.states = res.states || {};
      var names = Object.keys(S.states);
      var mature = names.filter(function (k) { return S.states[k].role === "mature"; });
      var prog = names.filter(function (k) { return S.states[k].role === "progenitor"; });
      var srcSel = el("selSource"), tgtSel = el("selTarget");
      var implemented = isImplemented(S.organ);
      srcSel.innerHTML = ""; tgtSel.innerHTML = "";

      var srcList = mature.concat(names.filter(function (s) { return mature.indexOf(s) < 0; }));
      var tgtList = prog.concat(names.filter(function (s) { return prog.indexOf(s) < 0; }));
      srcList.forEach(function (s) { var o = document.createElement("option"); o.value = s; o.textContent = s; srcSel.appendChild(o); });
      tgtList.forEach(function (s) {
        var o = document.createElement("option"); o.value = s;
        o.textContent = s + (S.states[s].role === "progenitor" ? "  ◆" : ""); tgtSel.appendChild(o);
      });

      var d = S.layerDefaults[S.layer] || {};
      S.source = (d.source && srcList.indexOf(d.source) >= 0) ? d.source : (srcList[0] || null);
      S.target = (d.target && tgtList.indexOf(d.target) >= 0) ? d.target : (prog[0] || tgtList[0] || null);
      srcSel.value = S.source || ""; tgtSel.value = S.target || "";
      srcSel.disabled = !implemented; tgtSel.disabled = !implemented;
      renderTransitionBox();
    });
  }

  function isImplemented(organId) {
    return (S.organs || []).some(function (o) { return o.id === organId && o.status === "implemented"; });
  }

  function renderSpecies() {
    document.querySelectorAll("#segSpecies button").forEach(function (b) {
      b.classList.toggle("on", b.dataset.v === S.species);
    });
  }

  function renderTransitionBox() {
    var box = el("transBox");
    var srole = S.states[S.source] ? S.states[S.source].role : "?";
    var trole = S.states[S.target] ? S.states[S.target].role : "?";
    box.innerHTML =
      '<div class="tb-lab">Source · adult / mature (' + esc(srole) + ")</div>" +
      '<div class="tb-state">' + esc(S.source || "—") + "</div>" +
      '<div class="arrow">↓ reverse ↓</div>' +
      '<div class="tb-lab">Target · embryonic progenitor (' + esc(trole) + ")</div>" +
      '<div class="tb-state">' + esc(S.target || "—") + " " + (trole === "progenitor" ? "◆" : "") + "</div>";
  }

  /* ---------- ribbon (grays un-run stages from the run index) ---------- */
  function renderRibbon() {
    var r = el("ribbon"); r.innerHTML = "";
    var stages = (S.meta && S.meta.stages) || [];
    var runStages = (S.run && S.run.stages) || {};
    stages.forEach(function (st, i) {
      var status = runStages[st.id] || "cached";
      var node = document.createElement("div");
      node.className = "node" + (st.id === S.stage ? " on" : "") + (status === "not_computed" ? " muted" : "");
      node.onclick = function () { S.stage = st.id; renderRibbon(); renderStage(); };
      var tag = status === "running" ? '<span class="rstat run">running…</span>'
              : status === "not_computed" ? '<span class="rstat no">not run</span>'
              : '<span class="rstat ok">ready</span>';
      node.innerHTML = '<div class="inner"><div class="stg">STAGE ' + st.id + "</div>" +
        '<div class="tt">' + esc(st.title) + "</div>" +
        '<div class="ss">' + esc(st.short) + "</div>" + tag + "</div>";
      r.appendChild(node);
      if (i < stages.length - 1) {
        var c = document.createElement("div"); c.className = "node cn"; c.style.flex = "0 0 22px";
        c.innerHTML = "→"; r.appendChild(c);
      }
    });
  }

  /* ---------- stage rendering ---------- */
  function stageObj(id) { return ((S.meta && S.meta.stages) || []).filter(function (s) { return s.id === id; })[0]; }

  function renderStageMeta() {
    var st = stageObj(S.stage); if (!st) return;
    el("stageMeta").innerHTML =
      '<div class="h2"><span class="stagenum">STAGE ' + st.id + "</span>" + esc(st.title) +
      '<span class="badge ' + (st.status === "implemented" ? "b-impl" : "b-plan") + '">' + esc(st.status) + "</span></div>" +
      '<div class="goal">' + esc(st.goal) + "</div>" +
      '<div class="cols">' +
      '<div class="io meth card"><div class="cb"><h4>Methods & tools</h4><ul>' + st.methods.map(function (x) { return "<li>" + esc(x) + "</li>"; }).join("") + "</ul></div></div>" +
      '<div><div class="io card" style="margin-bottom:12px"><div class="cb"><h4>Inputs</h4><ul>' + st.inputs.map(function (x) { return "<li>" + esc(x) + "</li>"; }).join("") + "</ul></div></div>" +
      '<div class="io out card"><div class="cb"><h4>Outputs</h4><ul>' + st.outputs.map(function (x) { return "<li>" + esc(x) + "</li>"; }).join("") + "</ul></div></div></div></div>" +
      '<div class="meta-row"><div class="m"><b>Source session:</b> ' + esc(st.session) + "</div><div class=\"m\"><b>Compute:</b> " + esc(st.compute) + "</div></div>";
  }

  /* ---------- explicit compute action (live backend only) ---------- */
  function runPanelHTML(payload) {
    var live = API.mode === "live";
    var reqs = (payload.requires || []).map(function (r) { return "<li>" + esc(r) + "</li>"; }).join("");
    return '<div class="dpanel run-panel"><div class="dh"><h3 style="font-size:13px">Compute this stage</h3>' +
      '<span class="tag">explicit action · runs as a background job</span></div><div class="db">' +
      '<p style="color:var(--mut);font-size:12.5px;margin:0 0 10px">A real run is attempted for this exact combination. Nothing is shown until a real result exists.</p>' +
      (reqs ? '<div class="reqhead">Requirements not met here</div><ul class="reqlist">' + reqs + "</ul>" : "") +
      '<div class="runrow"><button class="runbtn" id="runBtn"' + (live ? "" : " disabled") + ">Request computation</button>" +
      '<span id="runStatus" class="runstatus">' +
      (live ? "" : "Needs the live backend — start it with python3 -m backend.app") + "</span></div>" +
      "</div></div>";
  }

  function pollJob(jobId, status) {
    return new Promise(function (resolve, reject) {
      var tries = 0;
      (function tick() {
        API.getJob(jobId).then(function (job) {
          if (job.status === "unknown") return reject(new Error(job.error || "backend unreachable"));
          if (status) status.textContent = job.status + (job.progress ? " · " + job.progress : "");
          if (job.status === "done" || job.status === "failed") return resolve(job);
          if (++tries > 240) return reject(new Error("timed out waiting for job " + jobId));
          setTimeout(tick, 1000);
        }, reject);
      })();
    });
  }

  function startRun(stage) {
    var btn = el("runBtn"), status = el("runStatus");
    var p = window.params();
    var body = { organ: p.organ, layer: p.layer, source: p.source, target: p.target, species: p.species };
    btn.disabled = true;
    status.textContent = "submitting…";
    API.runStage(stage, body)
      .then(function (res) { return pollJob(res.job_id, status); })
      .then(function (job) {
        if (job.status === "done") { status.textContent = "done — refreshing"; return refresh(); }
        status.textContent = "not computed: " + (job.error || "the job failed");
        btn.disabled = false;
      })
      .catch(function (e) {
        status.textContent = "error: " + e.message;
        btn.disabled = false;
      });
  }

  function bindRun(stage) {
    var btn = el("runBtn");
    if (btn && !btn.disabled) btn.onclick = function () { startRun(stage); };
  }

  var renderSeq = 0;
  function renderStage() {
    renderStageMeta();
    var d = el("stageData");
    if (!isImplemented(S.organ)) { d.innerHTML = window.STAGES.plannedNotice(S.organ); return; }
    // Capture the stage + a sequence token so a slow in-flight fetch can't render
    // its (now-stale) payload after the user has switched stage or selection.
    var seq = ++renderSeq;
    var stage = S.stage;
    var p = window.params();
    d.innerHTML = '<div class="dpanel"><div class="db" style="color:var(--dim)">Loading ' + stage + " …</div></div>";

    var apply = function (html, payload) {
      if (seq !== renderSeq) return;
      d.innerHTML = html;
      if (payload && payload.status === "not_computed" && stage !== "A") {
        d.insertAdjacentHTML("beforeend", runPanelHTML(payload));
        bindRun(stage);
      }
    };

    if (stage === "F") {
      Promise.all([
        API.getStage("F", Object.assign({}, p, { species: "human" })),
        API.getStage("F", Object.assign({}, p, { species: "mouse" })),
      ]).then(function (both) {
        var selected = S.species === "mouse" ? both[1] : both[0];
        apply(window.STAGES.F(both[0], both[1]), selected);
      });
    } else {
      API.getStage(stage, p).then(function (payload) { apply(window.STAGES[stage](payload), payload); });
    }
  }

  /* ---------- refresh run index (ribbon) + stage ---------- */
  function refresh() {
    return API.getRuns(window.params()).then(function (run) {
      S.run = run; renderRibbon(); renderStage();
    });
  }

  /* ---------- provenance modal ---------- */
  function openProvenance() {
    var modal = el("provModal");
    API.getProvenance().then(function (prov) {
      var rows = (prov.stages || []).map(function (s) {
        return "<tr><td>" + esc(s.stage) + "</td><td>" + esc(s.session) + '</td><td class="mono" style="font-size:11px">' + s.artifacts.map(esc).join(" · ") + "</td></tr>";
      }).join("");
      el("provBody").innerHTML =
        '<p style="color:var(--mut);font-size:13px">' + esc(prov.statement) + "</p>" +
        '<table style="margin-top:10px"><thead><tr><th>Stage</th><th>Source session</th><th>Key artifacts</th></tr></thead><tbody>' + rows + "</tbody></table>";
      modal.classList.remove("hidden");
    });
  }

  /* ---------- live/offline badge ---------- */
  function setModeBadge(mode) {
    var b = el("modeBadge"); if (!b) return;
    if (mode === "offline") { b.textContent = "offline (snapshot)"; b.className = "modebadge off"; }
    else { b.textContent = "live backend"; b.className = "modebadge live"; }
  }

  /* ---------- wiring ---------- */
  function bind() {
    el("selOrgan").addEventListener("change", function (e) {
      S.organ = e.target.value;
      rebuildLayer().then(rebuildStates).then(refresh);
    });
    el("selLayer").addEventListener("change", function (e) {
      S.layer = e.target.value; rebuildStates().then(refresh);
    });
    el("selSource").addEventListener("change", function (e) { S.source = e.target.value; renderTransitionBox(); refresh(); });
    el("selTarget").addEventListener("change", function (e) { S.target = e.target.value; renderTransitionBox(); refresh(); });
    document.querySelectorAll("#segSpecies button").forEach(function (b) {
      b.addEventListener("click", function () { S.species = b.dataset.v; renderSpecies(); refresh(); });
    });
    el("provbtn").addEventListener("click", openProvenance);
    el("provClose").addEventListener("click", function () { el("provModal").classList.add("hidden"); });
    el("provModal").addEventListener("click", function (e) { if (e.target === this) this.classList.add("hidden"); });
  }

  function boot() {
    API.onmodechange = setModeBadge;
    API.getMeta().then(function (meta) {
      S.meta = meta;
      S.organs = meta.organs || [];
      S.layerDefaults = meta.layer_defaults || {};
      initOrganSelect();
      renderSpecies();
      bind();
      return rebuildLayer().then(rebuildStates).then(refresh);
    });
  }

  document.addEventListener("DOMContentLoaded", boot);
})();
