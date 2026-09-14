/* Kinder-Events Berlin — Verwaltung (Admin). Offen; Schutz folgt.
 * Quellen/Regeln/Einstellungen ausschließlich über /api/admin. */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => Array.from(el.querySelectorAll(s));

const TYP_LABEL = { intern: "intern", regeln: "Regeln", feed: "Feed" };
const TYP_HILFE = {
  intern: "Eigener Programm-Adapter (z. B. jup-berlin) — keine Regeln.",
  regeln: "HTML/JSON-LD-Extraktion über Regeldatei (Stufe 2).",
  feed: "RSS/Atom/iCal-Abo (Stufe 1) — folgt mit der Engine.",
};

const REGELN_VORLAGE = `# Regeln für eine Listen-Quelle (Stufe 2).
# item_css wählt EIN Event-Element; felder extrahieren daraus.
# 'format' ist ein Python-Datumsformat (z. B. %d.%m.%Y, %H:%M).
listing:
  url: https://www.zlb.de/veranstaltungen
  item_css: article.eventTeaser
  felder:
    titel: {css: ".eventTeaser__title"}
    start: {css: ".eventTeaser__date", format: "%d.%m.%Y"}
    url: {css: "a", attr: "href"}
    ort: {css: ".eventTeaser__location"}
detail:
  jsonld: true
  felder:
    beschreibung_kurz: {jsonld: "$.description"}
`;

/* ---------- API-Helfer (Fehler sichtbar, nie still) ---------- */
async function api(path, opts = {}) {
  const r = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!r.ok) {
    let msg = `HTTP ${r.status}`;
    try {
      const d = await r.json();
      const det = d.detail ?? d;
      if (typeof det === "string") msg = det;
      else if (det && Array.isArray(det.fehler)) msg = det.fehler.join(" · ");
      else if (typeof det.message === "string") msg = det.message;
    } catch { /* leer */ }
    throw new Error(msg);
  }
  if (r.status === 204) return null;
  return r.json();
}

function fehlerZeigen(msg) {
  $("#errortext").textContent = msg;
  $("#errorbar").classList.remove("hidden");
}
function meldung(el, text, ok = true) {
  if (!el) return;
  el.textContent = text;
  el.className = ok ? "hinweis" : "fehler";
}

function fmtZeit(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return isNaN(d) ? iso : d.toLocaleString("de-DE", { dateStyle: "short", timeStyle: "short" });
}

/* ---------- Quellen ---------- */
let quellen = [];
let bearbeite = null; // quelle-Key im Formular (null = neu)

function laufBadge(l) {
  if (!l) return '<span class="badge">nie</span>';
  const ok = l.status === "ok";
  const warn = l.status === "anomalie-0-events";
  const cls = warn ? "err" : ok ? "ok" : "err";
  return `<span class="badge ${cls}">${l.status}${warn ? " (0 Events)" : ""}</span>`;
}

function renderQuellen() {
  const tb = $("#quellenTabelle tbody");
  tb.innerHTML = "";
  if (!quellen.length) {
    tb.innerHTML = '<tr><td colspan="7" class="muted">Noch keine Quellen.</td></tr>';
    return;
  }
  quellen.forEach((q) => {
    const tr = document.createElement("tr");
    const l = q.letzter_lauf;
    const aktiv = q.aktiv
      ? '<span class="badge ok">aktiv</span>'
      : '<span class="badge off">pausiert</span>';
    tr.innerHTML = `
      <td><strong>${esc(q.quelle)}</strong><br/><span class="muted">${esc(q.name)}</span></td>
      <td><span class="badge">${TYP_LABEL[q.typ] || q.typ}</span></td>
      <td class="muted">${q.url ? `<a href="${esc(q.url)}" target="_blank" rel="noopener">${esc(q.url.replace(/^https?:\/\//, ""))}</a>` : "—"}</td>
      <td>${aktiv}</td>
      <td>${q.events ?? 0}</td>
      <td>${l ? `${laufBadge(l)}<br/><span class="muted">${fmtZeit(l.finished_at || l.started_at)} · ${l.n_events} Events · ${l.n_fehler} Fehler</span>` : '<span class="muted">kein Lauf</span>'}</td>
      <td><div class="btnrow">
        <button data-act="edit" data-q="${esc(q.quelle)}">Bearbeiten</button>
        ${q.typ === "regeln" ? `<button data-act="regeln" data-q="${esc(q.quelle)}">Regeln</button>` : ""}
        <button data-act="scrape" data-q="${esc(q.quelle)}">Scrapen</button>
        <button data-act="del" data-q="${esc(q.quelle)}" class="danger">Löschen</button>
      </div></td>`;
    tb.appendChild(tr);
  });
}

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

async function loadQuellen() {
  $("#statusline").textContent = "Lade Quellen…";
  try {
    quellen = await api("/api/admin/sources");
    renderQuellen();
    $("#statusline").textContent = `Aktualisiert ${new Date().toLocaleTimeString("de-DE")}`;
  } catch (e) {
    fehlerZeigen(`Quellen nicht geladen: ${e.message}`);
  }
}

/* ---------- Formular (neu / bearbeiten) ---------- */
function formWert(q, id, dflt = "") {
  const v = q ? q[id] : dflt;
  return v == null ? "" : v;
}

function zeigeFormular(q) {
  bearbeite = q ? q.quelle : null;
  const p = $("#quellenPanel");
  p.innerHTML = `
    <h3 style="margin:0 0 10px">${q ? `Quelle bearbeiten: ${esc(q.quelle)}` : "Neue Quelle"}</h3>
    <div class="formgrid">
      <label>Schlüssel (nur bei Neuanlage)<input id="f_quelle" ${q ? "disabled" : ""} placeholder="z. B. zlb" value="${esc(formWert(q, "quelle"))}"/></label>
      <label>Anzeigename<input id="f_name" placeholder="z. B. ZLB Berlin" value="${esc(formWert(q, "name"))}"/></label>
      <label>Typ
        <select id="f_typ">
          ${["regeln", "feed", "intern"].map((t) =>
            `<option value="${t}" ${(q && q.typ === t) || (!q && t === "regeln") ? "selected" : ""}>${TYP_LABEL[t]} — ${TYP_HILFE[t]}</option>`).join("")}
        </select>
      </label>
      <label>URL<input id="f_url" placeholder="https://…" value="${esc(formWert(q, "url"))}"/></label>
      <label>Rate-Limit (Sek. zwischen Requests)<input id="f_rate" type="number" step="0.5" min="0" value="${formWert(q, "rate_limit_s", "1")}"/></label>
      <label>Menge min (erwartet)<input id="f_min" type="number" min="0" value="${formWert(q, "menge_min")}"/></label>
      <label>Menge max (erwartet)<input id="f_max" type="number" min="0" value="${formWert(q, "menge_max")}"/></label>
      <label>Horizont (Tage)<input id="f_horizont" type="number" min="1" value="${formWert(q, "horizont_tage", "60")}"/></label>
      <label class="muted">robots/ToS-Notiz<input id="f_robots" value="${esc(formWert(q, "robots"))}"/></label>
      <label class="muted">Notiz<input id="f_notiz" value="${esc(formWert(q, "notiz"))}"/></label>
      <label style="flex-direction:row;align-items:center;gap:6px"><input id="f_aktiv" type="checkbox" ${q && !q.aktiv ? "" : "checked"}/> Aktiv (wird gescrapt)</label>
    </div>
    <div class="btnrow" style="margin-top:12px">
      <button id="f_save" type="button" class="primary">Speichern</button>
      <button id="f_abort" type="button" class="ghost">Abbrechen</button>
    </div>
    <div id="f_msg"></div>`;
  p.classList.remove("hidden");
  $("#f_abort").onclick = () => { p.classList.add("hidden"); };
  $("#f_save").onclick = async () => {
    const body = {
      name: $("#f_name").value.trim(), typ: $("#f_typ").value,
      url: $("#f_url").value.trim() || null,
      aktiv: $("#f_aktiv").checked,
      rate_limit_s: parseFloat($("#f_rate").value) || 1,
      menge_min: $("#f_min").value === "" ? null : parseInt($("#f_min").value, 10),
      menge_max: $("#f_max").value === "" ? null : parseInt($("#f_max").value, 10),
      horizont_tage: parseInt($("#f_horizont").value, 10) || 60,
      robots: $("#f_robots").value.trim() || null,
      notiz: $("#f_notiz").value.trim() || null,
    };
    const msg = $("#f_msg");
    try {
      if (bearbeite) {
        await api(`/api/admin/sources/${encodeURIComponent(bearbeite)}`, { method: "PUT", body: JSON.stringify(body) });
      } else {
        body.quelle = $("#f_quelle").value.trim();
        if (!body.quelle) throw new Error("Schlüssel fehlt (kleinbuchstaben, Bindestriche).");
        await api("/api/admin/sources", { method: "POST", body: JSON.stringify(body) });
      }
      meldung(msg, "Gespeichert.");
      p.classList.add("hidden");
      await Promise.all([loadQuellen(), loadRuns(), loadFehler()]);
    } catch (e) { meldung(msg, e.message, false); }
  };
}

/* ---------- Regel-Editor ---------- */
let regelQuelle = null;

async function zeigeRegeln(quelleKey) {
  regelQuelle = quelleKey;
  const p = $("#regelnPanel");
  p.classList.remove("hidden");
  p.innerHTML = `
    <h3 style="margin:0 0 6px">Scraping-Regeln: ${esc(quelleKey)}</h3>
    <div class="btnrow" style="margin-bottom:8px">
      <button id="r_vorlage" type="button" class="ghost">Vorlage einfügen</button>
      <button id="r_pruefen" type="button">Prüfen (ohne Speichern)</button>
      <button id="r_speichern" type="button" class="primary">Speichern</button>
      <button id="r_zu" type="button" class="ghost">Schließen</button>
    </div>
    <textarea id="r_yaml" spellcheck="false"></textarea>
    <div id="r_msg"></div>`;
  try {
    const r = await api(`/api/admin/sources/${encodeURIComponent(quelleKey)}/regeln`);
    if (r.regel_yaml) $("#r_yaml").value = r.regel_yaml;
  } catch (e) { meldung($("#r_msg"), e.message, false); }
  $("#r_zu").onclick = () => p.classList.add("hidden");
  $("#r_vorlage").onclick = () => {
    if (!$("#r_yaml").value.trim()) $("#r_yaml").value = REGELN_VORLAGE;
  };
  $("#r_pruefen").onclick = async () => {
    const msg = $("#r_msg");
    try {
      const out = await api(`/api/admin/sources/${encodeURIComponent(quelleKey)}/regeln/validate`, {
        method: "POST", body: JSON.stringify({ regel_yaml: $("#r_yaml").value }),
      });
      if (out.ok) meldung(msg, "Regeln gültig ✓");
      else meldung(msg, out.fehler.join("\n"), false);
    } catch (e) { meldung(msg, e.message, false); }
  };
  $("#r_speichern").onclick = async () => {
    const msg = $("#r_msg");
    try {
      await api(`/api/admin/sources/${encodeURIComponent(quelleKey)}/regeln`, {
        method: "PUT", body: JSON.stringify({ regel_yaml: $("#r_yaml").value }),
      });
      meldung(msg, "Regeln gespeichert ✓ (gelten ab dem nächsten Lauf)");
    } catch (e) { meldung(msg, e.message, false); }
  };
}

/* ---------- Aktionen ---------- */
$("#quellenTabelle").addEventListener("click", async (ev) => {
  const btn = ev.target.closest("button[data-act]");
  if (!btn) return;
  const q = btn.dataset.q;
  const act = btn.dataset.act;
  try {
    if (act === "edit") {
      const src = await api(`/api/admin/sources/${encodeURIComponent(q)}`);
      zeigeFormular(src);
    } else if (act === "regeln") {
      zeigeRegeln(q);
    } else if (act === "scrape") {
      btn.disabled = true;
      const orig = btn.textContent;
      btn.textContent = "Startet…";
      try {
        await api(`/api/admin/sources/${encodeURIComponent(q)}/scrape`, { method: "POST" });
        fehlerZeigen(""); $("#errorbar").classList.add("hidden");
        setTimeout(loadQuellen, 2500);
      } catch (e) { fehlerZeigen(`Scrape ${q}: ${e.message}`); }
      btn.disabled = false; btn.textContent = orig;
    } else if (act === "del") {
      if (!confirm(`Quelle „${q}“ wirklich löschen? (Regeln und künftige Läufe entfallen; vorhandene Events bleiben bis zur Bereinigung.)`)) return;
      await api(`/api/admin/sources/${encodeURIComponent(q)}`, { method: "DELETE" });
      await Promise.all([loadQuellen(), loadRuns()]);
    }
  } catch (e) { fehlerZeigen(e.message); }
});

$("#neuBtn").onclick = () => zeigeFormular(null);
$("#refreshBtn").onclick = () => Promise.all([loadQuellen(), loadRuns(), loadFehler()]).catch((e) => fehlerZeigen(e.message));
$("#errorbar").addEventListener("click", () => $("#errorbar").classList.add("hidden"));

/* ---------- Läufe + Fehler ---------- */
async function loadRuns() {
  const runs = await api("/api/admin/runs?limit=25");
  const tb = $("#runsTabelle tbody");
  tb.innerHTML = "";
  if (!runs.length) { tb.innerHTML = '<tr><td colspan="7" class="muted">Noch keine Läufe.</td></tr>'; return; }
  runs.forEach((r) => {
    const tr = document.createElement("tr");
    const warn = r.status === "anomalie-0-events";
    tr.innerHTML = `<td>${fmtZeit(r.finished_at || r.started_at)}</td>
      <td>${esc(r.quelle)}</td>
      <td>${laufBadge(r)}</td>
      <td>${r.n_neu}</td><td>${r.n_geaendert}</td><td>${r.n_fehler}</td>
      <td class="muted">${r.dauer_s != null ? r.dauer_s.toFixed(0) + " s" : "—"}</td>`;
    if (warn) tr.style.background = "rgba(248,81,73,.06)";
    tb.appendChild(tr);
  });
}

async function loadFehler() {
  const errs = await api("/api/admin/errors?limit=15");
  const el = $("#fehlerListe");
  if (!errs.length) { el.innerHTML = "Keine Fehler."; return; }
  el.innerHTML = "";
  errs.forEach((e) => {
    const d = document.createElement("div");
    d.style.cssText = "border-bottom:1px solid var(--border);padding:6px 0;font-size:12.5px";
    d.innerHTML = `<span class="muted">${fmtZeit(e.zeitpunkt)}</span> <span class="badge">${esc(e.quelle)}</span><br/>${esc(e.grund)}`;
    if (e.roh && e.roh.titel) d.innerHTML += `<br/><span class="muted">Event: ${esc(e.roh.titel)}</span>`;
    el.appendChild(d);
  });
}

/* ---------- Einstellungen ---------- */
async function loadSettings() {
  const s = await api("/api/admin/settings");
  // Geltende Konfiguration anzeigen: gesetzte Uhrzeit, sonst Intervall-Modus
  // (Feld leer), sonst der Code-Standard 05:30.
  $("#setAt").value = s.scrape_at || (s.scrape_interval_h ? "" : "05:30");
  $("#setInterval").value = s.scrape_interval_h || "24";
}
$("#settingsBtn").onclick = async () => {
  const msg = $("#settingsMsg");
  try {
    await api("/api/admin/settings", {
      method: "PUT",
      body: JSON.stringify({
        scrape_at: $("#setAt").value.trim(),
        scrape_interval_h: $("#setInterval").value,
      }),
    });
    meldung(msg, "Gespeichert — gilt ab dem nächsten Scheduler-Zyklus.");
  } catch (e) { meldung(msg, e.message, false); }
};
/* ---------- Tabs: Obertab (Quellen | Termine | Einstellungen) ---------- */
let obentab = "quellen";
let untertab = "uebersicht"; // uebersicht | quelle:<key> | schulen

function unterTabZeigen(name) {
  untertab = name;
  $$("#unterTabs button").forEach((b) =>
    b.classList.toggle("aktiv", b.dataset.unter === name));
  ["uebersicht", "quelle", "schulen"].forEach((t) =>
    $("#unter-" + t).classList.toggle("hidden", t !== name.split(":")[0]));
  if (name === "schulen") loadSchulen();
  if (name.startsWith("quelle:")) quelleEventsLaden(name.split(":")[1]);
}

function tabAktiv(name) {
  obentab = name;
  $$("#tabs button").forEach((b) => b.classList.toggle("aktiv", b.dataset.tab === name));
  ["quellen", "termine", "einstellungen", "ortsvorschlaege"].forEach((t) => {
    const el = $("#tab-" + t);
    if (el) el.classList.toggle("hidden", t !== name);
  });
  if (name === "termine") loadAlleTermine();
  if (name === "ortsvorschlaege") loadOrtsvorschlaege();
  if (name === "quellen" && !$("#unterTabs").dataset.gefuellt) baueUnterTabs();
}
$("#tabs").addEventListener("click", (ev) => {
  const b = ev.target.closest("button[data-tab]");
  if (!b) return;
  tabAktiv(b.dataset.tab);
  if (b.dataset.tab === "einstellungen") loadTags();
  if (b.dataset.tab === "schulrecherche") {   // eigener Tab: Zustände frisch holen
    if (typeof loadRecherche === "function") loadRecherche();
    if (typeof loadBrave === "function") loadBrave();
    if (typeof loadMail === "function") loadMail();
  }
});

/* Unter-Tabs aus den aktiven Quellen bauen: Übersicht + je Quelle + Schulen */
async function baueUnterTabs() {
  const nav = $("#unterTabs");
  nav.dataset.gefuellt = "1";
  nav.innerHTML = '<button data-unter="uebersicht" class="aktiv">Übersicht</button>';
  try {
    const qs = await api("/api/admin/sources");
    quellen = qs;
    qs.filter((q) => q.aktiv).forEach((q) => {
      const b = document.createElement("button");
      b.dataset.unter = "quelle:" + q.quelle;
      b.className = "unter";
      b.innerHTML = `${esc(q.name)} <span class="count">${q.events}</span>`;
      nav.appendChild(b);
    });
    const sch = document.createElement("button");
    sch.dataset.unter = "schulen";
    sch.className = "unter";
    sch.innerHTML = "🏫 Schulen <span class=\"manuell-kennz\">(manuelle Termine)</span>";
    nav.appendChild(sch);
  } catch (e) {
    fehlerZeigen(`Quellen für Unter-Tabs: ${e.message}`);
  }
  nav.addEventListener("click", (ev) => {
    const b = ev.target.closest("button[data-unter]");
    if (b) unterTabZeigen(b.dataset.unter);
  });
  loadQuellen(); // Übersicht füllen
}

/* Termine einer einzelnen Quelle (Unter-Tab) — alle sind editierbar */
let quelleEventsCache = new Map();
async function quelleEventsLaden(quelleKey) {
  const q = quellen.find((x) => x.quelle === quelleKey);
  $("#quelleKopf").innerHTML = q
    ? `<div class="quellkopf"><span class="name">${esc(q.name)}</span>
       <a href="${esc(q.url || "#")}" target="_blank" rel="noopener">Website ↗</a>
       <span class="muted">${esc(q.typ === "intern" ? "Eigener Adapter" : q.typ)}</span></div>`
    : "";
  const tbody = $("#quelleEvents tbody");
  tbody.innerHTML = '<tr><td colspan="6" class="muted">Lade Termine…</td></tr>';
  try {
    const evs = await api(`/api/admin/events?quelle=${encodeURIComponent(quelleKey)}&limit=500`);
    quelleEventsCache.set(quelleKey, evs);
    tbody.innerHTML = evs.length
      ? evs.map((e) => eventZeile(e, false)).join("")
      : '<tr><td colspan="6" class="muted">Keine Termine von dieser Quelle.</td></tr>';
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="6" class="fehler">${esc(e.message)}</td></tr>`;
  }
}

/* ---------- Schulen ---------- */
let schulFilter = { q: "", bezirk: "", schulform: "", ohne_termin: false, mit_email: false };
/* Mehrfachauswahl für Sammel-Mail und Sammel-Recherche */
let schulAuswahl = new Set();

function schulAuswahlZaehlen() {
  const n = schulAuswahl.size;
  $("#schulAuswahlZaehler").textContent = `${n} ausgewählt`;
  $("#schulMailBatch").disabled = n === 0;
  $("#schulRechercheBatch").disabled = n === 0;
  $("#schulMailBatch").textContent = n ? `Ausgewählte anschreiben (${n})…` : "Ausgewählte anschreiben…";
  $("#schulRechercheBatch").textContent = n ? `Ausgewählte recherchieren (${n})` : "Ausgewählte recherchieren";
}

function schulAuswahlAufraeumen(sichtbare) {
  // Auswahl nur für sichtbare Schulen behalten — sonst verschwinden Häkchen still
  const menge = new Set(sichtbare);
  [...schulAuswahl].forEach((bsn) => { if (!menge.has(bsn)) schulAuswahl.delete(bsn); });
  schulAuswahlZaehlen();
}

function schulAdresse(s) {
  const teile = [s.strasse, [s.plz, s.ortsteil].filter(Boolean).join(" ")].filter(Boolean);
  return teile.join("<br/>") || "—";
}

function statusBadge(status) {
  if (status === "bestaetigt") return '<span class="badge ok">bestätigt</span>';
  return '<span class="badge warn">ungeprüft</span>';
}

function terminZeile(t, schulname) {
  const zeit = t.start_zeit ? ` ${t.start_zeit} Uhr` : "";
  const beleg = t.quelle_hinweis || "";
  const auto = beleg.startsWith("automatisch erkannt") ? '<span class="badge">auto</span> ' : "";
  return `<div class="termzeile">
    <div>
      <span class="termtitel">${esc(t.titel)}</span>
      ${schulname ? `<span class="klein"> · ${esc(schulname)}</span>` : ""}<br/>
      <span class="termmt">${esc(t.start_datum)}${zeit} · ${statusBadge(t.status)} ${auto}
      ${beleg ? `<a href="${esc(t.url || beleg.replace(/^automatisch erkannt: /, ""))}" target="_blank" rel="noopener" title="Fundseite öffnen">Beleg ↗</a>` : ""}</span>
    </div>
    <div class="btnrow">
      ${t.status !== "bestaetigt" ? `<button data-tid="${t.id}" data-act="freigeben" class="primary" title="Termin öffentlich auf der Karte zeigen">Freigeben</button>` : `<button data-tid="${t.id}" data-act="zurueckziehen" title="Nicht mehr öffentlich zeigen">Zurückziehen</button>`}
      <button data-tid="${t.id}" data-act="edit">Bearbeiten</button>
      <button data-tid="${t.id}" data-act="del" class="danger">Löschen</button>
    </div>
  </div>`;
}

async function loadSchulen() {
  const qs = new URLSearchParams();
  if (schulFilter.q) qs.set("q", schulFilter.q);
  if (schulFilter.bezirk) qs.set("bezirk", schulFilter.bezirk);
  if (schulFilter.schulform) qs.set("schulform", schulFilter.schulform);
  if (schulFilter.ohne_termin) qs.set("ohne_termin", "true");
  if (schulFilter.mit_email) qs.set("nur_mit_email", "true");
  const tb = $("#schuleListe tbody");
  tb.innerHTML = '<tr><td colspan="7" class="muted">Lade Schulen…</td></tr>';
  try {
    const list = await api("/api/admin/schulen?" + qs.toString());
    tb.innerHTML = "";
    if (!list.length) {
      tb.innerHTML = '<tr><td colspan="7" class="muted">Keine Schulen gefunden.</td></tr>';
      $("#schulZaehler").textContent = "";
      schulAuswahl.clear();
      schulAuswahlZaehlen();
      return;
    }
    const ohneTermin = list.filter((s) => !s.hat_termin).length;
    $("#schulZaehler").textContent = `${list.length} Schulen · ${ohneTermin} ohne Termin`;
    schulAuswahlAufraeumen(list.map((s) => s.bsn));
    list.forEach((s) => {
      const tr = document.createElement("tr");
      tr.className = "schule" + (schulAuswahl.has(s.bsn) ? " gewaehlt" : "");
      tr.dataset.bsn = s.bsn;
      const nTermine = s.n_termine ?? 0;
      tr.innerHTML = `
        <td class="wahl"><input type="checkbox" class="schulwahl" data-bsn="${esc(s.bsn)}"
          ${schulAuswahl.has(s.bsn) ? "checked" : ""} /></td>
        <td><strong>${esc(s.name)}</strong><br/><span class="muted">BSN ${esc(s.bsn)}</span></td>
        <td>${esc(s.schulform || "—")}</td>
        <td class="adr">${schulAdresse(s)}</td>
        <td class="klein">${s.email ? esc(s.email) + "<br/>" : ""}${s.website ? `<a href="${esc(s.website)}" target="_blank" rel="noopener" onclick="event.stopPropagation()">Website ↗</a>` : "—"}</td>
        <td><span class="badge ${s.hat_termin ? "ok" : "off"}">${s.hat_termin ? "Termin " + esc(isoNachDe(s.naechster_termin)) : "kein Termin"}</span>
          <div class="muted klein">${nTermine} Eintrag/Einträge</div></td>
        <td><div class="btnrow">
          <button data-bsn="${esc(s.bsn)}" data-act="oeffnen">Termine verwalten</button>
          ${s.email ? `<button data-bsn="${esc(s.bsn)}" data-act="mail">E-Mail</button>` : ""}
        </div></td>`;
      tb.appendChild(tr);
    });
  } catch (e) { fehlerZeigen(`Schulen: ${e.message}`); }
}

function schuleDetailZeigen(s) {
  $("#schuleUebersicht").classList.add("hidden");
  $("#schuleDetail").classList.remove("hidden");
  $("#schuleDetail").dataset.bsn = s.bsn; // für Aktionen im Detail
  const terme = s.termine || [];
  const kont = $("#schuleDetailInhalt");
  kont.innerHTML = `
    <h2 style="margin-top:0">${esc(s.name)} <span class="muted klein">BSN ${esc(s.bsn)}</span></h2>
    <div class="panel">
      <div class="spalte" style="grid-template-columns:1fr 1fr">
        <div class="adr">
          <strong>${esc(s.schulform || "")}</strong><br/>
          ${esc(s.strasse || "")}<br/>
          ${[s.plz, s.ortsteil, s.bezirk].filter(Boolean).join(" · ")}
        </div>
        <div>
          ${s.email ? `<div>✉ <a href="mailto:${esc(s.email)}">${esc(s.email)}</a></div>` : ""}
          ${s.website ? `<div style="margin-top:4px">🌐 <a href="${esc(s.website)}" target="_blank" rel="noopener">${esc(s.website.replace(/^https?:\/\//, ""))} ↗</a> <span class="klein">(Homepage — Termin gegenprüfen)</span></div>` : ""}
          ${s.schulzweig_id ? `<div style="margin-top:4px">📋 <a href="https://www.bildung.berlin.de/Schulverzeichnis/Schulportrait.aspx?IDSchulzweig=${encodeURIComponent(s.schulzweig_id)}" target="_blank" rel="noopener">Schulportrait ↗</a> <span class="klein">(offizielles Profil)</span></div>` : ""}
          ${s.angefragt_am ? `<div class="klein" style="margin-top:4px">Anfrage gesendet: ${fmtZeit(s.angefragt_am)}</div>` : ""}
          ${s.notiz ? `<div class="klein" style="margin-top:4px">${esc(s.notiz)}</div>` : ""}
        </div>
      </div>
      <div class="btnrow" style="margin-top:12px">
        <button id="neuTerminBtn" type="button" class="primary">+ Termin manuell eintragen</button>
        ${s.email ? `<button id="mailFensterBtn" type="button">✉ Termin-Anfrage-Mail</button>` : '<span class="muted">Keine E-Mail-Adresse hinterlegt.</span>'}
      </div>
    </div>
    <div id="terminForm" class="panel hidden"></div>
    <div id="mailForm" class="panel hidden"></div>
    <h3>Termine dieser Schule <span class="count">(${terme.length})</span></h3>
    <div id="schuleTermine">${terme.length ? terme.map((t) => terminZeile(t)).join("") : '<div class="muted">Noch keine Termine — automatisch erkannte Termine erscheinen hier nach dem Import, manuelle nach dem Anlegen.</div>'}</div>`;
  $("#schuleZurueck").onclick = () => {
    $("#schuleDetail").classList.add("hidden");
    $("#schuleUebersicht").classList.remove("hidden");
    loadSchulen();
  };
  $("#neuTerminBtn").onclick = () => { terminFormularZeigen(s); };
  const mf = $("#mailFensterBtn");
  if (mf) mf.onclick = () => mailFormularZeigen(s);
}

async function terminFormularZeigen(s, t = null) {
  const p = $("#terminForm");
  p.classList.remove("hidden");
  if (!window._titelVorschlaege) {
    try { window._titelVorschlaege = await api("/api/admin/termine/vorschlaege"); }
    catch { window._titelVorschlaege = []; }
  }
  const vorschlaege = (window._titelVorschlaege || [])
    .map((x) => `<option value="${esc(x)}"></option>`).join("");
  const datumIso = t && t.start_datum ? deNachIso(t.start_datum) : "";
  const endeIso = t && t.ende_datum ? deNachIso(t.ende_datum) : "";
  p.innerHTML = `
    <h3>${t ? "Termin bearbeiten" : "Neuer Termin"}</h3>
    <div class="formgrid">
      <label>Titel<input id="t_titel" list="titelVorschlaege" value="${esc(t ? t.titel : "")}" placeholder="z. B. Tag der offenen Tür" /></label>
      <label>Datum<input id="t_datum" type="date" value="${datumIso}" /></label>
      <label>Uhrzeit (Start, optional)<input id="t_zeit" type="time" value="${esc(t ? t.start_zeit || "" : "")}" /></label>
      <label>Ende-Datum (optional, mehrtägig)<input id="t_endedatum" type="date" value="${endeIso}" /></label>
      <label>End-Uhrzeit (optional)<input id="t_endezeit" type="time" value="${esc(t ? t.ende_zeit || "" : "")}" /></label>
      <label>Ort<input id="t_ort" value="${esc(t ? t.ort || "" : "")}" placeholder="z. B. Aula" /></label>
      <label>Link (Fund-/Detailseite)<input id="t_url" value="${esc(t ? t.url || "" : "")}" placeholder="https://…" /></label>
      <label style="flex-direction:row;align-items:center;gap:6px"><input id="t_ganztags" type="checkbox" ${t && t.ganztags ? "checked" : ""}/> Ganztägig</label>
    </div>
    <datalist id="titelVorschlaege">${vorschlaege}</datalist>
    <label style="margin-top:8px">Beschreibung / Notiz
      <textarea id="t_beschreibung" style="min-height:70px">${esc(t ? t.beschreibung || "" : "")}</textarea>
    </label>
    <div class="btnrow" style="margin-top:10px">
      <button id="t_save" type="button" class="primary">Speichern</button>
      <button id="t_abort" type="button" class="ghost">Abbrechen</button>
    </div>
    <div id="t_msg"></div>`;
  const ganztagsBox = $("#t_ganztags");
  const zeitFelder = [$("#t_zeit"), $("#t_endezeit"), $("#t_endedatum")];
  const setzeZeitSperre = () => {
    const an = ganztagsBox.checked;
    zeitFelder.forEach((f) => { if (f) f.disabled = an; });
  };
  ganztagsBox.addEventListener("change", setzeZeitSperre);
  setzeZeitSperre();
  $("#t_abort").onclick = () => { p.classList.add("hidden"); };
  $("#t_save").onclick = async () => {
    const msg = $("#t_msg");
    const body = {
      titel: $("#t_titel").value.trim(),
      start_datum: isoNachDe($("#t_datum").value),
      start_zeit: $("#t_zeit").value.trim() || null,
      ende_datum: isoNachDe($("#t_endedatum").value),
      ende_zeit: $("#t_endezeit").value.trim() || null,
      ort: $("#t_ort").value.trim() || null,
      url: $("#t_url").value.trim() || null,
      beschreibung: $("#t_beschreibung").value.trim() || null,
      ganztags: ganztagsBox.checked ? 1 : 0,
    };
    try {
      if (t) await api(`/api/admin/termine/${t.id}`, { method: "PUT", body: JSON.stringify(body) });
      else await api("/api/admin/termine", { method: "POST", body: JSON.stringify({ ...body, schule_bsn: s.bsn }) });
      meldung(msg, "Gespeichert.");
      p.classList.add("hidden");
      schuleDetailZeigen(await api(`/api/admin/schulen/${encodeURIComponent(s.bsn)}?mit_termine=1`));
    } catch (e) { meldung(msg, e.message, false); }
  };
}

/* Datums-Helfer: Formular (TT.MM.JJJJ) ↔ date-input (JJJJ-MM-TT) */
function deNachIso(de) {
  const m = /^(\d{1,2})\.(\d{1,2})\.(\d{4})$/.exec((de || "").trim());
  return m ? `${m[3]}-${m[2].padStart(2, "0")}-${m[1].padStart(2, "0")}` : "";
}
function isoNachDe(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec((iso || "").trim());
  return m ? `${m[3]}.${m[2]}.${m[1]}` : "";
}

function mailFormularZeigen(s) {
  const p = $("#mailForm");
  p.classList.remove("hidden");
  p.innerHTML = `
    <h3>Termin-Anfrage an ${esc(s.name)}</h3>
    <div class="formgrid">
      <label>An — Empfänger aus dem Schuldatensatz
        <input id="m_an" type="email" readonly>
      </label>
      <label>Reply-To — hierhin antwortet die Schule
        <input id="m_replyto" type="email">
      </label>
      <label>Betreff
        <input id="m_betreff" type="text">
      </label>
    </div>
    <label style="margin-top:10px">Nachricht
      <span class="muted klein">Platzhalter sind schon durch die Schuldaten ersetzt — hier direkt änderbar.</span>
      <textarea id="m_text" class="mail" spellcheck="false"></textarea>
    </label>
    <div class="btnrow" style="margin-top:10px">
      <button id="m_vorlage" type="button" class="ghost">Vorschau neu laden</button>
      <button id="m_senden" type="button" class="primary">Senden</button>
      <button id="m_abort" type="button" class="ghost">Schließen</button>
    </div>
    <div id="m_msg"></div>`;
  async function ladeVorschau() {
    try {
      const d = await api(`/api/admin/schulen/${encodeURIComponent(s.bsn)}/anfrage/vorschau`);
      $("#m_an").value = d.an || "";
      $("#m_replyto").value = d.reply_to || "";
      $("#m_betreff").value = d.betreff || "";
      $("#m_text").value = d.text || "";
      if (!d.hat_email) {
        meldung($("#m_msg"), "Diese Schule hat keine E-Mail-Adresse hinterlegt.", false);
      }
    } catch (e) { meldung($("#m_msg"), e.message, false); }
  }
  ladeVorschau();
  $("#m_abort").onclick = () => p.classList.add("hidden");
  $("#m_vorlage").onclick = ladeVorschau;
  $("#m_senden").onclick = async () => {
    const msg = $("#m_msg");
    const btn = $("#m_senden");
    btn.disabled = true;
    try {
      await api(`/api/admin/schulen/${encodeURIComponent(s.bsn)}/anfrage`, {
        method: "POST",
        body: JSON.stringify({
          betreff: $("#m_betreff").value,
          text: $("#m_text").value,
          reply_to: $("#m_replyto").value.trim(),
        }),
      });
      meldung(msg, "Mail gesendet ✓");
      p.classList.add("hidden");
      schuleDetailZeigen(await api(`/api/admin/schulen/${encodeURIComponent(s.bsn)}?mit_termine=1`));
    } catch (e) { meldung(msg, e.message, false); }
    btn.disabled = false;
  };
}

/* Sammel-Mail an mehrere Schulen: erst prüfen, dann senden */
function batchErgebnisZeigen(d, msgEl) {
  const zeilen = (d.ergebnisse || []).map((e) => `<tr>
      <td>${esc(e.schule || e.bsn)}</td>
      <td class="klein">${esc(e.an || "—")}</td>
      <td>${e.ok ? '<span class="badge ok">gesendet</span>' : `<span class="badge off">nicht gesendet</span>`}</td>
      <td class="klein">${esc(e.grund || "")}</td>
    </tr>`).join("");
  $("#batchErgebnis").innerHTML = `<p style="margin:8px 0 4px">
      ${d.trocken ? "Prüflauf" : "Versand"}: <strong>${d.gesendet}</strong> von ${d.ausgewaehlt} zugestellt
      ${d.uebersprungen ? `· <span class="rot">${d.uebersprungen} nicht gesendet</span>` : ""}
      ${d.abbruch ? `<br><span class="rot">${esc(d.abbruch)}</span>` : ""}</p>
    <table><thead><tr><th>Schule</th><th>Empfänger</th><th>Status</th><th>Grund</th></tr></thead>
    <tbody>${zeilen}</tbody></table>`;
  if (msgEl) meldung(msgEl, d.trocken
    ? `${d.gesendet} Empfänger geprüft — es wurde nichts gesendet.`
    : `${d.gesendet} Mails gesendet${d.uebersprungen ? `, ${d.uebersprungen} nicht` : ""}.`,
    d.gesendet > 0 || d.trocken);
}

async function sammelMailFenster(bsns) {
  if (!bsns.length) return;
  const p = $("#schulBatchForm");
  p.classList.remove("hidden");
  p.innerHTML = `
    <h3>Termin-Anfrage an ${bsns.length} ausgewählte Schulen</h3>
    <p class="muted" style="margin-top:0">Platzhalter werden je Schule ersetzt.
      Mit „Empfänger prüfen" siehst du vorab, wer angeschrieben wird und wer keine
      E-Mail-Adresse hat — dabei geht nichts raus.</p>
    <div class="formgrid">
      <label>Reply-To — hierhin antworten die Schulen
        <input id="batchReplyTo" type="email"></label>
      <label>Betreff
        <input id="batchBetreff" type="text"></label>
    </div>
    <label style="margin-top:10px">Nachricht
      <span class="muted klein">Platzhalter: {schule} {schulform} {bezirk} {jahr}</span>
      <textarea id="batchText" class="mail" spellcheck="false"></textarea></label>
    <div class="btnrow">
      <button id="batchPruefen" type="button">Empfänger prüfen (keine Mail senden)</button>
      <button id="batchSenden" type="button" class="primary">Jetzt senden</button>
      <button id="batchAbort" type="button" class="ghost">Schließen</button>
      <span id="batchMsg" class="msg"></span>
    </div>
    <div id="batchErgebnis"></div>`;
  try {
    const s = await api("/api/admin/settings");
    $("#batchBetreff").value = s.mail_betreff || "";
    $("#batchText").value = s.mail_text || "";
    $("#batchReplyTo").value = s.smtp_reply_to || "";
  } catch (e) { meldung($("#batchMsg"), e.message, false); }

  const koerper = (trocken) => JSON.stringify({
    bsn: bsns,
    betreff: $("#batchBetreff").value,
    text: $("#batchText").value,
    reply_to: $("#batchReplyTo").value.trim(),
    trocken,
  });
  $("#batchAbort").onclick = () => p.classList.add("hidden");
  $("#batchPruefen").onclick = async () => {
    const btn = $("#batchPruefen");
    btn.disabled = true;
    try {
      batchErgebnisZeigen(await api("/api/admin/schulen/mail-batch",
        { method: "POST", body: koerper(true) }), $("#batchMsg"));
    } catch (e) { meldung($("#batchMsg"), e.message, false); }
    btn.disabled = false;
  };
  $("#batchSenden").onclick = async () => {
    const btn = $("#batchSenden");
    if (!confirm(`Jetzt ${bsns.length} Schulen anschreiben?`)) return;
    btn.disabled = true;
    try {
      const d = await api("/api/admin/schulen/mail-batch",
        { method: "POST", body: koerper(false) });
      batchErgebnisZeigen(d, $("#batchMsg"));
      loadSchulen();
      if (typeof loadMail === "function") loadMail();
    } catch (e) { meldung($("#batchMsg"), e.message, false); }
    btn.disabled = false;
  };
}

/* Sammel-Recherche für die ausgewählten Schulen */
async function sammelRecherche(bsns) {
  if (!bsns.length) return;
  const msg = $("#schulBatchMsg");
  msg.className = "msg";
  msg.textContent = `Recherche für ${bsns.length} Schulen wird gestartet …`;
  try {
    const r = await api("/api/admin/recherche/lauf", {
      method: "POST",
      body: JSON.stringify({ bsn: bsns, dry_run: $("#rechercheDry") ? $("#rechercheDry").checked : false }),
    });
    meldung(msg, `Lauf für ${r.anzahl_auswahl || bsns.length} ausgewählte Schulen gestartet` +
      `${r.dry_run ? " (Probelauf)" : ""}. Ergebnisse in der Recherche-Tabelle.`);
    setTimeout(() => { if (typeof loadRecherche === "function") loadRecherche(); }, 8000);
  } catch (e) { meldung(msg, e.message, false); }
}

/* Schulen-Liste: Klicks (Zeile + Aktionen) */
$("#schuleListe").addEventListener("click", async (ev) => {
  const box = ev.target.closest("input.schulwahl");
  if (box) {
    ev.stopPropagation();
    const tr = box.closest("tr.schule");
    if (box.checked) { schulAuswahl.add(box.dataset.bsn); tr.classList.add("gewaehlt"); }
    else { schulAuswahl.delete(box.dataset.bsn); tr.classList.remove("gewaehlt"); }
    $("#schulAlleBox").checked = false;
    schulAuswahlZaehlen();
    return;
  }
  const btn = ev.target.closest("button[data-act]");
  const zeile = ev.target.closest("tr.schule");
  if (btn) {
    ev.stopPropagation();
    const bsn = btn.dataset.bsn;
    const act = btn.dataset.act;
    try {
      if (act === "oeffnen") {
        schuleDetailZeigen(await api(`/api/admin/schulen/${encodeURIComponent(bsn)}?mit_termine=1`));
      } else if (act === "mail") {
        const s = await api(`/api/admin/schulen/${encodeURIComponent(bsn)}?mit_termine=1`);
        schuleDetailZeigen(s);
        mailFormularZeigen(s);
      }
    } catch (e) { fehlerZeigen(e.message); }
    return;
  }
  if (zeile && !ev.target.closest("a")) {
    try {
      schuleDetailZeigen(await api(`/api/admin/schulen/${encodeURIComponent(zeile.dataset.bsn)}?mit_termine=1`));
    } catch (e) { fehlerZeigen(e.message); }
  }
});

/* Schulen-Detail: Termin-Aktionen (Freigabe/Edit/Löschen) */
$("#schuleDetailInhalt").addEventListener("click", async (ev) => {
  const btn = ev.target.closest("button[data-act]");
  if (!btn) return;
  const tid = btn.dataset.tid;
  const act = btn.dataset.act;
  const bsn = $("#schuleDetail").dataset.bsn; // aktuell geöffnete Schule
  try {
    if (act === "freigeben") {
      await api(`/api/admin/termine/${tid}`, { method: "PUT", body: JSON.stringify({ status: "bestaetigt" }) });
    } else if (act === "zurueckziehen") {
      await api(`/api/admin/termine/${tid}`, { method: "PUT", body: JSON.stringify({ status: "ungeprueft" }) });
    } else if (act === "del") {
      if (!confirm("Termin wirklich löschen?")) return;
      await api(`/api/admin/termine/${tid}`, { method: "DELETE" });
    } else if (act === "edit") {
      const t = await api(`/api/admin/termine/${tid}`);
      const schule = await api(`/api/admin/schulen/${encodeURIComponent(t.schule_bsn)}`);
      await terminFormularZeigen(schule, t);
      return; // Detail nicht neu laden (Formular bleibt offen)
    }
    // Nach Aktion: Detail der Schule neu laden (Termin-Liste aktualisiert)
    schuleDetailZeigen(await api(`/api/admin/schulen/${encodeURIComponent(bsn)}?mit_termine=1`));
  } catch (e) { fehlerZeigen(e.message); }
});

/* Suche/Filter (Schulen) */
$("#schulSuche").addEventListener("input", () => {
  schulFilter.q = $("#schulSuche").value.trim();
  loadSchulen();
});
$("#schulBezirk").addEventListener("change", () => {
  schulFilter.bezirk = $("#schulBezirk").value;
  loadSchulen();
});
$("#schulForm").addEventListener("change", () => {
  schulFilter.schulform = $("#schulForm").value;
  loadSchulen();
});
async function fuelleSchulFilter() {
  // Bezirke mit denselben Bezeichnungen wie im Frontend, Schulformen aus dem Bestand
  try {
    const f = await api("/api/admin/schul-filter");
    const optionen = (liste, leer) => '<option value="">' + leer + '</option>' +
      liste.map((x) => `<option value="${esc(x.key ?? x)}">${esc(x.label ?? x)}</option>`).join("");
    const bezirke = optionen(f.bezirke || [], "Alle Bezirke");
    const formen = optionen((f.schulformen || []).map((s) => ({ key: s, label: s })), "Alle Schulformen");
    for (const id of ["schulBezirk", "rechercheBezirk"]) { if ($("#" + id)) $("#" + id).innerHTML = bezirke; }
    for (const id of ["schulForm", "rechercheForm"]) { if ($("#" + id)) $("#" + id).innerHTML = formen; }
  } catch (e) { /* Filter optional — Fehler nicht blockierend */ }

  // Gemeinsame Filter der Recherche spiegeln beim Start (siehe rechercheStart)
  ["schulOhneTermin", "schulMitEmail"].forEach((id) => {
    const el = $("#" + id);
    if (el) el.addEventListener("change", () => {
      schulFilter.ohne_termin = $("#schulOhneTermin").checked;
      schulFilter.mit_email = $("#schulMitEmail").checked;
      loadSchulen();
    });
  });
  $("#schulAlleWaehlen").onclick = () => {
    $("#schuleListe").querySelectorAll("tr.schule").forEach((tr) => {
      schulAuswahl.add(tr.dataset.bsn);
      tr.classList.add("gewaehlt");
      const box = tr.querySelector("input.schulwahl");
      if (box) box.checked = true;
    });
    schulAuswahlZaehlen();
  };
  $("#schulAlleBox").onchange = () => {
    if ($("#schulAlleBox").checked) $("#schulAlleWaehlen").click();
    else $("#schulKeineWaehlen").click();
  };
  $("#schulKeineWaehlen").onclick = () => {
    schulAuswahl.clear();
    $("#schuleListe").querySelectorAll("input.schulwahl").forEach((b) => { b.checked = false; });
    $("#schuleListe").querySelectorAll("tr.schule").forEach((tr) => tr.classList.remove("gewaehlt"));
    schulAuswahlZaehlen();
  };
  $("#schulMailBatch").onclick = () => sammelMailFenster([...schulAuswahl]);
  $("#schulRechercheBatch").onclick = () => sammelRecherche([...schulAuswahl]);
  schulAuswahlZaehlen();
}

/* ---------- Termine: ALLE Events (gescrapt + manuell) ---------- */
function evDatumKurz(e) {
  // start_local "2026-09-12T18:00:00" → "12.09.2026"
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}:\d{2})?/.exec(e.start_local || "");
  if (!m) return "—";
  const zeit = m[4] ? ` ${m[4]} Uhr` : "";
  return `${m[3]}.${m[2]}.${m[1]}${zeit}`;
}
function evTags(e) {
  const t = e.kategorien || [];
  if (!t.length) return "<span class=\"muted\">—</span>";
  // Quellen-Kategorien sind Kurz-IDs (z. B. "fest") → Template-Namen anzeigen
  return t.map((x) => {
    const tag = tagListe.find((tg) => tg.id === x || tg.name === x);
    return `<span class="chip">${esc(tag ? tag.name : x)}</span>`;
  }).join(" ");
}
function eventZeile(e, mitQuelle = false) {
  const status = e.manuell
    ? '<span class="badge warn" title="Von dir bearbeitet — Scrape überschreibt nicht mehr">manuell gepflegt</span>'
    : '<span class="badge">gescrapt</span>';
  return `<tr data-ev-id="${esc(e.id)}">
    <td style="white-space:nowrap">${evDatumKurz(e)}</td>
    ${mitQuelle ? `<td>${esc(e.quelle)}</td>` : ""}
    <td><strong>${esc(e.titel)}</strong>${e.beschreibung_kurz ? `<br/><span class="klein">${esc(e.beschreibung_kurz.slice(0, 80))}${e.beschreibung_kurz.length > 80 ? "…" : ""}</span>` : ""}</td>
    <td>${esc(e.ort || "—")}</td>
    <td>${evTags(e)}</td>
    <td>${status}</td>
    <td><div class="btnrow">
      <button data-evid="${esc(e.id)}" data-act="edit">Bearbeiten</button>
      ${e.quelle === "manuell" ? `<button data-evid="${esc(e.id)}" data-tid="${esc(e.source_event_id)}" data-act="del" class="danger">Löschen</button>` : ""}
    </div></td>
  </tr>`;
}

let alleTermine = [];
async function loadAlleTermine() {
  const q = $("#termineFilterQuelle")?.value || "";
  const status = $("#termineFilterStatus")?.value || "";
  const suche = $("#termineSuche")?.value.trim() || "";
  const qs = new URLSearchParams();
  if (q) qs.set("quelle", q);
  if (suche) qs.set("q", suche);
  const tb = $("#termineListe tbody");
  tb.innerHTML = '<tr><td colspan="7" class="muted">Lade…</td></tr>';
  try {
    alleTermine = await api("/api/admin/events?" + qs.toString());
    tb.innerHTML = alleTermine.length
      ? alleTermine.map((e) => eventZeile(e, true)).join("")
      : '<tr><td colspan="7" class="muted">Keine Termine gefunden.</td></tr>';
    const z = $("#termineZaehler");
    if (z) z.textContent = alleTermine.length + " Termine";
  } catch (e) { fehlerZeigen(`Termine: ${e.message}`); }
}
["termineFilterQuelle", "termineFilterStatus", "termineSuche"].forEach((id) => {
  const el = $("#" + id);
  if (el) el.addEventListener("change", loadAlleTermine);
});
$("#termineSuche")?.addEventListener("input", debounce(loadAlleTermine, 300));

function debounce(fn, ms) {
  let t;
  return () => { clearTimeout(t); t = setTimeout(fn, ms); };
}

/* Event-Bearbeitungs-Formular (alle Termine; speichert als manuell gepflegt) */
let tagListe = []; // [id, name, farbe, template]
async function ladeTags() {
  try {
    tagListe = await api("/api/admin/tags");
  } catch { tagListe = []; }
  return tagListe;
}
let eventFormularOffen = false;
async function eventFormularZeigen(ev) {
  eventFormularOffen = true;
  if (!tagListe.length) await ladeTags();
  if (!window._titelVorschlaege) {
    try { window._titelVorschlaege = await api("/api/admin/termine/vorschlaege"); }
    catch { window._titelVorschlaege = []; }
  }
  const vorschlaege = (window._titelVorschlaege || [])
    .map((x) => `<option value="${esc(x)}"></option>`).join("");
  const panel = $("#eventPanel") || document.createElement("div");
  panel.id = "eventPanel";
  panel.className = "panel";
  $("#tab-termine").prepend(panel);
  panel.classList.remove("hidden");
  const gewaehlt = new Set(ev.kategorien || []);
  const tagChips = tagListe.map((t) => {
    const an = gewaehlt.has(t.name) || gewaehlt.has(t.id);
    return `<button type="button" class="tagbtn${an ? " aktiv" : ""}" data-tagname="${esc(t.name)}"
       style="border-color:${esc(t.farbe || "#888")};color:${esc(t.farbe || "#ccc")}">${esc(t.name)}</button>`;
  }).join("");
  const [datumIso, zeit] = (() => {
    const m = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})?/.exec(ev.start_local || "");
    if (!m) return ["", ""];
    return [m[1], m[2] || ""];
  })();
  panel.innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:center;gap:8px">
      <h3 style="margin:0">Termin bearbeiten${ev.quelle === "manuell" ? " (Schul-Termin)" : ` — ${esc(ev.quelle)}`}</h3>
      <button id="evClose" type="button" class="ghost">✕</button>
    </div>
    <div class="muted" style="margin:6px 0">Nach dem Speichern gilt der Termin als <b>manuell gepflegt</b> —
      ein Scrape überschreibt deine Änderungen nicht mehr.</div>
    <div class="formgrid">
      <label style="grid-column:1/-1">Titel<input id="ev_titel" list="titelVorschlaegeEv" value="${esc(ev.titel)}" /></label>
      <label>Datum<input id="ev_datum" type="date" value="${datumIso}" /></label>
      <label>Uhrzeit (HH:MM, leer = ganztags)<input id="ev_zeit" type="time" value="${zeit}" /></label>
      <label>Ort<input id="ev_ort" value="${esc(ev.ort || "")}" /></label>
      <label>Bezirk<input id="ev_bezirk" value="${esc(ev.bezirk || "")}" /></label>
      <label style="grid-column:1/-1">Kurzbeschreibung
        <textarea id="ev_beschreibung" rows="2" style="font-family:inherit">${esc(ev.beschreibung_kurz || "")}</textarea></label>
      <label style="grid-column:1/-1">Tags
        <div class="tagwahl" id="ev_tags"></div></label>
      <label style="flex-direction:row;align-items:center;gap:8px"><input id="ev_kostenlos" type="checkbox" ${ev.kostenlos ? "checked" : ""} /> Kostenlos</label>
    </div>
    <datalist id="titelVorschlaegeEv">${vorschlaege}</datalist>
    <div class="btnrow" style="margin-top:12px">
      <button id="ev_save" type="button" class="primary">Speichern</button>
      <button id="ev_abort" type="button" class="ghost">Abbrechen</button>
      <span id="ev_msg"></span>
    </div>`;
  const chipContainer = $("#ev_tags");
  chipContainer.innerHTML = tagChips || '<span class="muted">Noch keine Tags angelegt (Einstellungen → Tags).</span>';
  chipContainer.querySelectorAll(".tagbtn").forEach((b) => {
    b.onclick = () => {
      b.classList.toggle("aktiv");
    };
  });
  const schliessen = () => { panel.classList.add("hidden"); eventFormularOffen = false; };
  $("#evClose").onclick = schliessen;
  $("#ev_abort").onclick = schliessen;
  $("#ev_save").onclick = async () => {
    const msg = $("#ev_msg");
    const datumIso = $("#ev_datum").value.trim();
    const mDatum = /^(\d{4})-(\d{2})-(\d{2})$/.exec(datumIso);
    if (!mDatum) { meldung(msg, "Bitte ein Datum wählen.", false); return; }
    const zeitRaw = $("#ev_zeit").value.trim();
    const aktiv = Array.from(chipContainer.querySelectorAll(".tagbtn.aktiv")).map((b) => b.dataset.tagname);
    // Kanonische Form: bekannte Tags als id (Kurzform), unbekannte als Name
    const kanonisch = aktiv.map((name) => {
      const tag = tagListe.find((t) => t.name === name || t.id === name);
      return tag ? tag.id : name;
    });
    const startLocal = `${mDatum[1]}-${mDatum[2]}-${mDatum[3]}T${zeitRaw || "00:00"}:00`;
    const body = {
      titel: $("#ev_titel").value.trim(),
      start_local: startLocal,
      ort: $("#ev_ort") ? $("#ev_ort").value.trim() : null,
      bezirk: $("#ev_bezirk") ? $("#ev_bezirk").value.trim() : null,
      beschreibung_kurz: $("#ev_beschreibung") ? $("#ev_beschreibung").value.trim() : null,
      kategorien: kanonisch,
      kostenlos: $("#ev_kostenlos") ? $("#ev_kostenlos").checked : false,
    };
    try {
      if (ev.quelle === "manuell") {
        // Spiegel eines termine_manuell → über dessen API (syncen selbst)
        await api(`/api/admin/termine/${ev.source_event_id}`, {
          method: "PUT",
          body: JSON.stringify({ titel: body.titel, start_datum: `${mDatum[3]}.${mDatum[2]}.${mDatum[1]}`,
            start_zeit: zeitRaw || null, ort: body.ort, beschreibung: body.beschreibung_kurz,
            kategorie_id: null }),
        });
      } else {
        await api(`/api/admin/events/${encodeURIComponent(ev.id)}`, {
          method: "PUT", body: JSON.stringify(body),
        });
      }
      schliessen();
      loadAlleTermine();
    } catch (e) { meldung(msg, e.message, false); }
  };
}

/* Termine-Tab: Quelle-Filter-Optionen füllen */
async function fuelleTerminQuellen() {
  try {
    const qs = await api("/api/admin/sources");
    $("#termineFilterQuelle").innerHTML = '<option value="">Alle Quellen</option>' +
      qs.filter((q) => q.aktiv).map((q) => `<option value="${esc(q.quelle)}">${esc(q.name)}</option>`).join("") +
      '<option value="manuell">Schulen (manuell)</option>';
  } catch { /* optional */ }
}

/* Termine-Tab Aktionen (Delegation) */
$("#termineListe").addEventListener("click", async (ev) => {
  const btn = ev.target.closest("button[data-act]");
  if (!btn) return;
  const evid = btn.dataset.evid;
  const act = btn.dataset.act;
  try {
    if (act === "del") {
      if (!confirm("Termin wirklich löschen? Der nächste Scrape legt gescrapte Termine neu an — manuell gepflegte bleiben gelöscht.")) return;
      if (btn.dataset.tid) {
        await api(`/api/admin/termine/${btn.dataset.tid}`, { method: "DELETE" });
      }
      loadAlleTermine();
      return;
    }
    if (act === "edit") {
      const ev = alleTermine.find((x) => x.id === evid) ||
        (await api("/api/admin/events")).find((x) => x.id === evid);
      if (ev) eventFormularZeigen(ev);
      return;
    }
    loadAlleTermine();
  } catch (e) { fehlerZeigen(e.message); }
});

/* ---------- Tags (Einstellungen) ---------- */
async function loadTags() {
  const tb = $("#tagTabelle tbody");
  tb.innerHTML = "";
  try {
    const list = await api("/api/admin/tags");
    tagListe = list;
    if (!list.length) { tb.innerHTML = '<tr><td colspan="4" class="muted">Noch keine Tags.</td></tr>'; return; }
    list.forEach((k) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `<td><strong>${esc(k.name)}</strong> <span class="klein">(${esc(k.id)})</span></td>
        <td><span style="display:inline-block;width:18px;height:18px;border-radius:4px;background:${esc(k.farbe || "#888")};border:1px solid var(--border)"></span> ${esc(k.farbe || "—")}</td>
        <td>${k.template ? '<span class="badge ok">Template</span>' : '<span class="badge">eigen</span>'}</td>
        <td><div class="btnrow">
          <button data-tid2="${esc(k.id)}" data-act="edit">Bearbeiten</button>
          ${k.template ? "" : `<button data-tid2="${esc(k.id)}" data-act="del" class="danger">Löschen</button>`}
        </div></td>`;
      tb.appendChild(tr);
    });
  } catch (e) { fehlerZeigen(`Tags: ${e.message}`); }
}

function tagFormularZeigen(k = null) {
  const p = $("#tagPanel");
  p.classList.remove("hidden");
  p.innerHTML = `
    <h3>${k ? `Tag bearbeiten: ${esc(k.name)}` : "Eigenes Tag anlegen"}</h3>
    <div class="formgrid" style="max-width:640px">
      <label>Schlüssel (nur bei Neuanlage)<input id="t_id" ${k ? "disabled" : ""} value="${esc(k ? k.id : "")}" placeholder="z. B. wandern" /></label>
      <label>Name<input id="t_name" value="${esc(k ? k.name : "")}" placeholder="Wandern" /></label>
      <label>Farbe (Hex)<input id="t_farbe" value="${esc(k ? k.farbe || "" : "")}" placeholder="#2ea043" /></label>
      <label>Sortierung<input id="t_sort" type="number" value="${k ? k.sort ?? 0 : 0}" /></label>
    </div>
    <div class="btnrow" style="margin-top:10px">
      <button id="t_save" type="button" class="primary">Speichern</button>
      <button id="t_abort" type="button" class="ghost">Abbrechen</button>
    </div>
    <div id="t_msg"></div>`;
  $("#t_abort").onclick = () => p.classList.add("hidden");
  $("#t_save").onclick = async () => {
    const msg = $("#t_msg");
    const body = { name: $("#t_name").value.trim(), farbe: $("#t_farbe").value.trim() || null, sort: parseInt($("#t_sort").value, 10) || 0 };
    try {
      if (k) await api(`/api/admin/tags/${encodeURIComponent(k.id)}`, { method: "PUT", body: JSON.stringify(body) });
      else { body.id = $("#t_id").value.trim(); await api("/api/admin/tags", { method: "POST", body: JSON.stringify(body) }); }
      p.classList.add("hidden");
      loadTags();
    } catch (e) { meldung(msg, e.message, false); }
  };
}
$("#tagNeu").onclick = () => tagFormularZeigen(null);
$("#tagTabelle").addEventListener("click", async (ev) => {
  const btn = ev.target.closest("button[data-act]");
  if (!btn) return;
  const kid = btn.dataset.tid2;
  try {
    if (btn.dataset.act === "edit") {
      const k = (await api("/api/admin/tags")).find((x) => x.id === kid);
      tagFormularZeigen(k);
    } else if (btn.dataset.act === "del") {
      if (!confirm(`Tag „${kid}“ löschen? Bereits vergebene Tags an Terminen bleiben erhalten.`)) return;
      await api(`/api/admin/tags/${encodeURIComponent(kid)}`, { method: "DELETE" });
      loadTags();
    }
  } catch (e) { fehlerZeigen(e.message); }
});

/* ---------- LLM-Endpunkt + Schul-Recherche (Change 010) ---------- */
let llmKonfig = {};

async function loadLlm() {
  try {
    llmKonfig = await api("/api/admin/llm");
    const s = await api("/api/admin/settings");
    $("#setLlmBase").value = llmKonfig.llm_base_url || "";
    $("#setLlmModel").value = llmKonfig.llm_model || "";
    $("#setLlmTimeout").value = llmKonfig.llm_timeout_s || "";
    $("#setLlmExtra").value = llmKonfig.llm_extra_json || "";
    $("#setLlmMax").value = s.recherche_max_schulen || "20";
    $("#setRechercheAktiv").checked =
      ["1", "true", "ja", "on"].includes(String(s.recherche_aktiv || "0").trim().toLowerCase());
    if (llmKonfig.llm_api_key_gesetzt) {
      $("#setLlmKey").placeholder = "gespeichert — leer lassen zum Behalten";
    }
  } catch (e) { fehlerZeigen(`LLM-Einstellungen: ${e.message}`); }
}

$("#llmBtn").onclick = async () => {
  const msg = $("#llmMsg");
  const body = {
    llm_base_url: $("#setLlmBase").value.trim(),
    llm_model: $("#setLlmModel").value.trim(),
    llm_timeout_s: $("#setLlmTimeout").value.trim(),
    llm_extra_json: $("#setLlmExtra").value.trim(),
    recherche_aktiv: $("#setRechercheAktiv").checked ? "1" : "0",
    recherche_max_schulen: $("#setLlmMax").value.trim() || "20",
  };
  const key = $("#setLlmKey").value;
  if (key !== "") body.llm_api_key = key;
  try {
    await api("/api/admin/settings", { method: "PUT", body: JSON.stringify(body) });
    $("#setLlmKey").value = "";
    meldung(msg, "Gespeichert — gilt für den nächsten Lauf.");
  } catch (e) { meldung(msg, e.message, false); }
};

$("#llmTestBtn").onclick = async () => {
  const msg = $("#llmMsg");
  const box = $("#llmTestergebnis");
  meldung(msg, "Teste Endpunkt …");
  try {
    const r = await api("/api/admin/llm/test", {
      method: "POST",
      body: JSON.stringify({
        llm_base_url: $("#setLlmBase").value.trim(),
        llm_model: $("#setLlmModel").value.trim(),
        llm_timeout_s: $("#setLlmTimeout").value.trim(),
        llm_extra_json: $("#setLlmExtra").value.trim(),
      }),
    });
    box.classList.remove("hidden");
    if (r.ok) {
      meldung(msg, `Endpunkt antwortet (${r.dauer_s}s).`);
      box.innerHTML = `<p class="hinweis" style="margin:0 0 6px">Antwort von
        <code>${esc(r.basis_url || "")}</code> · Modell <code>${esc(r.modell || "")}</code>
        · ${r.dauer_s}s · JSON erkannt: ${r.json_erkannt ? "ja" : "nein"}</p>
        <pre class="klein" style="white-space:pre-wrap;margin:0">${esc(r.antwort || "")}</pre>`;
    } else {
      meldung(msg, "Endpunkt antwortet nicht.", false);
      box.innerHTML = `<p class="fehler" style="margin:0">${esc(r.fehler || "Unbekannter Fehler")}</p>`;
    }
  } catch (e) {
    meldung(msg, e.message, false);
  }
};

async function loadRecherche() {
  const tb = $("#rechercheTabelle tbody");
  const ohne = $("#rechercheOhne").checked;
  try {
    const d = await api(`/api/admin/recherche?nur_ohne_fund=${ohne ? "true" : "false"}`);
    const lauf = await api("/api/admin/recherche/letzter-lauf");
    const box = $("#rechercheLauf");
    if (lauf.vorhanden) {
      const st = Object.entries(lauf.status || {}).map(([k, v]) => `${esc(k)}: ${v}`).join(" · ");
      box.classList.remove("hidden");
      box.innerHTML = `<p style="margin:0 0 4px"><strong>Letzter Lauf</strong>
        ${esc(lauf.start || "")} · ${lauf.geprueft} Schulen geprüft ·
        ${lauf.llm_calls} LLM-Aufrufe · <strong>${lauf.belegt} belegte Vorschläge</strong> ·
        ${lauf.dauer_s}s${lauf.dry_run ? " · Probelauf (nichts eingetragen)" : ""}</p>
        <p class="muted" style="margin:0">Status: ${st || "—"}${
          Object.keys(lauf.verworfen || {}).length
            ? ` · verworfen: ${Object.entries(lauf.verworfen).map(([k, v]) => `${esc(k)}×${v}`).join(", ")}`
            : ""}</p>`;
    } else {
      box.classList.add("hidden");
    }
    tb.innerHTML = "";
    if (!d.schulen.length) {
      tb.innerHTML = '<tr><td colspan="5" class="muted">Keine Schulen mit Website im Stamm.</td></tr>';
      return;
    }
    d.schulen.forEach((s) => {
      const tr = document.createElement("tr");
      const stand = s.recherche_am ? esc(s.recherche_am.slice(0, 16).replace("T", " ")) : "nie geprüft";
      const badge = { gefunden: "ok", keinFund: "", keinIndiz: "", abrufFehler: "warn", fehler: "warn" }[s.recherche_status] ?? "";
      tr.innerHTML = `<td><strong>${esc(s.name)}</strong>
          <div class="klein muted">${esc(s.schulform || "")} · ${esc(s.bsn)} ·
          <a href="${esc(s.website)}" target="_blank" rel="noopener">Website ↗</a></div></td>
        <td>${esc(s.bezirk || "")}</td>
        <td>${stand}<div><span class="badge ${badge}">${esc(s.recherche_status || "—")}</span></div></td>
        <td>${s.n_offen ? `<span class="badge ok">${s.n_offen} ungeprüft</span>` : "—"}</td>
        <td class="klein">${esc(s.recherche_notiz || "")}
          ${s.letzte_url ? `<div><a href="${esc(s.letzte_url)}" target="_blank" rel="noopener">Fundstelle ↗</a></div>` : ""}
          ${s.letzter_grund ? `<div class="muted">verworfen: ${esc(s.letzter_grund)}</div>` : ""}</td>`;
      tb.appendChild(tr);
    });
  } catch (e) { fehlerZeigen(`Recherche: ${e.message}`); }
}

$("#rechercheReload").onclick = () => loadRecherche();
$("#rechercheOhne").onchange = () => loadRecherche();
$("#rechercheStart").onclick = async () => {
  const msg = $("#rechercheMsg");
  try {
    const r = await api("/api/admin/recherche/lauf", {
      method: "POST",
      body: JSON.stringify({
        limit: parseInt($("#rechercheUmfang").value, 10),
        dry_run: $("#rechercheDry").checked,
        bezirk: $("#rechercheBezirk") ? $("#rechercheBezirk").value : "",
        schulform: $("#rechercheForm") ? $("#rechercheForm").value : "",
        ohne_termin: $("#rechercheOhneTermin") ? $("#rechercheOhneTermin").checked : false,
        bsn: ($("#rechercheNurAuswahl") && $("#rechercheNurAuswahl").checked)
          ? [...schulAuswahl] : [],
      }),
    });
    meldung(msg, `Lauf gestartet (${r.anzahl_auswahl || r.limit} Schulen${r.dry_run ? ", Probelauf" : ""}). ` +
      "Er antwortet seitenweise — Liste in ein paar Sekunden aktualisieren.");
    setTimeout(loadRecherche, 8000);
  } catch (e) { meldung(msg, e.message, false); }
};

/* ---------- E-Mail: Versand und Empfang (Change 013) ---------- */
let mailStatus = {};

function mailPanelZeigen(d) {
  const box = $("#mailPanel");
  box.classList.remove("hidden");
  const letzte = (d.letzte || []).map((m) => `<li class="klein">${esc((m.zeitpunkt || "").slice(0, 16))}
      ${m.ok ? "✓" : '<span class="rot">✗</span>'} an ${esc(m.an)}
      ${m.schule_bsn ? "· " + esc(m.schule_bsn) : ""}
      ${m.fehler ? `<span class="rot">· ${esc(m.fehler)}</span>` : ""}</li>`).join("");
  box.innerHTML = `<p style="margin:0 0 6px">
      Absender <strong>${esc(d.adresse)}</strong> · Reply-To <strong>${esc(d.reply_to)}</strong></p>
    <p style="margin:0 0 6px">Versand: heute ${d.versand.heute}
      · letzte Stunde ${d.versand.diese_stunde} · gesamt ${d.versand.gesamt}
      ${d.versand.fehler_gesamt ? `· <span class="rot">${d.versand.fehler_gesamt} Fehlversuche</span>` : ""}
      ${d.bremse ? `<br><span class="rot">${esc(d.bremse)}</span>` : ""}
      ${(d.fehlende_angaben || []).length
          ? `<br><span class="rot">Noch offen: ${esc(d.fehlende_angaben.join(", "))}</span>`
          : '<br><span class="gruen">Postfach ist vollständig eingerichtet.</span>'}</p>
    ${letzte ? `<p class="muted klein" style="margin:6px 0 2px">Letzte Mails:</p>
      <ul style="margin:0">${letzte}</ul>` : ""}
    <div id="mailNachrichten"></div>`;
}

async function loadMail() {
  try {
    mailStatus = await api("/api/admin/mail");
    const s = await api("/api/admin/settings");
    $("#setMailFrom").value = s.smtp_from || s.smtp_user || "";
    $("#setSmtpHost").value = s.smtp_host || "";
    $("#setSmtpPort").value = s.smtp_port || "465";
    $("#setSmtpVerschl").value = s.smtp_verschluesselung || "ssl";
    $("#setImapHost").value = s.imap_host || s.smtp_host || "";
    $("#setImapPort").value = s.imap_port || "993";
    $("#setImapVerschl").value = s.imap_verschluesselung || "ssl";
    $("#setMailReplyTo").value = s.smtp_reply_to || "";
    $("#setMailBetreff").value = s.mail_betreff || "";
    $("#setMailText").value = s.mail_text || "";
    $("#setMailAktiv").checked = ["1", "true", "ja", "on"].includes(
      (s.mail_aktiv || "0").trim().toLowerCase());
    $("#setMailMaxTag").value = s.mail_max_pro_tag ?? "40";
    $("#setMailMaxStunde").value = s.mail_absender_pro_stunde ?? "20";
    mailPanelZeigen(mailStatus);
  } catch (e) { fehlerZeigen(`E-Mail-Status: ${e.message}`); }
}

$("#mailSpeichern").onclick = async () => {
  const msg = $("#mailMsg");
  const body = {
    smtp_from: $("#setMailFrom").value.trim(),
    smtp_user: $("#setMailFrom").value.trim(),
    smtp_host: $("#setSmtpHost").value.trim(),
    smtp_port: $("#setSmtpPort").value,
    smtp_verschluesselung: $("#setSmtpVerschl").value,
    imap_host: $("#setImapHost").value.trim(),
    imap_port: $("#setImapPort").value,
    imap_verschluesselung: $("#setImapVerschl").value,
    smtp_reply_to: $("#setMailReplyTo").value.trim(),
    mail_betreff: $("#setMailBetreff").value,
    mail_text: $("#setMailText").value,
    mail_aktiv: $("#setMailAktiv").checked ? "1" : "0",
    mail_max_pro_tag: $("#setMailMaxTag").value,
    mail_absender_pro_stunde: $("#setMailMaxStunde").value,
  };
  const pass = $("#setMailPass").value;
  if (pass) body.smtp_pass = pass;
  try {
    await api("/api/admin/settings", { method: "PUT", body: JSON.stringify(body) });
    $("#setMailPass").value = "";
    meldung(msg, "E-Mail-Einstellungen gespeichert.");
    loadMail();
  } catch (e) { meldung(msg, e.message, false); }
};

$("#mailTesten").onclick = async () => {
  const msg = $("#mailMsg");
  msg.className = "msg";
  msg.textContent = "Verbindung wird geprüft …";
  const pass = $("#setMailPass").value;
  try {
    const d = await api("/api/admin/mail/test",
      { method: "POST", body: JSON.stringify(pass ? { smtp_pass: pass } : {}) });
    if (d.smtp.ok && d.imap.ok) {
      meldung(msg, `SMTP und IMAP: Anmeldung OK (${d.smtp.server}).`);
    } else {
      const teile = [];
      if (!d.smtp.ok) teile.push(`SMTP: ${d.smtp.fehler}`);
      if (!d.imap.ok) teile.push(`IMAP: ${d.imap.fehler}`);
      meldung(msg, teile.join(" · "), false);
    }
    loadMail();
  } catch (e) { meldung(msg, e.message, false); }
};

$("#mailTestmail").onclick = async () => {
  const msg = $("#mailMsg");
  msg.className = "msg";
  msg.textContent = "Testmail wird gesendet …";
  try {
    const d = await api("/api/admin/mail/testmail", { method: "POST", body: JSON.stringify({}) });
    meldung(msg, `Testmail an ${d.an} gesendet (Betreff: ${d.betreff}).`);
    loadMail();
  } catch (e) { meldung(msg, e.message, false); }
};

$("#mailAbrufen").onclick = async () => {
  const msg = $("#mailMsg");
  msg.className = "msg";
  msg.textContent = "Postfach wird gelesen …";
  try {
    const d = await api("/api/admin/mail/abrufen",
      { method: "POST", body: JSON.stringify({ limit: 20 }) });
    meldung(msg, `${d.anzahl} ungelesene Nachricht(en) geholt.`);
    const ziel = $("#mailNachrichten");
    if (ziel) {
      ziel.innerHTML = d.nachrichten.map((n) => `<div class="panel" style="margin-top:6px">
          <strong>${esc(n.betreff || "(ohne Betreff)")}</strong>
          <span class="muted klein">· ${esc(n.von)} · ${esc(n.datum)}</span>
          <pre class="klein" style="white-space:pre-wrap;margin:6px 0 0">${esc((n.text || "").slice(0, 1200))}</pre>
        </div>`).join("") || '<p class="muted">Keine ungelesenen Nachrichten.</p>';
    }
  } catch (e) { meldung(msg, e.message, false); }
};

/* ---------- Websuche / Brave-Kontingent (Change 012) ---------- */
let braveStatus = {};

function braveStatusZeigen(d) {
  const box = $("#bravePanel");
  box.classList.remove("hidden");
  const letzte = (d.letzte || []).map((a) => `<li class="klein">${esc(a.zeitpunkt.slice(0, 16))}
      HTTP ${esc(String(a.http_code))} · ${esc(String(a.treffer))} Treffer ·
      ${esc(a.query)}
      ${a.fehler ? `<span class="rot">· ${esc(a.fehler)}</span>` : ""}</li>`).join("");
  box.innerHTML = `<p style="margin:0 0 6px">
      <strong>${d.verbraucht_monat} von ${d.monats_limit}</strong> Anfragen diesen Monat
      (${d.rest_monat} frei) · heute ${d.verbraucht_heute}${d.tages_limit ? " von " + d.tages_limit : ""}
      · insgesamt ${d.verbraucht_gesamt} (≈ ${d.kosten_usd} $ laut Brave-Tarif)
      ${d.fehler_monat ? ` · <span class="rot">${d.fehler_monat} Fehlversuche im Monat</span>` : ""}</p>
    <p style="margin:0 0 6px">${d.budget_fehler
        ? `<span class="rot">${esc(d.budget_fehler)}</span>`
        : (d.aktiv ? "Websuche ist im Lauf aktiv." : "Websuche ist im Lauf ausgeschaltet.")}
      ${d.key_gesetzt ? "" : ' <span class="rot">Kein API-Key hinterlegt.</span>'}</p>
    ${letzte ? `<p class="muted klein" style="margin:6px 0 2px">Letzte Aufrufe:</p>
      <ul style="margin:0">${letzte}</ul>` : ""}`;
}

async function loadBrave() {
  try {
    braveStatus = await api("/api/admin/brave");
    const s = await api("/api/admin/settings");
    $("#setBraveMonat").value = s.brave_monat_limit || "900";
    $("#setBraveTag").value = s.brave_tages_limit ?? "30";
    $("#setBraveRate").value = s.brave_anfragen_pro_s || "1";
    $("#setBraveWdh").value = s.brave_wiederholung_tage ?? "30";
    $("#setBraveAktiv").checked = ["1", "true", "ja", "on"].includes(
      (s.brave_websuche_aktiv || "0").trim().toLowerCase());
    braveStatusZeigen(braveStatus);
  } catch (e) { fehlerZeigen(`Websuche-Status: ${e.message}`); }
}

$("#braveSpeichern").onclick = async () => {
  const msg = $("#braveMsg");
  const body = {
    brave_monat_limit: $("#setBraveMonat").value,
    brave_tages_limit: $("#setBraveTag").value,
    brave_anfragen_pro_s: $("#setBraveRate").value,
    brave_wiederholung_tage: $("#setBraveWdh").value,
    brave_websuche_aktiv: $("#setBraveAktiv").checked ? "1" : "0",
  };
  const key = $("#setBraveKey").value.trim();
  if (key) body.brave_api_key = key;
  try {
    await api("/api/admin/settings", { method: "PUT", body: JSON.stringify(body) });
    $("#setBraveKey").value = "";
    meldung(msg, "Websuche gespeichert.");
    loadBrave();
  } catch (e) { meldung(msg, e.message, false); }
};

$("#braveTesten").onclick = async () => {
  const msg = $("#braveMsg");
  msg.className = "msg";
  msg.textContent = "Testanfrage läuft …";
  const key = $("#setBraveKey").value.trim();
  try {
    const d = await api("/api/admin/brave/test",
      { method: "POST", body: JSON.stringify(key ? { brave_api_key: key } : {}) });
    if (!d.ok) { meldung(msg, `Fehlgeschlagen: ${d.fehler}`, false); }
    else { meldung(msg, `OK — ${d.treffer} Treffer (${d.verbraucht_monat}/${d.monats_limit} verbraucht).`); }
    loadBrave();
  } catch (e) { meldung(msg, e.message, false); }
};

/* ---------- Dubletten (Change 011) ---------- */
function dedupeBerichtZeigen(d) {
  const box = $("#dedupePanel");
  box.classList.remove("hidden");
  const gruppen = (d.beispiele || []).map((b) => `<li><strong>${esc(b.behalten)}</strong>
      <span class="klein muted">(bleibt, Quelle ${esc(b.behalten_quelle)})</span>
      <ul>${b.entfernt.map((e) => `<li class="klein">entfernt: ${esc(e.titel)}
      <span class="muted">(${esc(e.quelle)})</span></li>`).join("")}</ul></li>`).join("");
  const verdacht = (d.verdachtsfaelle || []).map((v) => `<li class="klein">${esc(v.datum)}
      ${esc(v.titel)} <span class="muted">· ${esc(v.grund)}</span></li>`).join("");
  box.innerHTML = `<p style="margin:0 0 6px">${d.geprueft} Events geprüft ·
      <strong>${d.gruppen} Gruppen</strong> · ${d.entfernbar} überzählige Datensätze ·
      ${d.verdacht} Verdachtsfälle${d.dry_run ? " · Probelauf" : ""}</p>
    ${gruppen ? `<ul style="margin:6px 0">${gruppen}</ul>` : ""}
    ${verdacht ? `<p class="muted" style="margin:6px 0 0">Verdacht (nicht zusammengeführt,
      weil Uhrzeit oder Ort abweicht):</p><ul style="margin:4px 0">${verdacht}</ul>` : ""}`;
}

$("#dedupePruefen").onclick = async () => {
  const msg = $("#dedupeMsg");
  try {
    const d = await api("/api/admin/dedupe");
    meldung(msg, d.entfernbar ? `${d.entfernbar} Datensätze könnten zusammengeführt werden.`
                              : "Keine Dubletten gefunden.");
    dedupeBerichtZeigen(d);
  } catch (e) { meldung(msg, e.message, false); }
};
$("#dedupeAnwenden").onclick = async () => {
  const msg = $("#dedupeMsg");
  try {
    const d = await api("/api/admin/dedupe/anwenden", { method: "POST", body: JSON.stringify({}) });
    meldung(msg, `${d.entfernt} Datensätze zusammengeführt, ${d.felder_ergaenzt} Felder ergänzt.`);
    dedupeBerichtZeigen(d);
    loadRuns(); loadQuellen();
  } catch (e) { meldung(msg, e.message, false); }
};

/* ================= Ortsvorschläge (Change 022) =================
   Vorschläge der LLM-Ortsprüfung prüfen und einzeln oder im Batch übernehmen.
   Übernehmen setzt Ort/Adresse/Treffpunkt am Termin und markiert ihn als
   manuell gepflegt — der nächste Scrape setzt ihn dann nicht zurück. */

let ortDaten = [];

function ortQuellenFilterFuellen() {
  const sel = $("#ortFilterQuelle");
  if (sel.dataset.gefuellt) return;
  sel.dataset.gefuellt = "1";
  api("/api/admin/sources").then((qs) => {
    qs.forEach((q) => {
      const o = document.createElement("option");
      o.value = q.quelle;
      o.textContent = `${q.name} (${q.events})`;
      sel.appendChild(o);
    });
  }).catch((e) => fehlerZeigen(`Quellen für Ortsfilter: ${e.message}`));
}

async function loadOrtsvorschlaege() {
  ortQuellenFilterFuellen();
  const p = new URLSearchParams({ limit: "1500" });
  if ($("#ortFilterStatus").value) p.set("status", $("#ortFilterStatus").value);
  if ($("#ortFilterQuelle").value) p.set("quelle", $("#ortFilterQuelle").value);
  if ($("#ortFilterBand").value) p.set("band", $("#ortFilterBand").value);
  const s = $("#ortSuche").value.trim();
  if (s) p.set("q", s);
  try {
    const d = await api(`/api/admin/ort/vorschlaege?${p.toString()}`);
    ortDaten = d.vorschlaege || [];
    const z = d.zaehler || {};
    $("#ortZaehler").textContent =
      `${ortDaten.length} angezeigt · offen ${z.vorschlag ?? 0} · übernommen ${z.uebernommen ?? 0}` +
      ` · verworfen ${z.verworfen ?? 0}`;
    const ll = d.letzter_lauf || {};
    $("#ortLaufInfo").textContent = ll.feendet_am || ll.beendet_am
      ? `Letzter Lauf ${fmtZeit(ll.beendet_am)}: ${ll.kandidaten ?? 0} Kandidaten, ` +
        `${ll.vorschlaege ?? 0} Vorschläge, ${ll.verworfen ?? 0} verworfen, ` +
        `${(ll.llm_fehler ?? 0) + (ll.abruf_fehler ?? 0)} Fehler (${ll.modell || "?"})`
      : (ll.fehler ? `Letzter Lauf FEHLER: ${ll.fehler}` : "Noch kein Lauf in der App");
    const tb = $("#ortListe tbody");
    tb.innerHTML = "";
    if (!ortDaten.length) {
      tb.innerHTML = '<tr><td colspan="10" class="muted">Keine Vorschläge für diese Auswahl.</td></tr>';
    }
    ortDaten.forEach((v) => tb.appendChild(ortZeile(v)));
    $("#ortAlle").checked = false;
    $("#ortErgebnis").className = "meldung hidden";
  } catch (e) {
    fehlerZeigen(`Ortsvorschläge laden: ${e.message}`);
  }
}

function ortZeile(v) {
  const tr = document.createElement("tr");
  const offen = v.status === "vorschlag";
  const adresse = v.adresse_vorschlag ? ` · ${esc(v.adresse_vorschlag)}`
    : (v.adresse_jetzt ? ` · ${esc(v.adresse_jetzt)}` : "");
  tr.innerHTML = `
    <td>${offen ? `<input type="checkbox" class="ortHaken" value="${v.id}" />` : ""}</td>
    <td><b>${esc(v.ort_vorschlag || "—")}</b></td>
    <td>${esc(v.adresse_vorschlag || "—")}</td>
    <td>${esc(v.treffpunkt || "—")}</td>
    <td class="muted">${esc(v.ort_jetzt || "—")}${v.adresse_jetzt ? `<br>${esc(v.adresse_jetzt)}` : ""}
      ${v.manuell ? '<span class="badge">manuell gepflegt</span>' : ""}</td>
    <td class="muted" style="max-width:300px">${esc(v.beleg || "—")}</td>
    <td>${esc(v.belegherkunft || "—")}${v.name_im_text ? "" : '<br><span class="muted">Name nicht wörtlich geprüft</span>'}</td>
    <td>${esc(v.ortsband || "n/v")}${v.abstand_m != null ? `<br><span class="muted">${v.abstand_m} m</span>` : ""}</td>
    <td>${esc((v.titel || "").slice(0, 60))}<br><span class="muted">${esc((v.start_local || "").slice(0, 16).replace("T", " "))}</span>
      ${v.source_url ? ` <a href="${esc(v.source_url)}" target="_blank" rel="noopener">Fundstelle</a>` : ""}</td>
    <td>${offen
        ? `<button class="primary" data-ort-uebernehmen="${v.id}">übernehmen</button>
           <button class="ghost" data-ort-verwerfen="${v.id}">verwerfen</button>`
        : esc(v.status) + (v.geprueft_am ? `<br><span class="muted">${fmtZeit(v.geprueft_am)}</span>` : "")}</td>`;
  return tr;
}

function ortAusgewaehlt() {
  return $$("#ortListe .ortHaken").filter((c) => c.checked).map((c) => Number(c.value));
}

async function ortAktion(aktion, ids) {
  const el = $("#ortErgebnis");
  if (!ids.length) {
    meldung(el, "Nichts ausgewählt — bitte die Zeilen ankreuzen.", false);
    return;
  }
  const wort = aktion === "verwerfen" ? "verwerfen" : "übernehmen";
  if (ids.length > 25 && !confirm(`${ids.length} Vorschläge wirklich ${wort}?`)) return;
  meldung(el, `${ids.length} Vorschlag/Vorschläge werden bearbeitet…`, false);
  try {
    const d = await api(`/api/admin/ort/${aktion}`,
      { method: "POST", body: JSON.stringify({ ids }) });
    if (aktion === "verwerfen") {
      meldung(el, `${d.verworfen} verworfen.`, true);
    } else {
      const fehl = (d.ergebnis || []).filter((r) => !r.ok);
      const ohnePos = (d.ergebnis || []).filter((r) => r.ok && /keine Position/.test(r.position || ""));
      meldung(el, `${d.uebernommen} übernommen`
        + (ohnePos.length ? `, davon ${ohnePos.length} ohne neue Position` : "")
        + (fehl.length ? ` · ${fehl.length} nicht übernommen: `
            + fehl.slice(0, 3).map((f) => `#${f.id} ${f.grund}`).join(", ") : ""), fehl.length === 0);
    }
    await loadOrtsvorschlaege();
  } catch (e) {
    meldung(el, `Fehler: ${e.message}`, false);
  }
}

document.addEventListener("click", (ev) => {
  const ueber = ev.target.closest("[data-ort-uebernehmen]");
  if (ueber) {
    ortAktion("uebernehmen", [Number(ueber.dataset.ortUebernehmen)]);
    return;
  }
  const ver = ev.target.closest("[data-ort-verwerfen]");
  if (ver) {
    ortAktion("verwerfen", [Number(ver.dataset.ortVerwerfen)]);
  }
});

$("#ortRefresh").addEventListener("click", () => loadOrtsvorschlaege());
$("#ortSuche").addEventListener("keydown", (e) => { if (e.key === "Enter") loadOrtsvorschlaege(); });
["ortFilterStatus", "ortFilterQuelle", "ortFilterBand"].forEach((id) =>
  $("#" + id).addEventListener("change", () => loadOrtsvorschlaege()));
$("#ortWaehlen").addEventListener("click", () => {
  $$("#ortListe .ortHaken").forEach((c) => { c.checked = true; });
});
$("#ortAlle").addEventListener("change", (e) => {
  $$("#ortListe .ortHaken").forEach((c) => { c.checked = e.target.checked; });
});
$("#ortUebernehmen").addEventListener("click", () => ortAktion("uebernehmen", ortAusgewaehlt()));
$("#ortVerwerfen").addEventListener("click", () => ortAktion("verwerfen", ortAusgewaehlt()));
$("#ortLauf").addEventListener("click", async () => {
  const el = $("#ortErgebnis");
  if (!confirm("Ortsprüfung jetzt starten? Das liest die Quellseiten und fragt das Modell — "
               + "das dauert bei vielen Terminen eine Weile. Es wird nichts automatisch übernommen.")) return;
  try {
    const d = await api("/api/admin/ort/lauf", { method: "POST", body: JSON.stringify({}) });
    meldung(el, `Lauf gestartet (${d.quelle}) — Ergebnis erscheint oben nach dem „Aktualisieren“.`, true);
  } catch (e) {
    meldung(el, `Start fehlgeschlagen: ${e.message}`, false);
  }
});

/* ---------- Init ---------- */
fuelleSchulFilter();
Promise.all([loadQuellen(), loadRuns(), loadFehler(), loadSettings(), ladeTags(), fuelleTerminQuellen(), loadLlm(), loadBrave(), loadMail()])
  .catch((e) => fehlerZeigen(e.message));
baueUnterTabs(); // Quellen-Tab ist beim Laden aktiv → Unter-Tabs sofort bauen
