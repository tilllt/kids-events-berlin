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

/* ---------- Init ---------- */
Promise.all([loadQuellen(), loadRuns(), loadFehler(), loadSettings()])
  .catch((e) => fehlerZeigen(e.message));
