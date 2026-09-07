/* Kinder-Events Berlin — Karte + Filter, Vanilla JS.
 * Daten: /api/events.geojson (gefiltert), Optionen: /api/meta. */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => Array.from(el.querySelectorAll(s));

const state = {
  bezirk: [], altersband: [], uhrzeit: [],
  kostenlos: false, von: "", bis: "", zeitraum: "demnächst", zeitstufe: null, meta: null,
  q: "",
};

function fmtDate(s) {
  if (!s) return "";
  const [d, t] = s.split("T");
  const [y, m, dd] = d.split("-");
  return t ? `${dd}.${m}.${y}, ${t.slice(0, 5)}` : `${dd}.${m}.${y}`;
}
function fmtZeit(e) {
  const s = fmtDate(e.start_local);            // „05.09.2026, 10:00“
  const [sd, st] = s.split(", ");
  const en = e.ende_local ? fmtDate(e.ende_local).split(", ") : null;
  const ed = en ? en[0] : null;
  const et = en ? en[1] : "";
  if (e.ganztags) {
    // mehrlägig ganztägig: Datumsbereich, sonst nur der Tag
    return ed && ed !== sd ? `${sd} – ${ed}, ganztägig` : `${sd}, ganztägig`;
  }
  if (!e.ende_local) return `${sd} ${st || ""} Uhr`;
  // Ende an anderem Tag → End-DATUM mitzeigen (kein „Event von gestern“-Eindruck)
  return ed !== sd
    ? `${sd} ${st} – ${ed} ${et} Uhr`
    : `${sd} ${st} – ${et} Uhr`;
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
  { id: "demnächst", label: "Demnächst", von: () => berlinDateStr(0), bis: () => berlinDateStr(13) },
  { id: "heute", label: "Heute", von: () => berlinDateStr(0), bis: () => berlinDateStr(0) },
  { id: "morgen", label: "Morgen", von: () => berlinDateStr(1), bis: () => berlinDateStr(1) },
  { id: "diese-woche", label: "Diese Woche", von: () => berlinDateStr(0), bis: () => berlinDateStr(6) },
  { id: "naechste-woche", label: "Nächste Woche", von: () => berlinDateStr(7), bis: () => berlinDateStr(13) },
];
const ZEITRAUM_IDS = ZEITRAUM_OPTIONEN.map((o) => o.id);

/* Zeit-Farbkodierung (Karte + Liste): Distanz des Event-Starttags zu heute.
   Opazität wie gewünscht: heute voll sichtbar, dann abnehmend. */
const ZEIT_STUFEN = {
  heute:      { farbe: "#3b82f6", op: 1.0, label: "Heute" },
  morgen:     { farbe: "#157a3e", op: 0.7, label: "Morgen" },
  uebermorgen:{ farbe: "#4ade80", op: 0.5, label: "Übermorgen" },
  woche:      { farbe: "#facc15", op: 0.4, label: "Diese Woche" },
  spaeter:    { farbe: "#94a3b8", op: 0.35, label: "Später" },
};
const ZEIT_STUFEN_REIHENFOLGE = ["heute", "morgen", "uebermorgen", "woche", "spaeter"];

function tageDifferenz(tagA, tagB) {
  return Math.round((Date.parse(tagA + "T00:00:00Z") - Date.parse(tagB + "T00:00:00Z")) / 86400000);
}

/* Zeitstufe eines Events: läuft es gerade (Start gestern, Ende heute/morgen),
   zählt der heutige Tag; vergangene Events → neutral „später“. */
function zeitStufe(e) {
  const heute = berlinDateStr(0);
  const s = (e.start_local || "").slice(0, 10);
  if (!s) return "spaeter";
  const d = tageDifferenz(s, heute);
  if (d < 0) {
    const en = ((e.ende_local && e.ende_local.slice(0, 10)) || s);
    return tageDifferenz(en, heute) >= 0 ? "heute" : "spaeter";
  }
  if (d === 0) return "heute";
  if (d === 1) return "morgen";
  if (d === 2) return "uebermorgen";
  if (d <= 6) return "woche";
  return "spaeter";
}

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
  state.kostenlos = false; state.von = ""; state.bis = ""; state.zeitraum = "demnächst";
  state.q = ""; state.zeitstufe = null;
  $$("#bezirk-list input").forEach((i) => (i.checked = false));
  $$(".chips button").forEach((b) => b.classList.remove("on"));
  $("#kostenlos").checked = false;
  const suche = $("#suche");
  if (suche) suche.value = "";
  syncZeitraumUI();
  syncLegendeUI();
  apply();
}

function queryParams() {
  const p = new URLSearchParams();
  if (state.bezirk.length) p.set("bezirk", state.bezirk.join(","));
  if (state.altersband.length) p.set("altersband", state.altersband.join(","));
  if (state.uhrzeit.length) p.set("uhrzeit", state.uhrzeit.join(","));
  if (state.kostenlos) p.set("kostenlos", "true");
  if (state.q) p.set("q", state.q);
  if (ZEITRAUM_IDS.includes(state.zeitraum)) p.set("zeitraum", state.zeitraum);
  if (state.zeitstufe) p.set("zeitstufe", state.zeitstufe);
  if (state.von) p.set("von", state.von);
  if (state.bis) p.set("bis", state.bis);
  const qs = p.toString();
  history.replaceState(null, "", qs ? "?" + qs : location.pathname);
  return qs;
}

function readUrl() {
  const p = new URLSearchParams(location.search);
  state.bezirk = (p.get("bezirk") || "").split(",").filter(Boolean);
  state.zeitstufe = p.get("zeitstufe") || null;
  state.altersband = (p.get("altersband") || "").split(",").filter(Boolean);
  state.uhrzeit = (p.get("uhrzeit") || "").split(",").filter(Boolean);
  state.kostenlos = p.get("kostenlos") === "true";
  state.q = p.get("q") || "";
  const zr = p.get("zeitraum");
  state.zeitraum = ZEITRAUM_IDS.includes(zr) ? zr : (p.get("von") || p.get("bis") ? "benutzerdefiniert" : "demnächst");
  state.von = p.get("von") || ""; state.bis = p.get("bis") || "";
}

/* ---------- Karte ---------- */
const map = L.map("map", { zoomControl: true }).setView([52.52, 13.405], 11);
L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 18,
  attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
}).addTo(map);
legendeEinrichten();
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
    const st = ZEIT_STUFEN[zeitStufe(p)];
    /* divIcon statt SVG-Kreis: 30×30px Trefferfläche (Touch-tauglich),
       sichtbarer Punkt 14px mit 2px Rand — Optik wie der alte Kreis. */
    const ic = L.divIcon({
      className: "ev-marker",
      html: `<span class="ev-marker__dot" style="background:${st.farbe};opacity:${st.op}"></span>`,
      iconSize: [30, 30], iconAnchor: [15, 15], popupAnchor: [0, -4],
    });
    const m = L.marker([f.geometry.coordinates[1], f.geometry.coordinates[0]], { icon: ic });
    m.bindPopup(popupHtml(p));
    m._ev = p;
    if (cluster) cluster.addLayer(m); else m.addTo(map);
    markers.push(m);
  });
  if (cluster) map.addLayer(cluster);
  if (!state.zeitstufe && withPos > 0 && markers.length === withPos && !useCluster) {
    const b = L.latLngBounds(markers.map((m) => m.getLatLng()));
    if (b.isValid()) map.fitBounds(b.pad(0.15), { maxZoom: 13 });
  } else if (!state.zeitstufe && withPos === 1 && markers.length === 1) {
    map.setView(markers[0].getLatLng(), 14);
  }
}

/* Karten-Legende: erklärt die Zeit-Farben und filtert bei Klick auf die
   gewünschte Stufe (erneuter Klick hebt den Filter auf). */
function legendeEinrichten() {
  const ctrl = L.control({ position: "bottomleft" });
  ctrl.onAdd = () => {
    const div = L.DomUtil.create("div", "map-legende");
    L.DomEvent.disableClickPropagation(div);
    const zeilen = ZEIT_STUFEN_REIHENFOLGE.map((k) => {
      const s = ZEIT_STUFEN[k];
      return `<button type="button" class="map-legende__zeile" data-stufe="${k}"
        title="Nur ${s.label.toLowerCase()} anzeigen — erneut klicken zum Aufheben">
        <span class="map-legende__punkt" style="background:${s.farbe};opacity:${s.op}"></span>
        <span>${s.label}</span></button>`;
    }).join("");
    div.innerHTML = `<div class="map-legende__titel">Wann? — filtern</div>${zeilen}`;
    div.querySelectorAll(".map-legende__zeile").forEach((z) =>
      z.addEventListener("click", () => {
        const k = z.dataset.stufe;
        state.zeitstufe = state.zeitstufe === k ? null : k;
        syncLegendeUI();
        apply();
      }));
    return div;
  };
  ctrl.addTo(map);
}

function syncLegendeUI() {
  $$(".map-legende__zeile").forEach((z) =>
    z.classList.toggle("on", z.dataset.stufe === state.zeitstufe));
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
    li.className = "tz-" + zeitStufe(e);
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
    /* Zeitstufen-Filter (Legenden-Klick): client-seitig nach der Stufe des
       Starttags — wirkt auf Karte UND Liste. */
    if (state.zeitstufe) {
      const st = state.zeitstufe;
      gj.features = gj.features.filter((f) => zeitStufe(f.properties) === st);
      gj.ohne_position = (gj.ohne_position || []).filter((e) => zeitStufe(e) === st);
      gj.anzahl = gj.features.length + (gj.ohne_position || []).length;
    }
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

/* Aktive Filter im Fuß-Badge zählen — „Heute“ als Standard zählt nicht. */
function updateFilterCount() {
  const el = $("#filter-count");
  let n = state.bezirk.length + state.altersband.length + state.uhrzeit.length;
  if (!["heute", "demnächst"].includes(state.zeitraum)) n += 1;
  if (state.zeitstufe) n += 1;  // Legenden-Filter (Zeitstufe)
  if (state.kostenlos) n += 1;
  if (state.q) n += 1;
  el.textContent = `${n} aktiv`;
  el.classList.toggle("hidden", n === 0);
}

/* ---------- Init ---------- */
// Filter-Tabs: auf Mobile (≤820px) starten alle Kategorien zugeklappt,
// damit die Eventliste Platz bekommt — nur die Tab-Leiste + Suche sind
// sichtbar. Auf Desktop ist „Bezirk" offen (Standard im HTML).
(function initFilterTabs() {
  if (!window.matchMedia("(max-width: 820px)").matches) return;
  $$(".filter-tab").forEach((t) => {
    t.classList.remove("on");
    t.setAttribute("aria-selected", "false");
  });
  $$(".filter-panel").forEach((p) => p.classList.add("hidden"));
})();
document.addEventListener("click", (ev) => {
  const tab = ev.target && ev.target.closest ? ev.target.closest(".filter-tab") : null;
  if (!tab) return;
  const panel = tab.dataset.panel;
  const schliessen = tab.classList.contains("on"); // aktiven Tab erneut klicken = Panel zu
  $$(".filter-tab").forEach((t) => {
    const aktiv = !schliessen && t === tab;
    t.classList.toggle("on", aktiv);
    t.setAttribute("aria-selected", String(aktiv));
  });
  $$(".filter-panel").forEach((p) => p.classList.toggle("hidden", schliessen || p.id !== `panel-${panel}`));
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
    if (state.q) $("#suche").value = state.q;
    syncZeitraumUI();
    syncLegendeUI();
    return load();
  })
  .catch((err) => {
    $("#errortext").textContent = `Meta nicht erreichbar: ${err.message}`;
    $("#errorbar").classList.remove("hidden");
  });

// Volltextsuche: debounced, Filter-Zähler aktualisieren
let sucheTimer = null;
$("#suche").addEventListener("input", (ev) => {
  state.q = ev.target.value.trim();
  clearTimeout(sucheTimer);
  sucheTimer = setTimeout(() => { updateFilterCount(); apply(); }, 350);
});
