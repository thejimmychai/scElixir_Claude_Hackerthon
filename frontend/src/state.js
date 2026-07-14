/* state.js — the selection store (organ / layer / source / target / species /
 * stage) plus tiny shared helpers. Kept as a plain global so the classic-script
 * modules (api.js, stages.js, app.js) share it without a build step. */
(function () {
  "use strict";

  window.STATE = {
    organ: "lung",
    layer: "epithelial",
    source: null,
    target: null,
    species: "human",
    stage: "A",
    // hydrated caches (filled by app.js on boot / selection change)
    meta: null,
    organs: [],
    layers: [],
    states: {},        // { name: {role, master_tfs} } for the current layer
    layerDefaults: {},
    run: null,         // latest run-index payload
  };

  window.el = function (id) { return document.getElementById(id); };

  window.esc = function (s) {
    return (s == null ? "" : String(s)).replace(/[&<>]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c];
    });
  };

  window.params = function () {
    var S = window.STATE;
    return { organ: S.organ, layer: S.layer, source: S.source, target: S.target, species: S.species };
  };
})();
