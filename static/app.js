/* WC 2026 match predictor front-end. Vanilla JS; charts are hand-built SVG. */
"use strict";

const COLORS = { a: "#9085e9", b: "#0d9488", neutral: "#6b7280", muted: "#898781",
                 ink: "#ffffff", ink2: "#c3c2b7", grid: "#2c2c2a" };
const BAND_ORDER = ["F", "AM", "M", "DM", "D", "GK"];   // top of pitch -> keeper
const BAND_NAMES = { GK: "Goalkeeper", D: "Defence", DM: "Def. midfield",
                     M: "Midfield", AM: "Att. midfield", F: "Attack" };

const state = {
  mode: "knockout", venue: "neutral", formations: {},
  sides: { A: null, B: null },     // {team, flag, formation, xi:[{slot,player_id}], players:Map, bestIds:Set}
  picker: null, timer: null,
};

const $ = (sel) => document.querySelector(sel);
const esc = (s) => String(s).replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const eur = (v) => v >= 9.95e6 ? `€${(v / 1e6).toFixed(0)}m`
  : v >= 1e6 ? `€${(v / 1e6).toFixed(1)}m` : `€${Math.round(v / 1e3)}k`;
const pct = (p) => `${(p * 100).toFixed(p >= 0.10 ? 0 : 1)}%`;
const band = (slot) => slot === "GK" ? "GK" : slot.startsWith("DM") ? "DM"
  : slot.startsWith("D") ? "D" : slot.startsWith("AM") ? "AM" : slot.startsWith("M") ? "M" : "F";
const lastName = (n) => { const p = n.split(" "); return p.length > 1 ? p.slice(1).join(" ") : n; };

async function init() {
  const meta = await (await fetch("/api/teams")).json();
  state.formations = meta.formations;
  state.teamsMeta = Object.fromEntries(meta.teams.map((t) => [t.name, t]));
  state.bySlug = Object.fromEntries(meta.teams.map((t) => [t.slug, t.name]));
  $("#results-through").textContent = meta.results_through;
  for (const key of ["A", "B"]) {
    const sel = $(`#team-${key}`);
    sel.innerHTML = meta.teams.map((t) =>
      `<option value="${esc(t.name)}">${t.flag} ${esc(t.name)}</option>`).join("");
    sel.addEventListener("change", () => onTeamChange(key, sel.value));
  }

  // permalink: /england-vs-norway?fa=4-4-2&xa=1.2.3...&mode=group&venue=home_a
  let initA = "England", initB = "Norway";
  const m = location.pathname.match(/^\/([a-z0-9-]+)-vs-([a-z0-9-]+)$/);
  if (m && state.bySlug[m[1]] && state.bySlug[m[2]] && m[1] !== m[2]) {
    initA = state.bySlug[m[1]];
    initB = state.bySlug[m[2]];
  }
  const q = new URLSearchParams(location.search);
  if (["knockout", "group", "friendly"].includes(q.get("mode"))) state.mode = q.get("mode");
  if (["neutral", "home_a", "home_b"].includes(q.get("venue"))) state.venue = q.get("venue");
  $("#mode").value = state.mode;
  $("#venue").value = state.venue;
  $("#team-A").value = initA;
  $("#team-B").value = initB;
  $("#mode").addEventListener("change", (e) => { state.mode = e.target.value; schedulePredict(); });
  $("#venue").addEventListener("change", (e) => { state.venue = e.target.value; schedulePredict(); });
  $("#share").addEventListener("click", sharePermalink);
  await Promise.all([
    loadSide("A", initA, { formation: q.get("fa"), xiIds: q.get("xa") }),
    loadSide("B", initB, { formation: q.get("fb"), xiIds: q.get("xb") }),
  ]);
  schedulePredict();
}

function onTeamChange(key, name) {
  const other = key === "A" ? "B" : "A";
  if (state.sides[other] && state.sides[other].team === name) {   // swap instead of duplicating
    const prev = state.sides[key].team;
    $(`#team-${other}`).value = prev;
    loadSide(other, prev).then(() => loadSide(key, name)).then(schedulePredict);
    return;
  }
  loadSide(key, name).then(schedulePredict);
}

async function loadSide(key, name, override) {
  const d = await (await fetch(`/api/team/${encodeURIComponent(name)}`)).json();
  const side = {
    team: name, flag: d.flag,
    formation: d.default.formation,
    xi: d.default.xi.map((e) => ({ slot: e.slot, player_id: e.player_id })),
    players: new Map(d.players.map((p) => [p.id, p])),
    bestIds: new Set(d.best_xi_ids),
    fetched: d.default.fetched,
    defaultFormation: d.default.formation,
    defaultIds: d.default.xi.map((e) => e.player_id).join("."),
  };
  if (override) applyOverride(side, override);
  state.sides[key] = side;
  renderPanel(key);
}

/* restore formation/XI from permalink params; fall back to default on anything invalid */
function applyOverride(side, override) {
  let slots = side.xi.map((e) => e.slot);
  if (override.formation && state.formations[override.formation]) {
    slots = state.formations[override.formation];
    side.formation = override.formation;
  }
  if (override.xiIds) {
    const ids = override.xiIds.split(".").map(Number);
    const valid = ids.length === 11 && new Set(ids).size === 11 &&
      ids.every((id) => side.players.has(id));
    if (valid) side.xi = slots.map((slot, i) => ({ slot, player_id: ids[i] }));
    else if (side.formation !== side.defaultFormation) side.formation = side.defaultFormation;
  } else if (side.formation !== side.defaultFormation) {
    setFormationSlots(side, slots);   // formation given without ids: refill from default XI
  }
}

function setFormationSlots(side, newSlots) {
  const pool = {};
  for (const e of side.xi) (pool[band(e.slot)] = pool[band(e.slot)] || []).push(e.player_id);
  const xi = newSlots.map((slot) => {
    const b = band(slot);
    if (pool[b] && pool[b].length) return { slot, player_id: pool[b].shift() };
    return { slot, player_id: null };
  });
  const leftovers = Object.values(pool).flat()
    .sort((x, y) => (side.players.get(y).value_eur || 0) - (side.players.get(x).value_eur || 0));
  for (const e of xi) if (e.player_id === null) e.player_id = leftovers.shift();
  side.xi = xi;
}

function formationSlots(side) {
  return side.xi.map((e) => e.slot);
}

function setFormation(key, name) {
  const side = state.sides[key];
  const newSlots = state.formations[name];
  if (!newSlots) return;
  setFormationSlots(side, newSlots);
  side.formation = name;
  renderPanel(key);
  schedulePredict();
}

/* ---------- permalinks ---------- */

function buildPermalink() {
  const params = new URLSearchParams();
  if (state.mode !== "knockout") params.set("mode", state.mode);
  if (state.venue !== "neutral") params.set("venue", state.venue);
  for (const [k, suffix] of [["A", "a"], ["B", "b"]]) {
    const side = state.sides[k];
    const ids = side.xi.map((e) => e.player_id).join(".");
    if (side.formation !== side.defaultFormation) {
      params.set("f" + suffix, side.formation);
      params.set("x" + suffix, ids);
    } else if (ids !== side.defaultIds) {
      params.set("x" + suffix, ids);
    }
  }
  const slugA = state.teamsMeta[state.sides.A.team].slug;
  const slugB = state.teamsMeta[state.sides.B.team].slug;
  const qs = params.toString();
  return `/${slugA}-vs-${slugB}${qs ? "?" + qs : ""}`;
}

function syncUrl() {
  if (!state.sides.A || !state.sides.B) return;
  history.replaceState(null, "", buildPermalink());
  document.title = `${state.sides.A.team} vs ${state.sides.B.team} — Football Analytics`;
}

async function sharePermalink() {
  const url = location.origin + buildPermalink();
  const title = document.title;
  try {
    if (navigator.share) { await navigator.share({ title, url }); return; }
    await navigator.clipboard.writeText(url);
    const btn = $("#share"), old = btn.innerHTML;
    btn.innerHTML = "✓ Link copied";
    setTimeout(() => { btn.innerHTML = old; }, 1600);
  } catch (e) { /* share sheet dismissed */ }
}

function renderPanel(key) {
  const side = state.sides[key];
  const meta = state.teamsMeta[side.team];
  $(`#head-${key}`).innerHTML =
    `<span class="flag">${side.flag}</span><span class="name">${esc(side.team)}</span>` +
    `<span class="chip">Elo ${meta.rating} · #${meta.rank}</span>` +
    `<span class="chip" id="adj-${key}" title="lineup Elo adjustment"></span>`;
  const fsel = $(`#formation-${key}`);
  const names = Object.keys(state.formations);
  if (!names.includes(side.formation)) names.unshift(side.formation);
  fsel.innerHTML = names.map((f) => `<option${f === side.formation ? " selected" : ""}>${f}</option>`).join("");
  fsel.onchange = () => setFormation(key, fsel.value);

  const rows = { };
  side.xi.forEach((e, idx) => (rows[band(e.slot)] = rows[band(e.slot)] || []).push({ ...e, idx }));
  const sideOrd = (s) => s.endsWith("L") ? 0 : s.endsWith("R") ? 2 : 1;
  let html = "";
  for (const b of BAND_ORDER) {
    if (!rows[b]) continue;
    rows[b].sort((x, y) => sideOrd(x.slot) - sideOrd(y.slot));
    html += `<div class="band-row">` + rows[b].map((e) => {
      const p = side.players.get(e.player_id);
      const oop = p.position !== ({ GK: "GK", D: "DF", DM: "MF", M: "MF", AM: "MF", F: "FW" }[b]);
      return `<button class="slot ${p.status}" data-key="${key}" data-idx="${e.idx}" ` +
        `title="${esc(p.name)} · ${p.position} · ${eur(p.value_eur)}">` +
        `<span class="num">${p.shirt_no ?? "–"}</span>` +
        `<span class="nm">${esc(lastName(p.name))}</span>` +
        `<span class="val">${eur(p.value_eur)}</span>` +
        `<span class="pos-tag">${e.slot}${oop ? " · " + p.position : ""}</span></button>`;
    }).join("") + `</div>`;
  }
  $(`#pitch-${key}`).innerHTML = html;
  $(`#pitch-${key}`).querySelectorAll(".slot").forEach((el) =>
    el.addEventListener("click", () => openPicker(el.dataset.key, +el.dataset.idx)));
  const total = side.xi.reduce((s, e) => s + (side.players.get(e.player_id).value_eur || 0), 0);
  $(`#meta-${key}`).textContent =
    `XI market value ${eur(total)} · default from rotowire (${(side.fetched || "").slice(0, 10)})`;
}

function openPicker(key, idx) {
  state.picker = { key, idx };
  const side = state.sides[key];
  const entry = side.xi[idx];
  const cur = side.players.get(entry.player_id);
  const inXI = new Set(side.xi.map((e) => e.player_id));
  const groups = { GK: [], DF: [], MF: [], FW: [] };
  for (const p of side.players.values()) groups[p.position].push(p);
  let html = `<h3>${esc(side.team)} — pick for ${entry.slot} (currently ${esc(cur.name)})</h3>`;
  for (const g of ["GK", "DF", "MF", "FW"]) {
    html += `<div class="group-h">${g}</div>` + groups[g]
      .sort((a, z) => (z.value_eur || 0) - (a.value_eur || 0))
      .map((p) => {
        const sel = inXI.has(p.id);
        const badges =
          (side.bestIds.has(p.id) ? `<span class="badge star">BEST XI</span>` : "") +
          (p.status === "doubtful" ? `<span class="badge doubtful">DOUBT</span>` : "") +
          (p.status === "out" ? `<span class="badge out">OUT</span>` : "");
        return `<div class="prow${sel ? " selected" : ""}" data-id="${p.id}">` +
          `<span class="num">${p.shirt_no ?? ""}</span>` +
          `<span class="nm">${esc(p.name)} ${badges}${sel ? " <span class='badge'>IN XI</span>" : ""}</span>` +
          `<span class="club">${esc(p.club)} · ${p.caps} caps</span>` +
          `<span class="val">${eur(p.value_eur)}</span></div>`;
      }).join("");
  }
  $("#picker-body").innerHTML = html;
  $("#overlay").style.display = "flex";
  $("#picker-body").querySelectorAll(".prow:not(.selected)").forEach((el) =>
    el.addEventListener("click", () => choosePlayer(+el.dataset.id)));
}

function choosePlayer(pid) {
  const { key, idx } = state.picker;
  const side = state.sides[key];
  const already = side.xi.findIndex((e) => e.player_id === pid);
  if (already >= 0) side.xi[already].player_id = side.xi[idx].player_id;   // swap slots
  side.xi[idx].player_id = pid;
  closePicker();
  renderPanel(key);
  schedulePredict();
}

function closePicker() { $("#overlay").style.display = "none"; state.picker = null; }

function schedulePredict() {
  syncUrl();
  clearTimeout(state.timer);
  $("#spin").textContent = "computing…";
  state.timer = setTimeout(runPredict, 300);
}

async function runPredict() {
  const body = {
    mode: state.mode, venue: state.venue,
    sides: ["A", "B"].map((k) => ({
      team: state.sides[k].team,
      xi: state.sides[k].xi,
    })),
  };
  const resp = await fetch("/api/predict", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const rep = await resp.json();
  $("#spin").textContent = "";
  if (rep.error) { $("#spin").textContent = `⚠ ${rep.error}`; return; }
  renderReport(rep);
}

/* ---------- rendering the report ---------- */

function renderReport(rep) {
  $("#results").style.display = "block";
  const [ta, tb] = [state.sides.A.team, state.sides.B.team];
  const pa = rep.p_advance[ta], pb = rep.p_advance[tb];
  for (const [k, t] of [["A", ta], ["B", tb]]) {
    const adj = rep.adjustments[t];
    const el = $(`#adj-${k}`);
    el.textContent = `lineup ${adj >= -0.5 ? "±0" : adj.toFixed(0)} Elo`;
    el.className = "chip" + (adj < -0.5 ? " adj-neg" : "");
  }
  $("#hero").innerHTML =
    `<div class="side a"><div>${state.sides.A.flag} ${esc(ta)}</div><div class="pctnum">${pct(pa)}</div></div>` +
    `<div class="side b"><div>${esc(tb)} ${state.sides.B.flag}</div><div class="pctnum">${pct(pb)}</div></div>`;
  $("#hero-bar").innerHTML = splitBar(pa, pb);
  $("#hero-note").textContent = rep.mode === "knockout"
    ? "Chance of advancing — draws resolved via extra time and penalties."
    : "Match result probabilities.";
  const [w, d, l] = rep.sections.find((s) => s.id === "verdict").data.wdl;
  $("#wdl").innerHTML = stackedWDL(w, d, l, ta, tb);
  $("#scorelines").innerHTML = scorelinesChart(rep.prediction.scorelines, ta, tb);

  const la = rep.sections.find((s) => s.id === `lineup_${ta}`).data.per_band;
  const lb = rep.sections.find((s) => s.id === `lineup_${tb}`).data.per_band;
  $("#bands-legend").innerHTML =
    `<span><span class="dot" style="background:${COLORS.a}"></span>${esc(ta)}</span>` +
    `<span><span class="dot" style="background:${COLORS.b}"></span>${esc(tb)}</span>`;
  $("#bands").innerHTML = bandsChart(la, lb);

  renderWarnings(rep, ta, "A");
  renderWarnings(rep, tb, "B");
  $("#analysis").innerHTML = rep.sections.map((s) => sectionCard(s, ta, tb)).join("");
  attachTooltips();
}

function renderWarnings(rep, team, key) {
  const sec = rep.sections.find((s) => s.id === `lineup_${team}`);
  const w = sec ? sec.data.warnings : [];
  $(`#warn-${key}`).innerHTML = w.map((x) =>
    `<div class="${/OUT|massive/.test(x) ? "crit" : ""}">⚠ ${esc(x)}</div>`).join("");
}

/* ---------- charts (SVG strings) ---------- */

function splitBar(pa, pb) {
  const W = 600, H = 18, R = 4, gap = 2;
  const wa = Math.max(8, (W - gap) * pa), wb = W - gap - wa;
  return `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="advance probability split">
    <path d="M${R},0 h${wa - R} v${H} h-${wa - R} a${R},${R} 0 0 1 -${R},-${R} v-${H - 2 * R} a${R},${R} 0 0 1 ${R},-${R} z" fill="${COLORS.a}"/>
    <path d="M${wa + gap},0 h${wb - R} a${R},${R} 0 0 1 ${R},${R} v${H - 2 * R} a${R},${R} 0 0 1 -${R},${R} h-${wb - R} z" fill="${COLORS.b}"/>
  </svg>`;
}

function stackedWDL(w, d, l, ta, tb) {
  const W = 600, H = 46, bh = 18, R = 4, gap = 2;
  const total = w + d + l;
  const ww = (W - 2 * gap) * (w / total), wd = (W - 2 * gap) * (d / total), wl = (W - 2 * gap) * (l / total);
  const seg = (x, wid, color, first, last) => {
    const r = first || last ? R : 0;
    return `<rect x="${x}" y="0" width="${wid}" height="${bh}" rx="${r}" fill="${color}"
      data-tip="${first ? `${ta} win ${pct(w / total)}` : last ? `${tb} win ${pct(l / total)}` : `Draw ${pct(d / total)}`}"/>`;
  };
  const lbl = (x, text, color, anchor = "start") =>
    `<text x="${x}" y="${H - 6}" fill="${color}" font-size="12" text-anchor="${anchor}">${text}</text>`;
  return `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="90 minute win draw loss">
    ${seg(0, ww, COLORS.a, true, false)}
    ${seg(ww + gap, wd, COLORS.neutral, false, false)}
    ${seg(ww + gap + wd + gap, wl, COLORS.b, false, true)}
    ${lbl(0, `${esc(ta)} ${pct(w)}`, COLORS.ink2)}
    ${lbl(W / 2, `draw ${pct(d)}`, COLORS.muted, "middle")}
    ${lbl(W, `${esc(tb)} ${pct(l)}`, COLORS.ink2, "end")}
  </svg>`;
}

function scorelinesChart(scorelines, ta, tb) {
  const W = 560, rowH = 26, bh = 16, left = 44, right = 52;
  const H = scorelines.length * rowH + 6;
  const max = scorelines[0].prob;
  const rows = scorelines.map((s, i) => {
    const y = i * rowH + 4;
    const w = Math.max(3, (W - left - right) * (s.prob / max));
    return `<text x="${left - 8}" y="${y + bh - 4}" fill="${COLORS.ink2}" font-size="12" text-anchor="end" style="font-variant-numeric:tabular-nums">${s.score}</text>
      <rect x="${left}" y="${y}" width="${w}" height="${bh}" rx="4" fill="#9085e9" data-tip="${ta} ${s.score} ${tb} · ${pct(s.prob)}"/>
      <text x="${left + w + 6}" y="${y + bh - 4}" fill="${COLORS.muted}" font-size="11" style="font-variant-numeric:tabular-nums">${pct(s.prob)}</text>`;
  }).join("");
  return `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="most likely scorelines">
    <line x1="${left}" y1="0" x2="${left}" y2="${H}" stroke="${COLORS.grid}"/>${rows}</svg>`;
}

function bandsChart(pa, pb) {
  const bands = ["GK", "D", "DM", "M", "AM", "F"].filter((b) => (pa[b] || 0) + (pb[b] || 0) > 0);
  const W = 560, groupH = 46, bh = 14, left = 96, right = 56, gap = 2;
  const H = bands.length * groupH + 4;
  const max = Math.max(...bands.flatMap((b) => [pa[b] || 0, pb[b] || 0]));
  const bar = (y, v, color, tipName, b) => {
    const w = Math.max(2, (W - left - right) * (v / max));
    return `<rect x="${left}" y="${y}" width="${w}" height="${bh}" rx="4" fill="${color}"
        data-tip="${tipName} ${BAND_NAMES[b]} · ${eur(v)}"/>
      <text x="${left + w + 6}" y="${y + bh - 3}" fill="${COLORS.muted}" font-size="11" style="font-variant-numeric:tabular-nums">${eur(v)}</text>`;
  };
  const rows = bands.map((b, i) => {
    const y = i * groupH + 4;
    return `<text x="${left - 8}" y="${y + bh + 2}" fill="${COLORS.ink2}" font-size="12" text-anchor="end">${BAND_NAMES[b]}</text>` +
      bar(y, pa[b] || 0, COLORS.a, state.sides.A.team, b) +
      bar(y + bh + gap + 2, pb[b] || 0, COLORS.b, state.sides.B.team, b);
  }).join("");
  return `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="lineup value by pitch band">
    <line x1="${left}" y1="0" x2="${left}" y2="${H}" stroke="${COLORS.grid}"/>${rows}</svg>`;
}

/* ---------- analysis sections ---------- */

function sectionCard(s, ta, tb) {
  let extra = "";
  if (s.id === "form") {
    extra = `<div class="chart-row">` + [ta, tb].map((t) => {
      const d = s.data[t];
      return `<div><table class="mini"><tr><th>${esc(t)} — last 5</th><th></th><th></th></tr>` +
        d.matches.slice(0, 5).map((m) =>
          `<tr><td>${esc(m.opponent)}</td><td>${m.score}</td><td class="res-${m.result}">${m.result}</td></tr>`).join("") +
        `</table></div>`;
    }).join("") + `</div>`;
  } else if (s.id === "h2h" && s.data.recent && s.data.recent.length) {
    extra = `<table class="mini">` + s.data.recent.map((m) =>
      `<tr><td>${m.date}</td><td>${esc(m.fixture)}</td><td>${esc(m.tournament)}</td></tr>`).join("") + `</table>`;
  } else if (s.id.startsWith("lineup_") && s.data.absentees.length) {
    extra = `<table class="mini"><tr><th>Not selected (best-XI value)</th><th>Value</th><th>Status</th></tr>` +
      s.data.absentees.map((p) =>
        `<tr><td>${esc(p.name)}</td><td>${eur(p.value || 0)}</td><td>${p.status === "fit" ? "fit"
          : `<span class="badge ${p.status}">${p.status.toUpperCase()}</span>`}</td></tr>`).join("") + `</table>`;
  } else if (s.id === "sensitivity") {
    extra = `<div class="chart-row">` + [ta, tb].map((t) => {
      const swaps = s.data[t] || [];
      if (!swaps.length) return `<div></div>`;
      return `<div><table class="mini"><tr><th>${esc(t)}</th><th>for</th><th>Δ</th></tr>` +
        swaps.map((x) => `<tr><td>${esc(x.in)}</td><td>${esc(x.out)}</td><td>+${(x.gain * 100).toFixed(1)}pts</td></tr>`).join("") +
        `</table></div>`;
    }).join("") + `</div>`;
  }
  return `<div class="card"><h3>${esc(s.title)}</h3><p>${esc(s.prose)}</p>${extra}</div>`;
}

/* ---------- tooltip ---------- */

function attachTooltips() {
  const tip = $("#tooltip");
  document.querySelectorAll("[data-tip]").forEach((el) => {
    el.addEventListener("mousemove", (ev) => {
      tip.style.display = "block";
      tip.textContent = el.dataset.tip;
      tip.style.left = `${ev.clientX + 14}px`;
      tip.style.top = `${ev.clientY + 10}px`;
    });
    el.addEventListener("mouseleave", () => { tip.style.display = "none"; });
  });
}

$("#overlay").addEventListener("click", (e) => { if (e.target.id === "overlay") closePicker(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closePicker(); });
init();
