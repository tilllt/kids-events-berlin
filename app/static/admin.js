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
  $("#setSmtpHost").value = s.smtp_host || "";
  $("#setSmtpPort").value = s.smtp_port || "";
  $("#setSmtpUser").value = s.smtp_user || "";
  $("#setSmtpFrom").value = s.smtp_from || "";
  $("#setVorlage").value = s.mail_vorlage || "";
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
$("#smtpBtn").onclick = async () => {
  const msg = $("#smtpMsg");
  try {
    await api("/api/admin/settings", {
      method: "PUT",
      body: JSON.stringify({
        smtp_host: $("#setSmtpHost").value.trim(),
        smtp_port: $("#setSmtpPort").value.trim(),
        smtp_user: $("#setSmtpUser").value.trim(),
        smtp_pass: $("#setSmtpPass").value,
        smtp_from: $("#setSmtpFrom").value.trim(),
      }),
    });
    $("#setSmtpPass").value = ""; // nie im DOM behalten
    meldung(msg, "SMTP gespeichert.");
  } catch (e) { meldung(msg, e.message, false); }
};
$("#vorlageBtn").onclick = async () => {
  const msg = $("#vorlageMsg");
  try {
    await api("/api/admin/settings", {
      method: "PUT",
      body: JSON.stringify({ mail_vorlage: $("#setVorlage").value }),
    });
    meldung(msg, "Vorlage gespeichert.");
  } catch (e) { meldung(msg, e.message, false); }
};

/* ---------- Tabs ---------- */
function tabAktiv(name) {
  $$("#tabs button").forEach((b) => b.classList.toggle("aktiv", b.dataset.tab === name));
  ["quellen", "schulen", "termine", "kategorien", "einstellungen"].forEach((t) => {
    $("#tab-" + t).classList.toggle("hidden", t !== name);
  });
}
$("#tabs").addEventListener("click", (ev) => {
  const b = ev.target.closest("button[data-tab]");
  if (!b) return;
  tabAktiv(b.dataset.tab);
  if (b.dataset.tab === "schulen") loadSchulen();
  if (b.dataset.tab === "termine") loadTermine();
  if (b.dataset.tab === "kategorien") loadKategorien();
});

/* ---------- Schulen ---------- */
let schulFilter = { q: "", bezirk: "", schulform: "" };

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
  const tb = $("#schuleListe tbody");
  tb.innerHTML = '<tr><td colspan="6" class="muted">Lade Schulen…</td></tr>';
  try {
    const list = await api("/api/admin/schulen?" + qs.toString());
    tb.innerHTML = "";
    if (!list.length) {
      tb.innerHTML = '<tr><td colspan="6" class="muted">Keine Schulen gefunden.</td></tr>';
      $("#schulZaehler").textContent = "";
      return;
    }
    $("#schulZaehler").textContent = `${list.length} Schulen`;
    list.forEach((s) => {
      const tr = document.createElement("tr");
      tr.className = "schule";
      tr.dataset.bsn = s.bsn;
      const nTermine = s.n_termine ?? 0;
      tr.innerHTML = `
        <td><strong>${esc(s.name)}</strong><br/><span class="muted">BSN ${esc(s.bsn)}</span></td>
        <td>${esc(s.schulform || "—")}</td>
        <td class="adr">${schulAdresse(s)}</td>
        <td class="klein">${s.email ? esc(s.email) + "<br/>" : ""}${s.website ? `<a href="${esc(s.website)}" target="_blank" rel="noopener" onclick="event.stopPropagation()">Website ↗</a>` : "—"}</td>
        <td><span class="badge ${nTermine ? "ok" : "off"}">${nTermine} Termine</span></td>
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
  $("#neuTerminBtn").onclick = () => terminFormularZeigen(s);
  const mf = $("#mailFensterBtn");
  if (mf) mf.onclick = () => mailFormularZeigen(s);
}

function terminFormularZeigen(s, t = null) {
  const p = $("#terminForm");
  p.classList.remove("hidden");
  p.innerHTML = `
    <h3>${t ? "Termin bearbeiten" : "Neuer Termin"}</h3>
    <div class="formgrid">
      <label>Titel<input id="t_titel" value="${esc(t ? t.titel : "")}" placeholder="z. B. Tag der offenen Tür" /></label>
      <label>Datum (TT.MM.JJJJ)<input id="t_datum" value="${esc(t ? t.start_datum : "")}" placeholder="15.10.2026" /></label>
      <label>Uhrzeit (optional)<input id="t_zeit" value="${esc(t ? t.start_zeit || "" : "")}" placeholder="16:00" /></label>
      <label>Ende-Datum (optional, mehrjährig)<input id="t_endedatum" value="${esc(t ? t.ende_datum || "" : "")}" /></label>
      <label>Ort<input id="t_ort" value="${esc(t ? t.ort || "" : "")}" placeholder="z. B. Aula" /></label>
      <label>Link (Fund-/Detailseite)<input id="t_url" value="${esc(t ? t.url || "" : "")}" placeholder="https://…" /></label>
      <label style="flex-direction:row;align-items:center;gap:6px"><input id="t_ganztags" type="checkbox" ${t && t.ganztags ? "checked" : ""}/> Ganztägig</label>
    </div>
    <label style="margin-top:8px">Beschreibung / Notiz
      <textarea id="t_beschreibung" style="min-height:70px">${esc(t ? t.beschreibung || "" : "")}</textarea>
    </label>
    <div class="btnrow" style="margin-top:10px">
      <button id="t_save" type="button" class="primary">Speichern</button>
      <button id="t_abort" type="button" class="ghost">Abbrechen</button>
    </div>
    <div id="t_msg"></div>`;
  $("#t_abort").onclick = () => { p.classList.add("hidden"); };
  $("#t_save").onclick = async () => {
    const msg = $("#t_msg");
    const body = {
      titel: $("#t_titel").value.trim(),
      start_datum: $("#t_datum").value.trim(),
      start_zeit: $("#t_zeit").value.trim() || null,
      ende_datum: $("#t_endedatum").value.trim() || null,
      ort: $("#t_ort").value.trim() || null,
      url: $("#t_url").value.trim() || null,
      beschreibung: $("#t_beschreibung").value.trim() || null,
      ganztags: $("#t_ganztags").checked ? 1 : 0,
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

function mailFormularZeigen(s) {
  const p = $("#mailForm");
  p.classList.remove("hidden");
  p.innerHTML = `
    <h3>Termin-Anfrage an ${esc(s.name)}</h3>
    <p class="muted" style="margin-top:0">An: <strong>${esc(s.email)}</strong>. Die Vorlage aus den
      Einstellungen wird unten angezeigt und kann je Schule angepasst werden.</p>
    <textarea id="m_text" class="mail" spellcheck="false"></textarea>
    <div class="btnrow" style="margin-top:10px">
      <button id="m_vorlage" type="button" class="ghost">Vorlage neu laden</button>
      <button id="m_senden" type="button" class="primary">Senden</button>
      <button id="m_abort" type="button" class="ghost">Schließen</button>
    </div>
    <div id="m_msg"></div>`;
  async function ladeVorlage() {
    try {
      const s2 = await api("/api/admin/settings");
      const vorlage = s2.mail_vorlage || "";
      if (vorlage) { $("#m_text").value = vorlage; }
      else {
        // Fallback: Standardtext ohne Server-Roundtrip bauen
        $("#m_text").value = `Betreff: Tage der offenen Tür ${new Date().getFullYear()} – Bitte um Terminmitteilung\n\n` +
          `Sehr geehrte Damen und Herren,\n\nwir betreiben den Veranstaltungskalender „kinderkram“ …\n\n` +
          `Für die ${s.schulform || "Schule"} ${s.name} (${s.bezirk || ""}) bitten wir um Mitteilung der Termine …`;
      }
    } catch (e) { meldung($("#m_msg"), e.message, false); }
  }
  ladeVorlage();
  $("#m_abort").onclick = () => p.classList.add("hidden");
  $("#m_vorlage").onclick = ladeVorlage;
  $("#m_senden").onclick = async () => {
    const msg = $("#m_msg");
    const btn = $("#m_senden");
    btn.disabled = true;
    try {
      await api(`/api/admin/schulen/${encodeURIComponent(s.bsn)}/anfrage`, {
        method: "POST", body: JSON.stringify({ text: $("#m_text").value }),
      });
      meldung(msg, "Mail gesendet ✓");
      p.classList.add("hidden");
      schuleDetailZeigen(await api(`/api/admin/schulen/${encodeURIComponent(s.bsn)}?mit_termine=1`));
    } catch (e) { meldung(msg, e.message, false); }
    btn.disabled = false;
  };
}

/* Schulen-Liste: Klicks (Zeile + Aktionen) */
$("#schuleListe").addEventListener("click", async (ev) => {
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
      terminFormularZeigen(schule, t);
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
  // Bezirke + Schulformen aus einer ungefilterten Stichprobe (max. 200 reichen für die Optionsmengen)
  try {
    const alle = await api("/api/admin/schulen?q=");
    const bezirke = [...new Set(alle.map((s) => s.bezirk).filter(Boolean))].sort();
    const formen = [...new Set(alle.map((s) => s.schulform).filter(Boolean))].sort();
    $("#schulBezirk").innerHTML = '<option value="">Alle Bezirke</option>' +
      bezirke.map((b) => `<option>${esc(b)}</option>`).join("");
    $("#schulForm").innerHTML = '<option value="">Alle Schulformen</option>' +
      formen.map((f) => `<option>${esc(f)}</option>`).join("");
  } catch (e) { /* Filter optional — Fehler nicht blockierend */ }
}

/* ---------- Termine (Tab) ---------- */
async function loadTermine() {
  const status = $("#termineFilterStatus").value;
  const qs = new URLSearchParams();
  if (status) qs.set("status", status);
  const tb = $("#termineListe tbody");
  tb.innerHTML = '<tr><td colspan="6" class="muted">Lade…</td></tr>';
  try {
    const list = await api("/api/admin/termine?" + qs.toString());
    tb.innerHTML = "";
    if (!list.length) { tb.innerHTML = '<tr><td colspan="6" class="muted">Keine manuellen Termine.</td></tr>'; return; }
    list.forEach((t) => {
      const tr = document.createElement("tr");
      const beleg = t.quelle_hinweis || "";
      tr.innerHTML = `
        <td style="white-space:nowrap">${esc(t.start_datum)}${t.start_zeit ? `<br/><span class="klein">${esc(t.start_zeit)} Uhr</span>` : ""}</td>
        <td><strong>${esc(t.schulname || t.schule_bsn)}</strong>${t.schulbezirk ? `<br/><span class="klein">${esc(t.schulbezirk)}</span>` : ""}</td>
        <td>${esc(t.titel)}${t.kategorie_name ? `<br/><span class="badge">${esc(t.kategorie_name)}</span>` : ""}</td>
        <td>${statusBadge(t.status)}</td>
        <td class="klein">${beleg ? `<a href="${esc(t.url || beleg.replace(/^automatisch erkannt: /, ""))}" target="_blank" rel="noopener">Beleg ↗</a>` : "—"}</td>
        <td><div class="btnrow">
          ${t.status !== "bestaetigt" ? `<button data-tid="${t.id}" data-act="freigeben" class="primary">Freigeben</button>` : `<button data-tid="${t.id}" data-act="zurueckziehen">Zurückziehen</button>`}
          <button data-tid="${t.id}" data-bsn="${esc(t.schule_bsn)}" data-act="edit">Bearbeiten</button>
          <button data-tid="${t.id}" data-act="del" class="danger">Löschen</button>
        </div></td>`;
      tb.appendChild(tr);
    });
  } catch (e) { fehlerZeigen(`Termine: ${e.message}`); }
}
$("#termineFilterStatus").addEventListener("change", loadTermine);

/* Termine-Tab Aktionen (Delegation) */
$("#termineListe").addEventListener("click", async (ev) => {
  const btn = ev.target.closest("button[data-act]");
  if (!btn) return;
  const tid = btn.dataset.tid;
  const act = btn.dataset.act;
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
      // In den Schulen-Tab wechseln und Detail öffnen
      tabAktiv("schulen");
      schuleDetailZeigen(await api(`/api/admin/schulen/${encodeURIComponent(t.schule_bsn)}?mit_termine=1`));
      terminFormularZeigen(schule, t);
      return;
    }
    loadTermine();
  } catch (e) { fehlerZeigen(e.message); }
});

/* ---------- Kategorien (Tab) ---------- */
async function loadKategorien() {
  const tb = $("#katTabelle tbody");
  tb.innerHTML = "";
  try {
    const list = await api("/api/admin/kategorien");
    if (!list.length) { tb.innerHTML = '<tr><td colspan="4" class="muted">Noch keine Kategorien — z. B. „Tag der offenen Tür“, „Infoabend“, „Schnuppertag“.</td></tr>'; return; }
    list.forEach((k) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `<td><strong>${esc(k.name)}</strong> <span class="klein">(${esc(k.id)})</span></td>
        <td><span style="display:inline-block;width:18px;height:18px;border-radius:4px;background:${esc(k.farbe || "#888")};border:1px solid var(--border)"></span> ${esc(k.farbe || "—")}</td>
        <td>${k.sort ?? 0}</td>
        <td><div class="btnrow">
          <button data-kid="${esc(k.id)}" data-act="edit">Bearbeiten</button>
          <button data-kid="${esc(k.id)}" data-act="del" class="danger">Löschen</button>
        </div></td>`;
      tb.appendChild(tr);
    });
  } catch (e) { fehlerZeigen(`Kategorien: ${e.message}`); }
}

function kategorieFormularZeigen(k = null) {
  const p = $("#katPanel");
  p.classList.remove("hidden");
  p.innerHTML = `
    <h3>${k ? `Kategorie bearbeiten: ${esc(k.name)}` : "Neue Kategorie"}</h3>
    <div class="formgrid" style="max-width:640px">
      <label>Schlüssel (nur bei Neuanlage)<input id="k_id" ${k ? "disabled" : ""} value="${esc(k ? k.id : "")}" placeholder="z. B. tdot" /></label>
      <label>Name<input id="k_name" value="${esc(k ? k.name : "")}" placeholder="Tag der offenen Tür" /></label>
      <label>Farbe (Hex)<input id="k_farbe" value="${esc(k ? k.farbe || "" : "")}" placeholder="#2ea043" /></label>
      <label>Sortierung<input id="k_sort" type="number" value="${k ? k.sort ?? 0 : 0}" /></label>
    </div>
    <div class="btnrow" style="margin-top:10px">
      <button id="k_save" type="button" class="primary">Speichern</button>
      <button id="k_abort" type="button" class="ghost">Abbrechen</button>
    </div>
    <div id="k_msg"></div>`;
  $("#k_abort").onclick = () => p.classList.add("hidden");
  $("#k_save").onclick = async () => {
    const msg = $("#k_msg");
    const body = { name: $("#k_name").value.trim(), farbe: $("#k_farbe").value.trim() || null, sort: parseInt($("#k_sort").value, 10) || 0 };
    try {
      if (k) await api(`/api/admin/kategorien/${encodeURIComponent(k.id)}`, { method: "PUT", body: JSON.stringify(body) });
      else { body.id = $("#k_id").value.trim(); await api("/api/admin/kategorien", { method: "POST", body: JSON.stringify(body) }); }
      p.classList.add("hidden");
      loadKategorien();
    } catch (e) { meldung(msg, e.message, false); }
  };
}
$("#katNeu").onclick = () => kategorieFormularZeigen(null);
$("#katTabelle").addEventListener("click", async (ev) => {
  const btn = ev.target.closest("button[data-act]");
  if (!btn) return;
  const kid = btn.dataset.kid;
  try {
    if (btn.dataset.act === "edit") {
      const k = (await api("/api/admin/kategorien")).find((x) => x.id === kid);
      kategorieFormularZeigen(k);
    } else if (btn.dataset.act === "del") {
      if (!confirm(`Kategorie „${kid}“ löschen? (Termine behalten sie, aber ohne Kategorie.)`)) return;
      await api(`/api/admin/kategorien/${encodeURIComponent(kid)}`, { method: "DELETE" });
      loadKategorien();
    }
  } catch (e) { fehlerZeigen(e.message); }
});

/* ---------- Init ---------- */
fuelleSchulFilter();
Promise.all([loadQuellen(), loadRuns(), loadFehler(), loadSettings()])
  .catch((e) => fehlerZeigen(e.message));
