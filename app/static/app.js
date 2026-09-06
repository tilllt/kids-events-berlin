/* Kinder-Events Berlin — Karte + Filter, Vanilla JS.
 * Daten: /api/events.geojson (gefiltert), Optionen: /api/meta. */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => Array.from(el.querySelectorAll(s));

const state = {
  bezirk: [], altersband: [], uhrzeit: [],
  kostenlos: false, von: "", bis: "", zeitraum: "heute", meta: null,
};

function fmtDate(s) {
  if (!s) return "";
  const [d, t] = s.split("T");
  const [y, m, dd] = d.split("-");
  return t ? `${dd}.${m}.${y}, ${t.slice(0, 5)}` : `${dd}.${m}.${y}`;
}
function fmtZeit(e) {
  const start = fmtDate(e.start_local).replace(",", "");
  if (e.ganztags) return `${start}, ganztägig`;
  const end = e.ende_local ? fmtDate(e.ende_local).split(",")[1].trim() : "";
  return `${start}${end ? " – " + end : ""} Uhr`;
}
function alterLabel(e) {
  if (e.alters_familie) return "Familie";
  if (e.altersband_min != null && e.altersband_max != null) return `${e.altersband_min}–${e.altersband_max} J.`;
  if (e.altersband_min != null) return `ab ${e.altersband_min}`;
  if (e.altersband_max != null) return `bis ${e.altersband_max} J.`;
  return null;
}

/* ---------- Zeitraum-Schnellwahl (Europe/Berlin) ---------- */
function berlinDateStr(offsetDays) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Europe/Berlin", year: "numeric", month: "2-digit", day: "2-digit",
  }).formatToParts(new Date());
  const m = {};
  parts.forEach((p) => (m[p.type] = p.value));
  const d = new Date(Date.UTC(+m.year, +m.month - 1, +m.day) + (offsetDays || 0) * 86400000);
  return d.toISOString().slice(0, 10);
}
const ZEITRAUM_OPTIONEN = [
  { id: "heute", label: "Heute", von: () => berlinDateStr(0), bis: () => berlinDateStr(0) },
  { id: "morgen", label: "Morgen", von: () => berlinDateStr(1), bis: () => berlinDateStr(1) },
  { id: "diese-woche", label: "Diese Woche", von: () => berlinDateStr(0), bis: () => berlinDateStr(6) },
  { id: "naechste-woche", label: "Nächste Woche", von: () => berlinDateStr(7), bis: () => berlinDateStr(13) },
];
const ZEITRAUM_IDS = ZEITRAUM_OPTIONEN.map((o) => o.id);

function zeitChip(opt) {
  const b = document.createElement("button");
  b.type = "button";
  b.textContent = opt.label;
  b.dataset.id = opt.id;
  b.addEventListener("click", () => {
    state.zeitraum = opt.id;
    syncZeitraumUI();
    apply();
  });
  return b;
}

/* Aktive Schnellwahl: berechnete Grenzen setzen + Von/Bis-Felder sperren.
 * Benutzerdefiniert: Felder frei, Werte aus state. */
function syncZeitraumUI() {
  const auto = ZEITRAUM_IDS.includes(state.zeitraum);
  $$("#zeitraum-list button").forEach((b) => b.classList.toggle("on", b.dataset.id === state.zeitraum));
  $("#von").disabled = auto;
  $("#bis").disabled = auto;
  if (auto) {
    const o = ZEITRAUM_OPTIONEN.find((x) => x.id === state.zeitraum);
    state.von = o.von();
    state.bis = o.bis();
  }
  $("#von").value = state.von;
  $("#bis").value = state.bis;
}

/* ---------- Filter-Optionen aus /api/meta ---------- */
async function loadMeta() {
  const r = await fetch("/api/meta");
  if (!r.ok) throw new Error(`meta ${r.status}`);
  state.meta = await r.json();
  const bz = $("#bezirk-list");
  state.meta.bezirke.forEach((o) => {
    const [slug, label] = Object.entries(o)[0];
    const l = document.createElement("label");
    l.innerHTML = `<input type="checkbox" value="${slug}" /> ${label}`;
    l.querySelector("input").addEventListener("change", (ev) => {
      const set = new Set(state.bezirk);
      ev.target.checked ? set.add(slug) : set.delete(slug);
      state.bezirk = [...set];
      apply();
    });
    bz.appendChild(l);
  });
  const al = $("#alter-list");
  state.meta.altersbaender.forEach((o) => al.appendChild(chip(o.id, o.label, "altersband")));
  const uz = $("#uhrzeit-list");
  state.meta.uhrzeiten.forEach((o) => uz.appendChild(chip(o.id, o.label, "uhrzeit")));
  const zl = $("#zeitraum-list");
  ZEITRAUM_OPTIONEN.forEach((o) => zl.appendChild(zeitChip(o)));
  $("#kostenlos").addEventListener("change", (ev) => { state.kostenlos = ev.target.checked; apply(); });
  $("#von").addEventListener("change", (ev) => { state.von = ev.target.value; state.zeitraum = "benutzerdefiniert"; syncZeitraumUI(); apply(); });
  $("#bis").addEventListener("change", (ev) => { state.bis = ev.target.value; state.zeitraum = "benutzerdefiniert"; syncZeitraumUI(); apply(); });
  $("#resetbtn").addEventListener("click", resetFilters);
  $("#retrybtn").addEventListener("click", () => { $("#errorbar").classList.add("hidden"); load(); });
  const note = $("#meta-note");
  const nq = (state.meta.quellen || []).length;
  note.textContent = `${nq} aktive Quellen · ${state.meta.events_gesamt} Events im Bestand · LLM-freie Auswertung`;
}

function chip(id, label, key) {
  const b = document.createElement("button");
  b.type = "button";
  b.textContent = label;
  b.dataset.id = id;
  b.addEventListener("click", () => {
    const set = new Set(state[key]);
    set.has(id) ? set.delete(id) : set.add(id);
    state[key] = [...set];
    b.classList.toggle("on", set.has(id));
    apply();
  });
  return b;
}

function resetFilters() {
  state.bezirk = []; state.altersband = []; state.uhrzeit = [];
  state.kostenlos = false; state.von = ""; state.bis = ""; state.zeitraum = "heute";
  $$("#bezirk-list input").forEach((i) => (i.checked = false));
  $$(".chips button").forEach((b) => b.classList.remove("on"));
  $("#kostenlos").checked = false;
  syncZeitraumUI();
  apply();
}

function queryParams() {
  const p = new URLSearchParams();
  if (state.bezirk.length) p.set("bezirk", state.bezirk.join(","));
  if (state.altersband.length) p.set("altersband", state.altersband.join(","));
  if (state.uhrzeit.length) p.set("uhrzeit", state.uhrzeit.join(","));
  if (state.kostenlos) p.set("kostenlos", "true");
  if (ZEITRAUM_IDS.includes(state.zeitraum)) p.set("zeitraum", state.zeitraum);
  if (state.von) p.set("von", state.von);
  if (state.bis) p.set("bis", state.bis);
  const qs = p.toString();
  history.replaceState(null, "", qs ? "?" + qs : location.pathname);
  return qs;
}

function readUrl() {
  const p = new URLSearchParams(location.search);
  state.bezirk = (p.get("bezirk") || "").split(",").filter(Boolean);
  state.altersband = (p.get("altersband") || "").split(",").filter(Boolean);
  state.uhrzeit = (p.get("uhrzeit") || "").split(",").filter(Boolean);
  state.kostenlos = p.get("kostenlos") === "true";
  const zr = p.get("zeitraum");
  state.zeitraum = ZEITRAUM_IDS.includes(zr) ? zr : (p.get("von") || p.get("bis") ? "benutzerdefiniert" : "heute");
  state.von = p.get("von") || ""; state.bis = p.get("bis") || "";
}

/* ---------- Karte ---------- */
const map = L.map("map", { zoomControl: true }).setView([52.52, 13.405], 11);
L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 18,
  attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
}).addTo(map);
let cluster = null;
let markers = [];

function clearMarkers() {
  if (cluster) { map.removeLayer(cluster); cluster = null; }
  markers.forEach((m) => m.remove());
  markers = [];
}

function popupHtml(e) {
  const badges = [];
  if (e.kostenlos) badges.push('<span class="badge free">kostenlos</span>');
  if (e.alters_familie || e.altersband_min != null || e.altersband_max != null)
    badges.push(`<span class="badge">${alterLabel(e)}</span>`);
  badges.push(`<span class="badge src">${escapeHtml(e.quelle)}</span>`);
  return `<strong>${escapeHtml(e.titel)}</strong><br/>
    <span>${fmtZeit(e)}</span><br/>
    <span>${escapeHtml(e.ort || "")}${e.bezirk_label && e.bezirk_label !== "Ohne Angabe" ? " · " + e.bezirk_label : ""}</span><br/>
    ${badges.join("")}<br/>
    <button type="button" class="mapbtn popup-detail-btn" id="popup-detail" data-ev-id="${escapeHtml(e.id)}">Details anzeigen</button>
    <br/><a href="${escapeHtml(e.source_url)}" target="_blank" rel="noopener noreferrer">Zur Quelle ↗</a>`;
}

function escapeHtml(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function renderGeo(gj) {
  clearMarkers();
  const withPos = gj.features.length;
  const useCluster = withPos > 40 && typeof L.markerClusterGroup === "function";
  cluster = useCluster ? L.markerClusterGroup({ chunkedLoading: true }) : null;
  gj.features.forEach((f) => {
    const p = f.properties;
    const m = L.marker([f.geometry.coordinates[1], f.geometry.coordinates[0]]);
    m.bindPopup(popupHtml(p));
    m._ev = p;
    if (cluster) cluster.addLayer(m); else m.addTo(map);
    markers.push(m);
  });
  if (cluster) map.addLayer(cluster);
  if (withPos > 0 && markers.length === withPos && !useCluster) {
    const b = L.latLngBounds(markers.map((m) => m.getLatLng()));
    if (b.isValid()) map.fitBounds(b.pad(0.15), { maxZoom: 13 });
  } else if (withPos === 1 && markers.length === 1) {
    map.setView(markers[0].getLatLng(), 14);
  }
}

/* ---------- Detail-Ansicht ---------- */
function openDetail(e) {
  const rows = [];
  rows.push(`<div class="detail__row"><span class="k">Wann</span>${fmtZeit(e)}</div>`);
  const wo = [escapeHtml(e.ort || ""), e.bezirk_label && e.bezirk_label !== "Ohne Angabe" ? e.bezirk_label : ""]
    .filter(Boolean).join(" · ");
  if (wo) rows.push(`<div class="detail__row"><span class="k">Wo</span>${wo}</div>`);
  if (e.adresse) rows.push(`<div class="detail__row"><span class="k">Adresse</span>${escapeHtml(e.adresse)}</div>`);
  const extras = [];
  const age = alterLabel(e);
  if (age) extras.push(`<span class="badge">${age}</span>`);
  if (e.kostenlos) extras.push('<span class="badge free">kostenlos</span>');
  else if (e.kostenlos === false) extras.push('<span class="badge">kostenpflichtig</span>');
  extras.push(`<span class="badge src">${escapeHtml(e.quelle)}</span>`);
  rows.push(`<div class="detail__row"><span class="k">Details</span><span class="badges" style="display:inline-flex">${extras.join("")}</span></div>`);
  if (e.beschreibung_kurz) rows.push(`<div class="detail__desc">${escapeHtml(e.beschreibung_kurz)}</div>`);
  const kannKarte = e.lat != null && e.lon != null;
  rows.push(`<div class="detail__actions">
    <a class="btn primary" href="${escapeHtml(e.source_url)}" target="_blank" rel="noopener noreferrer">Zur Quelle ↗</a>
    ${kannKarte ? '<button type="button" class="btn" id="detail-karte">Auf der Karte zeigen</button>' : ""}
  </div>`);
  $("#detail-titel").textContent = e.titel;
  $("#detail-body").innerHTML = rows.join("");
  const kb = $("#detail-karte");
  if (kb) kb.addEventListener("click", () => { closeDetail(); zeigeMarker(e.id); });
  $("#detail").classList.remove("hidden");
  document.body.style.overflow = "hidden";
}
function closeDetail() {
  $("#detail").classList.add("hidden");
  document.body.style.overflow = "";
}
function zeigeMarker(id) {
  const target = markers.find((m) => m._ev && m._ev.id === id);
  if (target) { map.flyTo(target.getLatLng(), Math.max(map.getZoom(), 14)); target.openPopup(); }
}

/* ---------- Liste ---------- */
function renderList(gj) {
  const all = [...gj.features.map((f) => f.properties), ...(gj.ohne_position || [])];
  const ul = $("#eventlist");
  ul.innerHTML = "";
  const ls = $("#liststate");
  if (all.length === 0) {
    ls.textContent = "Keine Veranstaltungen für diese Filter.";
    ls.classList.remove("hidden");
    return;
  }
  ls.textContent = `${all.length} Veranstaltung(en)${gj.ohne_position && gj.ohne_position.length ? ` (${gj.ohne_position.length} ohne Kartenposition)` : ""} — Filter teilen: URL kopieren`;
  ls.classList.remove("hidden");
  all.sort((a, b) => a.start_local.localeCompare(b.start_local));
  all.forEach((e) => {
    const li = document.createElement("li");
    const badges = [];
    if (e.kostenlos) badges.push('<span class="badge free">kostenlos</span>');
    const age = alterLabel(e);
    if (age) badges.push(`<span class="badge">${age}</span>`);
    const hatPos = e.lat != null && e.lon != null;
    const main = document.createElement("div");
    main.className = "li-main";
    main.innerHTML = `<h3>${escapeHtml(e.titel)}</h3>
      <div class="when">${fmtZeit(e)}</div>
      <div class="where">${escapeHtml(e.ort || "")}${e.bezirk_label && e.bezirk_label !== "Ohne Angabe" ? " · " + e.bezirk_label : ""}</div>
      <div class="badges">${badges.join("")}</div>`;
    const acts = document.createElement("div");
    acts.className = "li-actions";
    if (hatPos) {
      const kb = document.createElement("button");
      kb.type = "button"; kb.className = "mapbtn"; kb.textContent = "Karte";
      kb.title = "Auf der Karte anzeigen";
      kb.addEventListener("click", (ev) => { ev.stopPropagation(); zeigeMarker(e.id); });
      acts.appendChild(kb);
    }
    li.appendChild(main);
    li.appendChild(acts);
    li.title = "Details anzeigen";
    li.addEventListener("click", () => openDetail(e));
    ul.appendChild(li);
  });
}

/* ---------- Laden ---------- */
let busy = false;
async function load() {
  if (busy) return;
  busy = true;
  $("#statusline").textContent = "Lade Veranstaltungen…";
  try {
    const qs = queryParams();
    const r = await fetch(`/api/events.geojson${qs ? "?" + qs : ""}`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const gj = await r.json();
    renderGeo(gj);
    renderList(gj);
    $("#statusline").textContent = `Aktualisiert ${new Date().toLocaleTimeString("de-DE")} · ${gj.anzahl} Events`;
  } catch (err) {
    $("#statusline").textContent = "Fehler beim Laden.";
    $("#errortext").textContent = `API nicht erreichbar: ${err.message}`;
    $("#errorbar").classList.remove("hidden");
  } finally {
    busy = false;
  }
}

function apply() {
  updateFilterCount();
  load();
}

/* Aktive Filter im Toggle-Button zählen (Mobile) — „Heute“ als Standard
   zählt nicht als aktiver Filter. */
function updateFilterCount() {
  const el = $("#filter-count");
  let n = state.bezirk.length + state.altersband.length + state.uhrzeit.length;
  if (state.zeitraum !== "heute") n += 1;
  if (state.kostenlos) n += 1;
  el.textContent = `${n} aktiv`;
  el.classList.toggle("hidden", n === 0);
}

/* ---------- Init ---------- */
// Filter collapsible (Mobile): Toggle zwischen offen/zugeklappt
$("#filter-toggle").addEventListener("click", () => {
  const aside = $("#filters");
  const zu = aside.classList.toggle("filters-closed");
  $("#filter-toggle").setAttribute("aria-expanded", String(!zu));
});
$("#detail-close").addEventListener("click", closeDetail);
$("#detail").addEventListener("click", (ev) => { if (ev.target === ev.currentTarget) closeDetail(); });
document.addEventListener("keydown", (ev) => { if (ev.key === "Escape") closeDetail(); });
// Popup-„Details anzeigen“: Delegation (Popup-Elemente sind flüchtig)
document.addEventListener("click", (ev) => {
  const btn = ev.target && ev.target.closest ? ev.target.closest("#popup-detail") : null;
  if (!btn) return;
  const id = btn.dataset.evId;
  const ziel = markers.find((m) => m._ev && m._ev.id === id);
  if (ziel) { map.closePopup(); openDetail(ziel._ev); }
});
readUrl();
loadMeta()
  .then(() => {
    const p = new URLSearchParams(location.search);
    $$("#bezirk-list input").forEach((i) => (i.checked = state.bezirk.includes(i.value)));
    $$(".chips button").forEach((b) => {
      const key = b.parentElement.id === "alter-list" ? "altersband" : "uhrzeit";
      b.classList.toggle("on", state[key].includes(b.dataset.id));
    });
    $("#kostenlos").checked = state.kostenlos;
    syncZeitraumUI();
    return load();
  })
  .catch((err) => {
    $("#errortext").textContent = `Meta nicht erreichbar: ${err.message}`;
    $("#errorbar").classList.remove("hidden");
  });
